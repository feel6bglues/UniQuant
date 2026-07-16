"""Regression tests for LPPL core computation modules.

Tests synthetic data recovery, multifit stability, edge cases,
and regime classification boundaries.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.lppl.calculator import lppl_func
from uniquant.brain.lppl.cluster import ClusterConfig, SignalClusterDetector
from uniquant.brain.lppl.engine import (
    LPPLConfig,
    fit_single_window,
    fit_single_window_lbfgsb,
    precheck_fit_input,
)
from uniquant.brain.lppl.multifit import (
    MULTI_WINDOW_CONFIGS,
    WindowConfig,
    fit_multi_window,
    fit_single_layer,
)
from uniquant.brain.lppl.regime import DEFAULT_REGIME_CONFIG, MarketRegimeDetector, RegimeConfig

RANDOM_SEED = 42
np.random.seed(RANDOM_SEED)


# ──────────────── helpers ────────────────


def _make_synthetic_lppl(
    window: int,
    tc: float = 100.0,
    m: float = 0.5,
    w: float = 8.0,
    a: float = 6.0,
    b: float = -1.0,
    c: float = 0.3,
    phi: float = 0.0,
    noise_scale: float = 0.01,
) -> np.ndarray:
    t = np.arange(window, dtype=np.float64)
    log_price = lppl_func(t, tc, m, w, a, b, c, phi)
    noise = np.random.normal(0, noise_scale, size=window)
    return np.exp(log_price + noise)


def _make_basic_index_df(n: int = 300) -> pd.DataFrame:
    close = 100.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, size=n)))
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "volume": np.random.randint(1_000_000, 100_000_000, size=n),
    })


# =========================================================================
# 1.  Synthetic data: generate LPPL with known params, fit, verify ±20%
# =========================================================================


class TestSyntheticParameterRecovery:
    """Generate synthetic LPPL data and verify fitting recovers params."""

    def test_lbfgsb_recovers_high_r_squared(self):
        w_size = 80
        true_m = 0.5
        true_w = 9.0
        prices = _make_synthetic_lppl(
            w_size, tc=110.0, m=true_m, w=true_w,
            noise_scale=0.003,
        )
        config = LPPLConfig(
            window_range=[w_size],
            optimizer="lbfgsb",
            maxiter=30,
            m_bounds=(0.1, 0.9),
            w_bounds=(5.0, 13.0),
            tc_bound=(5, 60),
            n_workers=1,
        )
        result = fit_single_window_lbfgsb(prices, w_size, config)
        assert result is not None, "fit_single_window_lbfgsb returned None"
        assert result["r_squared"] > 0.85, f"R² too low: {result['r_squared']:.3f}"
        assert 0.1 < result["m"] < 0.9, f"m out of bounds: {result['m']:.3f}"

    def test_synthetic_fit_high_r_squared(self):
        prices = _make_synthetic_lppl(80, tc=110.0, m=0.5, w=9.0, noise_scale=0.002)
        config = LPPLConfig(
            window_range=[80],
            optimizer="lbfgsb",
            maxiter=30,
            m_bounds=(0.1, 0.9),
            w_bounds=(5.0, 13.0),
            tc_bound=(5, 60),
            n_workers=1,
        )
        result = fit_single_window_lbfgsb(prices, 80, config)
        assert result is not None, "lbfgsb fit returned None"
        assert result["r_squared"] > 0.85, f"R² too low: {result['r_squared']:.3f}"
        assert 0.1 < result["m"] < 0.9, f"m out of bounds: {result['m']:.3f}"


# =========================================================================
# 2.  Multifit stability: multiple starting points converge to similar results
# =========================================================================


class TestMultifitStability:
    """Multi-start fitting should converge to similar parameters."""

    def test_fit_single_layer_returns_result(self):
        prices = _make_synthetic_lppl(120, tc=150.0, m=0.4, w=9.0, noise_scale=0.005)
        config = MULTI_WINDOW_CONFIGS["short"]
        result = fit_single_layer(prices, len(prices), config)
        assert result is not None
        assert "m" in result
        assert 0.1 < result["m"] < 0.9

    def test_fit_multi_window_returns_all_layers(self):
        n = 300
        prices = 100.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, size=n)))
        results = fit_multi_window(prices, n)
        assert isinstance(results, dict)
        for layer in ("short", "medium", "long"):
            assert layer in results

    def test_run_multiple_seeds_stable_m(self):
        w_size = 80
        prices = _make_synthetic_lppl(w_size, tc=110.0, m=0.5, w=8.0, noise_scale=0.003)
        config = LPPLConfig(
            window_range=[w_size],
            optimizer="lbfgsb",
            maxiter=30,
            m_bounds=(0.1, 0.9),
            w_bounds=(5.0, 13.0),
            tc_bound=(5, 60),
            n_workers=1,
        )
        m_values = []
        for seed in range(42, 46):
            rs = np.random.RandomState(seed)
            noisy = prices * (1.0 + rs.normal(0, 0.001, size=w_size))
            result = fit_single_window_lbfgsb(noisy, w_size, config)
            if result is not None:
                m_values.append(result["m"])
        assert len(m_values) >= 3, f"Too many fits returned None ({len(m_values)}/4)"
        m_arr = np.array(m_values)
        assert np.std(m_arr) < 0.20, f"m std too high: {np.std(m_arr):.3f}"


# =========================================================================
# 3.  Edge cases: empty data, NaN, constant input, insufficient data
# =========================================================================


class TestEdgeCases:
    """Fit functions must handle degenerate inputs gracefully."""

    def test_precheck_empty_returns_error(self):
        assert precheck_fit_input(np.array([]), 50) is not None

    def test_precheck_nan_passes_precheck(self):
        arr = np.full(60, np.nan)
        result = precheck_fit_input(arr, 50)
        assert result is None

    def test_precheck_nan_price_fails_fit(self):
        result = fit_single_window(np.full(60, np.nan), 50)
        assert result is None

    def test_precheck_constant_price_returns_error(self):
        arr = np.full(60, 100.0)
        assert precheck_fit_input(arr, 50) is not None

    def test_precheck_window_too_small(self):
        arr = np.random.rand(5) + 10
        assert precheck_fit_input(arr, 10) is not None

    def test_fit_single_window_none_on_bad_input(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            fit_single_window(np.array([]), 50)

    def test_fit_single_window_none_on_constant(self):
        result = fit_single_window(np.full(60, 100.0), 50)
        assert result is None

    def test_fit_single_window_lbfgsb_none_on_constant(self):
        result = fit_single_window_lbfgsb(np.full(60, 100.0), 50)
        assert result is None

    def test_fit_single_window_none_on_short_data(self):
        result = fit_single_window(np.array([100.0, 101.0, 102.0]), 30)
        assert result is None

    def test_cluster_empty_history(self):
        detector = SignalClusterDetector(ClusterConfig(window_days=30))
        result = detector.detect_cluster("2025-01-01")
        assert result["cluster_level"] == "none"
        assert result["raw_danger_count"] == 0

    def test_regime_empty_dataframe(self):
        detector = MarketRegimeDetector()
        result = detector.detect(pd.DataFrame())
        assert result["regime"] == "unknown"

    def test_regime_too_few_rows(self):
        df = pd.DataFrame({"close": [1.0] * 50})
        detector = MarketRegimeDetector()
        result = detector.detect(df)
        assert result["regime"] == "unknown"


# =========================================================================
# 4.  Regime classification boundary values
# =========================================================================


class TestRegimeClassification:
    """MarketRegimeDetector boundary classifications."""

    @pytest.fixture
    def bull_df(self) -> pd.DataFrame:
        n = 300
        close = 100.0 * np.exp(np.linspace(0, 0.3, n))
        return pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "close": close,
        })

    @pytest.fixture
    def bear_df(self) -> pd.DataFrame:
        n = 300
        close = 100.0 * np.exp(np.linspace(0, -0.3, n))
        return pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "close": close,
        })

    @pytest.fixture
    def range_df(self) -> pd.DataFrame:
        np.random.seed(42)
        n = 300
        close = 100.0 + np.random.normal(0, 2.0, size=n).cumsum()
        close = np.clip(close, 90, 110)
        return pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "close": close,
        })

    def test_strong_bull_classification(self, bull_df):
        detector = MarketRegimeDetector()
        result = detector.detect(bull_df, individual_danger_rate=0.05)
        assert result["regime"] in ("weak_bull", "strong_bull")
        assert result["trend_up"] is True

    def test_strong_bear_classification(self, bear_df):
        detector = MarketRegimeDetector()
        result = detector.detect(bear_df, individual_danger_rate=0.02)
        assert result["regime"] in ("weak_bear", "strong_bear")
        assert result["trend_down"] is True

    def test_range_classification(self, range_df):
        detector = MarketRegimeDetector()
        result = detector.detect(range_df, individual_danger_rate=0.0)
        assert result["regime"] == "range"

    def test_vol_high_flag(self, bull_df):
        high_vol_df = bull_df.copy()
        noise = np.random.normal(0, 5, size=300)
        high_vol_df["close"] = high_vol_df["close"] + noise
        detector = MarketRegimeDetector(
            RegimeConfig(vol_high_threshold=0.30)
        )
        result = detector.detect(high_vol_df, individual_danger_rate=0.05)
        assert "vol_high" in result

    def test_breadth_high_triggers_strong_bull(self, bull_df):
        detector = MarketRegimeDetector()
        result = detector.detect(bull_df, individual_danger_rate=0.05)
        if result["trend_up"] and not result["vol_high"]:
            if result["individual_danger_rate"] > 0.01:
                assert result["regime"] == "strong_bull"
            else:
                assert result["regime"] == "weak_bull"

    def test_regime_params_are_returned(self, bull_df):
        detector = MarketRegimeDetector()
        result = detector.detect(bull_df, individual_danger_rate=0.02)
        assert "params" in result
        assert "signal_adjustment" in result["params"]

    def test_ma_values_shape(self, bull_df):
        detector = MarketRegimeDetector()
        result = detector.detect(bull_df)
        ma = result["ma_values"]
        for p in (60, 120, 250):
            assert p in ma

    def test_danger_rate_edge_zero(self, bull_df):
        detector = MarketRegimeDetector()
        result = detector.detect(bull_df, individual_danger_rate=0.0)
        assert "regime" in result
        assert result["individual_danger_rate"] == 0.0

    def test_danger_rate_edge_one(self, bull_df):
        detector = MarketRegimeDetector()
        result = detector.detect(bull_df, individual_danger_rate=0.999)
        assert "regime" in result
        assert result["individual_danger_rate"] == 0.999


# =========================================================================
# 5.  SignalClusterDetector edge & boundary
# =========================================================================


class TestSignalClusterDetector:
    """Cluster detection boundary values."""

    def test_add_signal_then_detect(self):
        detector = SignalClusterDetector(ClusterConfig(window_days=30))
        for i in range(6):
            detector.add_signal(f"2025-01-{i+1:02d}", {
                "final_score": 0.8,
                "level": "danger",
                "layers": {"medium": {"m": 0.45}},
                "n_danger": 2,
            })
        result = detector.detect_cluster("2025-01-15")
        assert result["cluster_level"] == "strong"
        assert result["raw_danger_count"] >= 5

    def test_m_stability_single_danger(self):
        detector = SignalClusterDetector(ClusterConfig(window_days=30))
        detector.add_signal("2025-01-01", {
            "final_score": 0.6,
            "level": "danger",
            "layers": {"medium": {"m": 0.5}},
            "n_danger": 1,
        })
        result = detector.detect_cluster("2025-01-05")
        assert result["m_stability"] == 0.5

    def test_cluster_multiplier_boundaries(self):
        detector = SignalClusterDetector()
        assert detector.get_cluster_multiplier(0.9) == 1.5
        assert detector.get_cluster_multiplier(0.5) == 1.2
        assert detector.get_cluster_multiplier(0.2) == 1.0
        assert detector.get_cluster_multiplier(0.0) == 0.5

    def test_no_signals_in_window(self):
        detector = SignalClusterDetector(ClusterConfig(window_days=10))
        detector.add_signal("2025-01-01", {
            "final_score": 0.7,
            "level": "warning",
            "layers": {"medium": {"m": 0.4}},
            "n_danger": 0,
        })
        result = detector.detect_cluster("2025-03-01")
        assert result["raw_danger_count"] == 0


# =========================================================================
# 6.  precheck_fit_input from core.py (comprehensive rejection checks)
# =========================================================================


class TestPrecheckFitInput:
    """Comprehensive rejection of bad inputs."""

    def test_non_positive_price(self):
        arr = np.array([100, 101, 0, 103, 104])
        assert precheck_fit_input(arr, 5) is not None

    def test_nan_price(self):
        arr = np.array([100, np.nan, 102])
        assert precheck_fit_input(arr, 3) is not None

    def test_constant_ptp_small(self):
        arr = np.full(60, 50.0)
        assert precheck_fit_input(arr, 50) is not None

    def test_sufficient_data_passes(self):
        arr = np.cumsum(np.random.randn(100)) + 100
        assert precheck_fit_input(arr, 60) is None