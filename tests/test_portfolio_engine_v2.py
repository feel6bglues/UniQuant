"""
Tests for PortfolioEngine
"""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from uniquant.hands.backtest.portfolio_engine import PortfolioEngine, Position
from uniquant.hands.backtest.unified_matching_engine import FillResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signals_data():
    dates = pd.bdate_range("2024-01-01", periods=100)
    stocks = ["000001.SZ", "600001.SH", "300001.SZ"]
    signals = []
    for d in dates:
        for s in stocks:
            signals.append({"date": d, "symbol": s, "signal": 0.0})
    signals = pd.DataFrame(signals)
    signals.loc[
        (signals["date"] == dates[10]) & (signals["symbol"] == "000001.SZ"), "signal"
    ] = 1.0
    signals.loc[
        (signals["date"] == dates[20]) & (signals["symbol"] == "000001.SZ"), "signal"
    ] = -1.0
    return signals, dates


def _make_price_data(dates):
    stocks = ["000001.SZ", "600001.SH", "300001.SZ"]
    return {
        "price": pd.DataFrame(
            {s: np.full(len(dates), 10.5) for s in stocks},
            index=pd.DatetimeIndex(dates, name="date"),
        ),
        "pre_close": pd.DataFrame(
            {s: np.full(len(dates), 10.0) for s in stocks},
            index=pd.DatetimeIndex(dates, name="date"),
        ),
    }


def _make_fill_buy():
    def fill_buy(px, sh, cash, pc, sym, ts, vol, adv):
        n = len(px)
        affordable = ((cash - 5.0) / np.maximum(px, 1e-8)).astype(np.int64)
        actual = np.where(cash > px * sh, sh, np.minimum(sh, affordable))
        actual = np.maximum(actual, 0)
        return FillResult(
            executed_shares=actual,
            exec_prices=px,
            commissions=np.maximum(actual * px * 0.0003, np.full(n, 5.0)),
            stamp_duties=np.zeros(n),
            slippages=np.zeros(n),
            rejected_mask=actual <= 0,
            t1_violation_mask=np.zeros(n, dtype=bool),
            limit_violation_mask=np.zeros(n, dtype=bool),
            cash_shortfall_mask=actual < sh,
        )
    return fill_buy


def _make_fill_sell():
    def fill_sell(px, sh, pos, pcost, pc, sym, ts, bd, vol, adv):
        n = len(px)
        actual = np.where(sh > 0, sh, 0)
        return FillResult(
            executed_shares=actual,
            exec_prices=px,
            commissions=np.maximum(actual * px * 0.0003, np.full(n, 5.0)),
            stamp_duties=actual * px * 0.001,
            slippages=np.zeros(n),
            rejected_mask=actual <= 0,
            t1_violation_mask=np.zeros(n, dtype=bool),
            limit_violation_mask=np.zeros(n, dtype=bool),
            cash_shortfall_mask=np.zeros(n, dtype=bool),
        )
    return fill_sell


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPortfolioEngine:

    # ------------------------------------------------
    # 1. Initialization
    # ------------------------------------------------
    def test_initialization(self):
        engine = PortfolioEngine()
        assert engine.initial_capital == 100000.0
        assert engine.cash == engine.initial_capital
        assert engine.max_positions == 5
        assert len(engine.positions) == 0
        assert len(engine.equity_curve) == 0
        assert len(engine.trades) == 0

    def test_initialization_custom(self):
        engine = PortfolioEngine(initial_capital=50000, max_positions=3)
        assert engine.initial_capital == 50000
        assert engine.max_positions == 3
        assert engine.cash == 50000

    # ------------------------------------------------
    # 2. Batch open positions
    # ------------------------------------------------
    def test_batch_open_positions(self):
        engine = PortfolioEngine(initial_capital=100000)
        engine.matching.fill_buy = MagicMock(side_effect=_make_fill_buy())

        positions = engine.batch_open_positions(
            signals={"000001.SZ": 1.0},
            prices={"000001.SZ": 10.5},
            pre_closes={"000001.SZ": 10.0},
            timestamps=pd.Timestamp("2024-01-15"),
        )

        assert len(positions) == 1
        assert "000001.SZ" in engine.positions
        pos = engine.positions["000001.SZ"]
        assert pos.shares > 0
        assert pos.cost_basis > 0
        assert engine.cash < engine.initial_capital

    def test_batch_open_positions_no_signal(self):
        engine = PortfolioEngine(initial_capital=100000)
        result = engine.batch_open_positions(
            signals={},
            prices={"000001.SZ": 10.5},
            pre_closes={"000001.SZ": 10.0},
            timestamps=pd.Timestamp("2024-01-15"),
        )
        assert result == []

    def test_batch_open_positions_max_positions(self):
        engine = PortfolioEngine(initial_capital=100000, max_positions=1)
        engine.matching.fill_buy = MagicMock(side_effect=_make_fill_buy())

        engine.batch_open_positions(
            signals={"000001.SZ": 1.0},
            prices={"000001.SZ": 10.5},
            pre_closes={"000001.SZ": 10.0},
            timestamps=pd.Timestamp("2024-01-15"),
        )
        second = engine.batch_open_positions(
            signals={"600001.SH": 1.0},
            prices={"600001.SH": 10.5},
            pre_closes={"600001.SH": 10.0},
            timestamps=pd.Timestamp("2024-01-16"),
        )
        assert len(second) == 0
        assert len(engine.positions) == 1

    # ------------------------------------------------
    # 3. Batch close positions
    # ------------------------------------------------
    def test_batch_close_positions(self):
        engine = PortfolioEngine(initial_capital=100000)
        engine.matching.fill_buy = MagicMock(side_effect=_make_fill_buy())
        engine.matching.fill_sell = MagicMock(side_effect=_make_fill_sell())

        engine.batch_open_positions(
            signals={"000001.SZ": 1.0},
            prices={"000001.SZ": 10.5},
            pre_closes={"000001.SZ": 10.0},
            timestamps=pd.Timestamp("2024-01-10"),
        )
        cash_after_buy = engine.cash
        assert "000001.SZ" in engine.positions

        closed = engine.batch_close_positions(
            signals={"000001.SZ": -1.0},
            prices={"000001.SZ": 10.5},
            pre_closes={"000001.SZ": 10.0},
            timestamps=pd.Timestamp("2024-01-20"),
        )

        assert closed == 1
        assert "000001.SZ" not in engine.positions
        assert engine.cash > cash_after_buy

    def test_batch_close_no_signal(self):
        engine = PortfolioEngine(initial_capital=100000)
        assert engine.batch_close_positions({}, {}, {}, pd.Timestamp("2024-01-15")) == 0

    # ------------------------------------------------
    # 4. Cash constraint
    # ------------------------------------------------
    def test_cash_constraint(self):
        engine = PortfolioEngine(initial_capital=1000)
        engine.matching.fill_buy = MagicMock(side_effect=_make_fill_buy())

        engine.batch_open_positions(
            signals={"000001.SZ": 1.0, "600001.SH": 1.0},
            prices={"000001.SZ": 100.0, "600001.SH": 100.0},
            pre_closes={"000001.SZ": 100.0, "600001.SH": 100.0},
            timestamps=pd.Timestamp("2024-01-15"),
        )

        total_exposure = sum(p.shares * p.cost_basis for p in engine.positions.values())
        assert engine.cash >= 0
        assert engine.cash + total_exposure <= engine.initial_capital + 1e-6

    # ------------------------------------------------
    # 5. Run returns equity curve
    # ------------------------------------------------
    def test_run_returns_equity_curve(self):
        signals, dates = _make_signals_data()
        pd_data = _make_price_data(dates)

        engine = PortfolioEngine(initial_capital=100000)
        engine.matching.fill_buy = MagicMock(side_effect=_make_fill_buy())
        engine.matching.fill_sell = MagicMock(side_effect=_make_fill_sell())

        result = engine.run(signals, pd_data["price"], pd_data["pre_close"])

        assert not result.empty
        assert "equity" in result.columns
        assert "daily_return" in result.columns
        assert len(result) == len(dates)

    def test_run_with_volume_data(self):
        signals, dates = _make_signals_data()
        pd_data = _make_price_data(dates)
        stocks = ["000001.SZ", "600001.SH", "300001.SZ"]
        vol_data = pd.DataFrame(
            {s: np.full(len(dates), 1e6) for s in stocks},
            index=pd.DatetimeIndex(dates, name="date"),
        )
        adv_data = pd.DataFrame(
            {s: np.full(len(dates), 5e6) for s in stocks},
            index=pd.DatetimeIndex(dates, name="date"),
        )

        engine = PortfolioEngine(initial_capital=100000)
        engine.matching.fill_buy = MagicMock(side_effect=_make_fill_buy())
        engine.matching.fill_sell = MagicMock(side_effect=_make_fill_sell())

        result = engine.run(
            signals, pd_data["price"], pd_data["pre_close"],
            volume_data=vol_data, avg_daily_volume_data=adv_data,
        )

        assert not result.empty

    # ------------------------------------------------
    # 6. Drawdown in result via calculate_metrics
    # ------------------------------------------------
    def test_run_drawdown_in_result(self):
        signals, dates = _make_signals_data()
        pd_data = _make_price_data(dates)

        engine = PortfolioEngine(initial_capital=100000)
        engine.matching.fill_buy = MagicMock(side_effect=_make_fill_buy())
        engine.matching.fill_sell = MagicMock(side_effect=_make_fill_sell())

        result = engine.run(signals, pd_data["price"], pd_data["pre_close"])
        metrics = engine.calculate_metrics(result["equity"])

        assert "max_drawdown" in metrics
        assert isinstance(metrics["max_drawdown"], float)
        assert metrics["max_drawdown"] <= 0.0
        assert "sharpe_ratio" in metrics
        assert "total_return" in metrics
        assert "total_trades" in metrics

    def test_calculate_metrics_empty(self):
        engine = PortfolioEngine(initial_capital=100000)
        metrics = engine.calculate_metrics(pd.Series([], dtype=float))
        assert metrics["total_return"] == 0.0
        assert metrics["max_drawdown"] == 0.0
        assert metrics["total_trades"] == 0

    # ------------------------------------------------
    # 7. Empty signals
    # ------------------------------------------------
    def test_empty_signals(self):
        engine = PortfolioEngine(initial_capital=100000)
        result = engine.run(
            pd.DataFrame(columns=["date", "symbol", "signal"]),
            pd.DataFrame(),
            pd.DataFrame(),
        )
        assert result.empty

    def test_empty_signals_missing_column(self):
        engine = PortfolioEngine(initial_capital=100000)
        result = engine.run(
            pd.DataFrame(columns=["date", "symbol"]),
            pd.DataFrame(),
            pd.DataFrame(),
        )
        assert result.empty

    # ------------------------------------------------
    # 8. Reset
    # ------------------------------------------------
    def test_reset(self):
        engine = PortfolioEngine(initial_capital=100000)
        engine.matching.fill_buy = MagicMock(side_effect=_make_fill_buy())
        engine.matching.fill_sell = MagicMock(side_effect=_make_fill_sell())

        engine.batch_open_positions(
            signals={"000001.SZ": 1.0},
            prices={"000001.SZ": 10.5},
            pre_closes={"000001.SZ": 10.0},
            timestamps=pd.Timestamp("2024-01-15"),
        )
        engine.update_equity({"000001.SZ": 10.5})
        assert len(engine.positions) > 0
        assert len(engine.equity_curve) > 0

        engine.reset()
        assert engine.cash == engine.initial_capital
        assert len(engine.positions) == 0
        assert len(engine.equity_curve) == 0
        assert len(engine.trades) == 0
