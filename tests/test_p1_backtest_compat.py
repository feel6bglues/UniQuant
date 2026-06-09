from __future__ import annotations

from datetime import datetime

import pandas as pd

from uniquant.hands.backtest.engine import BacktestEngine


class _AlwaysTradingCalendar:
    def is_trading_day(self, date):
        return True

    def get_trade_calendar(self, start_date, end_date):
        return pd.DataFrame(
            {"trade_date": pd.date_range(start=start_date, end=end_date, freq="D")}
        )


def test_legacy_backtest_blocks_pending_buy_on_suspension_bar():
    engine = BacktestEngine(
        initial_capital=100_000,
        trade_calendar=_AlwaysTradingCalendar(),
    )
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "open": [10.0, 10.0, 10.0],
            "high": [10.1, 10.1, 10.1],
            "low": [9.9, 9.9, 9.9],
            "close": [10.0, 10.0, 10.0],
            "pre_close": [10.0, 10.0, 10.0],
            "volume": [10000, 0, 10000],
            "avg_daily_volume": [10000, 10000, 10000],
        }
    )

    def buy_first_day(_df, idx, state):
        if idx == 0 and state["position"] == 0:
            return {"action": "BUY", "reason": "pending buy"}
        return {"action": "HOLD"}

    result = engine.run_backtest(
        df,
        buy_first_day,
        symbol="600000.SH",
        position_size=100,
    )

    assert [t.action for t in result.trades] == []
    assert engine.position == 0


def test_legacy_execute_buy_uses_a_share_lot_rounding_on_cash_shortfall():
    engine = BacktestEngine(
        initial_capital=1_000,
        trade_calendar=_AlwaysTradingCalendar(),
    )

    trade = engine.execute_buy(
        price=10.0,
        shares=100,
        timestamp=datetime(2024, 1, 2),
        pre_close=10.0,
        symbol="600000.SH",
        volume=10_000,
        avg_daily_volume=10_000,
    )

    assert trade is None
    assert engine.position == 0
    assert engine.cash == engine.initial_capital


def test_legacy_execute_buy_accepts_bare_six_digit_symbol():
    engine = BacktestEngine(
        initial_capital=100_000,
        trade_calendar=_AlwaysTradingCalendar(),
    )

    trade = engine.execute_buy(
        price=10.0,
        shares=100,
        timestamp=datetime(2024, 1, 2),
        pre_close=10.0,
        symbol="000001",
        volume=10_000,
        avg_daily_volume=10_000,
    )

    assert trade is not None
    assert trade.shares == 100
