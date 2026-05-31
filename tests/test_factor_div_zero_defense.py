"""
测试自定义因子的除零/NaN 防御编程

覆盖场景：
1. 一字板（最高价 = 最低价）→ compute_price_position_20d 分母为 0
2. 均线重合（短期均线 = 长期均线）→ compute_ma_ratio_* 分母为 0
3. 成交量为零（停牌股）→ compute_volume_ratio_5_20 分母为 0
4. 全 NaN 输入 → 所有因子应安全返回 NaN 而非抛异常
5. Inf 传播 → 因子值中不应出现 Inf
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.factors.custom_factors import (
    compute_ma_ratio_5_20,
    compute_ma_ratio_10_60,
    compute_price_position_20d,
    compute_volume_ratio_5_20,
    compute_momentum_20d,
    compute_momentum_60d,
    compute_volatility_20d,
    compute_volatility_60d,
    compute_rsi_14,
    compute_turnover_momentum_20d,
)


class TestDivZeroDefense:
    """除零防御测试"""

    # ------------------------------------------------------------------ #
    #  测试 1：一字板 — 最高价 = 最低价
    # ------------------------------------------------------------------ #
    def test_price_position_limit_up_down(self):
        """一字板时，high_20 == low_20，分母为 0，应返回 NaN 而非 Inf。"""
        n = 30
        df = pd.DataFrame({
            "close": [10.0] * n,
            "high": [10.0] * n,
            "low": [10.0] * n,
        })

        result = compute_price_position_20d(df)

        assert len(result) == n
        # 不应出现 Inf
        assert not np.isinf(result).any()
        # 第 19 行起（窗口满）应为 NaN 或 0（分子也为 0 时）
        # 安全实现应返回 NaN
        assert result.iloc[19:].isna().all() or (result.iloc[19:] == 0.0).all()

    # ------------------------------------------------------------------ #
    #  测试 2：均线重合 — 短期均线 = 长期均线
    # ------------------------------------------------------------------ #
    def test_ma_ratio_constant_prices(self):
        """价格恒定时，MA5 == MA20，分母为 0，应返回 NaN 而非 Inf。"""
        n = 30
        df = pd.DataFrame({
            "close": [10.0] * n,
        })

        result = compute_ma_ratio_5_20(df)

        assert len(result) == n
        assert not np.isinf(result).any()
        # 窗口满后应为 0（10/10 - 1 = 0）或 NaN
        assert result.iloc[19:].isna().all() or (result.iloc[19:] == 0.0).all()

    def test_ma_ratio_10_60_constant_prices(self):
        """价格恒定时，MA10 == MA60，分母为 0。"""
        n = 70
        df = pd.DataFrame({
            "close": [10.0] * n,
        })

        result = compute_ma_ratio_10_60(df)

        assert len(result) == n
        assert not np.isinf(result).any()

    # ------------------------------------------------------------------ #
    #  测试 3：成交量为零（停牌股）
    # ------------------------------------------------------------------ #
    def test_volume_ratio_zero_volume(self):
        """停牌股成交量为 0，分母为 0，应返回 NaN 而非 Inf。"""
        n = 30
        df = pd.DataFrame({
            "volume": [0] * n,
        })

        result = compute_volume_ratio_5_20(df)

        assert len(result) == n
        assert not np.isinf(result).any()
        # 窗口满后应为 NaN
        assert result.iloc[19:].isna().all() or (result.iloc[19:] == 0.0).all()

    def test_volume_ratio_mixed_zero(self):
        """部分天成交量为 0，部分天有成交。"""
        n = 30
        df = pd.DataFrame({
            "volume": [1000 if i % 3 != 0 else 0 for i in range(n)],
        })

        result = compute_volume_ratio_5_20(df)

        assert len(result) == n
        assert not np.isinf(result).any()

    # ------------------------------------------------------------------ #
    #  测试 4：全 NaN 输入
    # ------------------------------------------------------------------ #
    def test_all_factors_handle_all_nan(self):
        """所有因子对全 NaN 输入应安全返回 NaN，不抛异常。"""
        n = 30
        df = pd.DataFrame({
            "close": [np.nan] * n,
            "high": [np.nan] * n,
            "low": [np.nan] * n,
            "volume": [np.nan] * n,
        })

        factors = [
            compute_momentum_20d,
            compute_momentum_60d,
            compute_volatility_20d,
            compute_volatility_60d,
            compute_ma_ratio_5_20,
            compute_ma_ratio_10_60,
            compute_volume_ratio_5_20,
            compute_rsi_14,
            compute_price_position_20d,
        ]

        for factor_fn in factors:
            result = factor_fn(df)
            assert len(result) == n, f"{factor_fn.__name__}: wrong length"
            assert not np.isinf(result).any(), f"{factor_fn.__name__}: contains Inf"

    # ------------------------------------------------------------------ #
    #  测试 5：Inf 传播防护 — 确保所有因子输出不含 Inf
    # ------------------------------------------------------------------ #
    def test_no_inf_in_normal_data(self):
        """正常数据下，所有因子输出不应包含 Inf。"""
        np.random.seed(42)
        n = 100
        df = pd.DataFrame({
            "close": 10 + np.cumsum(np.random.randn(n) * 0.5),
            "high": 10 + np.cumsum(np.random.randn(n) * 0.5) + 0.5,
            "low": 10 + np.cumsum(np.random.randn(n) * 0.5) - 0.5,
            "volume": np.random.randint(1000, 10000, n).astype(float),
        })

        factors = [
            compute_momentum_20d,
            compute_volatility_20d,
            compute_ma_ratio_5_20,
            compute_ma_ratio_10_60,
            compute_volume_ratio_5_20,
            compute_rsi_14,
            compute_price_position_20d,
        ]

        for factor_fn in factors:
            result = factor_fn(df)
            assert not np.isinf(result.dropna()).any(), (
                f"{factor_fn.__name__}: output contains Inf"
            )

    # ------------------------------------------------------------------ #
    #  测试 6：极小分母 — 接近零但不为零
    # ------------------------------------------------------------------ #
    def test_price_position_near_zero_denominator(self):
        """high_20 - low_20 极小时，结果不应爆炸为 Inf。"""
        n = 30
        df = pd.DataFrame({
            "close": [10.0 + 1e-15] * n,
            "high": [10.0 + 1e-15] * n,
            "low": [10.0] * n,
        })

        result = compute_price_position_20d(df)

        assert len(result) == n
        assert not np.isinf(result).any()

    # ------------------------------------------------------------------ #
    #  测试 7：RSI 极端数据 — 全涨/全跌
    # ------------------------------------------------------------------ #
    def test_rsi_all_gains_no_losses(self):
        """全涨无跌时，loss 为 0，RSI 应返回 100 而非 Inf。"""
        n = 30
        df = pd.DataFrame({
            "close": list(range(1, n + 1)),  # 单调递增
        })

        result = compute_rsi_14(df)

        assert len(result) == n
        assert not np.isinf(result).any()
        # RSI 应在 [0, 100] 范围内
        valid = result.dropna()
        if len(valid) > 0:
            assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_all_losses_no_gains(self):
        """全跌无涨时，gain 为 0，RSI 应返回 0 而非 NaN/Inf。"""
        n = 30
        df = pd.DataFrame({
            "close": list(range(n, 0, -1)),  # 单调递减
        })

        result = compute_rsi_14(df)

        assert len(result) == n
        assert not np.isinf(result).any()
        valid = result.dropna()
        if len(valid) > 0:
            assert (valid >= 0).all() and (valid <= 100).all()

    # ------------------------------------------------------------------ #
    #  测试 8：turnover_momentum_20d — 流通市值为 0
    # ------------------------------------------------------------------ #
    def test_turnover_momentum_zero_market_cap(self):
        """流通市值为 0 时，不应产生 Inf。"""
        n = 30
        df = pd.DataFrame({
            "volume": [1000] * n,
            "close": [10.0] * n,
            "circulating_market_cap": [0.0] * n,
        })

        result = compute_turnover_momentum_20d(df)

        assert len(result) == n
        assert not np.isinf(result).any()
