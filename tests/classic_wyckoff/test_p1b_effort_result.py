"""P1-B: Step2 VDB 量价背离检测 TDD 验收测试。

对应 CLASSIC_WYCKOFF_P1_RESEARCH_PLAN.md §P1-B:
- detect_effort_result_divergence(df, lookback=30) → str
- 纯函数,无状态,独立可测试
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.wyckoff.effort_result import detect_effort_result_divergence
from uniquant.brain.wyckoff.models import Step2Result


def _make_ts(prices, volumes, n=30):
    """构造 OHLCV DataFrame。"""
    closes = np.asarray(prices, dtype=float)
    vols = np.asarray(volumes, dtype=float)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": closes * 1.01,
        "low": closes * 0.99,
        "close": closes,
        "volume": vols,
    })
    return df


# ─── T1: 价跌量缩 → bullish_divergence ───

def test_bullish_divergence():
    """price_change < -0.03 且 volume_trend < 0.8 → bullish_divergence。"""
    n = 30
    prices = np.linspace(10.0, 9.5, n)  # -5%
    vols = np.full(n, 1e6)
    vols[:10] = 2e6   # 前 20 日高量
    vols[-10:] = 3e5  # 最近 10 日缩量
    df = _make_ts(prices, vols, n)
    result = detect_effort_result_divergence(df, lookback=30)
    assert result == "bullish_divergence", f"expected bullish_divergence, got {result}"


# ─── T2: 价升量缩 → bearish_divergence ───

def test_bearish_divergence():
    """price_change > 0.03 且 volume_trend < 0.8 → bearish_divergence。"""
    n = 30
    prices = np.linspace(10.0, 10.5, n)  # +5%
    vols = np.full(n, 1e6)
    vols[:10] = 2e6
    vols[-10:] = 3e5
    df = _make_ts(prices, vols, n)
    result = detect_effort_result_divergence(df, lookback=30)
    assert result == "bearish_divergence", f"expected bearish_divergence, got {result}"


# ─── T3: 随机摆动数据 → none ───

def test_no_divergence_random():
    """随机摆动数据 → none（无错误）。"""
    rng = np.random.default_rng(42)
    n = 30
    prices = 10.0 + rng.normal(0, 0.005, n).cumsum()
    prices = np.clip(prices, 9.5, 10.5)
    vols = np.full(n, 1e6)
    df = _make_ts(prices, vols, n)
    result = detect_effort_result_divergence(df, lookback=30)
    assert result == "none", f"expected none, got {result}"


def test_no_divergence_flat():
    """价格平盘 → none。"""
    n = 30
    prices = np.full(n, 10.0)
    vols = np.full(n, 1e6)
    df = _make_ts(prices, vols, n)
    result = detect_effort_result_divergence(df, lookback=30)
    assert result == "none", f"expected none, got {result}"


# ─── T4: Step2Result 构造兼容新字段 ───

def test_step2_result_vdb_divergence_field():
    """Step2Result 构造兼容 vdb_divergence 字段（向后兼容）。"""
    r = Step2Result()
    assert r.vdb_divergence == "none"

    r2 = Step2Result(vdb_divergence="bullish_divergence")
    assert r2.vdb_divergence == "bullish_divergence"

    r3 = Step2Result(vdb_divergence="bearish_divergence")
    assert r3.vdb_divergence == "bearish_divergence"

    r4 = Step2Result(phenomena=["test"], accumulation_evidence=0.5)
    assert r4.vdb_divergence == "none"


# ─── T5: engine._step2_effort_result 返回含 vdb_divergence ───

def test_engine_step2_contains_vdb_divergence():
    """engine._step2_effort_result 返回的 Step2Result 含 vdb_divergence。"""
    from unittest.mock import patch
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    n = 30
    rng = np.random.default_rng(42)
    prices = 10.0 + rng.normal(0, 0.003, n).cumsum()
    closes = np.clip(prices, 9.6, 10.4)
    vols = np.full(n, 1e6)
    df = _make_ts(closes, vols, n)

    engine = WyckoffEngine()
    engine.rules = None

    # 构造一个最小 Step1Result
    from uniquant.brain.wyckoff.models import Step1Result
    step1 = Step1Result()

    result = engine._step2_effort_result(df, step1)
    assert isinstance(result, Step2Result)
    assert hasattr(result, "vdb_divergence")
    assert result.vdb_divergence in ("none", "bullish_divergence", "bearish_divergence")


# ─── T6: 窗口不足 → none ───

def test_short_window_returns_none():
    """不足窗口返回 none。"""
    n = 5
    prices = np.linspace(10.0, 9.5, n)
    vols = np.full(n, 1e6)
    df = _make_ts(prices, vols, n)
    result = detect_effort_result_divergence(df, lookback=30)
    assert result == "none", f"expected none, got {result}"


# ─── T7: 边界值 — 恰好 3% 下跌 + 缩量 ───

def test_bullish_at_threshold():
    """price_change = -0.03 边界触发。"""
    n = 30
    prices = np.linspace(10.0, 9.7, n)  # -3.0%
    vols = np.full(n, 1e6)
    vols[:10] = 2e6
    vols[-10:] = 3e5
    df = _make_ts(prices, vols, n)
    result = detect_effort_result_divergence(df, lookback=30)
    assert result == "bullish_divergence", f"expected bullish_divergence, got {result}"


def test_bearish_at_threshold():
    """price_change = 0.03 边界触发。"""
    n = 30
    prices = np.linspace(10.0, 10.3, n)  # +3.0%
    vols = np.full(n, 1e6)
    vols[:10] = 2e6
    vols[-10:] = 3e5
    df = _make_ts(prices, vols, n)
    result = detect_effort_result_divergence(df, lookback=30)
    assert result == "bearish_divergence", f"expected bearish_divergence, got {result}"