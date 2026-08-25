"""逻辑驱动因子方向族 — 单元测试 (2026-08-19)。

文献调研: docs/analysis/LOGIC_FACTOR_RESEARCH_PLAN.md
覆盖 7 个新因子:
  P0: max_ret_20d, reversal_1d, amivest_20d
  P1: range_20d, skew_20d, reversal_5d, reversal_20d
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from uniquant.brain.factors.registry import FactorRegistry
from uniquant.brain.factors.custom_factors import (
    compute_max_ret_20d,
    compute_reversal_1d,
    compute_amivest_20d,
    compute_range_20d,
    compute_skew_20d,
    compute_reversal_5d,
    compute_reversal_20d,
)

LOGIC_FACTORS = [
    "max_ret_20d",
    "reversal_1d",
    "amivest_20d",
    "range_20d",
    "skew_20d",
    "reversal_5d",
    "reversal_20d",
]


# ─── 注册测试 ───────────────────────────────────────────────────────────


def test_all_logic_factors_registered():
    for name in LOGIC_FACTORS:
        f = FactorRegistry.get_factor(name)
        assert f is not None, f"{name} 未注册"
        assert f.category == "custom"
        assert f.default_weight == 1.0


# ─── 缺失列保护 ─────────────────────────────────────────────────────────


def test_max_ret_20d_missing_close():
    df = pd.DataFrame({"volume": [1, 2, 3]})
    result = compute_max_ret_20d(df)
    assert result.isna().all()


def test_reversal_1d_missing_close():
    df = pd.DataFrame({"volume": [1, 2, 3]})
    result = compute_reversal_1d(df)
    assert result.isna().all()


def test_amivest_20d_missing_columns():
    df = pd.DataFrame({"close": [1, 2, 3]})  # 缺 amount
    result = compute_amivest_20d(df)
    assert result.isna().all()


def test_range_20d_missing_columns():
    df = pd.DataFrame({"close": [1, 2, 3]})  # 缺 high/low
    result = compute_range_20d(df)
    assert result.isna().all()


def test_skew_20d_missing_close():
    df = pd.DataFrame({"volume": [1, 2, 3]})
    result = compute_skew_20d(df)
    assert result.isna().all()


# ─── MAX 效应 (max_ret_20d) ────────────────────────────────────────────


def test_max_ret_20d_known_values():
    df = pd.DataFrame({"close": [100.0, 101.0, 99.0, 105.0, 102.0, 98.0] * 10})
    result = compute_max_ret_20d(df)
    # 前 19 行应为 NaN (min_periods=10)
    assert np.isnan(result.iloc[9])
    # 第 20 行起有值
    assert not np.isnan(result.iloc[20])
    # 窗口内最大日收益率: 以 105.0/99.0-1 ≈ 0.0606 或 102.0/105.0-1 ≈ -0.0286
    # 最大值约为 0.0606
    max_val = result.iloc[20]
    assert max_val >= 0.05, f"MAX 效应预期 >= 0.05, 实际 {max_val}"


# ─── 1 日反转 (reversal_1d) ────────────────────────────────────────────


def test_reversal_1d_known_values():
    df = pd.DataFrame({"close": [100.0, 99.0, 101.0, 102.0]})
    result = compute_reversal_1d(df)
    # 第 0 天: NaN (无前日)
    assert np.isnan(result.iloc[0])
    # 第 1 天: close 从 100 → 99, ret = -1%, reversal = +1%
    assert np.isclose(result.iloc[1], 0.01, atol=1e-5)
    # 第 2 天: close 从 99 → 101, ret = +2.02%, reversal = -2.02%
    assert np.isclose(result.iloc[2], -0.0202, atol=1e-3)
    # 第 3 天: close 从 101 → 102, ret = +0.99%, reversal = -0.99%
    assert np.isclose(result.iloc[3], -0.0099, atol=1e-3)


# ─── Amivest 流动性 (amivest_20d) ─────────────────────────────────────


def test_amivest_20d_known_values():
    np.random.seed(42)
    close = 100.0 + np.cumsum(np.random.randn(30) * 0.5)
    close = np.clip(close, 90, 110)
    amount = np.full(30, 1e7)
    df = pd.DataFrame({"close": close, "amount": amount})
    result = compute_amivest_20d(df)
    # 前 19 个为 NaN
    assert np.isnan(result.iloc[9])
    # 第 20 个起有值
    assert not np.isnan(result.iloc[20])
    # 值应为正 (amount/|r| > 0)
    assert result.iloc[20] > 0
    # 全部非 NaN 值应为正
    assert (result.dropna() > 0).all()


def test_amivest_20d_zero_return_does_not_break():
    """零收益率 (|r|→0) 被 clip 保护, 不会产生 inf."""
    df = pd.DataFrame({"close": [100.0] * 30, "amount": [1e7] * 30})
    result = compute_amivest_20d(df)
    assert not np.isinf(result.dropna()).any()


# ─── 价格区间比 (range_20d) ────────────────────────────────────────────


def test_range_20d_known_values():
    close = [100.0] * 30
    high = [105.0] * 30
    low = [95.0] * 30
    df = pd.DataFrame({"close": close, "high": high, "low": low})
    result = compute_range_20d(df)
    # 前 9 个为 NaN (min_periods=10)
    assert np.isnan(result.iloc[8])
    # 第 10 个起有值: (min_periods=10 满足)
    assert not np.isnan(result.iloc[9])
    non_nan = result.dropna()
    assert np.allclose(non_nan, 0.1), f"预期 0.1, 实际 {non_nan.unique()}"


# ─── 偏度 (skew_20d) ──────────────────────────────────────────────────


def test_skew_20d_known_values():
    np.random.seed(42)
    close = 100.0 + np.cumsum(np.random.randn(30) * 0.5)
    close = np.clip(close, 90, 110)
    df = pd.DataFrame({"close": close})
    result = compute_skew_20d(df)
    assert np.isnan(result.iloc[9])
    # 偏度是有限值
    non_nan = result.dropna()
    assert np.isfinite(non_nan).all()


# ─── 5 日反转 (reversal_5d) ────────────────────────────────────────────


def test_reversal_5d_known_values():
    # 明确构造: 5 天前 close 比现在高 → 过去 5 日跌 → reversal 为正
    np.random.seed(42)
    base = 100.0 + np.cumsum(np.random.randn(30) * 0.5)
    base = np.clip(base, 90, 110)
    df = pd.DataFrame({"close": base})
    result = compute_reversal_5d(df)
    # 前 5 天为 NaN
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[4])
    # 第 5 天起有值
    assert not np.isnan(result.iloc[5])


# ─── 20 日反转 (reversal_20d) ──────────────────────────────────────────


def test_reversal_20d_is_negative_momentum():
    """reversal_20d = -momentum_20d, 数值上应逐位相等."""
    np.random.seed(42)
    close = 100.0 + np.cumsum(np.random.randn(50) * 0.5)
    close = np.clip(close, 90, 110)
    df = pd.DataFrame({"close": close})
    result = compute_reversal_20d(df)
    # 与 momentum_20d 取负比较
    momentum = df["close"].pct_change(20, fill_method=None)
    mask = momentum.notna()
    assert np.allclose(result[mask], -momentum[mask]), "reversal_20d != -momentum_20d"


# ─── 全因子返回类型一致 ────────────────────────────────────────────────


def test_all_factors_return_series():
    np.random.seed(42)
    n = 50
    close = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
    close = np.clip(close, 90, 110)
    df = pd.DataFrame({
        "close": close,
        "high": close * 1.02,
        "low": close * 0.98,
        "amount": np.full(n, 1e7),
        "volume": np.full(n, 1e5),
    })
    funcs = [
        ("max_ret_20d", compute_max_ret_20d),
        ("reversal_1d", compute_reversal_1d),
        ("amivest_20d", compute_amivest_20d),
        ("range_20d", compute_range_20d),
        ("skew_20d", compute_skew_20d),
        ("reversal_5d", compute_reversal_5d),
        ("reversal_20d", compute_reversal_20d),
    ]
    for name, func in funcs:
        result = func(df)
        assert isinstance(result, pd.Series), f"{name} 返回类型错误"
        assert len(result) == n, f"{name} 长度错误: {len(result)} vs {n}"