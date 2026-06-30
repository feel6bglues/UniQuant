"""Tests for BacktestResult.compare() method."""

import datetime

import pytest

from uniquant.hands.backtest.unified_engine import BacktestResult, TradeRecord


class TestBacktestResultCompare:
    """BacktestResult.compare() 测试"""

    def _make_result(self, equity_curve, daily_returns, trades, initial_capital=100000.0):
        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            daily_returns=daily_returns,
            initial_capital=initial_capital,
            final_cash=initial_capital,
        )

    def _make_trade(self, action, pnl=0.0):
        return TradeRecord(
            timestamp=datetime.datetime(2024, 1, 15, 9, 30),
            action=action,
            symbol="000001.SZ",
            price=10.0,
            shares=100,
            commission=5.0,
            pnl=pnl,
        )

    def test_identical_results_all_zero(self):
        r1 = self._make_result(
            equity_curve=[100000, 110000],
            daily_returns=[0.0, 0.1],
            trades=[self._make_trade("SELL", pnl=1000.0)],
        )
        diff = r1.compare(r1)
        for key, val in diff.items():
            assert val == 0.0, f"{key} should be 0, got {val}"

    def test_compare_different_metrics(self):
        r1 = self._make_result(
            equity_curve=[100000, 110000],
            daily_returns=[0.001, 0.002],
            trades=[
                self._make_trade("SELL", pnl=1000.0),
                self._make_trade("SELL", pnl=500.0),
            ],
        )
        r2 = self._make_result(
            equity_curve=[100000, 105000],
            daily_returns=[0.0, 0.05],
            trades=[self._make_trade("SELL", pnl=500.0)],
        )
        diff = r1.compare(r2)
        assert diff["total_return_diff"] == pytest.approx(0.05)
        assert diff["total_trades_diff"] == 1
        assert diff["sharpe_diff"] != 0.0

    def test_empty_results(self):
        r1 = self._make_result(equity_curve=[], daily_returns=[], trades=[])
        r2 = self._make_result(equity_curve=[], daily_returns=[], trades=[])
        diff = r1.compare(r2)
        for key, val in diff.items():
            assert val == 0.0, f"{key} should be 0, got {val}"

    def test_one_empty_one_with_data(self):
        r1 = self._make_result(
            equity_curve=[100000, 110000],
            daily_returns=[0.0, 0.1],
            trades=[self._make_trade("SELL", pnl=1000.0)],
        )
        r2 = self._make_result(equity_curve=[], daily_returns=[], trades=[])
        diff = r1.compare(r2)
        assert diff["total_return_diff"] > 0
        assert diff["total_trades_diff"] == 1

    def test_compare_dict_structure(self):
        r1 = self._make_result(equity_curve=[100000], daily_returns=[], trades=[])
        r2 = self._make_result(equity_curve=[100000], daily_returns=[], trades=[])
        diff = r1.compare(r2)
        expected_keys = {
            "total_return_diff", "sharpe_diff", "max_drawdown_diff",
            "total_trades_diff", "win_rate_diff", "profit_factor_diff",
        }
        assert set(diff.keys()) == expected_keys
