"""第九轮（2026-10-17）覆盖率补测：``brain/lppl/core.py``。

覆盖 ``cost_function`` / ``_cost_function_python`` / ``validate_input_data`` /
``detect_negative_bubble`` / ``calculate_bottom_signal_strength`` /
``precheck_fit_input`` / ``track_fit_failure`` 的全部可达分支。

三个 ``@njit`` 内核（``_lppl_func_numba`` / ``_cost_function_numba`` /
``_fused_cost_numba``）在 ``NUMBA_AVAILABLE`` 为真时被编译为原生码，coverage
tracer 不可见其函数体——故经 CPUDispatcher 的 ``.py_func``（同一份源码行的纯
Python 实现）做**等价逻辑**单元测试（口径同
``tests/brain/lppl/test_lppl_numba_optimizer_coverage.py``）。

未覆盖项（**不可达防御**，不写"强行命中"的测试）：
* ``import numba`` 失败的 ``except ImportError`` 回退（:52-54）——numbba 是硬依赖，本仓/CI 恒可导入。

不触网、不读数据湖、不依赖 czsc/backtrader。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.lppl import core
from uniquant.brain.lppl.core import (
    calculate_bottom_signal_strength,
    cost_function,
    detect_negative_bubble,
    precheck_fit_input,
    track_fit_failure,
    validate_input_data,
)


class TestTrackFitFailure:
    def test_increments_stats_when_provided(self) -> None:
        stats: dict = {}
        track_fit_failure("insufficient_data", stats, context="unit-test")
        track_fit_failure("insufficient_data", stats)
        assert stats == {"insufficient_data": 2}

    def test_no_stats_does_not_raise(self) -> None:
        # stats=None 时仅写日志，不抛异常
        assert track_fit_failure("optimizer_failed") is None


class TestPrecheckFitInput:
    def test_insufficient_data(self) -> None:
        assert precheck_fit_input(np.arange(10.0) + 1.0, 50) == "insufficient_data"

    def test_non_positive_price(self) -> None:
        x = np.arange(60.0) + 1.0
        x[-1] = 0.0  # 必须落在末尾 window_size 切片内
        assert precheck_fit_input(x, 50) == "non_positive_price"

    def test_nan_or_inf(self) -> None:
        x = np.arange(60.0) + 1.0
        x[-3] = np.nan
        assert precheck_fit_input(x, 50) == "nan_or_inf"

    def test_constant_price(self) -> None:
        assert precheck_fit_input(np.full(60, 7.0), 50) == "constant_price"

    def test_valid_returns_none(self) -> None:
        assert precheck_fit_input(np.linspace(1.0, 2.0, 60), 50) is None


class TestCostFunctionDispatch:
    def test_python_path_when_numba_disabled(self, monkeypatch) -> None:
        monkeypatch.setattr(core, "ENABLE_NUMBA_JIT", False)
        t = np.arange(20.0)
        lp = np.log(70.0 - t)
        val = cost_function((70.0, 0.5, 8.0, 1.0, -1.0, 0.1, 0.5), t, lp)
        assert np.isfinite(val)

    def test_numba_path_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setattr(core, "ENABLE_NUMBA_JIT", True)
        t = np.arange(20.0)
        lp = np.log(70.0 - t)
        val = cost_function(
            np.array([70.0, 0.5, 8.0, 1.0, -1.0, 0.1, 0.5]), t, lp
        )
        assert np.isfinite(val)

    def test_python_numerical_error_returns_sentinel(self, monkeypatch) -> None:
        """形状不匹配 ⇒ ``lppl_func``/广播抛 ``ValueError`` ⇒ 兜底返回 1e10。"""
        monkeypatch.setattr(core, "ENABLE_NUMBA_JIT", False)
        val = core._cost_function_python(
            (70.0, 0.5, 8.0, 1.0, -1.0, 0.1, 0.5),
            np.arange(5.0),
            np.arange(3.0),
        )
        assert val == 1e10


class TestValidateInputData:
    @staticmethod
    def _df(n: int = 60) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n, freq="D"),
                "open": np.linspace(10, 11, n),
                "high": np.linspace(10.5, 11.5, n),
                "low": np.linspace(9.5, 10.5, n),
                "close": np.linspace(10, 11, n),
                "volume": np.full(n, 1e6),
            }
        )

    def test_none_or_empty(self) -> None:
        ok, msg = validate_input_data(pd.DataFrame(), "000001.SZ")
        assert ok is False and "empty" in msg

    def test_missing_columns(self) -> None:
        df = self._df().drop(columns=["volume"])
        ok, msg = validate_input_data(df, "000001.SZ")
        assert ok is False and "Missing required columns" in msg

    def test_insufficient_rows(self) -> None:
        ok, msg = validate_input_data(self._df(30), "000001.SZ")
        assert ok is False and "Insufficient data rows" in msg

    def test_null_close(self) -> None:
        df = self._df()
        df.loc[5, "close"] = np.nan
        ok, msg = validate_input_data(df, "000001.SZ")
        assert ok is False and "Null values" in msg

    def test_non_positive_close(self) -> None:
        df = self._df()
        df.loc[5, "close"] = 0.0
        ok, msg = validate_input_data(df, "000001.SZ")
        assert ok is False and "Non-positive prices" in msg

    def test_valid(self) -> None:
        ok, msg = validate_input_data(self._df(), "000001.SZ")
        assert ok is True and msg == ""


class TestDetectNegativeBubble:
    def test_out_of_bounds_m_returns_no_signal(self) -> None:
        is_neg, sig = detect_negative_bubble(m=-5.0, w=8.0, b=1.0, days_left=10.0)
        assert is_neg is False and sig == "无抄底信号"

    def test_out_of_bounds_w_returns_no_signal(self) -> None:
        is_neg, sig = detect_negative_bubble(m=0.5, w=500.0, b=1.0, days_left=10.0)
        assert is_neg is False and sig == "无抄底信号"

    def test_b_non_positive_returns_no_signal(self) -> None:
        is_neg, sig = detect_negative_bubble(m=0.5, w=8.0, b=-1.0, days_left=10.0)
        assert is_neg is False and sig == "无抄底信号"

    @pytest.mark.parametrize(
        ("days_left", "expected"),
        [
            (5.0, "强抄底信号 (Strong Buy)"),
            (30.0, "中等抄底信号 (Buy)"),
            (100.0, "弱抄底信号 (Watch for Buy)"),
        ],
    )
    def test_days_left_grades(self, days_left: float, expected: str) -> None:
        is_neg, sig = detect_negative_bubble(m=0.5, w=8.0, b=1.0, days_left=days_left)
        assert is_neg is True
        assert sig == expected


class TestBottomSignalStrength:
    def test_zero_when_params_out_of_bounds(self) -> None:
        assert calculate_bottom_signal_strength(m=-5.0, w=8.0, b=1.0, rmse=0.01) == 0.0

    def test_zero_when_b_non_positive(self) -> None:
        assert calculate_bottom_signal_strength(m=0.5, w=8.0, b=0.0, rmse=0.01) == 0.0

    def test_strength_within_unit_interval(self) -> None:
        val = calculate_bottom_signal_strength(m=0.5, w=8.0, b=1.0, rmse=0.0)
        assert 0.0 <= val <= 1.0
        assert val == pytest.approx(1.0)

    def test_bounded_when_inputs_poor(self) -> None:
        val = calculate_bottom_signal_strength(m=0.9, w=1.0, b=0.01, rmse=10.0)
        assert 0.0 <= val <= 1.0


class TestNumbaKernels:
    """经 ``.py_func`` 覆盖 ``@njit`` 内核的等价纯 Python 逻辑（tracer 伪影说明见模块 docstring）。"""

    def test_lppl_func_kernel_normal(self) -> None:
        t = np.arange(30.0)
        out = core._lppl_func_numba.py_func(
            t, 100.0, 0.5, 8.0, 1.0, -1.0, 0.1, 0.5
        )
        assert out.shape == (30,)
        assert np.isfinite(out).all()

    def test_lppl_func_kernel_tau_floor_branch(self) -> None:
        # 所有 tau < 1e-8 ⇒ 走 tau_i = 1e-8 归一化分支
        t = np.array([1.0, 1.0 + 1e-12, 1.0 + 2e-12])
        out = core._lppl_func_numba.py_func(
            t, 1.0 + 3e-12, 0.5, 8.0, 1.0, -1.0, 0.1, 0.5
        )
        assert np.isfinite(out).all()

    def test_cost_function_numba_kernel(self) -> None:
        t = np.arange(30.0)
        lp = np.log(100.0 - t)
        val = core._cost_function_numba.py_func(
            np.array([100.0, 0.5, 8.0, 1.0, -1.0, 0.1, 0.5]), t, lp
        )
        assert np.isfinite(val)
        assert val >= 0.0

    def test_fused_cost_kernel_normal(self) -> None:
        t = np.arange(30.0)
        lp = np.log(100.0 - t)
        val = core._fused_cost_numba.py_func(
            np.array([100.0, 0.5, 8.0, 1.0, -1.0, 0.1, 0.5]), t, lp
        )
        assert np.isfinite(val) and val >= 0.0

    def test_fused_cost_kernel_tau_floor_branch(self) -> None:
        t = np.array([1.0, 1.0 + 1e-12, 1.0 + 2e-12])
        lp = np.zeros(3)
        val = core._fused_cost_numba.py_func(
            np.array([1.0 + 3e-12, 1.0, 8.0, 1.0, -1.0, 0.1, 0.5]), t, lp
        )
        assert np.isfinite(val)
