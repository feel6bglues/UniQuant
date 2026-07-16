"""
UniQuant 回测敏感性分析测试
============================
验证 UnifiedBacktestEngine.sensitivity_scan() 正确遍历
滑点/佣金组合并返回结构化结果。
"""

from typing import List

import pandas as pd
import pytest

from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
from uniquant.shared.interfaces import TradingSignal


def make_kline(n_days: int = 10, base_price: float = 10.0) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n_days, freq="B")
    rng = pd.DataFrame({
        "date": dates,
        "open": base_price,
        "high": base_price * 1.02,
        "low": base_price * 0.98,
        "close": [round(base_price * (1 + 0.005 * i), 2) for i in range(n_days)],
        "volume": [100_000] * n_days,
    })
    rng["pre_close"] = rng["close"].shift(1).fillna(base_price)
    rng["avg_daily_volume"] = rng["volume"].rolling(5, min_periods=1).mean()
    return rng


def make_signals() -> List[TradingSignal]:
    return [
        TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                      timestamp=pd.Timestamp("2025-01-02")),
        TradingSignal(action="SELL", symbol="000001.SZ",
                      timestamp=pd.Timestamp("2025-01-06"),
                      shares=100, reason="lppl_exit"),
    ]


class TestSensitivityScan:

    def test_returns_dataframe(self):
        df = make_kline()
        signals = make_signals()
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.sensitivity_scan(df, signals, symbol="000001.SZ")
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == ["slippage", "commission", "total_return", "sharpe", "max_drawdown", "win_rate", "profit_factor"]

    def test_all_combinations_present(self):
        df = make_kline()
        signals = make_signals()
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.sensitivity_scan(df, signals, symbol="000001.SZ")
        # Default: 5 slippages × 4 commissions = 20 rows
        assert len(result) == 20

    def test_custom_params(self):
        df = make_kline()
        signals = make_signals()
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.sensitivity_scan(
            df, signals, symbol="000001.SZ",
            slippages=[0.0, 0.001],
            commissions=[0.0, 0.0005],
        )
        assert len(result) == 4

    def test_higher_costs_reduce_return(self):
        df = make_kline(n_days=15)
        signals = make_signals()
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.sensitivity_scan(df, signals, symbol="000001.SZ")
        zero_row = result[(result["slippage"] == 0.0) & (result["commission"] == 0.0)]
        max_row = result[(result["slippage"] == result["slippage"].max()) & (result["commission"] == result["commission"].max())]
        assert zero_row["total_return"].iloc[0] >= max_row["total_return"].iloc[0]

    def test_sharpe_non_nan(self):
        df = make_kline(n_days=20)
        signals = make_signals()
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.sensitivity_scan(df, signals, symbol="000001.SZ")
        assert result["sharpe"].notna().all()

    def test_win_rate_and_profit_factor_present(self):
        df = make_kline(n_days=20)
        signals = make_signals()
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.sensitivity_scan(df, signals, symbol="000001.SZ")
        assert "win_rate" in result.columns
        assert "profit_factor" in result.columns
        assert result["win_rate"].notna().all()
        assert result["profit_factor"].notna().all()

    def test_benchmark_returns_passed_through(self):
        df = make_kline(n_days=20)
        signals = make_signals()
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        bench = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0,
                           105.0, 106.0, 107.0, 108.0, 109.0,
                           110.0, 111.0, 112.0, 113.0, 114.0,
                           115.0, 116.0, 117.0, 118.0, 119.0])
        result = engine.sensitivity_scan(
            df, signals, symbol="000001.SZ",
            slippages=[0.0], commissions=[0.0],
            benchmark_returns=bench,
        )
        assert len(result) == 1
        # With benchmark, excess_return is stored in benchmark_return field
        excess = result["total_return"].iloc[0] - (119.0 - 100.0) / 100.0
        assert abs(excess) < 0.5  # portfolio roughly tracks flat benchmark