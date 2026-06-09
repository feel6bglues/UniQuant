from __future__ import annotations

from types import MethodType

import numpy as np
import pandas as pd

from uniquant.hands.backtest.engine import BacktestEngine
from uniquant.hands.backtest.result import TradeRecord
from uniquant.hands.strategies.backtest import _block_bootstrap


class _AlwaysTradingCalendar:
    def is_trading_day(self, date):
        return True

    def get_trade_calendar(self, start_date, end_date):
        return pd.DataFrame(
            {"trade_date": pd.date_range(start=start_date, end=end_date, freq="D")}
        )


def test_block_bootstrap_accepts_injected_rng():
    rets = np.arange(60, dtype=float)

    first = _block_bootstrap(
        rets,
        block_size=10,
        rng=np.random.default_rng(7),
    )
    np.random.seed(999)
    second = _block_bootstrap(
        rets,
        block_size=10,
        rng=np.random.default_rng(7),
    )

    assert np.array_equal(first, second)


def test_legacy_backtest_monte_carlo_metadata_uses_configured_seed(monkeypatch):
    captured_seeds = []

    class _FakeMonteCarloSimulator:
        def __init__(self, n_simulations, seed=None):
            self.seed = seed
            captured_seeds.append(seed)

        def run_shuffle(self, returns):
            return {"method": "shuffle", "seed": self.seed}

        def run_bootstrap(self, equity_curve):
            return {"method": "bootstrap", "seed": self.seed}

    monkeypatch.setattr(
        "uniquant.hands.backtest.monte_carlo.MonteCarloSimulator",
        _FakeMonteCarloSimulator,
    )

    engine = BacktestEngine(
        initial_capital=100_000,
        trade_calendar=_AlwaysTradingCalendar(),
        monte_carlo_seed=123,
    )

    def fake_buy(self, price, shares, timestamp, **kwargs):
        trade = TradeRecord(
            timestamp=timestamp,
            action="BUY",
            price=price,
            shares=shares,
            commission=0.0,
            slippage=0.0,
        )
        self.trades.append(trade)
        self.position = shares
        self.position_cost = price
        self.cash -= price * shares
        return trade

    def fake_sell(self, price, shares, timestamp, **kwargs):
        trade = TradeRecord(
            timestamp=timestamp,
            action="SELL",
            price=price,
            shares=shares,
            commission=0.0,
            slippage=0.0,
            pnl=1.0,
        )
        self.trades.append(trade)
        self.position = 0
        self.position_cost = 0.0
        self.cash += price * shares
        return trade

    engine.execute_buy = MethodType(fake_buy, engine)
    engine.execute_sell = MethodType(fake_sell, engine)

    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=50, freq="D"),
            "open": np.linspace(10.0, 12.0, 50),
            "high": np.linspace(10.1, 12.1, 50),
            "low": np.linspace(9.9, 11.9, 50),
            "close": np.linspace(10.0, 12.0, 50),
            "pre_close": np.linspace(10.0, 12.0, 50),
            "volume": np.full(50, 100_000),
            "avg_daily_volume": np.full(50, 100_000),
        }
    )

    def alternating_signal(_df, idx, state):
        if state["position"] == 0:
            return {"action": "BUY", "reason": f"buy-{idx}"}
        return {"action": "SELL", "reason": f"sell-{idx}"}

    result = engine.run_backtest(
        df,
        alternating_signal,
        symbol="600000.SH",
        position_size=100,
    )

    assert captured_seeds == [123]
    assert result.metadata["monte_carlo_seed"] == 123
    assert result.metadata["monte_carlo_shuffle"]["seed"] == 123
    assert result.metadata["monte_carlo_bootstrap"]["seed"] == 123
