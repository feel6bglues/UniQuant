# -*- coding: utf-8 -*-
"""
Wyckoff Event Detection Module.
Handles BC, SC, Spring, Upthrust, UTAD, False Breakout, SOS, and Phase C Testing.
"""

from typing import Callable, Optional, Tuple

import numpy as np
import pandas as pd

from uniquant.brain.indicators.indicators import Indicators
from uniquant.brain.wyckoff.classifiers import classify_volume, detect_limit_moves
from uniquant.brain.wyckoff.effort_result import detect_effort_result_divergence
from uniquant.brain.wyckoff.models import (
    BCPoint,
    Rule0Result,
    SCPoint,
    Step1Result,
    Step2Result,
    Step3Result,
    WyckoffPhase,
)
from uniquant.brain.wyckoff.rules import V3Rules


def scan_bc_sc(
    df: pd.DataFrame, rules: Optional[V3Rules] = None
) -> Tuple[Optional[BCPoint], Optional[SCPoint]]:
    """Vectorized BC/SC Scoring System using Pandas/NumPy array operations."""
    if df.empty:
        return None, None

    if rules is None:
        rules = V3Rules()

    df = df.copy()
    n = len(df)

    # 1. Basic metrics vectorization
    vol_rank = df["volume"].rank(pct=True).to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()

    ranges = high - low
    shadow_upper = high - close
    shadow_lower = close - low

    shadow_ratio_up = shadow_upper / (ranges + 1e-9)
    shadow_ratio_lo = shadow_lower / (ranges + 1e-9)

    # 2. Subsequent price movement vectorization
    # Rolling min/max backwards using flip
    close_rev = close[::-1]

    # Get subsequent 9-day low/high: rolling window of size 9, then shifted
    sub_low_rev = pd.Series(close_rev).rolling(9, min_periods=1).min().to_numpy()
    sub_high_rev = pd.Series(close_rev).rolling(9, min_periods=1).max().to_numpy()

    subsequent_low = sub_low_rev[::-1]
    subsequent_high = sub_high_rev[::-1]

    # Shift forward by 1 (which means subsequent days after index i)
    subsequent_low = np.roll(subsequent_low, -1)
    subsequent_low[-1] = close[-1]
    subsequent_high = np.roll(subsequent_high, -1)
    subsequent_high[-1] = close[-1]

    # 3. Vectorized scoring for BC
    bc_scores = np.zeros(n)
    bc_scores += np.where(vol_rank > 0.8, 2, np.where(vol_rank > 0.6, 1, 0))
    bc_scores += np.where(shadow_ratio_up > 0.6, 2, np.where(shadow_ratio_up > 0.4, 1, 0))

    # Drop check
    drop_pct = (high - subsequent_low) / (high + 1e-9)
    mask_last5 = np.arange(n) < (n - 5)
    bc_scores += np.where((drop_pct > 0.05) & mask_last5, 2, 0)

    # 4. Vectorized scoring for SC
    sc_scores = np.zeros(n)
    sc_scores += np.where(vol_rank > 0.8, 2, 0)
    sc_scores += np.where(shadow_ratio_lo > 0.6, 2, np.where(shadow_ratio_lo > 0.4, 1, 0))

    # Rise check
    rise_pct = (subsequent_high - low) / (low + 1e-9)
    sc_scores += np.where((rise_pct > 0.05) & mask_last5, 2, 0)

    # 5. Extract top candidates
    df["bc_score"] = bc_scores
    df["sc_score"] = sc_scores

    peak_idx = df["high"].idxmax()
    trough_idx = df["low"].idxmin()

    # Get highest score first, then nlargest to resolve
    bc_candidates = df.sort_values(by=["bc_score", "high"], ascending=[False, False])
    sc_candidates = df.sort_values(by=["sc_score", "low"], ascending=[False, True])

    bc_point = None
    sc_point = None

    if not bc_candidates.empty:
        best_bc = bc_candidates.iloc[0]
        score = float(best_bc["bc_score"])
        with np.errstate(over="ignore"):
            prob_confidence = 1.0 / (1.0 + np.exp(-(score - 3.0)))

        volume_level = classify_volume(best_bc["volume"], df["volume"], rules=rules)
        bc_point = BCPoint(
            date=str(best_bc["date"]),
            price=float(best_bc["high"]),
            volume_level=volume_level,
            is_extremum=(best_bc.name == peak_idx),
            confidence_score=prob_confidence,
        )

    if not sc_candidates.empty:
        best_sc = sc_candidates.iloc[0]
        score = float(best_sc["sc_score"])
        with np.errstate(over="ignore"):
            prob_confidence = 1.0 / (1.0 + np.exp(-(score - 3.0)))

        volume_level = classify_volume(best_sc["volume"], df["volume"], rules=rules)
        sc_point = SCPoint(
            date=str(best_sc["date"]),
            price=float(best_sc["low"]),
            volume_level=volume_level,
            is_extremum=(best_sc.name == trough_idx),
            confidence_score=prob_confidence,
        )

    return bc_point, sc_point


def scan_spring(df: pd.DataFrame, boundary_lower: float) -> Optional[dict]:
    """Scan for Spring in the recent window.

    O 列跌破 TR 下沿 0.5-1.5% 后 1-2 列内收回 + 量能萎缩确认。
    返回 {"date": str, "low": float, "vol_ratio": float, "pos": int} 或 None。
    """
    if boundary_lower <= 0 or len(df) < 5:
        return None
    recent = df.tail(30)
    vol_med = float(recent["volume"].median())
    if vol_med <= 0:
        return None
    lows = recent["low"].to_numpy()
    closes = recent["close"].to_numpy()
    vols = recent["volume"].to_numpy()
    dates = recent["date"].to_numpy()
    n = len(recent)
    offset = len(df) - n
    for i in range(n):
        low = lows[i]
        # O 列跌破 TR 下沿 0.5-1.5%（跌破但不过深）
        if not (boundary_lower * 0.985 <= low < boundary_lower):
            continue
        # 量能萎缩确认
        vol_ratio = vols[i] / vol_med if vol_med > 0 else 0.0
        if vol_ratio > 0.8:
            continue  # 量能未萎缩
        # 1-2 列内收回
        for j in range(i + 1, min(i + 3, n)):
            if closes[j] >= boundary_lower:
                return {
                    "date": str(dates[i]),
                    "low": float(low),
                    "vol_ratio": vol_ratio,
                    "pos": offset + i,
                }
    return None


def scan_utad(df: pd.DataFrame, boundary_upper: float) -> Optional[dict]:
    """Scan for UTAD (Upthrust After Distribution) in the recent window.

    X 列突破 TR 上沿 2%+ 后 1-2 列内收回 + 放量确认（量比 > 1.5）。
    返回 {"date": str, "vol_ratio": float} 或 None。
    """
    if boundary_upper <= 0 or len(df) < 5:
        return None
    recent = df.tail(30)
    vol_med = float(recent["volume"].median())
    if vol_med <= 0:
        return None
    highs = recent["high"].to_numpy()
    closes = recent["close"].to_numpy()
    vols = recent["volume"].to_numpy()
    dates = recent["date"].to_numpy()
    n = len(recent)
    for i in range(n):
        if highs[i] <= boundary_upper * 1.02:
            continue  # 未突破 TR 上沿 2%+
        vol_ratio = vols[i] / vol_med if vol_med > 0 else 0.0
        if vol_ratio <= 1.5:
            continue  # 量能不足
        for j in range(i, min(i + 3, n)):
            if closes[j] <= boundary_upper * 1.01:  # 1-2 列内收回
                return {"date": str(dates[i]), "vol_ratio": vol_ratio}
    return None


def scan_false_breakout(df: pd.DataFrame, boundary_upper: float) -> Optional[dict]:
    """CF-C4: 检测假突破（突破 TR 上沿 2%+ 后 3 列内跌回 TR）。

    与 UTAD 同源：突破上沿需放量确认（量比>1.5），但跌回窗口放宽到 3 列，
    用于标记 false_breakout 惩罚（信号置信度降级）。
    返回 {"date": str, "close_high": float} 或 None。
    """
    if boundary_upper <= 0 or len(df) < 5:
        return None
    recent = df.tail(30)
    highs = recent["high"].to_numpy()
    closes = recent["close"].to_numpy()
    volumes = recent["volume"].to_numpy()
    dates = recent["date"].to_numpy()
    n = len(recent)
    vol_med = float(np.median(volumes)) if n else 0.0
    for i in range(n - 1):
        if highs[i] <= boundary_upper * 1.02:
            continue  # 未显著突破 TR 上沿
        if vol_med <= 0 or volumes[i] < 1.5 * vol_med:
            continue  # 量能不足
        for j in range(i + 1, min(i + 4, n)):  # 3 列内
            if closes[j] <= boundary_upper * 0.995:  # 跌回上沿下方
                return {"date": str(dates[i]), "close_high": float(highs[i])}
    return None


def detect_spring(df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
    """Detect spring/Selling Climax pattern as an accumulation hint."""
    if not (ctx["short_trend_pct"] <= -0.02 and ctx["relative_position"] <= 0.55):
        return None
    last_row = df.iloc[-1]
    close_val = float(last_row["close"])
    open_val = float(last_row["open"])
    high_val = float(last_row["high"])
    low_val = float(last_row["low"])
    body_val = abs(close_val - open_val)
    lower_wick_val = min(close_val, open_val) - low_val
    close_loc = (close_val - low_val) / max(high_val - low_val, 0.01)
    amplitude = (high_val - low_val) / max(low_val, 0.01)
    is_new_low = low_val == df.iloc[-11:-1]["low"].min()
    wick_ratio = lower_wick_val / max(body_val, 0.01)
    rebound_ratio = (close_val - low_val) / max(low_val, 0.01)
    if amplitude >= 0.02:
        if (close_loc >= 0.58 and lower_wick_val > body_val) or (
            is_new_low and rebound_ratio >= 0.01 and wick_ratio >= 0.6
        ):
            return {"phase": WyckoffPhase.UNKNOWN, "unknown_candidate": "sc_st_candidate"}
    return None


def detect_utad(
    df: pd.DataFrame,
    ctx: dict,
    rule0: Rule0Result,
    scan_utad_fn: Optional[Callable] = None,
) -> Optional[dict]:
    """Detect UTAD (Upthrust After Distribution) pattern."""
    boundary_upper = rule0.tr_upper if rule0.tr_upper else ctx["price_high"]
    fn = scan_utad_fn or scan_utad
    if fn(df, boundary_upper) is not None:
        return {"phase": WyckoffPhase.DISTRIBUTION, "unknown_candidate": "upthrust_candidate"}
    return None


def detect_sos(df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
    """P1-3: 检测 SOS (Sign of Strength) 候选信号。

    判断条件:
      1. 价格突破 TR 上沿 (close > boundary_upper * 0.98)
      2. 量能确认 (volume > 20日均量 * 1.2)
      3. 收盘价在 K 线上半部 (c_loc >= 0.5)
    """
    boundary_upper = rule0.boundary_upper if hasattr(rule0, "boundary_upper") else 0
    if boundary_upper <= 0:
        return None
    recent = df.tail(5)
    avg_vol = float(df["volume"].tail(20).mean()) if len(df) >= 20 else float(df["volume"].mean())
    if avg_vol <= 0:
        return None
    for row in recent.itertuples():
        c_val = float(row.close)
        if c_val > boundary_upper * 0.98:
            c_loc = (c_val - float(row.low)) / max(float(row.high) - float(row.low), 0.01)
            if c_loc >= 0.5:
                vol_ratio = float(row.volume) / avg_vol
                if vol_ratio > 1.2:
                    return {
                        "date": str(row.date),
                        "close": c_val,
                        "vol_ratio": vol_ratio,
                        "boundary_upper": boundary_upper,
                    }
    return None


def step2_effort_result(df: pd.DataFrame, step1: Step1Result) -> Step2Result:
    """Step 2: 努力与结果（含跳空缺口检测与量价背离）"""
    phenomena = []
    accumulation_evidence = 0.0
    distribution_evidence = 0.0

    recent_20 = df.tail(20)
    if len(recent_20) < 10:
        return Step2Result()

    avg_vol = recent_20["volume"].mean()
    price_change = (recent_20["close"].iloc[-1] - recent_20["close"].iloc[0]) / recent_20[
        "close"
    ].iloc[0]
    vol_change = (recent_20["volume"].iloc[-1] - avg_vol) / avg_vol if avg_vol > 0 else 0

    # 成交额维度分析（基于amount）
    if "amount" in recent_20.columns and recent_20["amount"].notna().all():
        avg_amt = recent_20["amount"].mean()
        amt_change = (recent_20["amount"].iloc[-1] - avg_amt) / avg_amt if avg_amt > 0 else 0

        # 金额与成交量同步放大 → 确认异常
        if amt_change > 0.3 and vol_change > 0.3 and abs(price_change) < 0.02:
            distribution_evidence += 0.4
            phenomena.append("量额双放大滞涨")

        # 金额放大但量缩 → 大单交易（金额主导的吸筹/派发）
        if amt_change > 0.2 and vol_change < -0.2:
            if price_change > 0.02:
                accumulation_evidence += 0.3
                phenomena.append("大单推升（金额放量但量能萎缩）")
            elif price_change < -0.02:
                distribution_evidence += 0.3
                phenomena.append("大单砸盘（金额放量但量能萎缩）")

        # 金额萎缩但量放大 → 散户化交易
        if amt_change < -0.2 and vol_change > 0.2:
            phenomena.append("散户化交易（量增额缩）")

    # 放量滞涨 → 派发倾向
    if vol_change > 0.3 and abs(price_change) < 0.02:
        distribution_evidence += 0.3
        phenomena.append("放量滞涨")

    # 缩量上推 → 吸筹倾向
    if vol_change < -0.3 and price_change > 0.02:
        accumulation_evidence += 0.2
        phenomena.append("缩量上推")

    # 下边界供给枯竭
    if step1.boundary_lower > 0:
        recent_low = float(recent_20["low"].min())
        if recent_low <= step1.boundary_lower * 1.02:
            low_vol = recent_20[recent_20["low"] <= step1.boundary_lower * 1.02]["volume"].mean()
            if low_vol < avg_vol * 0.7:
                accumulation_evidence += 0.3
                phenomena.append("下边界供给枯竭")

    # 高位炸板遗迹
    for row in recent_20.itertuples():
        pct = (row.close - row.open) / row.open if row.open > 0 else 0
        if pct > 0.09 and row.high > row.close * 1.02:
            distribution_evidence += 0.3
            phenomena.append("高位炸板遗迹")
            break

    # 跳空缺口检测
    has_breakaway_gap = False
    has_exhaustion_gap = False
    has_escape_gap = False
    for i in range(1, len(recent_20)):
        prev_row = recent_20.iloc[i - 1]
        curr_row = recent_20.iloc[i]

        # 向上跳空缺口：当前最低价 > 前一天最高价
        if curr_row["low"] > prev_row["high"]:
            gap_size = (curr_row["low"] - prev_row["high"]) / prev_row["high"] * 100
            if gap_size > 1.0:  # 缺口大于1%
                # 判断缺口类型
                if curr_row["close"] > curr_row["open"]:  # 阳线
                    phenomena.append(f"向上突破缺口({gap_size:.1f}%)")
                    accumulation_evidence += 0.2
                    has_breakaway_gap = True
                else:  # 阴线
                    phenomena.append(f"向上竭尽缺口({gap_size:.1f}%)")
                    distribution_evidence += 0.2
                    has_exhaustion_gap = True

        # 向下跳空缺口：当前最高价 < 前一天最低价
        elif curr_row["high"] < prev_row["low"]:
            gap_size = (prev_row["low"] - curr_row["high"]) / prev_row["low"] * 100
            if gap_size > 1.0:  # 缺口大于1%
                # 判断缺口类型
                if curr_row["close"] < curr_row["open"]:  # 阴线
                    phenomena.append(f"向下逃逸缺口({gap_size:.1f}%)")
                    distribution_evidence += 0.3
                    has_escape_gap = True
                else:  # 阳线
                    phenomena.append(f"向下竭尽缺口({gap_size:.1f}%)")
                    accumulation_evidence += 0.2

    net_bias = "neutral"
    if accumulation_evidence > distribution_evidence + 0.1:
        net_bias = "accumulation"
    elif distribution_evidence > accumulation_evidence + 0.1:
        net_bias = "distribution"

    vdb = detect_effort_result_divergence(df)
    if vdb != "none":
        phenomena.append(f"量价背离({vdb})")

    return Step2Result(
        phenomena=phenomena,
        accumulation_evidence=round(accumulation_evidence, 2),
        distribution_evidence=round(distribution_evidence, 2),
        net_bias=net_bias,
        has_breakaway_gap=has_breakaway_gap,
        has_exhaustion_gap=has_exhaustion_gap,
        has_escape_gap=has_escape_gap,
        vdb_divergence=vdb,
    )


def step3_phase_c_t1(
    df: pd.DataFrame,
    step1: Step1Result,
    rule0: Rule0Result,
    rules: V3Rules,
    scan_spring_fn: Optional[Callable] = None,
    scan_utad_fn: Optional[Callable] = None,
    detect_sos_fn: Optional[Callable] = None,
    detect_limit_moves_fn: Optional[Callable] = None,
) -> Step3Result:
    """Step 3: Spring/UTAD + T+1 风险"""
    spring_detected = False
    spring_quality = "无"
    spring_date = None
    spring_low_price = None
    utad_detected = False
    utad_date = None
    utad_quality = "无"
    st_detected = False
    sos_candidate_detected = False
    lps_confirmed = False
    lps_stage = "not_test"
    test_low = None
    spring_volume = ""

    _scan_spring = scan_spring_fn or scan_spring
    _scan_utad = scan_utad_fn or scan_utad
    _detect_sos = detect_sos_fn or detect_sos

    # ATR 提前计算（LPS 判定需要）
    atr_series = Indicators.calc_atr(df)
    current_atr = float(atr_series.iloc[-1]) if len(atr_series) > 0 else 0.0

    # Spring 检测（在 ACCUMULATION、UNKNOWN 和 MARKUP 阶段都可能有效）
    if (
        step1.phase in (WyckoffPhase.ACCUMULATION, WyckoffPhase.UNKNOWN, WyckoffPhase.MARKUP)
        and step1.boundary_lower > 0
    ):
        low_bound = step1.boundary_lower
        spring_found = _scan_spring(df, low_bound)

        if spring_found is not None:
            spring_detected = True
            spring_date = spring_found["date"]
            spring_low_price = spring_found["low"]

            # 量能质量评估（基于 Spring 当日量比）
            vol_ratio = spring_found["vol_ratio"]
            spring_volume = rules.rule1_relative_volume(
                vol_ratio * float(df["volume"].tail(30).median()),
                df["volume"],
            )
            if spring_volume in ("地量", "萎缩"):
                spring_quality = "二级(缩量待确认)"
            else:
                spring_quality = "一级(放量确认)"

            # Spring 当日数值量（LPS 供给枯竭参照）
            spring_volume_value = float(df["volume"].iloc[spring_found["pos"]])

            # LPS 验证（规则6）- 分层判定（P0-A 重构）
            post_spring_idx = spring_found["pos"]
            if post_spring_idx < len(df) - 3:
                post_spring_df = df.iloc[post_spring_idx + 1 :]
                lps_result = rules.rule6_spring_validation(
                    True,
                    post_spring_df,
                    spring_low_price,
                    spring_volume=spring_volume_value,
                    atr=current_atr,
                )
                lps_confirmed = lps_result["lps_confirmed"]
                lps_stage = lps_result.get("lps_stage", "not_test")
                test_low = lps_result.get("test_low")
                if lps_confirmed:
                    spring_quality = lps_result["quality"]

        # 如果没有检测到Spring，检查是否有SOS信号
        if not spring_detected and step1.phase == WyckoffPhase.ACCUMULATION:
            if step1.boundary_upper > 0:
                recent_5 = df.tail(5)
                for row in recent_5.itertuples():
                    if row.close > step1.boundary_upper * 0.95:
                        vol_level = rules.rule1_relative_volume(row.volume, df["volume"])
                        if vol_level in ("高于平均", "天量", "平均"):
                            st_detected = True
                            sos_candidate_detected = True
                            break

    # P1-3: 独立 SOS 检测 (TR 上沿突破 + 量能确认，不拘泥于 ACCUMULATION 阶段)
    if not sos_candidate_detected and step1.boundary_upper > 0:
        sos_found = _detect_sos(df, {}, rule0)
        if sos_found is not None:
            sos_candidate_detected = True

    # UTAD 检测（DISTRIBUTION 阶段）：X 列突破上沿 2%+ → 1-2 列内收回 + 放量确认
    if step1.phase == WyckoffPhase.DISTRIBUTION and step1.boundary_upper > 0:
        utad_found = _scan_utad(df, step1.boundary_upper)
        if utad_found is not None:
            utad_detected = True
            utad_date = utad_found["date"]
            vol_ratio = utad_found["vol_ratio"]
            if vol_ratio >= 2.0:
                utad_quality = "一级(放量确认)"
            else:
                utad_quality = "二级(温和放量)"

    # T+1 压力测试（含涨跌停流动性警告 + ATR动态阈值）
    current_price = float(df.iloc[-1]["close"])
    recent_30_low = float(df.tail(30)["low"].min())
    if detect_limit_moves_fn is not None:
        limit_moves = detect_limit_moves_fn(df)
    else:
        limit_moves = detect_limit_moves(df, rules=rules)
    limit_moves_data = [{"price": lm.price, "type": lm.move_type.value} for lm in limit_moves]
    t1_result = rules.rule3_t1_risk_test(
        current_price, recent_30_low, limit_moves_data, current_atr
    )

    return Step3Result(
        spring_detected=spring_detected,
        spring_quality=spring_quality,
        spring_date=spring_date,
        spring_low_price=spring_low_price,
        utad_detected=utad_detected,
        utad_quality=utad_quality,
        utad_date=utad_date,
        st_detected=st_detected,
        sos_candidate_detected=sos_candidate_detected,
        lps_confirmed=lps_confirmed,
        lps_stage=lps_stage,
        test_low=test_low,
        spring_volume=spring_volume,
        t1_max_drawdown_pct=t1_result["pct"],
        t1_verdict=t1_result["verdict"],
        t1_description=t1_result["desc"],
    )


__all__ = [
    "detect_sos",
    "detect_spring",
    "detect_utad",
    "scan_bc_sc",
    "scan_false_breakout",
    "scan_spring",
    "scan_utad",
    "step2_effort_result",
    "step3_phase_c_t1",
]
