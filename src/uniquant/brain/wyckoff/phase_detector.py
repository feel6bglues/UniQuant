# -*- coding: utf-8 -*-
"""
Wyckoff Phase Detection and Transition Logic Module.
"""

from typing import Callable, List, Optional

import pandas as pd

from uniquant.brain.wyckoff.classifiers import (
    classify_accumulation_sub_phase,
    classify_distribution_sub_phase,
    classify_unknown_candidate,
)
from uniquant.brain.wyckoff.constants import (
    ENGINE_DEFAULT_RANGE_THRESHOLD,
    ENGINE_DEFAULT_TREND_THRESHOLD,
)
from uniquant.brain.wyckoff.event_detector import (
    detect_sos,
    detect_spring,
    detect_utad,
    scan_bc_sc,
    scan_utad,
)
from uniquant.brain.wyckoff.events import detect_all_events, event_sequence_key
from uniquant.brain.wyckoff.models import (
    Rule0Result,
    Step1Result,
    WyckoffPhase,
)
from uniquant.brain.wyckoff.rules import V3Rules
from uniquant.shared.logger_factory import get_logger

logger = get_logger(__name__)


def compute_step1_context(
    df: pd.DataFrame,
    rule0: Rule0Result,
    range_threshold: float = ENGINE_DEFAULT_RANGE_THRESHOLD,
    trend_threshold: float = ENGINE_DEFAULT_TREND_THRESHOLD,
) -> dict:
    """Compute preliminary metrics shared by all phase detectors."""
    recent_60 = df.tail(60)
    price_high = float(recent_60["high"].max())
    price_low = float(recent_60["low"].min())
    current_price = float(df.iloc[-1]["close"])
    ma5 = float(df.shift(1).tail(5)["close"].mean())
    ma20 = float(df.shift(1).tail(20)["close"].mean())
    total_range_pct = (price_high - price_low) / price_low if price_low > 0 else 1.0
    relative_position = (
        (current_price - price_low) / (price_high - price_low)
        if price_high > price_low
        else 0.5
    )

    if len(df) >= 40:
        recent_mean = float(df.shift(1).tail(20)["close"].mean())
        prev_mean = float(df.iloc[-40:-20]["close"].mean())
    else:
        recent_mean = float(df.shift(1).tail(10)["close"].mean())
        prev_mean = float(df.head(10)["close"].mean())
    short_trend_pct = (recent_mean - prev_mean) / prev_mean if prev_mean > 0 else 0.0

    is_in_trading_range = (
        total_range_pct <= range_threshold
    ) and (abs(short_trend_pct) < trend_threshold)

    prior_window = df.iloc[:-60] if len(df) > 60 else pd.DataFrame()
    if len(prior_window) >= 10:
        prior_first = float(prior_window["close"].iloc[0])
        prior_last = float(prior_window["close"].iloc[-1])
        prior_trend_pct = (
            (prior_last - prior_first) / prior_first if prior_first > 0 else 0.0
        )
    else:
        prior_trend_pct = 0.0

    return {
        "price_high": price_high,
        "price_low": price_low,
        "current_price": current_price,
        "ma5": ma5,
        "ma20": ma20,
        "total_range_pct": total_range_pct,
        "relative_position": relative_position,
        "short_trend_pct": short_trend_pct,
        "is_in_trading_range": is_in_trading_range,
        "prior_trend_pct": prior_trend_pct,
    }


def detect_accumulation(
    df: pd.DataFrame,
    ctx: dict,
    rule0: Rule0Result,
    calibration: Optional[dict] = None,
) -> Optional[dict]:
    """Detect accumulation phase."""
    cal = calibration or {}
    st_max = cal.get("accum_short_trend_max", -0.02)
    require_both = cal.get("accum_require_both_bc_sc", False)

    # PH-C1: 事件序列优先驱动 ACCUMULATION（忽略 price_position）
    try:
        events = detect_all_events(df)
        seq_key = event_sequence_key(events)
        if "PS" in seq_key and "SC" in seq_key and seq_key.count("ST") >= 2:
            return {
                "phase": WyckoffPhase.ACCUMULATION,
                "unknown_candidate": "accumulation_event_sequence",
            }
    except (AttributeError, TypeError, ValueError, KeyError):
        logger.warning("Event sequence detection failed for accumulation", exc_info=True)

    # 前置守卫: 若最近 5 根创新低(>2%)则不是积累(仍在下跌)
    if len(df) >= 10:
        recent_5_low = float(df.tail(5)["low"].min())
        recent_10_low = float(df.tail(10)["low"].min())
        if recent_10_low > 0 and recent_5_low < recent_10_low * 0.98:
            return None

    if ctx["is_in_trading_range"]:
        if ctx["prior_trend_pct"] < -0.03:
            return {"phase": WyckoffPhase.ACCUMULATION}
        if ctx["relative_position"] <= 0.40 and rule0.bc_found:
            return {"phase": WyckoffPhase.ACCUMULATION}
    else:
        bc_sc_ok = (
            (rule0.bc_found and rule0.sc_found)
            if require_both
            else (rule0.bc_found or rule0.sc_found)
        )
        if (
            ctx["short_trend_pct"] <= st_max
            and ctx["current_price"] < ctx["ma20"]
            and ctx["ma5"] <= ctx["ma20"]
            and bc_sc_ok
        ):
            return {"phase": WyckoffPhase.ACCUMULATION}
    return None


def detect_markup(
    df: pd.DataFrame,
    ctx: dict,
    rule0: Rule0Result,
    calibration: Optional[dict] = None,
) -> Optional[dict]:
    """Detect markup phase."""
    cal = calibration or {}
    st_min = cal.get("markup_short_trend_min", 0.03)
    rp_min = cal.get("markup_relative_position_min", 0.50)
    cp_above_ma = cal.get("markup_cp_above_ma", 0.97)

    cp = ctx["current_price"]
    ma5 = ctx["ma5"]
    ma20 = ctx["ma20"]
    rp = ctx["relative_position"]
    st = ctx["short_trend_pct"]

    if ctx["is_in_trading_range"]:
        if (rp >= 0.55 or st >= st_min) and (
            (cp > ma20 * cp_above_ma and ma5 >= ma20 * 0.96) or (cp > ma5 and rp >= rp_min)
        ):
            return {"phase": WyckoffPhase.MARKUP}
    else:
        if st >= st_min and ((cp > ma20 and ma5 >= ma20) or (cp > ma5 and rp >= rp_min)):
            return {"phase": WyckoffPhase.MARKUP}
        if st >= 0.015 and cp > ma20 and ma5 >= ma20 * 0.98 and rp >= 0.70:
            return {"phase": WyckoffPhase.MARKUP}
        if st >= 0.05 and ma5 >= ma20 and cp >= ma20 * 0.99 and rp >= 0.65:
            return {"phase": WyckoffPhase.MARKUP}
    return None


def detect_distribution(
    df: pd.DataFrame,
    ctx: dict,
    rule0: Rule0Result,
    calibration: Optional[dict] = None,
    scan_utad_fn: Optional[Callable] = None,
) -> Optional[dict]:
    """Detect distribution phase."""
    # PH-C2: 事件序列优先驱动 DISTRIBUTION（UTAD 假突破 + 放量，忽略 price_position）
    cal = calibration or {}
    prior_trend_min = cal.get("distribution_prior_trend_min", 0.05)

    boundary_upper = rule0.tr_upper if rule0.tr_upper else ctx["price_high"]
    _scan_utad = scan_utad_fn or scan_utad
    if boundary_upper > 0 and _scan_utad(df, boundary_upper) is not None:
        return {
            "phase": WyckoffPhase.DISTRIBUTION,
            "unknown_candidate": "upthrust_candidate",
        }
    if ctx["is_in_trading_range"] and ctx["prior_trend_pct"] > prior_trend_min:
        return {"phase": WyckoffPhase.DISTRIBUTION}
    return None


def detect_markdown(
    df: pd.DataFrame,
    ctx: dict,
    rule0: Rule0Result,
    calibration: Optional[dict] = None,
) -> Optional[dict]:
    """Detect markdown phase."""
    cal = calibration or {}
    st_max = cal.get("markdown_short_trend_max", -0.05)
    cp_below_ma = cal.get("markdown_cp_below_ma", 0.95)

    cp = ctx["current_price"]
    ma5 = ctx["ma5"]
    ma20 = ctx["ma20"]
    rp = ctx["relative_position"]
    st = ctx["short_trend_pct"]

    if ctx["is_in_trading_range"]:
        if (
            rule0.bc_found
            and rule0.bc_position is not None
            and cp <= rule0.bc_position.price * 0.85
            and cp < ma20 * cp_below_ma
            and ma5 <= ma20
            and st <= -0.02
        ):
            return {"phase": WyckoffPhase.MARKDOWN}
    else:
        if st <= st_max and cp < ma20 * cp_below_ma:
            return {"phase": WyckoffPhase.MARKDOWN}
        if (
            rule0.bc_found
            and rule0.bc_position is not None
            and cp <= rule0.bc_position.price * 0.90
            and cp < ma20
            and ma5 <= ma20
            and st <= 0
        ):
            return {"phase": WyckoffPhase.MARKDOWN}
        if (
            rule0.bc_found
            and rule0.bc_position is not None
            and st <= -0.04
            and rp <= 0.25
            and cp <= rule0.bc_position.price * 0.75
        ):
            return {"phase": WyckoffPhase.MARKDOWN}
    return None


def step0_bc_tr_scan(
    df: pd.DataFrame,
    pnf_zone: Optional[tuple] = None,
    scan_bc_sc_fn: Optional[Callable] = None,
    range_threshold: float = ENGINE_DEFAULT_RANGE_THRESHOLD,
    rules: Optional[V3Rules] = None,
) -> Rule0Result:
    """Step 0: BC/TR 定位扫描"""
    if rules is None:
        rules = V3Rules()
    _scan = scan_bc_sc_fn or (lambda d: scan_bc_sc(d, rules=rules))
    bc_point, sc_point = _scan(df)

    # 计算 TR 边界：P&F 水平密集区优先（PF-C3），否则回落 OHLC 高低点
    recent_60 = df.tail(60)
    if pnf_zone and len(pnf_zone) == 2 and pnf_zone[1] > pnf_zone[0] > 0:
        tr_upper = float(pnf_zone[1])
        tr_lower = float(pnf_zone[0])
        tr_source_override = "pnf_congestion"
    else:
        tr_upper = float(recent_60["high"].max())
        tr_lower = float(recent_60["low"].min())
        tr_source_override = None

    bc_found = bc_point is not None
    sc_found = sc_point is not None
    tr_defined = (
        (tr_upper - tr_lower) / tr_lower <= range_threshold * 1.25 if tr_lower > 0 else False
    )

    fallback = rules.rule5_bc_tr_fallback(bc_found, tr_defined)

    tr_source = tr_source_override or (
        "bc_ar"
        if bc_found
        else ("sc_spring" if sc_found else ("rolling_range" if tr_defined else "none"))
    )

    return Rule0Result(
        bc_found=bc_found,
        bc_position=bc_point,
        sc_found=sc_found,
        sc_position=sc_point,
        bc_in_chart=bc_found,
        tr_upper=tr_upper if tr_defined else None,
        tr_lower=tr_lower if tr_defined else None,
        tr_source=tr_source,
        validity=fallback["validity"],
        confidence_base=fallback["confidence_base"],
    )


def step1_phase_determine(
    df: pd.DataFrame,
    rule0: Rule0Result,
    pnf_hint: Optional[str] = None,
    range_threshold: float = ENGINE_DEFAULT_RANGE_THRESHOLD,
    trend_threshold: float = ENGINE_DEFAULT_TREND_THRESHOLD,
    calibration: Optional[dict] = None,
    detectors: Optional[List[Callable]] = None,
    classify_unknown_candidate_fn: Optional[Callable] = None,
    classify_accumulation_sub_phase_fn: Optional[Callable] = None,
    classify_distribution_sub_phase_fn: Optional[Callable] = None,
) -> Step1Result:
    """Step 1: 大局观与阶段判定（分派到7个检测器，P&F phase_hint 优先驱动）"""
    ctx = compute_step1_context(df, rule0, range_threshold, trend_threshold)

    phase = WyckoffPhase.UNKNOWN
    unknown_candidate = ""
    pnf_phase_divergence: Optional[str] = None

    # 总是运行检测器链（用于分歧分析）
    chain_phase = WyckoffPhase.UNKNOWN
    chain_unknown_candidate = ""

    if detectors is None:
        detectors = [
            lambda d, c, r: detect_markup(d, c, r, calibration),
            lambda d, c, r: detect_distribution(d, c, r, calibration),
            lambda d, c, r: detect_markdown(d, c, r, calibration),
            lambda d, c, r: detect_accumulation(d, c, r, calibration),
            lambda d, c, r: detect_spring(d, c, r),
            lambda d, c, r: detect_utad(d, c, r),
            lambda d, c, r: detect_sos(d, c, r),
        ]

    for detector in detectors:
        result = detector(df, ctx, rule0)
        if result is not None:
            chain_phase = result["phase"]
            chain_unknown_candidate = result.get("unknown_candidate", "")
            break

    if chain_phase == WyckoffPhase.UNKNOWN and not chain_unknown_candidate:
        _classify_unknown = classify_unknown_candidate_fn or classify_unknown_candidate
        chain_unknown_candidate = _classify_unknown(df, chain_phase, rule0)

    # PF-C1: P&F phase_hint 明确时优先驱动阶段判定，但记录分歧
    if pnf_hint in ("accumulation", "distribution"):
        phase = (
            WyckoffPhase.ACCUMULATION if pnf_hint == "accumulation" else WyckoffPhase.DISTRIBUTION
        )
        if chain_phase != phase:
            pnf_phase_divergence = f"PnF={pnf_hint}, DetectorChain={chain_phase.value}"
    else:
        phase = chain_phase
        unknown_candidate = chain_unknown_candidate

    # Phase A/B/C/D/E 细分
    sub_phase = ""
    temp_step1 = Step1Result(
        phase=phase,
        boundary_upper=rule0.tr_upper if rule0.tr_upper else ctx["price_high"],
        boundary_lower=rule0.tr_lower if rule0.tr_lower else ctx["price_low"],
    )
    if phase == WyckoffPhase.ACCUMULATION:
        _classify_accum = classify_accumulation_sub_phase_fn or classify_accumulation_sub_phase
        sub_phase = _classify_accum(df, temp_step1, rule0)
    elif phase == WyckoffPhase.DISTRIBUTION:
        _classify_dist = classify_distribution_sub_phase_fn or classify_distribution_sub_phase
        sub_phase = _classify_dist(df, temp_step1, rule0)

    # 边界锚定
    boundary_upper = rule0.tr_upper if rule0.tr_upper else ctx["price_high"]
    boundary_lower = rule0.tr_lower if rule0.tr_lower else ctx["price_low"]
    boundary_source = []
    if rule0.bc_found:
        boundary_source.append("BC")
    if rule0.tr_source == "rolling_range":
        boundary_source.append("rolling_30d")

    return Step1Result(
        phase=phase,
        sub_phase=sub_phase,
        unknown_candidate=unknown_candidate,
        prior_trend_pct=ctx["prior_trend_pct"],
        is_in_tr=ctx["is_in_trading_range"],
        short_trend_pct=ctx["short_trend_pct"],
        relative_position=ctx["relative_position"],
        ma5=ctx["ma5"],
        ma20=ctx["ma20"],
        boundary_upper=boundary_upper,
        boundary_lower=boundary_lower,
        boundary_source=boundary_source,
        pnf_phase_divergence=pnf_phase_divergence,
    )


__all__ = [
    "compute_step1_context",
    "detect_accumulation",
    "detect_distribution",
    "detect_markdown",
    "detect_markup",
    "step0_bc_tr_scan",
    "step1_phase_determine",
]
