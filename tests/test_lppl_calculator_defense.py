"""
测试 LPPLCalculator 防御编程

覆盖场景：
1. 零/负价格 → np.log 产生 -inf/NaN → 应返回空结果而非垃圾
2. np.abs(tc - t) 掩盖约束 → 应使用 tc - t 并惩罚 tau <= 0
3. 缓存键应使用稳定的 sha256 派生值，而不是 Python 内置 hash()
"""

import hashlib
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from uniquant.brain.lppl.calculator import LPPLCalculator


class TestLPPLCalculatorDefense:
    """LPPLCalculator 防御编程测试"""

    @pytest.fixture
    def calc(self):
        return LPPLCalculator()

    # ------------------------------------------------------------------ #
    #  测试 1：零价格 → np.log(0) = -inf → 应返回空结果
    # ------------------------------------------------------------------ #
    def test_fit_rejects_zero_prices(self, calc):
        """价格为 0 时，np.log 产生 -inf，应返回空结果。"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=70, freq="B"),
            "close": [0.0] * 70,
        })

        result = calc.fit(df, column="close")

        assert result == {} or "error" in result or result.get("is_bubble") is False

    # ------------------------------------------------------------------ #
    #  测试 2：负价格 → np.log 产生 NaN → 应返回空结果
    # ------------------------------------------------------------------ #
    def test_fit_rejects_negative_prices(self, calc):
        """价格为负时，np.log 产生 NaN，应返回空结果。"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=70, freq="B"),
            "close": [-1.0] * 70,
        })

        result = calc.fit(df, column="close")

        assert result == {} or "error" in result or result.get("is_bubble") is False

    # ------------------------------------------------------------------ #
    #  测试 3：含 NaN 价格 → 应返回空结果
    # ------------------------------------------------------------------ #
    def test_fit_rejects_nan_prices(self, calc):
        """价格含 NaN 时，应返回空结果。"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=70, freq="B"),
            "close": [10.0 if i < 35 else np.nan for i in range(70)],
        })

        result = calc.fit(df, column="close")

        assert result == {} or "error" in result or result.get("is_bubble") is False

    # ------------------------------------------------------------------ #
    #  测试 4：正常价格 → 应正常拟合
    # ------------------------------------------------------------------ #
    def test_fit_valid_prices(self, calc):
        """正常价格数据应正常拟合。"""
        np.random.seed(42)
        n = 100
        t = np.arange(n)
        # 模拟上升价格
        close = 10 + 0.05 * t + np.random.randn(n) * 0.3
        close = np.maximum(close, 1.0)

        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "close": close,
        })

        result = calc.fit(df, column="close")

        assert isinstance(result, dict)
        assert "is_bubble" in result
        assert "confidence" in result

    # ------------------------------------------------------------------ #
    #  测试 5：缓存键应使用稳定的 sha256 派生值
    # ------------------------------------------------------------------ #
    def test_fit_single_window_uses_sha256_cache_key(self, calc):
        """fit_single_window 应将结果缓存到 sha256 派生键下。"""
        prices = np.linspace(10.0, 20.0, 100)
        expected_key = hashlib.sha256(prices.tobytes()).hexdigest()[:16]

        fake_result = SimpleNamespace(success=True, x=np.array([150.0, 0.5, 8.0]))
        with patch("uniquant.brain.lppl.calculator.differential_evolution", return_value=fake_result):
            result = calc.fit_single_window(prices)

        assert result is not None
        assert expected_key in calc._fit_cache
        assert calc._fit_cache[expected_key] == result

    # ------------------------------------------------------------------ #
    #  测试 6：相同输入应命中缓存，不重复优化
    # ------------------------------------------------------------------ #
    def test_fit_single_window_reuses_cached_result(self, calc):
        """相同输入应直接命中缓存。"""
        prices = np.linspace(10.0, 20.0, 100)
        expected_key = hashlib.sha256(prices.tobytes()).hexdigest()[:16]
        cached_result = {"params": [150.0, 0.5, 8.0, 1.0, -1.0, 0.2, 0.0], "rmse": 0.01, "t_len": 100}
        calc._fit_cache[expected_key] = cached_result

        with patch("uniquant.brain.lppl.calculator.differential_evolution") as optimizer:
            result = calc.fit_single_window(prices)

        optimizer.assert_not_called()
        assert result is cached_result

    # ------------------------------------------------------------------ #
    #  测试 7：lppl_func 不接受 tau <= 0
    # ------------------------------------------------------------------ #
    def test_lppl_func_handles_negative_tau(self, calc):
        """当 tc < t 时，tau 应被 clamp 到 1e-8（与 core.py/engine.py 统一）。"""
        t = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
        tc = 3.0  # tc 在数据中间

        result = calc.lppl_func(t, tc, m=0.5, w=8.0, a=10.0, b=-1.0, c=0.5, phi=0.0)

        # tc < t 的点，tau 被 clamp 到 1e-8，返回有限值
        after_tc = t[t > tc]
        result_after = result[t > tc]
        assert np.all(np.isfinite(result_after)), (
            "lppl_func should return finite values for t > tc (tau clamped to 1e-8)"
        )

    # ------------------------------------------------------------------ #
    #  测试 8：fit_single_window 拒绝零价格
    # ------------------------------------------------------------------ #
    def test_fit_single_window_rejects_zero_prices(self, calc):
        """零价格序列应返回 None。"""
        prices = np.zeros(100)
        result = calc.fit_single_window(prices)
        assert result is None

    # ------------------------------------------------------------------ #
    #  测试 9：fit_single_window 拒绝负价格
    # ------------------------------------------------------------------ #
    def test_fit_single_window_rejects_negative_prices(self, calc):
        """负价格序列应返回 None。"""
        prices = np.full(100, -1.0)
        result = calc.fit_single_window(prices)
        assert result is None

    # ------------------------------------------------------------------ #
    #  测试 10：fit_single_window 正常数据
    # ------------------------------------------------------------------ #
    def test_fit_single_window_valid_prices(self, calc):
        """正常价格序列应返回有效结果。"""
        np.random.seed(42)
        n = 100
        prices = 10 + 0.05 * np.arange(n) + np.random.randn(n) * 0.3
        prices = np.maximum(prices, 1.0)

        result = calc.fit_single_window(prices)

        assert result is not None
        assert "params" in result
        assert "rmse" in result
