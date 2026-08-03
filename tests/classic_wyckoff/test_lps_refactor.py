"""P0-A: LPS 判定重构 — rule6 分层判定 TDD 验收测试。

对应设计文档: docs/analysis/WYCKOFF_LPS_REFACTOR_DESIGN_20260802.md §6.2

测试用例 (T1-T7):
  T1: spring 后回落测试守位 + 缩量 + 反弹 → lps_confirmed=True
  T2: spring 后测试跌破 spring 低点 → lps_confirmed=False, lps_stage=not_test
  T3: 守位 + 缩量但无反弹 → lps_confirmed=False, lps_stage=test_held
  T4: spring 后放量再创新低 → 作废 invalidated
  T5: 测试量放大(供给未枯竭) → lps_confirmed=False
  T6: 单日收阴但 5 根窗口内反弹 → lps_confirmed=True
  T7: 下影线瞬时破位但收盘守位(ATR 容忍) → 不误判作废
"""

from typing import Any, Dict

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.wyckoff.rules import V3Rules


def _make_post_spring_df(
    closes: list,
    lows: list,
    highs: list,
    opens: list,
    volumes: list,
    base_date: str = "2020-06-01",
) -> pd.DataFrame:
    """Helper to build a post-spring DataFrame from price arrays."""
    n = len(closes)
    return pd.DataFrame({
        "date": pd.date_range(base_date, periods=n, freq="D"),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def _build_t1_data() -> Dict[str, Any]:
    """T1: spring 后回落测试守位 + 缩量 + 反弹 → lps_confirmed=True

    spring_low=10.0, spring_volume=1e7, atr=0.4
    tolerance = max(0.25*0.4, 10.0*0.005) = max(0.1, 0.05) = 0.10
    守位阈值 = 10.0 - 0.10 = 9.90

    测试K线(index 2): low=10.02 ∈ [9.9, 10.5], open=10.20 ≤ 10.3 ✓
    test_vol_ratio = 3e6/1e7 = 0.30 ≤ 1.0 → supply_dry ✓
    test_high = 10.40, target = 10.40 + 0.4*0.5 = 10.60
    index 4 close=10.70 ≥ 10.60 → bounce ✓
    """
    closes = [10.50, 10.30, 10.25, 10.40, 10.70, 11.00]
    lows = [10.30, 10.10, 10.02, 10.20, 10.50, 10.80]
    highs = [10.60, 10.45, 10.40, 10.60, 10.90, 11.20]
    opens = [10.50, 10.35, 10.20, 10.35, 10.60, 10.90]
    volumes = [8e6, 7e6, 3e6, 4e6, 6e6, 5e6]
    return {
        "post_spring_df": _make_post_spring_df(closes, lows, highs, opens, volumes),
        "spring_low": 10.0,
        "spring_volume": 1e7,
        "atr": 0.4,
    }


def _build_t2_data() -> Dict[str, Any]:
    """T2: spring 后测试跌破 spring 低点 → lps_confirmed=False, lps_stage=not_test

    spring_low=10.0, atr=0.0 → tolerance=max(0, 0.05)=0.05, 守位阈值=9.95
    测试K线(index 2): low=9.92 ∈ [9.9, 10.5], open=10.10 ≤ 10.3 → 识别为测试K线
    index 4: low=9.98 ∈ [9.9, 10.5] 但 open=10.35 > 10.3 → 排除
    所以 test_idx=2, low=9.92 < 9.95 → 守位失败
    """
    closes = [10.50, 10.20, 9.95, 9.90, 10.10]
    lows = [10.30, 10.00, 9.92, 9.85, 9.98]
    highs = [10.60, 10.35, 10.10, 10.10, 10.25]
    opens = [10.50, 10.25, 10.10, 9.88, 10.35]
    volumes = [8e6, 7e6, 4e6, 5e6, 6e6]
    return {
        "post_spring_df": _make_post_spring_df(closes, lows, highs, opens, volumes),
        "spring_low": 10.0,
        "spring_volume": 1e7,
        "atr": 0.0,
    }


def _build_t3_data() -> Dict[str, Any]:
    """T3: 守位 + 缩量但无反弹 → lps_confirmed=False, lps_stage=test_held

    测试K线(index 2): low=10.02 ≥ 9.90 → 守位 ✓
    test_vol_ratio = 3e6/1e7 = 0.30 ≤ 1.0 → supply_dry ✓
    test_high = 10.40, target = 10.60
    后续K线收盘均 < 10.60 → 无反弹 ✗
    """
    closes = [10.50, 10.30, 10.25, 10.35, 10.40, 10.30]
    lows = [10.30, 10.10, 10.02, 10.20, 10.25, 10.15]
    highs = [10.60, 10.45, 10.40, 10.50, 10.55, 10.45]
    opens = [10.50, 10.35, 10.20, 10.30, 10.38, 10.35]
    volumes = [8e6, 7e6, 3e6, 4e6, 4e6, 3e6]
    return {
        "post_spring_df": _make_post_spring_df(closes, lows, highs, opens, volumes),
        "spring_low": 10.0,
        "spring_volume": 1e7,
        "atr": 0.4,
    }


def _build_t4_data() -> Dict[str, Any]:
    """T4: spring 后放量再创新低 → 作废 invalidated

    index 2: low=9.80 < 9.90 (spring_low*0.99), volume=20e6 > avg_vol*1.5
    """
    closes = [10.50, 10.20, 9.80, 9.90, 10.10]
    lows = [10.30, 10.00, 9.80, 9.85, 9.95]
    highs = [10.60, 10.35, 9.90, 10.10, 10.25]
    opens = [10.50, 10.25, 9.85, 9.88, 10.00]
    volumes = [8e6, 7e6, 20e6, 5e6, 6e6]
    return {
        "post_spring_df": _make_post_spring_df(closes, lows, highs, opens, volumes),
        "spring_low": 10.0,
        "spring_volume": 1e7,
        "atr": 0.4,
    }


def _build_t5_data() -> Dict[str, Any]:
    """T5: 测试量放大(供给未枯竭) → lps_confirmed=False

    _find_test_bar 识别最后一个满足条件的K线(index 3):
    low=10.10 ∈ [9.9, 10.5], open=10.28 ≤ 10.3 → test_idx=3
    test_vol_ratio = 18e6/1e7 = 1.80 > 1.0 → supply_dry ✗
    """
    closes = [10.50, 10.30, 10.25, 10.35, 10.40, 10.30]
    lows = [10.30, 10.10, 10.02, 10.10, 10.25, 10.15]
    highs = [10.60, 10.45, 10.40, 10.50, 10.55, 10.45]
    opens = [10.50, 10.40, 10.20, 10.28, 10.38, 10.35]
    volumes = [8e6, 7e6, 4e6, 18e6, 4e6, 3e6]
    return {
        "post_spring_df": _make_post_spring_df(closes, lows, highs, opens, volumes),
        "spring_low": 10.0,
        "spring_volume": 1e7,
        "atr": 0.4,
    }


def _build_t6_data() -> Dict[str, Any]:
    """T6: 单日收阴但 5 根窗口内反弹 → lps_confirmed=True

    _find_test_bar 识别最后一个满足条件的K线(index 2):
    low=10.02 ∈ [9.9, 10.5], open=10.20 ≤ 10.3 → test_idx=2
    index 3 (open=10.35 > 10.3) 被排除 → index 2 是最后一个
    test_vol_ratio = 3e6/1e7 = 0.30 ≤ 1.0 → supply_dry ✓
    test_high=10.40, target=10.40+0.4*0.5=10.60
    index 4 close=10.70 ≥ 10.60 → bounce ✓
    旧实现(bounce=last_close>last_open) 会因最后一根收阴而否决
    """
    closes = [10.50, 10.30, 10.10, 10.40, 10.70, 10.50]
    lows = [10.30, 10.10, 10.02, 10.20, 10.50, 10.35]
    highs = [10.60, 10.45, 10.40, 10.60, 10.90, 10.65]
    opens = [10.50, 10.35, 10.20, 10.35, 10.60, 10.55]
    volumes = [8e6, 7e6, 3e6, 4e6, 6e6, 4e6]
    return {
        "post_spring_df": _make_post_spring_df(closes, lows, highs, opens, volumes),
        "spring_low": 10.0,
        "spring_volume": 1e7,
        "atr": 0.4,
    }


def _build_t7_data() -> Dict[str, Any]:
    """T7: 下影线瞬时破位但收盘守位(ATR 容忍) → 不误判作废

    spring_low=10.0, tolerance=max(0.25*0.4, 10.0*0.005)=0.10
    守位阈值=9.90
    测试K线(index 2): low=9.92 ≥ 9.90 → 守位 ✓ (ATR 容忍)
    test_vol_ratio = 3e6/1e7 = 0.30 ≤ 1.0 → supply_dry ✓
    index 4 close=10.65 ≥ 10.60 → bounce ✓
    → lps_confirmed=True
    """
    closes = [10.50, 10.30, 10.20, 10.40, 10.65, 10.90]
    lows = [10.30, 10.10, 9.92, 10.20, 10.50, 10.75]
    highs = [10.60, 10.45, 10.35, 10.60, 10.85, 11.10]
    opens = [10.50, 10.35, 10.18, 10.35, 10.55, 10.85]
    volumes = [8e6, 7e6, 3e6, 4e6, 6e6, 5e6]
    return {
        "post_spring_df": _make_post_spring_df(closes, lows, highs, opens, volumes),
        "spring_low": 10.0,
        "spring_volume": 1e7,
        "atr": 0.4,
    }


# ─────────────────────── Test Cases ───────────────────────


def test_t1_spring_lps_confirmed():
    """T1: spring 后回落测试守位 + 缩量 + 反弹 → lps_confirmed=True"""
    data = _build_t1_data()
    result = V3Rules.rule6_spring_validation(
        True, data["post_spring_df"], data["spring_low"],
        spring_volume=data["spring_volume"], atr=data["atr"],
    )
    assert result["lps_confirmed"] is True, (
        f"T1: 应该 lps_confirmed=True, got {result}"
    )
    assert result["lps_stage"] == "lps_confirmed", (
        f"T1: 应该 lps_stage=lps_confirmed, got {result['lps_stage']}"
    )
    assert result["test_low"] == 10.02, (
        f"T1: test_low 应为 10.02, got {result['test_low']}"
    )
    assert result["test_vol_ratio"] is not None and result["test_vol_ratio"] <= 1.0, (
        f"T1: 量比应 <= 1.0, got {result['test_vol_ratio']}"
    )
    assert result["bounce_bars"] > 0, (
        f"T1: 应有反弹, bounce_bars={result['bounce_bars']}"
    )
    assert result["spring_invalidated"] is False


def test_t2_spring_test_breakdown():
    """T2: spring 后测试跌破 spring 低点 → lps_confirmed=False, lps_stage=not_test"""
    data = _build_t2_data()
    result = V3Rules.rule6_spring_validation(
        True, data["post_spring_df"], data["spring_low"],
        spring_volume=data["spring_volume"], atr=data["atr"],
    )
    assert result["lps_confirmed"] is False, (
        f"T2: 应该 lps_confirmed=False, got {result}"
    )
    assert result["lps_stage"] == "not_test", (
        f"T2: 应该 lps_stage=not_test, got {result['lps_stage']}"
    )
    assert result["test_low"] == 9.92, (
        f"T2: test_low 应为 9.92, got {result['test_low']}"
    )
    assert result["spring_invalidated"] is False


def test_t3_spring_hold_no_bounce():
    """T3: 守位 + 缩量但无反弹 → lps_confirmed=False, lps_stage=test_held"""
    data = _build_t3_data()
    result = V3Rules.rule6_spring_validation(
        True, data["post_spring_df"], data["spring_low"],
        spring_volume=data["spring_volume"], atr=data["atr"],
    )
    assert result["lps_confirmed"] is False, (
        f"T3: 应该 lps_confirmed=False, got {result}"
    )
    assert result["lps_stage"] == "test_held", (
        f"T3: 应该 lps_stage=test_held, got {result['lps_stage']}"
    )
    assert result["bounce_bars"] == 0, (
        f"T3: 不应有反弹, bounce_bars={result['bounce_bars']}"
    )
    assert result["spring_invalidated"] is False


def test_t4_spring_invalidated():
    """T4: spring 后放量再创新低 → 作废 invalidated"""
    data = _build_t4_data()
    result = V3Rules.rule6_spring_validation(
        True, data["post_spring_df"], data["spring_low"],
        spring_volume=data["spring_volume"], atr=data["atr"],
    )
    assert result["lps_confirmed"] is False, (
        f"T4: 应该 lps_confirmed=False, got {result}"
    )
    assert result["lps_stage"] == "invalidated", (
        f"T4: 应该 lps_stage=invalidated, got {result['lps_stage']}"
    )
    assert result["spring_invalidated"] is True, (
        f"T4: 应该 spring_invalidated=True, got {result}"
    )


def test_t5_spring_volume_surge():
    """T5: 测试量放大(供给未枯竭) → lps_confirmed=False"""
    data = _build_t5_data()
    result = V3Rules.rule6_spring_validation(
        True, data["post_spring_df"], data["spring_low"],
        spring_volume=data["spring_volume"], atr=data["atr"],
    )
    assert result["lps_confirmed"] is False, (
        f"T5: 应该 lps_confirmed=False, got {result}"
    )
    assert result["test_vol_ratio"] is not None and result["test_vol_ratio"] > 1.0, (
        f"T5: 量比应 > 1.0, got {result['test_vol_ratio']}"
    )
    assert result["spring_invalidated"] is False


def test_t6_down_day_5bar_bounce():
    """T6: 单日收阴但 5 根窗口内反弹 → lps_confirmed=True"""
    data = _build_t6_data()
    result = V3Rules.rule6_spring_validation(
        True, data["post_spring_df"], data["spring_low"],
        spring_volume=data["spring_volume"], atr=data["atr"],
    )
    assert result["lps_confirmed"] is True, (
        f"T6: 应该 lps_confirmed=True, got {result}"
    )
    assert result["lps_stage"] == "lps_confirmed", (
        f"T6: 应该 lps_stage=lps_confirmed, got {result['lps_stage']}"
    )
    assert result["bounce_bars"] > 0, (
        f"T6: 应有反弹, bounce_bars={result['bounce_bars']}"
    )
    assert result["spring_invalidated"] is False


def test_t7_shadow_break_atr_tolerance():
    """T7: 下影线瞬时破位但收盘守位(ATR 容忍) → 不误判作废"""
    data = _build_t7_data()
    result = V3Rules.rule6_spring_validation(
        True, data["post_spring_df"], data["spring_low"],
        spring_volume=data["spring_volume"], atr=data["atr"],
    )
    assert result["lps_confirmed"] is True, (
        f"T7: 应该 lps_confirmed=True, got {result}"
    )
    assert result["lps_stage"] == "lps_confirmed", (
        f"T7: 应该 lps_stage=lps_confirmed, got {result['lps_stage']}"
    )
    assert result["test_low"] == 9.92, (
        f"T7: test_low 应为 9.92, got {result['test_low']}"
    )
    assert result["spring_invalidated"] is False


# ─────────────────────── Edge Cases ───────────────────────


def test_no_spring_detected():
    """spring_detected=False 时应返回默认值"""
    result = V3Rules.rule6_spring_validation(
        False, pd.DataFrame(), 10.0,
    )
    assert result["lps_confirmed"] is False
    assert result["lps_stage"] == "not_test"
    assert result["spring_invalidated"] is False
    assert result["quality"] == "无"


def test_insufficient_post_spring_data():
    """post_spring_df 不足 3 行时应返回数据不足"""
    df = _make_post_spring_df([10.5], [10.3], [10.6], [10.5], [8e6])
    result = V3Rules.rule6_spring_validation(True, df, 10.0)
    assert result["lps_confirmed"] is False
    assert result["lps_stage"] == "not_test"
    assert result["quality"] == "二级(需ST验证)"


def test_no_test_bar_found():
    """post_spring_df 中无满足测试条件K线"""
    closes = [10.50, 10.80, 11.00, 11.20, 11.50]
    lows = [10.30, 10.60, 10.80, 11.00, 11.30]
    highs = [10.60, 10.95, 11.15, 11.35, 11.65]
    opens = [10.50, 10.70, 10.90, 11.10, 11.40]
    volumes = [8e6, 7e6, 6e6, 5e6, 4e6]
    df = _make_post_spring_df(closes, lows, highs, opens, volumes)
    result = V3Rules.rule6_spring_validation(True, df, 10.0, spring_volume=1e7, atr=0.4)
    assert result["lps_confirmed"] is False
    assert result["lps_stage"] == "not_test"


def test_zero_spring_volume_fallback():
    """spring_volume=0 时不应卡死, supply_dry 应弱化为 True"""
    data = _build_t1_data()
    result = V3Rules.rule6_spring_validation(
        True, data["post_spring_df"], data["spring_low"],
        spring_volume=0.0, atr=data["atr"],
    )
    # spring_volume=0 时 supply_dry 弱化为 True, 但 bounce 仍需要
    assert result["lps_confirmed"] is True, (
        f"spring_volume=0 时不应卡死, got {result}"
    )
    assert result["test_vol_ratio"] is None


def test_old_fields_preserved():
    """旧字段(lps_confirmed/quality/desc/spring_invalidated) 语义不变"""
    data = _build_t1_data()
    result = V3Rules.rule6_spring_validation(
        True, data["post_spring_df"], data["spring_low"],
        spring_volume=data["spring_volume"], atr=data["atr"],
    )
    assert "lps_confirmed" in result
    assert "quality" in result
    assert "desc" in result
    assert "spring_invalidated" in result
    assert isinstance(result["lps_confirmed"], bool)
    assert isinstance(result["quality"], str)
    assert isinstance(result["desc"], str)
    assert isinstance(result["spring_invalidated"], bool)