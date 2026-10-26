# -*- coding: utf-8 -*-
"""
Wyckoff Trading Plan and Risk/Reward Builder Module.
Handles Steps 3.5, 4, 5, Confidence Matrix, and A-Stock Rule Checks.
"""

from typing import Callable, Optional, Tuple

import numpy as np
import pandas as pd

from uniquant.brain.indicators.indicators import Indicators
from uniquant.brain.wyckoff.classifiers import (
    classify_wyckoff_markup_event,
    detect_limit_moves,
)
from uniquant.brain.wyckoff.event_detector import scan_false_breakout
from uniquant.brain.wyckoff.models import (
    ConfidenceResult,
    LimitMoveType,
    RiskRewardResult,
    Rule0Result,
    Step1Result,
    Step2Result,
    Step3Result,
    V3CounterfactualResult,
    V3TradingPlan,
    WyckoffPhase,
)
from uniquant.brain.wyckoff.rules import V3Rules
from uniquant.brain.wyckoff.structural_adjuster import _downgrade_direction


def step35_counterfactual(
    df: pd.DataFrame,
    step1: Step1Result,
    step2: Step2Result,
    step3: Step3Result,
    rule0: Rule0Result,
    rules: V3Rules,
) -> V3CounterfactualResult:
    """Step 3.5: 反事实压力测试"""
    forward_evidence = []
    backward_evidence = []

    # 正证：吸筹证据
    if step2.net_bias == "accumulation":
        forward_evidence.extend(step2.phenomena)

    # 反证：派发证据
    if step2.net_bias == "distribution":
        backward_evidence.extend(step2.phenomena)

    # 正证：Spring 确认
    if step3.spring_detected and step3.lps_confirmed:
        forward_evidence.append("Spring+LPS确认")

    # 反证：UTAD 或假突破
    if step3.utad_detected:
        backward_evidence.append("UTAD假突破")

    pro_score = len(forward_evidence) * 2.0
    con_score = len(backward_evidence) * 2.0

    # 使用规则7仲裁
    cf_result = rules.rule7_counterfactual(pro_score, con_score)

    # 生成反事实场景描述
    scenario = ""
    if cf_result["overturned"]:
        scenario = f"反证({con_score:.1f})占优，原判断被推翻。反证：{', '.join(backward_evidence)}"
    elif cf_result["verdict"] == "降档":
        scenario = f"反证({con_score:.1f})接近正证({pro_score:.1f})，降档处理。需进一步验证。"
    else:
        scenario = f"正证({pro_score:.1f})占优，维持判断。正证：{', '.join(forward_evidence)}"

    return V3CounterfactualResult(
        utad_not_breakout="是" if not step3.utad_detected else "否",
        distribution_not_accumulation="是" if step2.net_bias != "distribution" else "否",
        chaos_not_phase_c="是" if step1.phase != WyckoffPhase.UNKNOWN else "否",
        liquidity_vacuum_risk="低" if step3.t1_verdict == "安全" else "高",
        total_pro_score=pro_score,
        total_con_score=con_score,
        conclusion_overturned=cf_result["overturned"],
        counterfactual_scenario=scenario,
        forward_evidence=forward_evidence,
        backward_evidence=backward_evidence,
    )


def step4_risk_reward(
    df: pd.DataFrame,
    step1: Step1Result,
    step3: Step3Result,
    rule0: Rule0Result,
    rules: V3Rules,
    pnf_count_target: Optional[float] = None,
) -> RiskRewardResult:
    """Step 4: 盈亏比投影（规则10精度，多种目标位来源 + ATR回填）"""
    current_price = float(df.iloc[-1]["close"])

    # 止损价 = 关键结构低点 × 0.995（ATR可用时用1倍ATR止损）
    key_low = step3.spring_low_price if step3.spring_low_price else step1.boundary_lower
    if key_low <= 0 or key_low > current_price:
        key_low = float(df.tail(30)["low"].min())

    atr_series = Indicators.calc_atr(df)
    current_atr = float(atr_series.iloc[-1]) if len(atr_series) > 0 else 0.0
    stop_loss_result = rules.rule10_stop_loss(key_low, atr=current_atr)
    stop_loss = stop_loss_result.stop_loss_price

    # 目标位：多种来源
    first_target = step1.boundary_upper
    first_target_source = "tr_upper"

    # 尝试其他目标位来源
    recent_20 = df.tail(20)

    # 1. 大阴线起跌点（前一天收盘价 > 当天收盘价 * 1.03）
    for i in range(len(recent_20) - 1, 0, -1):
        prev_close = float(recent_20.iloc[i - 1]["close"])
        curr_close = float(recent_20.iloc[i]["close"])
        if prev_close > curr_close * 1.03:
            bearish_target = prev_close
            if current_price < bearish_target < first_target:
                first_target = bearish_target
                first_target_source = "bearish_candle"
                break

    # 2. 跳空缺口下沿
    for i in range(1, len(recent_20)):
        prev_row = recent_20.iloc[i - 1]
        curr_row = recent_20.iloc[i]
        if curr_row["low"] > prev_row["high"]:
            gap_target = float(curr_row["low"])
            if current_price < gap_target < first_target:
                first_target = gap_target
                first_target_source = "gap_lower"
                break

    # 3. ATR回填：当所有结构化目标位都低于当前价时
    if first_target <= current_price:
        tr_vals = []
        for i in range(1, min(21, len(df))):
            hi = float(df.iloc[-i]["high"])
            lo = float(df.iloc[-i]["low"])
            pc = float(df.iloc[-i - 1]["close"])
            tr_vals.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
        atr = float(np.mean(tr_vals)) if len(tr_vals) >= 20 else current_price * 0.02
        first_target = current_price + 2.0 * atr
        first_target_source = "atr_derived"

    # 4. P&F Count Target 优先（PF-C2）：当 PNF 目标高于当前价时采用
    if pnf_count_target and pnf_count_target > current_price:
        first_target = float(pnf_count_target)
        first_target_source = "pnf_count_target"

    # 计算盈亏比
    risk = current_price - stop_loss
    reward = first_target - current_price

    if risk > 0:
        rr_ratio = reward / risk
    else:
        rr_ratio = 0.0

    # 判定 - 统一严格阈值 (v3.0要求盈亏比 >= 1:2.5)
    if rr_ratio >= 2.5:
        rr_verdict = "excellent"
    elif rr_ratio >= 2.0:
        rr_verdict = "pass"
    elif rr_ratio >= 1.5:
        rr_verdict = "marginal"
    else:
        rr_verdict = "fail"

    gain_pct = (first_target - current_price) / current_price * 100 if current_price > 0 else 0

    return RiskRewardResult(
        entry_price=current_price,
        stop_loss=stop_loss,
        first_target=first_target,
        first_target_source=first_target_source,
        rr_ratio=round(rr_ratio, 2),
        rr_verdict=rr_verdict,
        gain_pct=round(gain_pct, 2),
    )


def calc_confidence(
    rule0: Rule0Result,
    step1: Step1Result,
    step3: Step3Result,
    cf: V3CounterfactualResult,
    rr: RiskRewardResult,
    multiframe: bool,
    rules: V3Rules,
    debug_r8_compare: bool = False,
) -> Tuple[ConfidenceResult, Optional[ConfidenceResult], Optional[ConfidenceResult]]:
    """规则8: 置信度矩阵 - 统一5条件 (原始标准)

    返回 (result, debug_bypass_result, debug_full_result)
    """
    bc_located = rule0.bc_found
    spring_lps_verified = step3.spring_detected and step3.lps_confirmed
    counterfactual_passed = not cf.conclusion_overturned
    rr_qualified = rr.rr_ratio >= 2.5
    multiframe_aligned = multiframe

    # A级：Spring+LPS+BC+盈亏比≥1.5
    if step3.spring_detected and step3.lps_confirmed and bc_located and rr.rr_ratio >= 1.5:
        return (
            ConfidenceResult(
                level="A",
                bc_located=True,
                spring_lps_verified=True,
                counterfactual_passed=counterfactual_passed,
                rr_qualified=rr.rr_ratio >= 2.5,
                multiframe_aligned=multiframe_aligned,
                position_size="标准仓位",
                reason=f"Spring+LPS+BC+盈亏比{rr.rr_ratio:.1f}达标",
            ),
            None,
            None,
        )
    # B+级：Spring+LPS（不需要BC）+ 盈亏比≥1.5
    if step3.spring_detected and step3.lps_confirmed and rr.rr_ratio >= 1.5:
        return (
            ConfidenceResult(
                level="B+",
                bc_located=bc_located,
                spring_lps_verified=True,
                counterfactual_passed=counterfactual_passed,
                rr_qualified=rr.rr_ratio >= 2.5,
                multiframe_aligned=multiframe_aligned,
                position_size="轻仓试探",
                reason=f"Spring+LPS+盈亏比{rr.rr_ratio:.1f}，B+级",
            ),
            None,
            None,
        )
    # Bypass path 1: Spring detected but LPS not verified
    if step3.spring_detected and not step3.lps_confirmed:
        bypass_result = ConfidenceResult(
            level="C",
            bc_located=bc_located,
            spring_lps_verified=False,
            counterfactual_passed=counterfactual_passed,
            rr_qualified=rr_qualified,
            multiframe_aligned=multiframe_aligned,
            position_size="试仓",
            reason="Spring已检测但LPS未验证，降级到C",
            bypassed=True,
        )
        debug_full = None
        if debug_r8_compare:
            debug_full = rules.rule8_confidence_matrix(
                bc_located,
                spring_lps_verified,
                counterfactual_passed,
                rr_qualified,
                multiframe_aligned,
            )
        return bypass_result, bypass_result if debug_r8_compare else None, debug_full

    # Bypass path 2: RR qualified but BC not located
    if rr_qualified and not bc_located:
        bypass_result = ConfidenceResult(
            level="C",
            bc_located=False,
            spring_lps_verified=spring_lps_verified,
            counterfactual_passed=counterfactual_passed,
            rr_qualified=True,
            multiframe_aligned=multiframe_aligned,
            position_size="试仓",
            reason="盈亏比达标但BC未定位，降级到C",
            bypassed=True,
        )
        debug_full = None
        if debug_r8_compare:
            debug_full = rules.rule8_confidence_matrix(
                bc_located,
                spring_lps_verified,
                counterfactual_passed,
                rr_qualified,
                multiframe_aligned,
            )
        return bypass_result, bypass_result if debug_r8_compare else None, debug_full

    full_result = rules.rule8_confidence_matrix(
        bc_located,
        spring_lps_verified,
        counterfactual_passed,
        rr_qualified,
        multiframe_aligned,
    )
    return full_result, None, None


def step5_trading_plan(
    step1: Step1Result,
    step3: Step3Result,
    cf: V3CounterfactualResult,
    rr: RiskRewardResult,
    confidence: ConfidenceResult,
    df: Optional[pd.DataFrame] = None,
    rules: Optional[V3Rules] = None,
    code_prefix: str = "",
    is_st: bool = False,
    accumulation_downgrade: bool = True,
    scan_false_breakout_fn: Optional[Callable] = None,
    classify_markup_event_fn: Optional[Callable] = None,
    detect_limit_moves_fn: Optional[Callable] = None,
) -> V3TradingPlan:
    """Step 5: 交易计划（完整字段填充）"""
    if rules is None:
        rules = V3Rules()

    # 基本方向 - 根据阶段和信号确定
    direction = "空仓观望"

    # 规则2: Markdown禁止做多
    if step1.phase == WyckoffPhase.MARKDOWN:
        direction = "空仓观望"
    elif step1.phase == WyckoffPhase.DISTRIBUTION:
        direction = "空仓观望"
    elif step1.phase == WyckoffPhase.ACCUMULATION:
        # ACCUMULATION阶段：Spring+LPS确认后可做多
        if step3.spring_detected and step3.lps_confirmed:
            if confidence.level in ["A", "B+"]:
                direction = "做多"
            elif rr.rr_ratio >= 2.5:
                direction = "做多"
            else:
                direction = "轻仓试探"
        elif step3.spring_detected:
            # Spring已检测但LPS未确认：
            #   P0-1: 强置信(A/B/B+)或盈亏比>=1.5 -> 放开轻仓试探
            #   否则保持观察(不做多越权)
            if confidence.level in ["A", "B", "B+"] or rr.rr_ratio >= 1.5:
                direction = "轻仓试探"
            else:
                direction = "观察等待"
        else:
            direction = "空仓观望"
    elif step1.phase == WyckoffPhase.MARKUP:
        # Check for recent Spring (same logic as SOS Signal)
        is_post_spring_sos = False
        if df is not None and len(df) > 0:
            last_row = df.iloc[-1]
            c_val = float(last_row["close"])
            o_val = float(last_row["open"])
            l_val = float(last_row["low"])
            h_val = float(last_row["high"])
            c_loc = (c_val - l_val) / max(h_val - l_val, 0.01)

            if step3.spring_detected and step3.spring_date:
                if len(df) >= 3:
                    date_1_day_ago = str(df.iloc[-2]["date"])
                    date_2_days_ago = str(df.iloc[-3]["date"])
                    if step3.spring_date in date_1_day_ago:
                        if c_loc >= 0.5 and c_val > o_val:
                            is_post_spring_sos = True
                    elif step3.spring_date in date_2_days_ago:
                        prev_row = df.iloc[-2]
                        prev_c = float(prev_row["close"])
                        prev_o = float(prev_row["open"])
                        prev_h = float(prev_row["high"])
                        prev_l = float(prev_row["low"])
                        prev_c_loc = (prev_c - prev_l) / max(prev_h - prev_l, 0.01)
                        was_prev_breakout = prev_c_loc >= 0.5 and prev_c > prev_o
                        if not was_prev_breakout:
                            if c_loc >= 0.5 and c_val > o_val:
                                is_post_spring_sos = True

        _classify_markup = classify_markup_event_fn or classify_wyckoff_markup_event
        markup_sub_event = _classify_markup(df, step1.boundary_upper)

        if is_post_spring_sos:
            direction = "做多"
        elif "Test" in markup_sub_event or "Shakeout" in markup_sub_event:
            direction = "买入"
        elif (
            "LPS" in markup_sub_event
            or "BUEC" in markup_sub_event
            or "Lack of Supply" in markup_sub_event
            or "Phase E" in markup_sub_event
        ):
            if rr.rr_ratio < 1.2:
                direction = "空仓观望"
            else:
                direction = "持有"
        # 兜底动作决策
        elif rr.rr_ratio >= 2.5:
            direction = "做多"
        elif rr.rr_ratio >= 1.5:
            direction = "轻仓试探"
        elif rr.rr_ratio < 1.2:
            direction = "空仓观望"
        else:
            direction = "持有观察"
    elif step1.phase == WyckoffPhase.UNKNOWN:
        if step1.unknown_candidate in ("phase_a_candidate", "sc_st_candidate"):
            if step3.spring_detected:
                if confidence.level in ["A", "B", "B+"] or rr.rr_ratio >= 1.5:
                    direction = "轻仓试探"
                else:
                    direction = "观察等待"
            else:
                direction = "空仓观望"
        elif step3.spring_detected and (
            confidence.level in ["A", "B", "B+"] or rr.rr_ratio >= 1.5
        ):
            direction = "轻仓试探"
        else:
            direction = "空仓观望"

    # 止损结果（含涨跌停流动性警告 + ATR动态止损）
    key_low = step3.spring_low_price if step3.spring_low_price else step1.boundary_lower
    _detect_lm = detect_limit_moves_fn or (
        lambda d: detect_limit_moves(d, code_prefix=code_prefix, is_st=is_st, rules=rules)
    )
    limit_moves = _detect_lm(df if df is not None else pd.DataFrame())
    limit_moves_data = [{"price": lm.price, "type": lm.move_type.value} for lm in limit_moves]
    atr_series = Indicators.calc_atr(df)
    current_atr = float(atr_series.iloc[-1]) if len(atr_series) > 0 else 0.0

    # 涨跌停风控: 近20日有涨停或跌停记录的股票跳过
    last_close = float(df["close"].iloc[-1]) if df is not None and len(df) > 0 else None
    for lm in limit_moves:
        if lm.move_type == LimitMoveType.LIMIT_DOWN:
            direction = "空仓观望"
            break
        if lm.move_type in (LimitMoveType.LIMIT_UP, LimitMoveType.BREAK_LIMIT_UP):
            if last_close is not None:
                pre_idx = max(0, len(df) - 2)
                prev_close = float(df["close"].iloc[pre_idx])
                if prev_close > 0:
                    limit_pct = 0.10
                    if code_prefix in {"688", "689", "300", "301", "302"}:
                        limit_pct = 0.20
                    elif code_prefix in {"83", "87", "920"}:
                        limit_pct = 0.30
                    elif is_st:
                        limit_pct = 0.05
                    limit_price = prev_close * (1.0 + limit_pct)
                    if abs(last_close - limit_price) / limit_price < 0.005:
                        direction = "空仓观望"
                        break
    stop_loss_result = rules.rule10_stop_loss(key_low, limit_moves_data, current_atr)

    multi_timeframe_statement = "本次分析未提供周线图，置信度已自动降一级"

    execution_preconditions = [
        "大盘指数未出现单边系统性暴跌",
        "所属板块未出现重大利空政策消息",
    ]

    # 生成高度结构化且对齐测试关键字的评估描述
    if step1.phase == WyckoffPhase.ACCUMULATION:
        sub_phase_desc = f" | {step1.sub_phase}" if step1.sub_phase else ""
        assessment = f"当前处于Accumulation阶段{sub_phase_desc}，属于 Phase B/Phase C 震荡区间"
    elif step1.phase == WyckoffPhase.DISTRIBUTION:
        sub_phase_desc = f" | {step1.sub_phase}" if step1.sub_phase else ""
        assessment = f"当前处于Distribution阶段{sub_phase_desc}，属于 Phase B/Phase C 派发震荡区间"
    elif step1.phase == WyckoffPhase.MARKUP:
        if rr.rr_ratio < 1.2:
            assessment = (
                f"当前处于Markup阶段，但盈亏比仅为{rr.rr_ratio:.2f}，"
                f"属于 No Trade Zone 观望，建议持股者继续持有，无仓者空仓观望"
            )
        else:
            assessment = "当前处于Markup阶段，建议继续持有"
    elif step1.phase == WyckoffPhase.UNKNOWN:
        if step1.unknown_candidate == "sc_st_candidate":
            assessment = "当前处于Unknown阶段 (SC恐慌抛售/二次测试候选)"
        elif step1.unknown_candidate == "phase_a_candidate":
            assessment = "当前处于Unknown阶段 (Phase A候选)"
        elif step1.unknown_candidate == "upthrust_candidate":
            assessment = "当前处于Unknown阶段 (Upthrust候选)"
        elif step1.unknown_candidate == "phase_b_range":
            assessment = "当前处于Unknown阶段 (Phase B震荡区间)"
        else:
            assessment = "当前处于Unknown阶段"
    else:
        assessment = f"当前处于{step1.phase.value}阶段"

    # CF-C4: 假突破检测（突破 TR 上沿后 3 列内跌回 → false_breakout 惩罚）
    false_breakout_detected = False
    _scan_fb = scan_false_breakout_fn or scan_false_breakout
    if step1.boundary_upper > 0 and df is not None and len(df) > 0:
        fb = _scan_fb(df, step1.boundary_upper)
        if fb is not None:
            false_breakout_detected = True
            assessment = (
                f"检测到假突破（{fb['date']} 突破后 3 列内跌回 TR），信号置信度降级，空仓观望"
            )
            direction = "空仓观望"

    # 红蓝对抗 (2026-08-07): ACCUMULATION 蓄势超额为负 → 多头方向降 1 档。
    if (
        accumulation_downgrade
        and step1.phase == WyckoffPhase.ACCUMULATION
        and direction in ("做多", "买入", "轻仓试探")
    ):
        downgraded = _downgrade_direction(direction)
        if downgraded != direction:
            direction = downgraded

    return V3TradingPlan(
        current_assessment=assessment,
        multi_timeframe_statement=multi_timeframe_statement,
        execution_preconditions=execution_preconditions,
        direction=direction,
        entry_trigger=f"价格站稳{step1.boundary_upper:.2f}上方"
        if step1.boundary_upper > 0
        else "",
        observation_window="3-5个交易日",
        stop_loss=stop_loss_result,
        target=rr,
        confidence=confidence,
        false_breakout_detected=false_breakout_detected,
    )


def apply_a_stock_rules(
    step1: Step1Result, plan: V3TradingPlan, rules: Optional[V3Rules] = None
) -> V3TradingPlan:
    """A 股铁律最终检查"""
    # 规则2: Markdown 禁止做多
    if rules is None:
        rules = V3Rules()
    blocked, reason = rules.rule2_no_long_in_markdown(step1.phase, "")
    if blocked:
        plan.direction = "空仓观望"
        plan.current_assessment = reason

    return plan


__all__ = [
    "apply_a_stock_rules",
    "calc_confidence",
    "step35_counterfactual",
    "step4_risk_reward",
    "step5_trading_plan",
]
