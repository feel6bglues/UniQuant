# -*- coding: utf-8 -*-
"""
Brain Boundary Tests — Push analysis engines to breaking points.

Tests LPPL, Wyckoff, and Factor engines with extreme/unusual inputs
to verify graceful degradation instead of infinite loops or silent corruption.
"""

import signal
import sys
import threading
from contextlib import contextmanager

import numpy as np
import pandas as pd
import pytest

# ── Timeout utility ──────────────────────────────────────────────────────────

class TimeoutError(Exception):
    pass

@contextmanager
def timeout(seconds: int, desc: str = ""):
    """Context manager that raises TimeoutError after `seconds` (Unix only)."""
    def _handler(signum, frame):
        raise TimeoutError(f"Timed out after {seconds}s: {desc}")
    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def run_with_timeout(func, args=(), kwargs=None, seconds=60, desc=""):
    """Run func in a thread with timeout. Returns (result, error_tuple_or_None)."""
    if kwargs is None:
        kwargs = {}
    result_box = [None]
    error_box = [None]

    def _target():
        try:
            result_box[0] = func(*args, **kwargs)
        except Exception:
            error_box[0] = sys.exc_info()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=seconds)
    if t.is_alive():
        return None, (TimeoutError, TimeoutError(f"Thread timed out after {seconds}s: {desc}"), None)
    return result_box[0], error_box[0]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ohlv_df(n: int, price_func=None, start_date="2020-01-01"):
    """Build a synthetic OHLCV DataFrame with n rows."""
    dates = pd.bdate_range(start=start_date, periods=n)
    if price_func is None:
        close = np.linspace(100, 120, n)
    else:
        close = price_func(n)
    close = close.astype(float)
    # Derive OHLV from close with small noise
    rng = np.random.RandomState(42)
    noise = rng.uniform(-0.5, 0.5, n)
    open_ = close + noise
    high = np.maximum(close, open_) + rng.uniform(0.1, 1.0, n)
    low = np.minimum(close, open_) - rng.uniform(0.1, 1.0, n)
    volume = rng.randint(100000, 1000000, n).astype(float)
    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Task 1: LPPL Extreme Parameter Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestLPPLBoundary:
    """Boundary tests for the LPPL engine."""

    def _get_fit_fn(self):
        """Import and return the fit_single_window function from engine.py."""
        from uniquant.brain.lppl.engine import fit_single_window
        return fit_single_window

    def _get_calc_fit(self):
        """Import and return LPPLCalculator.fit_single_window."""
        from uniquant.brain.lppl.calculator import LPPLCalculator
        calc = LPPLCalculator()
        return calc.fit_single_window

    # ── 1. Too-short window ──────────────────────────────────────────────────

    def test_too_short_window_returns_none(self):
        """fit_single_window with window_size=5 should return None (not hang)."""
        fit = self._get_fit_fn()
        prices = np.array([100.0, 101.0, 102.0, 103.0, 104.0])

        result, err = run_with_timeout(
            fit, args=(prices, 5), seconds=30,
            desc="fit_single_window with 5 points",
        )

        assert err is None, f"Unexpected exception: {err[1]}"
        # precheck_fit_input rejects window_size < 10 → returns None
        assert result is None, f"Expected None for window_size=5, got {result}"

    # ── 2. Flat price series ─────────────────────────────────────────────────

    def test_flat_prices_returns_none(self):
        """Perfectly flat prices (all 100.0) should return None, not hang."""
        fit = self._get_fit_fn()
        prices = np.full(50, 100.0)

        result, err = run_with_timeout(
            fit, args=(prices, 40), seconds=60,
            desc="fit_single_window with flat prices",
        )

        assert err is None, f"Unexpected exception: {err[1]}"
        # precheck_fit_input detects no_price_variation → returns None
        assert result is None, f"Expected None for flat prices, got {result}"

    # ── 3. Monotonic price series ────────────────────────────────────────────

    def test_monotonic_prices_no_hang(self):
        """Strictly increasing prices [1..100] should complete without hanging."""
        fit = self._get_fit_fn()
        prices = np.arange(1, 101, dtype=np.float64)

        result, err = run_with_timeout(
            fit, args=(prices, 80), seconds=120,
            desc="fit_single_window with monotonic prices",
        )

        assert err is None, f"Unexpected exception or timeout: {err[1]}"
        # May return a fit dict or None — both are acceptable as long as no hang
        if result is not None:
            assert isinstance(result, dict), f"Expected dict, got {type(result)}"
            assert "rmse" in result, "Result dict missing 'rmse' key"

    # ── 4. NaN injection ─────────────────────────────────────────────────────

    def test_nan_prices_returns_none(self):
        """Prices containing NaN should be caught; no NaN propagation into results."""
        fit = self._get_fit_fn()
        prices = np.array([100.0, 101.0, np.nan, 103.0, 104.0] * 20, dtype=np.float64)

        result, err = run_with_timeout(
            fit, args=(prices, 50), seconds=60,
            desc="fit_single_window with NaN prices",
        )

        assert err is None, f"Unexpected exception: {err[1]}"
        # The calculator.fit checks for NaN and returns None
        # The engine.fit_single_window does np.log(price_data) which produces NaN,
        # then cost_function returns 1e10 for NaN costs → DE should still fail gracefully
        # Either None or a result without NaN is acceptable
        if result is not None:
            assert isinstance(result, dict)
            rmse = result.get("rmse", 0)
            assert not np.isnan(rmse), f"NaN leaked into rmse: {rmse}"
            r2 = result.get("r_squared", 0)
            assert not np.isnan(r2), f"NaN leaked into r_squared: {r2}"

    def test_nan_via_calculator(self):
        """LPPLCalculator.fit_single_window should reject NaN prices explicitly."""
        calc_fit = self._get_calc_fit()
        prices = np.array([100.0, np.nan, 102.0, 103.0, 104.0] * 20, dtype=np.float64)

        result, err = run_with_timeout(
            calc_fit, args=(prices,), seconds=30,
            desc="LPPLCalculator.fit_single_window with NaN",
        )

        assert err is None, f"Unexpected exception: {err[1]}"
        assert result is None, f"Calculator should reject NaN prices, got {result}"

    # ── 5. Single-value array ────────────────────────────────────────────────

    def test_single_value_array(self):
        """Array of length 1 should be handled gracefully."""
        fit = self._get_fit_fn()
        prices = np.array([42.0])

        result, err = run_with_timeout(
            fit, args=(prices, 1), seconds=15,
            desc="fit_single_window with length-1 array",
        )

        assert err is None, f"Unexpected exception: {err[1]}"
        # window_size=1 < 10 → precheck returns "window_too_small" → None
        assert result is None, f"Expected None for single-element array, got {result}"

    # ── 6. Zero prices ───────────────────────────────────────────────────────

    def test_zero_prices_no_crash(self):
        """Prices starting from 0 (log(0) = -inf) should not crash."""
        fit = self._get_fit_fn()
        # Array with some zeros — np.log(0) = -inf
        prices = np.array([0.0, 1.0, 2.0, 3.0, 4.0] * 20, dtype=np.float64)

        result, err = run_with_timeout(
            fit, args=(prices, 50), seconds=60,
            desc="fit_single_window with zero prices",
        )

        # Should either return None or handle gracefully — NOT crash
        assert err is None or isinstance(err[1], (ValueError, FloatingPointError)), \
            f"Unexpected crash: {err[1] if err else 'none'}"

    # ── 7. Negative prices ───────────────────────────────────────────────────

    def test_negative_prices_no_crash(self):
        """Negative prices (impossible in real markets) should be handled."""
        fit = self._get_fit_fn()
        prices = np.array([-10.0, -5.0, 0.0, 5.0, 10.0] * 20, dtype=np.float64)

        result, err = run_with_timeout(
            fit, args=(prices, 50), seconds=30,
            desc="fit_single_window with negative prices",
        )

        # np.log of negative = NaN → should return None or raise
        assert err is None or isinstance(err[1], (ValueError, FloatingPointError)), \
            f"Unexpected crash: {err[1] if err else 'none'}"

    # ── 8. Extremely large prices ────────────────────────────────────────────

    def test_extremely_large_prices(self):
        """Prices in the billions should not cause numerical overflow."""
        fit = self._get_fit_fn()
        base = 1e12
        prices = np.linspace(base, base * 1.5, 80)

        result, err = run_with_timeout(
            fit, args=(prices, 70), seconds=120,
            desc="fit_single_window with 1e12 prices",
        )

        assert err is None, f"Unexpected exception or timeout: {err[1]}"
        # Should return a dict or None; large prices should still be log-able
        if result is not None:
            assert isinstance(result, dict)
            assert np.isfinite(result.get("rmse", 0)), "rmse is not finite"


# ═══════════════════════════════════════════════════════════════════════════════
# Task 2: Wyckoff Logic Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestWyckoffBoundary:
    """Boundary tests for the Wyckoff engine."""

    def _get_engine(self):
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        return WyckoffEngine(lookback_days=120)

    # ── 2015 crash scenario ──────────────────────────────────────────────────

    def test_2015_crash_not_accumulation(self):
        """Synthetic 2015 crash: rise 3000→5178 then crash to 3500 in 20 days.
        Engine must NOT report ACCUMULATION during the crash phase."""
        engine = self._get_engine()

        # Build crash dataset: 120 days rise, 20 days crash = 140 days total
        n_rise, n_crash = 120, 20
        dates = pd.bdate_range(start="2015-05-01", periods=n_rise + n_crash)

        # Phase 1: Bull run 3000→5178
        rise_close = np.linspace(3000, 5178, n_rise)
        # Phase 2: Crash 5178→3500
        crash_close = np.linspace(5178, 3500, n_crash)

        close = np.concatenate([rise_close, crash_close])
        rng = np.random.RandomState(42)
        noise = rng.uniform(-10, 10, len(close))
        close = close + noise
        open_ = close + rng.uniform(-15, 15, len(close))
        high = np.maximum(close, open_) + rng.uniform(5, 30, len(close))
        low = np.minimum(close, open_) - rng.uniform(5, 30, len(close))
        # Volume surges during crash
        volume = np.concatenate([
            rng.randint(1_000_000, 5_000_000, n_rise).astype(float),
            rng.randint(5_000_000, 20_000_000, n_crash).astype(float),
        ])

        df = pd.DataFrame({
            "date": dates, "open": open_, "high": high,
            "low": low, "close": close, "volume": volume,
        })

        result, err = run_with_timeout(
            engine.analyze, args=(df, "000001", "日线"), seconds=120,
            desc="Wyckoff 2015 crash analysis",
        )

        assert err is None, f"Wyckoff crashed or timed out: {err[1]}"

        # Get phase from the report
        phase = result.structure.phase if result.structure else None
        phase_str = phase.value if hasattr(phase, 'value') else str(phase)

        # During the crash tail, phase should NOT be ACCUMULATION
        assert phase_str != "accumulation", (
            f"Wyckoff falsely identified ACCUMULATION during a crash! "
            f"Phase={phase_str}, signal={result.signal.signal_type if result.signal else 'N/A'}"
        )

        # Acceptable phases: markdown, distribution, or unknown
        acceptable = {"markdown", "distribution", "unknown"}
        assert phase_str in acceptable, (
            f"Expected markdown/distribution/unknown during crash, got '{phase_str}'"
        )

    # ── Wyckoff with insufficient data ───────────────────────────────────────

    def test_insufficient_data_returns_no_signal(self):
        """Only 10 rows of daily data (below min 100) → no-signal report."""
        engine = self._get_engine()
        df = _make_ohlv_df(10)

        result, err = run_with_timeout(
            engine.analyze, args=(df, "TEST", "日线"), seconds=30,
            desc="Wyckoff with insufficient data",
        )

        assert err is None, f"Unexpected error: {err[1]}"
        # Should produce a no-signal report, not crash
        assert result is not None
        assert result.signal.signal_type == "no_signal" or result.structure.phase.value == "unknown"

    # ── Wyckoff with constant prices ─────────────────────────────────────────

    def test_constant_prices_no_crash(self):
        """All prices identical (zero volatility) → graceful handling."""
        engine = self._get_engine()
        n = 150
        dates = pd.bdate_range(start="2023-01-01", periods=n)
        df = pd.DataFrame({
            "date": dates,
            "open": np.full(n, 50.0),
            "high": np.full(n, 50.0),
            "low": np.full(n, 50.0),
            "close": np.full(n, 50.0),
            "volume": np.full(n, 100000.0),
        })

        result, err = run_with_timeout(
            engine.analyze, args=(df, "FLAT", "日线"), seconds=30,
            desc="Wyckoff with constant prices",
        )

        assert err is None, f"Crash on constant prices: {err[1]}"
        assert result is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Task 3: Factor Look-Ahead Bias Detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestFactorLookAheadBias:
    """Detect look-ahead bias in factor analysis pipeline."""

    def _get_analyzer(self):
        from uniquant.brain.factors.analyzer import FactorAnalyzer, AnalysisMode
        return FactorAnalyzer(), AnalysisMode

    # ── Look-ahead via future close as feature ───────────────────────────────

    def test_future_return_as_feature_lookahead_detection(self):
        """If future_return (T+1 return) is injected as a feature, the Rank IC
        should be near 1.0 — proving the pipeline accepts leaked future data
        without rejecting it. This is a detection test, not a prevention test.

        The pipeline in BACKTEST mode uses shift(-holding_period) internally to
        compute forward returns. If we inject the SAME value as a feature column,
        Rank IC should be ~1.0 cross-sectionally, proving the pipeline does NOT
        guard against look-ahead in BACKTEST mode."""
        analyzer, AnalysisMode = self._get_analyzer()

        n_stocks = 50
        n_days = 100
        rng = np.random.RandomState(42)

        codes = [f"SH{str(i).zfill(6)}" for i in range(n_stocks)]
        dates = pd.bdate_range(start="2023-01-01", periods=n_days)

        rows = []
        for code in codes:
            base_price = rng.uniform(10, 100)
            prices = base_price + np.cumsum(rng.randn(n_days) * 0.5)
            prices = np.maximum(prices, 1.0)
            for j, d in enumerate(dates):
                rows.append({
                    "code": code,
                    "date": d,
                    "close": prices[j],
                })

        df = pd.DataFrame(rows)
        df = df.sort_values(["code", "date"]).reset_index(drop=True)

        # Inject the ACTUAL future return as a feature column
        # This is the exact same value the pipeline computes internally as
        # _forward_ret_1 = close.shift(-1)/close - 1
        df["future_return_leak"] = df.groupby("code")["close"].transform(
            lambda s: s.shift(-1) / s - 1
        )
        df_valid = df.dropna(subset=["future_return_leak"])

        # Also add a random noise factor for comparison
        df_valid = df_valid.copy()
        df_valid["random_noise"] = rng.randn(len(df_valid))

        ic_results = analyzer.compute_ic_ir(
            df_valid,
            factor_cols=["future_return_leak", "random_noise"],
            holding_periods=[1],
            date_col="date",
            code_col="code",
            price_col="close",
            mode=AnalysisMode.BACKTEST,
        )

        assert "future_return_leak" in ic_results, "IC results missing the leaky factor"
        period_1 = ic_results["future_return_leak"].get(1)
        assert period_1 is not None, "No IC result for holding_period=1"

        ic_leak = period_1.ic_mean
        ic_noise = 0.0
        if "random_noise" in ic_results and ic_results["random_noise"].get(1):
            ic_noise = ic_results["random_noise"][1].ic_mean

        print("\n  [LOOK-AHEAD DETECTION]")
        print(f"    future_return_leak IC = {ic_leak:.4f}")
        print(f"    random_noise      IC = {ic_noise:.4f}")

        # The leaked future return should have near-perfect IC because it IS the
        # forward return the pipeline computes internally
        assert abs(ic_leak) > 0.90, (
            f"Expected IC > 0.90 for future_return leaky feature (it's the exact forward return), "
            f"got {ic_leak:.4f}. This suggests the IC pipeline has a bug or the "
            f"cross-sectional ranking is not working as expected."
        )

        # The random noise should have low IC
        assert abs(ic_noise) < 0.5, (
            f"Random noise IC suspiciously high: {ic_noise:.4f}"
        )

        print("  ⚠ LOOK-AHEAD CONFIRMED: Pipeline accepts future return as feature")
        print(f"    Leaked IC ({ic_leak:.4f}) >> Random IC ({ic_noise:.4f})")
        print("    BACKTEST mode does NOT reject future data — by design for offline analysis.")
        print("    LIVE mode correctly raises ValueError to prevent this.")

    # ── LIVE mode rejects negative shift ─────────────────────────────────────

    def test_live_mode_rejects_forward_returns(self):
        """AnalysisMode.LIVE should raise ValueError to prevent look-ahead."""
        analyzer, AnalysisMode = self._get_analyzer()

        n_stocks = 10
        n_days = 50
        rng = np.random.RandomState(42)

        rows = []
        for i in range(n_stocks):
            code = f"SH{str(i).zfill(6)}"
            prices = 50 + np.cumsum(rng.randn(n_days) * 0.5)
            for j, d in enumerate(pd.bdate_range("2023-01-01", periods=n_days)):
                rows.append({"code": code, "date": d, "close": prices[j], "factor_a": rng.randn()})

        df = pd.DataFrame(rows)

        with pytest.raises(ValueError, match="Lookahead"):
            analyzer.compute_ic_ir(
                df,
                factor_cols=["factor_a"],
                holding_periods=[1],
                mode=AnalysisMode.LIVE,
            )

    # ── Walk-forward: future data should not inflate OOS IC ──────────────────

    def test_walk_forward_no_perfect_oos_ic(self):
        """Walk-forward pipeline with a random factor should NOT yield OOS IC > 0.99."""
        from uniquant.brain.factors.walk_forward_pipeline import WalkForwardFactorPipeline

        n_stocks = 30
        n_days = 600  # enough for train+test windows
        rng = np.random.RandomState(42)

        rows = []
        for i in range(n_stocks):
            code = f"SH{str(i).zfill(6)}"
            prices = 50 + np.cumsum(rng.randn(n_days) * 0.5)
            prices = np.maximum(prices, 1.0)
            for j, d in enumerate(pd.bdate_range("2020-01-01", periods=n_days)):
                rows.append({
                    "code": code,
                    "date": d,
                    "close": prices[j],
                    "random_noise": rng.randn(),
                })

        df = pd.DataFrame(rows)

        pipeline = WalkForwardFactorPipeline(
            train_window=252,
            test_window=63,
            min_train_days=100,
        )

        result, err = run_with_timeout(
            pipeline.run,
            kwargs={"df": df, "factor_cols": ["random_noise"], "date_col": "date",
                     "code_col": "code", "price_col": "close"},
            seconds=120,
            desc="Walk-forward with random noise factor",
        )

        assert err is None, f"Walk-forward failed: {err[1]}"
        assert result is not None

        # OOS IC for random noise should be low
        oos_ic = abs(result.oos_ic_mean)
        print(f"\n  [WALK-FORWARD] Random noise OOS IC = {oos_ic:.4f}")

        assert oos_ic < 0.99, (
            f"OOS IC suspiciously high ({oos_ic:.4f}) for random noise — possible leakage"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point — run directly with python
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Print all tracebacks even on failure
    pytest.main([__file__, "-xvs", "--tb=long"])
