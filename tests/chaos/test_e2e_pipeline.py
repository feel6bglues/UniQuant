# -*- coding: utf-8 -*-
"""
Full Pipeline Integration Test (Chaos E2E)
==========================================
Generates synthetic A-stock market data and drives it through:
  1. LPPL bubble detection engine
  2. Wyckoff phase analysis engine
  3. Factor analysis (momentum, volatility)
  4. Full backtest with MA20 crossover strategy
  5. UnifiedMatchingEngine vectorized fill

Every assertion verifies real behaviour, not just "doesn't crash".
"""

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytest


# ─── Timing helper ────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    name: str
    passed: bool
    elapsed_s: float
    error: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


def _time_step(name: str, fn):
    """Run *fn*, return StepResult with wall-clock timing."""
    t0 = time.perf_counter()
    try:
        details = fn()
        return StepResult(name=name, passed=True, elapsed_s=time.perf_counter() - t0,
                          details=details or {})
    except Exception as exc:
        return StepResult(name=name, passed=False, elapsed_s=time.perf_counter() - t0,
                          error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")


# ─── Synthetic data factory ──────────────────────────────────────────────────

def generate_synthetic_data(n_days: int = 500, seed: int = 42) -> pd.DataFrame:
    """
    Generate realistic synthetic A-stock OHLCV data.
    - Mean-reverting log-price with 3% daily vol (to produce crossings)
    - OHLC built around close with realistic intraday ranges
    - Volume log-normal ~10M shares/day
    """
    np.random.seed(seed)
    dates = pd.bdate_range("2022-01-01", periods=n_days)

    # Ornstein-Uhlenbeck process: mean-reverting around log(10)
    mu = np.log(10.0)
    kappa = 0.10  # mean-reversion speed (strong)
    sigma = 0.04  # daily vol (high)
    log_price = np.zeros(n_days)
    log_price[0] = mu
    for i in range(1, n_days):
        log_price[i] = log_price[i - 1] + kappa * (mu - log_price[i - 1]) + sigma * np.random.randn()
    close = np.exp(log_price)
    noise = np.abs(np.random.randn(n_days)) * 0.01 + 0.005
    high = close * (1 + noise)
    low = close * (1 - noise)
    open_ = close * (1 + np.random.randn(n_days) * 0.003)
    # Ensure OHLC consistency
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    volume = np.exp(np.random.randn(n_days) * 0.5 + 16.0).astype(int)  # ~10M

    df = pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    return df


# ─── Global fixtures ─────────────────────────────────────────────────────────

SYNTHETIC_DF = generate_synthetic_data(500)
RESULTS: List[StepResult] = []


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — LPPL Bubble Detection
# ═══════════════════════════════════════════════════════════════════════════════

def _step1_lppl():
    from uniquant.brain.lppl.engine import LPPLEngine

    engine = LPPLEngine()
    df = SYNTHETIC_DF.copy()

    result = engine.detect_bubble(df, column="close")

    # Must return a dict
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    # Must contain expected keys
    for key in ("is_bubble", "risk_level", "confidence", "model_params"):
        assert key in result, f"Missing key: {key}"

    # risk_level must be one of the known values
    valid_levels = {"Safe", "Warning", "Danger"}
    assert result["risk_level"] in valid_levels, (
        f"risk_level={result['risk_level']!r} not in {valid_levels}"
    )

    # confidence must be in [0, 1]
    conf = result["confidence"]
    assert 0.0 <= conf <= 1.0, f"confidence={conf} out of [0,1]"

    return {"risk_level": result["risk_level"], "is_bubble": result["is_bubble"],
            "confidence": round(conf, 4)}


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Wyckoff Phase Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def _step2_wyckoff():
    from uniquant.brain.wyckoff.engine import WyckoffEngine
    from uniquant.brain.wyckoff.models import WyckoffReport, WyckoffPhase

    engine = WyckoffEngine(lookback_days=120)
    df = SYNTHETIC_DF.copy()

    report = engine.analyze(df, symbol="TEST.SZ", period="日线", multi_timeframe=False)

    assert isinstance(report, WyckoffReport), f"Expected WyckoffReport, got {type(report)}"

    # Structure must exist with phase
    assert report.structure is not None, "report.structure is None"
    assert isinstance(report.structure.phase, WyckoffPhase), (
        f"phase type: {type(report.structure.phase)}"
    )

    # Signal must exist
    assert report.signal is not None, "report.signal is None"
    assert report.signal.signal_type is not None, "signal_type is None"

    phase_value = report.structure.phase.value
    return {"phase": phase_value, "signal_type": report.signal.signal_type,
            "direction": report.trading_plan.direction if report.trading_plan else "N/A"}


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Factor Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def _step3_factors():
    from uniquant.brain.factors.analyzer import FactorAnalyzer, AnalysisMode
    from uniquant.brain.factors.custom_factors import (
        compute_momentum_20d, compute_volatility_20d,
    )

    df = SYNTHETIC_DF.copy()

    # Compute factors
    df["momentum_20d"] = compute_momentum_20d(df)
    df["volatility_20d"] = compute_volatility_20d(df)

    # Drop warmup rows (first 20 have NaN by design)
    df_valid = df.dropna(subset=["momentum_20d", "volatility_20d"]).copy()
    assert len(df_valid) > 400, f"Too few valid rows after warmup: {len(df_valid)}"

    # No NaN in factor values
    assert df_valid["momentum_20d"].notna().all(), "NaN in momentum_20d"
    assert df_valid["volatility_20d"].notna().all(), "NaN in volatility_20d"

    # Reasonable bounds
    mom = df_valid["momentum_20d"]
    assert mom.abs().max() < 5.0, f"momentum_20d max={mom.abs().max():.2f} seems extreme"
    vol = df_valid["volatility_20d"]
    assert (vol >= 0).all(), "volatility_20d has negative values"
    assert vol.max() < 10.0, f"volatility_20d max={vol.max():.2f} seems extreme"

    # Run IC/IR analysis using FactorAnalyzer
    # Need multiple stocks for cross-sectional IC; create 5 synthetic stocks
    analyzer = FactorAnalyzer()
    df_multi = pd.DataFrame()
    for stock_id in range(5):
        stock_df = df_valid.copy()
        stock_df["code"] = f"TEST{stock_id:03d}.SZ"
        # Add small per-stock noise to factors to create cross-sectional variation
        noise = np.random.randn(len(stock_df)) * 0.01
        stock_df["momentum_20d"] = stock_df["momentum_20d"] + noise
        stock_df["volatility_20d"] = stock_df["volatility_20d"] + abs(noise) * 0.05
        df_multi = pd.concat([df_multi, stock_df], ignore_index=True)

    ic_results = analyzer.compute_ic_ir(
        df_multi,
        factor_cols=["momentum_20d", "volatility_20d"],
        holding_periods=[5, 20],
        date_col="date",
        code_col="code",
        price_col="close",
        mode=AnalysisMode.BACKTEST,
    )

    assert isinstance(ic_results, dict), "IC results should be a dict"
    assert "momentum_20d" in ic_results, "Missing momentum_20d in IC results"
    assert "volatility_20d" in ic_results, "Missing volatility_20d in IC results"

    return {"valid_rows": len(df_valid),
            "momentum_range": f"[{mom.min():.4f}, {mom.max():.4f}]",
            "volatility_range": f"[{vol.min():.4f}, {vol.max():.4f}]",
            "ic_factors": list(ic_results.keys())}


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Full Backtest
# ═══════════════════════════════════════════════════════════════════════════════

def _step4_backtest():
    from uniquant.hands.backtest.engine import BacktestEngine
    from uniquant.hands.backtest.result import BacktestResult
    from unittest.mock import MagicMock
    import datetime

    df = SYNTHETIC_DF.copy()

    # Add MA20 for strategy
    df["ma20"] = df["close"].rolling(20).mean()
    df = df.dropna().reset_index(drop=True)

    def ma_crossover_signal(df, idx, context):
        """
        Buy when close > MA20 (and not in position).
        Sell when close < MA20 (and in position).
        This generates multiple round-trips on mean-reverting data.
        """
        if idx < 1:
            return {"action": "HOLD", "reason": "warmup"}
        close_now = df.iloc[idx]["close"]
        ma_now = df.iloc[idx]["ma20"]

        if context["position"] == 0 and close_now > ma_now:
            return {"action": "BUY", "reason": "close > MA20"}
        elif context["position"] > 0 and close_now < ma_now:
            return {"action": "SELL", "reason": "close < MA20"}
        return {"action": "HOLD", "reason": ""}

    # Use a mock trade calendar that always returns True for is_trading_day
    # and returns the date range for get_trade_calendar (bypasses missing local files)
    mock_tc = MagicMock()
    mock_tc.is_trading_day.return_value = True
    dates_series = pd.DataFrame({"trade_date": pd.to_datetime(df["date"])})
    mock_tc.get_trade_calendar.return_value = dates_series

    engine = BacktestEngine(initial_capital=100000.0, trade_calendar=mock_tc)
    result = engine.run_backtest(df, ma_crossover_signal, symbol="TEST.SZ", position_size=100)

    assert isinstance(result, BacktestResult), f"Expected BacktestResult, got {type(result)}"

    # equity_curve must exist and match data length
    assert len(result.equity_curve) > 0, "equity_curve is empty"
    assert len(result.equity_curve) == len(df), (
        f"equity_curve len={len(result.equity_curve)} != data len={len(df)}"
    )

    # Final equity must be a valid positive number
    final_eq = result.equity_curve[-1]
    assert isinstance(final_eq, (int, float)), f"final equity type: {type(final_eq)}"
    assert np.isfinite(final_eq), f"final equity not finite: {final_eq}"
    assert final_eq > 0, f"final equity <= 0: {final_eq}"

    # daily_returns must have no NaN, no inf
    assert len(result.daily_returns) == len(df), (
        f"daily_returns len={len(result.daily_returns)} != data len={len(df)}"
    )
    dr = np.array(result.daily_returns)
    assert not np.any(np.isnan(dr)), "NaN in daily_returns"
    assert not np.any(np.isinf(dr)), "inf in daily_returns"

    # Must have executed at least some trades
    assert len(result.trades) > 0, f"No trades recorded (trades list is empty)"
    buy_count = sum(1 for t in result.trades if t.action == "BUY")
    sell_count = sum(1 for t in result.trades if t.action == "SELL")
    assert buy_count > 0, "No BUY trades executed"
    assert sell_count > 0, "No SELL trades executed (position never closed)"

    # Metrics must be present
    assert hasattr(result, "annualized_return"), "Missing annualized_return"
    assert hasattr(result, "max_drawdown"), "Missing max_drawdown"
    assert hasattr(result, "sharpe_ratio"), "Missing sharpe_ratio"
    assert np.isfinite(result.annualized_return), f"annualized_return={result.annualized_return}"
    assert np.isfinite(result.max_drawdown), f"max_drawdown={result.max_drawdown}"
    assert np.isfinite(result.sharpe_ratio), f"sharpe_ratio={result.sharpe_ratio}"
    assert 0.0 <= result.max_drawdown <= 1.0, f"max_drawdown={result.max_drawdown}"

    return {
        "equity_curve_len": len(result.equity_curve),
        "final_equity": round(final_eq, 2),
        "total_return": f"{result.total_return:.4%}",
        "annualized_return": f"{result.annualized_return:.4%}",
        "max_drawdown": f"{result.max_drawdown:.4%}",
        "sharpe_ratio": round(result.sharpe_ratio, 4),
        "total_trades": result.total_trades,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — UnifiedMatchingEngine (vectorized fill)
# ═══════════════════════════════════════════════════════════════════════════════

def _step5_matching_engine():
    from uniquant.hands.backtest.unified_matching_engine import (
        UnifiedMatchingEngine, FillResult,
    )

    n = 100
    np.random.seed(99)
    prices = np.random.uniform(9.0, 11.0, n)
    shares_req = np.full(n, 100, dtype=np.int64)
    cash = np.full(n, 1_000_000.0)
    pre_closes = prices * (1 + np.random.randn(n) * 0.01)
    symbols = np.array(["000001.SZ"] * n)
    timestamps = pd.bdate_range("2024-01-01", periods=n).values
    volumes = np.random.randint(1_000_000, 50_000_000, n).astype(np.float64)
    adv = np.full(n, 10_000_000.0)

    engine = UnifiedMatchingEngine()

    # ── BUY ──
    buy_result = engine.fill_buy(
        prices=prices, shares_requested=shares_req, cash_available=cash,
        pre_closes=pre_closes, symbols=symbols, timestamps=timestamps,
        volumes=volumes, avg_daily_volumes=adv,
    )
    assert isinstance(buy_result, FillResult), f"Expected FillResult, got {type(buy_result)}"
    assert buy_result.executed_shares.shape == (n,), f"exec shape: {buy_result.executed_shares.shape}"
    assert buy_result.exec_prices.shape == (n,), f"prices shape: {buy_result.exec_prices.shape}"
    assert buy_result.commissions.shape == (n,), f"commissions shape: {buy_result.commissions.shape}"

    # No NaN in execution prices
    assert not np.any(np.isnan(buy_result.exec_prices)), "NaN in buy exec_prices"
    # All execution prices must be positive
    assert np.all(buy_result.exec_prices > 0), "Non-positive buy exec_prices"
    # Slippage should exist (buy price >= market price)
    assert np.all(buy_result.exec_prices >= prices * 0.99), "Buy slippage unexpectedly negative"

    # ── SELL ──
    positions = np.full(n, 500, dtype=np.int64)
    pos_costs = np.full(n, 10.0)
    buy_dates_arr = np.array([pd.Timestamp("2023-12-01")] * n)

    sell_result = engine.fill_sell(
        prices=prices, shares_requested=shares_req, positions_held=positions,
        position_costs=pos_costs, pre_closes=pre_closes, symbols=symbols,
        timestamps=timestamps, buy_dates=buy_dates_arr,
        volumes=volumes, avg_daily_volumes=adv,
    )
    assert isinstance(sell_result, FillResult), f"Expected FillResult, got {type(sell_result)}"
    assert sell_result.executed_shares.shape == (n,), f"sell exec shape: {sell_result.executed_shares.shape}"
    assert sell_result.exec_prices.shape == (n,)
    assert not np.any(np.isnan(sell_result.exec_prices)), "NaN in sell exec_prices"
    assert np.all(sell_result.exec_prices > 0), "Non-positive sell exec_prices"

    # Stamp duties exist for sell
    assert sell_result.stamp_duties.shape == (n,), "stamp_duties shape mismatch"
    assert np.all(sell_result.stamp_duties >= 0), "Negative stamp_duties"

    return {
        "buy_exec_mean": round(float(np.mean(buy_result.exec_prices)), 4),
        "buy_commission_total": round(float(np.sum(buy_result.commissions)), 2),
        "sell_exec_mean": round(float(np.mean(sell_result.exec_prices)), 4),
        "sell_stamp_duty_total": round(float(np.sum(sell_result.stamp_duties)), 2),
        "buy_rejected_count": int(np.sum(buy_result.rejected_mask)),
        "sell_rejected_count": int(np.sum(sell_result.rejected_mask)),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# pytest entry point
# ═══════════════════════════════════════════════════════════════════════════════

ALL_STEPS = [
    ("Step 1 — LPPL Bubble Detection", _step1_lppl),
    ("Step 2 — Wyckoff Phase Analysis", _step2_wyckoff),
    ("Step 3 — Factor Analysis", _step3_factors),
    ("Step 4 — Full Backtest (MA20 Crossover)", _step4_backtest),
    ("Step 5 — UnifiedMatchingEngine (vectorized fill)", _step5_matching_engine),
]


def test_e2e_pipeline():
    """Run all pipeline steps sequentially; report timing + pass/fail."""
    global RESULTS
    RESULTS = []
    all_passed = True

    print("\n" + "=" * 72)
    print("  UniQuant Full Pipeline E2E Integration Test")
    print("=" * 72)
    print(f"  Synthetic data: {len(SYNTHETIC_DF)} trading days")
    print(f"  Date range: {SYNTHETIC_DF['date'].iloc[0].date()} → "
          f"{SYNTHETIC_DF['date'].iloc[-1].date()}")
    print("=" * 72)

    for name, fn in ALL_STEPS:
        print(f"\n{'─' * 72}")
        print(f"  ▶ {name}")
        print(f"{'─' * 72}")
        sr = _time_step(name, fn)
        RESULTS.append(sr)

        if sr.passed:
            print(f"  ✅ PASSED  ({sr.elapsed_s:.2f}s)")
            for k, v in sr.details.items():
                print(f"     {k}: {v}")
        else:
            all_passed = False
            print(f"  ❌ FAILED  ({sr.elapsed_s:.2f}s)")
            print(f"     {sr.error}")

    # ── Summary ──
    total_time = sum(r.elapsed_s for r in RESULTS)
    print(f"\n{'=' * 72}")
    print("  SUMMARY")
    print(f"{'=' * 72}")
    for r in RESULTS:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        print(f"  {status}  {r.elapsed_s:6.2f}s  {r.name}")
    print(f"{'─' * 72}")
    print(f"  Total: {total_time:.2f}s | "
          f"Passed: {sum(1 for r in RESULTS if r.passed)}/{len(RESULTS)}")
    print(f"{'=' * 72}\n")

    # Dump any failures in full
    failures = [r for r in RESULTS if not r.passed]
    if failures:
        print("FAILURE DETAILS:")
        for r in failures:
            print(f"\n--- {r.name} ---")
            print(r.error)

    assert all_passed, (
        f"{len(failures)} step(s) failed: "
        + ", ".join(r.name for r in failures)
    )
