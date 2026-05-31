# -*- coding: utf-8 -*-
"""
Wyckoff classification functions - extracted from engine.py
"""

from typing import List

import pandas as pd

from uniquant.shared.constants import SPRING_LOW_FACTOR
from uniquant.shared.limits import is_limit_down, is_limit_up
from uniquant.brain.wyckoff.models import (
    LimitMove,
    LimitMoveType,
    Rule0Result,
    Step1Result,
    VolumeLevel,
    WyckoffPhase,
)
from uniquant.brain.wyckoff.rules import V3Rules


def classify_unknown_candidate(
    df: pd.DataFrame, phase: WyckoffPhase, rule0: Rule0Result
) -> str:
    """UNKNOWN 子状态分类"""
    if phase != WyckoffPhase.UNKNOWN or df.empty:
        return ""

    if rule0.tr_upper is None or rule0.tr_lower is None:
        return "unknown_range"

    last_row = df.iloc[-1]
    close_price = float(last_row["close"])
    open_price = float(last_row["open"])
    high_price = float(last_row["high"])
    low_price = float(last_row["low"])
    body = abs(close_price - open_price)
    upper_wick = high_price - max(close_price, open_price)
    lower_wick = min(close_price, open_price) - low_price
    avg_vol20 = float(df.tail(min(20, len(df)))["volume"].mean())
    vol_ratio = float(last_row["volume"]) / avg_vol20 if avg_vol20 > 0 else 1.0

    range_low = rule0.tr_lower
    range_high = rule0.tr_upper
    if range_high <= range_low:
        return "unknown_range"

    range_span = range_high - range_low
    relative_position = (close_price - range_low) / range_span
    close_location = (close_price - low_price) / max(high_price - low_price, 0.01)

    if (
        relative_position <= 0.38
        and close_location >= 0.58
        and (lower_wick > max(body, 0.01) or vol_ratio >= 1.05)
    ):
        return "sc_st_candidate"
    if (
        relative_position <= 0.50
        and close_price >= open_price
        and close_location >= 0.62
        and vol_ratio >= 0.95
    ):
        return "phase_a_candidate"
    if relative_position >= 0.62 and upper_wick > max(body * 1.2, 0.01) and vol_ratio >= 1.0:
        return "upthrust_candidate"
    if 0.38 < relative_position < 0.68:
        return "phase_b_range"
    return "unknown_range"


def classify_wyckoff_markup_event(df: pd.DataFrame, boundary_upper: float) -> str:
    """
    Classify the specific Wyckoff structural event under the Markup phase based on pure price-volume logic.
    """
    if len(df) < 20:
        return "处于上涨阶段 (Markup)"

    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]

    close_val = float(last_row["close"])
    open_val = float(last_row["open"])
    high_val = float(last_row["high"])
    low_val = float(last_row["low"])
    vol_val = float(last_row["volume"])

    prev_low = float(prev_row["low"])
    prev_vol = float(prev_row["volume"])

    # Tech indicators
    ma5 = df["close"].rolling(5).mean().iloc[-1]
    ma20 = df["close"].rolling(20).mean().iloc[-1]
    ma60 = df["close"].rolling(60).mean().iloc[-1]
    ma_vol20 = df["volume"].rolling(20).mean().iloc[-1]

    amplitude = (high_val - low_val) / max(low_val, 0.01)
    close_loc = (close_val - low_val) / max(high_val - low_val, 0.01)
    body_val = abs(close_val - open_val)
    lower_wick = min(close_val, open_val) - low_val

    # 1. Phase E: Perfect bull alignment, massive volume expansion and making new highs (using high price)
    is_new_high_30 = (high_val == df["high"].rolling(30).max().iloc[-1])
    if ma5 > ma20 > ma60 and vol_val > 1.5 * ma_vol20 and is_new_high_30:
        return "处于上涨阶段 (Markup - Phase E已确认)"

    # 2. BUEC (Back Up to Edge of Creek): Breakthrough confirmation after testing TR upper limit
    is_new_high_15 = (close_val == df["close"].rolling(15).max().iloc[-1])
    if is_new_high_15 and close_loc >= 0.8 and vol_val >= 1.0 * ma_vol20 and close_val > boundary_upper * 0.98:
        return "处于上涨阶段 (Markup - BUEC已确认)"

    # 3. Shakeout: Intraday deep plunge below previous low, but strongly recovered with higher volume
    if low_val < prev_low and close_loc >= 0.4 and vol_val > prev_vol and lower_wick > body_val:
        return "处于上涨阶段 (Markup - Shakeout已确认)"

    # 4. Test: Extremely low volume retest with narrow amplitude
    if vol_val < 0.65 * ma_vol20 and amplitude <= 0.025:
        return "处于上涨阶段 (Markup - Test已确认)"

    # 5. Lack of Supply: Low volume consolidation or minor pullback showing exhausted selling pressure
    if vol_val < 1.1 * ma_vol20 and close_val < open_val and body_val / open_val < 0.015:
        return "处于上涨阶段 (Markup - Lack of Supply已确认)"

    # 6. LPS (Last Point of Support): Breakthrough follow-up, closing near daily high with gold cross setup
    if close_loc >= 0.9 and close_val > open_val and ma5 >= ma20 * 0.99:
        return "处于上涨阶段 (Markup - LPS已确认)"

    return "处于上涨阶段 (Markup)"


def classify_accumulation_sub_phase(
    df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result, rules: V3Rules
) -> str:
    """Accumulation Phase A/B/C/D/E 细分"""
    if df.empty:
        return ""

    recent_20 = df.tail(20)
    if len(recent_20) < 10:
        return ""

    current_price = float(df.iloc[-1]["close"])
    boundary_lower = step1.boundary_lower
    boundary_upper = step1.boundary_upper

    if boundary_lower <= 0 or boundary_upper <= 0:
        return ""

    range_span = boundary_upper - boundary_lower
    relative_position = (current_price - boundary_lower) / range_span

    # 检查是否有Spring信号
    has_spring = False
    for row in recent_20.itertuples():
        if row.low < boundary_lower * SPRING_LOW_FACTOR and row.close >= boundary_lower * 0.97:
            has_spring = True
            break

    # 检查是否有SOS信号
    has_sos = False
    for row in recent_20.tail(5).itertuples():
        if row.close > boundary_upper * 0.98:
            vol_level = rules.rule1_relative_volume(row.volume, df["volume"])
            if vol_level in ("高于平均", "天量"):
                has_sos = True
                break

    # Phase分类
    if has_spring and has_sos:
        return "Phase D"  # Spring + SOS = Phase D
    elif has_spring:
        return "Phase C"  # Spring = Phase C
    elif relative_position <= 0.40:
        # 检查是否有SC信号
        for row in recent_20.itertuples():
            if row.low < boundary_lower * 1.05:
                vol_level = rules.rule1_relative_volume(row.volume, df["volume"])
                if vol_level in ("天量", "高于平均"):
                    return "Phase A"  # SC = Phase A
        return "Phase B"  # 区间下部但无SC
    elif relative_position >= 0.60:
        return "Phase B"  # 区间上部
    else:
        return "Phase B"  # 区间中部


def classify_distribution_sub_phase(
    df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result
) -> str:
    """Distribution Phase A/B/C/D/E 细分"""
    if df.empty:
        return ""

    recent_20 = df.tail(20)
    if len(recent_20) < 10:
        return ""

    current_price = float(df.iloc[-1]["close"])
    boundary_lower = step1.boundary_lower
    boundary_upper = step1.boundary_upper

    if boundary_lower <= 0 or boundary_upper <= 0:
        return ""

    range_span = boundary_upper - boundary_lower
    relative_position = (current_price - boundary_lower) / range_span

    # 检查是否有UTAD信号
    has_utad = False
    for row in recent_20.itertuples():
        if row.high > boundary_upper * 1.02 and row.close <= boundary_upper * 1.01:
            has_utad = True
            break

    # 检查是否有BC信号
    has_bc = rule0.bc_found

    # Phase分类
    if has_utad:
        return "Phase C"  # UTAD = Phase C
    elif has_bc:
        if relative_position >= 0.60:
            return "Phase B"  # BC后高位震荡
        else:
            return "Phase D"  # BC后下跌
    elif relative_position >= 0.70:
        return "Phase A"  # 高位
    elif relative_position <= 0.30:
        return "Phase D"  # 低位
    else:
        return "Phase B"  # 中部震荡


def classify_volume(volume: float, volume_series: pd.Series, rules: V3Rules) -> VolumeLevel:
    """相对量能分类"""
    return VolumeLevel(rules.rule1_relative_volume(volume, volume_series))


def detect_limit_moves(
    df: pd.DataFrame, code_prefix: str, is_st: bool = False, rules: V3Rules = None
) -> List[LimitMove]:
    """检测涨跌停与炸板异动"""
    limit_moves = []
    recent = df.tail(20)
    if is_st:
        limit_pct = 0.05
    elif code_prefix in {"688", "689", "300", "301", "302"}:
        limit_pct = 0.20
    elif code_prefix in {"83", "87", "920"}:
        limit_pct = 0.30
    else:
        limit_pct = 0.10
    limit_threshold = limit_pct - 0.005

    prev_close = float(df.iloc[-21]["close"]) if len(df) > 20 else None

    for row in recent.itertuples():
        if prev_close is None:
            prev_close = float(row.close)
            continue

        is_limit_up_flag = is_limit_up({"close": row.close}, prev_close, code_prefix, is_st=is_st)
        is_limit_down_flag = is_limit_down({"close": row.close}, prev_close, code_prefix, is_st=is_st)

        if not is_limit_up_flag and not is_limit_down_flag:
            prev_close = float(row.close)
            continue

        high_change = (row.high - prev_close) / prev_close if prev_close > 0 else 0.0
        low_change = (row.low - prev_close) / prev_close if prev_close > 0 else 0.0

        if is_limit_up_flag:
            if high_change < limit_threshold:
                move_type = LimitMoveType.BREAK_LIMIT_UP
                is_broken = True
            else:
                move_type = LimitMoveType.LIMIT_UP
                is_broken = False
        else:
            if low_change > -limit_threshold:
                move_type = LimitMoveType.BREAK_LIMIT_DOWN
                is_broken = True
            else:
                move_type = LimitMoveType.LIMIT_DOWN
                is_broken = False

        volume_level = classify_volume(row.volume, df["volume"], rules)

        limit_moves.append(
            LimitMove(
                date=str(row.date),
                move_type=move_type,
                price=float(row.close),
                volume_level=volume_level,
                is_broken=is_broken,
            )
        )
        prev_close = float(row.close)

    return limit_moves
