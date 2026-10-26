# -*- coding: utf-8 -*-
"""
Wyckoff Report Builder Module.
Constructs the in-memory WyckoffReport dataclass from analysis steps.
"""

from typing import Callable, Optional

import pandas as pd

from uniquant.brain.wyckoff.analysis import analyze_chips
from uniquant.brain.wyckoff.classifiers import (
    classify_wyckoff_markup_event,
    detect_limit_moves,
)
from uniquant.brain.wyckoff.models import (
    ConfidenceLevel,
    ConfidenceResult,
    RiskRewardProjection,
    RiskRewardResult,
    Rule0Result,
    Step1Result,
    Step2Result,
    Step3Result,
    StressTest,
    TradingPlan,
    V3CounterfactualResult,
    V3TradingPlan,
    VolumeLevel,
    WyckoffPhase,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
)
from uniquant.brain.wyckoff.structural_adjuster import _downgrade_confidence


def build_wyckoff_report(
    symbol: str,
    period: str,
    df: pd.DataFrame,
    rule0: Rule0Result,
    step1: Step1Result,
    step2: Step2Result,
    step3: Step3Result,
    step35: V3CounterfactualResult,
    rr: RiskRewardResult,
    confidence: ConfidenceResult,
    v3_plan: V3TradingPlan,
    pnf_result: Optional[dict] = None,
    regime_phase: Optional[str] = None,
    adjustment_status: str = "unknown",
    structural_score: float = 0.0,
    relative_strength: Optional[str] = None,
    relative_strength_detail: Optional[dict] = None,
    pnf_phase_divergence: Optional[str] = None,
    full_frame: Optional[pd.DataFrame] = None,
    classify_markup_event_fn: Optional[Callable] = None,
    detect_limit_moves_fn: Optional[Callable] = None,
    analyze_chips_fn: Optional[Callable] = None,
) -> WyckoffReport:
    """构建最终报告"""
    current_price = float(df.iloc[-1]["close"])
    current_date = str(df.iloc[-1]["date"])

    # 构建结构
    structure = WyckoffStructure(
        phase=step1.phase,
        unknown_candidate=step1.unknown_candidate,
        bc_point=rule0.bc_position,
        sc_point=None,
        support_levels=[],
        resistance_levels=[],
        trading_range_high=step1.boundary_upper,
        trading_range_low=step1.boundary_lower,
        current_price=current_price,
        current_date=current_date,
    )

    # 构建信号
    signal_type = "no_signal"
    signal_description = ""
    sos_candidate_detected_flag = step3.sos_candidate_detected

    if step1.phase == WyckoffPhase.MARKUP:
        # SOS Candidate / Spring Confirmation detection:
        # If we recently had a Spring (within step3冷静期) and price is rising strongly,
        # this marks a powerful Sign of Strength (SOS) confirming the transition to Markup.
        is_post_spring_sos = False
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

        if is_post_spring_sos:
            sos_candidate_detected_flag = True
            signal_type = "markup"
            signal_description = "处于上涨阶段 (Markup - SOS已确认)"
        else:
            signal_type = "markup"
            _classify_markup = classify_markup_event_fn or classify_wyckoff_markup_event
            signal_description = _classify_markup(df, step1.boundary_upper)
    elif step1.phase == WyckoffPhase.MARKDOWN:
        signal_type = "markdown"
        signal_description = "处于下跌阶段 (Markdown)，空仓观望"
    elif step1.phase == WyckoffPhase.DISTRIBUTION:
        if step3.utad_detected:
            signal_type = "utad"
            signal_description = "检测到UTAD假突破信号"
        else:
            signal_type = "distribution"
            signal_description = "处于派发阶段 (Distribution)，空仓观望"
    elif step3.spring_detected:
        signal_type = "spring"
        signal_description = f"检测到Spring信号，质量：{step3.spring_quality}"
        if step3.lps_confirmed:
            signal_description += "，LPS已确认"
    elif step3.utad_detected:
        signal_type = "utad"
        signal_description = "检测到UTAD假突破信号"
    elif step3.sos_candidate_detected:
        signal_type = "sos_candidate"
        signal_description = "检测到SOS候选信号"
    elif step1.phase == WyckoffPhase.ACCUMULATION:
        signal_type = "accumulation"
        signal_description = "处于积累阶段，等待Spring/SOS信号"
    else:
        signal_type = "no_signal"
        if step1.unknown_candidate == "sc_st_candidate":
            signal_description = "不确定阶段 (检测到SC恐慌抛售候选)，空仓观望"
        elif step1.unknown_candidate == "phase_a_candidate":
            signal_description = "不确定阶段 (检测到Phase A候选)，空仓观望"
        elif step1.unknown_candidate == "upthrust_candidate":
            signal_description = "不确定阶段 (检测到Upthrust候选)，空仓观望"
        else:
            signal_description = "不确定阶段，空仓观望"

    # CF-C4: 假突破惩罚 → 信号置信度 -1 级
    signal_confidence = confidence.level
    if v3_plan.false_breakout_detected:
        signal_confidence = _downgrade_confidence(signal_confidence)
    # CN-C4: 未复权数据 → 信号置信度 -1 级 (研究平台: 降级不拒绝)
    if adjustment_status == "raw":
        signal_confidence = _downgrade_confidence(signal_confidence)
    # P3-T2: markup 追买降级 — RS 非 leader 时降 1 级
    if signal_type in ("markup", "markup_buy") and relative_strength in (
        "follower",
        "systemic_decline",
    ):
        signal_confidence = _downgrade_confidence(signal_confidence)

    signal = WyckoffSignal(
        signal_type=signal_type,
        trigger_price=current_price,
        volume_confirmation=VolumeLevel.AVERAGE,
        confidence=ConfidenceLevel[signal_confidence],
        phase=step1.phase,
        description=signal_description if signal_description else v3_plan.current_assessment,
        t1_risk评估=step3.t1_description,
        spring_date=step3.spring_date,
    )

    # 盈亏比投影
    risk_reward = RiskRewardProjection(
        entry_price=rr.entry_price,
        stop_loss=rr.stop_loss,
        first_target=rr.first_target,
        reward_risk_ratio=rr.rr_ratio,
        risk_amount=rr.entry_price - rr.stop_loss,
        reward_amount=rr.first_target - rr.entry_price,
        structure_based=rr.first_target_source,
    )

    # P3-T3: RS 仓位过滤 — systemic_decline 时仓位降级
    trading_direction = v3_plan.direction
    if signal_type in ("spring", "markup") and relative_strength == "systemic_decline":
        trading_direction = "空仓观望"

    # 交易计划
    trading_plan = TradingPlan(
        direction=trading_direction,
        trigger_condition=v3_plan.entry_trigger,
        invalidation_point=v3_plan.stop_loss.stop_logic if v3_plan.stop_loss else "",
        first_target=f"{rr.first_target:.2f}" if rr.first_target > 0 else "",
        confidence=ConfidenceLevel[confidence.level],
        preconditions="; ".join(v3_plan.execution_preconditions)
        if v3_plan.execution_preconditions
        else "",
        current_qualification=v3_plan.current_assessment,
    )

    # 压力测试
    stress_tests = []
    for evidence in step35.forward_evidence:
        stress_tests.append(
            StressTest(
                scenario_name="正证",
                scenario_description=evidence,
                outcome="支持判断",
                passes=True,
                risk_level="低",
            )
        )
    for evidence in step35.backward_evidence:
        stress_tests.append(
            StressTest(
                scenario_name="反证",
                scenario_description=evidence,
                outcome="质疑判断",
                passes=False,
                risk_level="高",
            )
        )

    # 涨跌停检测
    _detect_lm = detect_limit_moves_fn or detect_limit_moves
    limit_moves = _detect_lm(df)

    # 筹码分析
    _analyze_ch = analyze_chips_fn or analyze_chips
    chip_analysis = _analyze_ch(df, structure)

    # SQ-C1: 结构完整性评分 (已在 _analyze_single 计算并加权置信度，此处直接透传)

    # P1-4~12: 标注面计算 (纯标注, 不改方向结论)
    evr_state, evr_level, evr_position_context = "none", 0, ""
    if hasattr(step2, "vdb_divergence") and step2.vdb_divergence != "none":
        evr_state = step2.vdb_divergence
        evr_level = 3
    pattern_failure_detected = False
    pattern_failure_ratio = 0.0
    if step1.boundary_upper > 0 and step1.boundary_lower > 0:
        range_width = step1.boundary_upper - step1.boundary_lower
        if range_width > 0 and current_price > 0:
            if step1.phase == WyckoffPhase.ACCUMULATION and current_price < step1.boundary_lower:
                fail_dist = (step1.boundary_lower - current_price) / range_width
                if fail_dist > 0.33:
                    pattern_failure_detected = True
                    pattern_failure_ratio = fail_dist
            elif step1.phase == WyckoffPhase.DISTRIBUTION and current_price > step1.boundary_upper:
                fail_dist = (current_price - step1.boundary_upper) / range_width
                if fail_dist > 0.33:
                    pattern_failure_detected = True
                    pattern_failure_ratio = fail_dist
    no_supply_detected = bool(
        step3.spring_volume in ("地量", "萎缩") if step3.spring_volume else False
    )
    nsd_detected = False
    vdu_detected = False
    if len(df) >= 5:
        recent_vol = df["volume"].tail(5).mean()
        hist_vol = df["volume"].tail(60).mean() if len(df) >= 60 else df["volume"].mean()
        if hist_vol > 0:
            vol_ratio = recent_vol / hist_vol
            if vol_ratio < 0.5:
                vdu_detected = True
            elif vol_ratio < 0.7:
                nsd_detected = True
    event_cooldown_active = False
    event_cooldown_days = 0
    if step3.spring_detected or step3.utad_detected or sos_candidate_detected_flag:
        event_cooldown_active = True
        event_cooldown_days = 5
    range_score = 0.0
    if step1.boundary_upper > 0 and step1.boundary_lower > 0:
        range_width = step1.boundary_upper - step1.boundary_lower
        if range_width > 0:
            range_score = min(round(structural_score / 100.0, 2), 1.0)
    avwap = 0.0
    if len(df) >= 5:
        recent_5 = df.tail(5)
        pv = (recent_5["close"] * recent_5["volume"]).sum()
        v = recent_5["volume"].sum()
        if v > 0:
            avwap = round(float(pv / v), 2)
    bias200 = 0.0
    bias_base = full_frame if full_frame is not None and len(full_frame) >= 200 else df
    if len(bias_base) >= 200:
        ma200 = float(bias_base["close"].tail(200).mean())
        if ma200 > 0:
            bias200 = round((current_price - ma200) / ma200, 4)

    return WyckoffReport(
        symbol=symbol,
        period=period,
        structure=structure,
        signal=signal,
        risk_reward=risk_reward,
        trading_plan=trading_plan,
        limit_moves=limit_moves,
        stress_tests=stress_tests,
        chip_analysis=chip_analysis,
        pnf_analysis=pnf_result,
        regime_phase=regime_phase,
        adjustment_status=adjustment_status,
        structural_score=structural_score,
        relative_strength=relative_strength,
        relative_strength_detail=relative_strength_detail,
        engine_version="v3.0",
        ruleset_version="v3.0",
        pnf_phase_divergence=pnf_phase_divergence,
        vdb_divergence=step2.vdb_divergence,
        lps_stage=step3.lps_stage,
        sos_candidate_detected=sos_candidate_detected_flag,
        evr_state=evr_state,
        evr_level=evr_level,
        evr_position_context=evr_position_context,
        pattern_failure_detected=pattern_failure_detected,
        pattern_failure_ratio=pattern_failure_ratio,
        no_supply_detected=no_supply_detected,
        nsd_detected=nsd_detected,
        vdu_detected=vdu_detected,
        event_cooldown_active=event_cooldown_active,
        event_cooldown_days=event_cooldown_days,
        range_score=range_score,
        avwap=avwap,
        bias200=bias200,
    )


__all__ = ["build_wyckoff_report"]
