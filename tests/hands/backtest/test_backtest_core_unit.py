"""Behavioural unit tests for ``hands/backtest`` core modules (round-8 coverage lift).

Scope:

* ``uniquant.hands.backtest.result`` — the **deprecated** statistics dataclasses
  (``TradeRecord`` / ``BacktestResult``) whose metric math (win rate, profit
  factor, drawdown, Sharpe, annualisation) and export helpers (``to_dict`` /
  ``to_dataframe`` / ``generate_report``) had zero coverage.
* ``uniquant.hands.backtest.unified_engine`` — the uncovered branches of the
  typed A-share backtest engine: result-property guards, state ``reset``,
  suspension / RETRYING rollovers, T+1 reject, ``PositionSizer`` integration,
  lot rounding, insufficient-funds auto-reduction and the defensive guards.

Design notes (CI-safety):

* Synthetic OHLCV only — no data-lake, no network, no ``czsc`` / ``backtrader``.
* Every engine is injected with an explicit **stub** trade calendar so the test
  never reaches the real ``TradeCalendarManager`` (which may hit akshare).
* The survivorship metadata lookup is stubbed by an autouse fixture so these
  unit tests stay hermetic; the real happy path is exercised elsewhere in
  ``test_survivorship_warning.py``.
"""

from __future__ import annotations

import datetime
import warnings

import pandas as pd
import pytest

from uniquant.hands.backtest.result import BacktestResult as StatsBacktestResult
from uniquant.hands.backtest.result import TradeRecord as StatsTradeRecord
from uniquant.hands.backtest.unified_engine import (
    BacktestResult,
    TradeRecord,
    UnifiedBacktestEngine,
)
from uniquant.shared.interfaces import TradingSignal


# ══════════════════════════════════════════════════════════════════════════
# Test helpers
# ══════════════════════════════════════════════════════════════════════════

class _AlwaysTradingCalendar:
    """Stub calendar: every calendar day is a trading day."""

    def is_trading_day(self, date) -> bool:  # noqa: D102
        return True

    def get_trade_calendar(self, start_date, end_date):  # noqa: D102
        return pd.DataFrame({"trade_date": []})


class _NeverTradingCalendar:
    """Stub calendar: no calendar day is a trading day."""

    def is_trading_day(self, date) -> bool:  # noqa: D102
        return False

    def get_trade_calendar(self, start_date, end_date):  # noqa: D102
        return pd.DataFrame({"trade_date": []})


class _StubSizer:
    """Minimal ``PositionSizerProtocol`` implementation for engine tests."""

    def __init__(self, suggested: int = 500, exc: Exception | None = None):
        self._suggested = suggested
        self._exc = exc

    def calculate_shares(self, price, stop_loss, czsc_bottom, market="CN", symbol="UNKNOWN"):
        if self._exc is not None:
            raise self._exc
        return {"suggested_shares": self._suggested}


def _engine(**kwargs) -> UnifiedBacktestEngine:
    """Build an engine with a stub calendar and zero base slippage."""
    kwargs.setdefault("trade_calendar", _AlwaysTradingCalendar())
    kwargs.setdefault("commission_rate", 0.0003)
    kwargs.setdefault("stamp_duty_rate", 0.0005)
    kwargs.setdefault("slippage_rate", 0.0)
    kwargs.setdefault("min_commission", 5.0)
    return UnifiedBacktestEngine(**kwargs)


def _basic_df(n: int = 3, price: float = 10.0) -> pd.DataFrame:
    """Flat OHLCV frame with a stub zero impact so arithmetic stays exact."""
    dates = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame({
        "date": dates,
        "open": [price] * n,
        "high": [price] * n,
        "low": [price] * n,
        "close": [price] * n,
        "volume": [1_000_000.0] * n,
        "pre_close": [price] * n,
        "avg_daily_volume": [0.0] * n,
    })


def _buy(symbol: str = "600000.SH", shares: int = 100, day: int = 2) -> TradingSignal:
    return TradingSignal(
        action="BUY", reason="entry", shares=shares, symbol=symbol,
        timestamp=datetime.datetime(2024, 1, day),
    )


def _sell(symbol: str = "600000.SH", shares: int = 100, day: int = 3) -> TradingSignal:
    return TradingSignal(
        action="SELL", reason="exit", shares=shares, symbol=symbol,
        timestamp=datetime.datetime(2024, 1, day),
    )


def _engine_trade(action: str = "BUY", pnl: float = 0.0, price: float = 10.0):
    """Unified-engine ``TradeRecord`` (non-deprecated variant)."""
    return TradeRecord(
        timestamp=datetime.datetime(2024, 1, 2),
        action=action,
        symbol="600000.SH",
        price=price,
        shares=100,
        commission=5.0,
        pnl=pnl,
    )


def _stats_trade(action: str = "SELL", pnl: float = 100.0) -> StatsTradeRecord:
    """Deprecated ``result.TradeRecord`` built without emitting a warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return StatsTradeRecord(
            timestamp=datetime.datetime(2024, 1, 2),
            action=action,
            price=10.0,
            shares=100,
            commission=5.0,
            slippage=0.0,
            pnl=pnl,
        )


@pytest.fixture(autouse=True)
def _isolate_survivorship(monkeypatch):
    """Keep these unit tests hermetic (never read ``data/`` metadata CSVs)."""
    import uniquant.data.managers.stock_metadata_manager as smm

    class _NoDelistManager:
        def get_delist_date(self, code):  # noqa: D102
            return None

    monkeypatch.setattr(smm, "StockMetadataManager", _NoDelistManager)


# ══════════════════════════════════════════════════════════════════════════
# result.py — deprecated TradeRecord
# ══════════════════════════════════════════════════════════════════════════

class TestDeprecatedTradeRecord:
    def test_post_init_emits_deprecation_warning(self):
        with pytest.warns(DeprecationWarning):
            rec = StatsTradeRecord(
                timestamp=datetime.datetime(2024, 1, 2),
                action="BUY",
                price=10.0,
                shares=100,
                commission=5.0,
                slippage=0.0,
            )
        assert rec.pnl == 0.0
        assert rec.pnl_pct == 0.0
        assert rec.reason == ""

    def test_to_dict_serialises_iso_timestamp_and_fields(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            rec = StatsTradeRecord(
                timestamp=datetime.datetime(2024, 1, 2, 9, 30),
                action="SELL",
                price=12.5,
                shares=200,
                commission=5.0,
                slippage=0.1,
                pnl=480.0,
                pnl_pct=0.04,
                reason="take profit",
            )
        assert rec.to_dict() == {
            "timestamp": "2024-01-02T09:30:00",
            "action": "SELL",
            "price": 12.5,
            "shares": 200,
            "commission": 5.0,
            "slippage": 0.1,
            "pnl": 480.0,
            "pnl_pct": 0.04,
            "reason": "take profit",
        }


# ══════════════════════════════════════════════════════════════════════════
# result.py — deprecated BacktestResult metric math + exports
# ══════════════════════════════════════════════════════════════════════════

class TestStatsBacktestResultMetrics:
    def test_calculate_metrics_empty_trades_returns_early(self):
        r = StatsBacktestResult()
        r.calculate_metrics()
        assert r.total_trades == 0
        assert r.final_capital == 0.0
        assert r.profit_factor == 0.0

    def test_calculate_metrics_open_only_trades_has_no_closed_stats(self):
        r = StatsBacktestResult(
            initial_capital=100_000.0,
            trades=[_stats_trade("BUY", pnl=0.0)],
        )
        r.calculate_metrics()
        assert r.total_trades == 0
        assert r.win_rate == 0.0

    def test_calculate_metrics_full_arithmetic(self):
        trades = [
            _stats_trade("BUY", 0.0),
            _stats_trade("SELL", 1000.0),
            _stats_trade("SELL", -400.0),
            _stats_trade("SELL", 600.0),
            _stats_trade("SELL", -200.0),
        ]
        r = StatsBacktestResult(initial_capital=100_000.0, trades=trades)
        r.calculate_metrics()
        assert r.total_trades == 4
        assert r.winning_trades == 2
        assert r.losing_trades == 2
        assert r.win_rate == pytest.approx(0.5)
        assert r.avg_win == pytest.approx(800.0)
        assert r.avg_loss == pytest.approx(-300.0)
        assert r.profit_factor == pytest.approx(1600.0 / 600.0)

    def test_calculate_metrics_profit_factor_infinite_without_losses(self):
        r = StatsBacktestResult(
            trades=[_stats_trade("SELL", 100.0), _stats_trade("SELL", 50.0)]
        )
        r.calculate_metrics()
        assert r.profit_factor == float("inf")

    def test_calculate_metrics_equity_curve_sharpe_and_annualisation(self):
        r = StatsBacktestResult(
            initial_capital=100_000.0,
            trades=[_stats_trade("SELL", 1000.0)],
            equity_curve=[100_000.0, 101_000.0, 100_000.0, 103_000.0],
            daily_returns=[0.0, 0.01, -0.0099, 0.03],
        )
        r.calculate_metrics()
        assert r.final_capital == 103_000.0
        assert r.total_return == pytest.approx(0.03)
        assert r.max_drawdown == pytest.approx(1000.0 / 101_000.0)
        assert r.sharpe_ratio != 0.0
        assert r.annualized_return == pytest.approx((1.03) ** (252 / 4) - 1)

    def test_calculate_metrics_equity_curve_without_daily_returns(self):
        r = StatsBacktestResult(
            initial_capital=100_000.0,
            trades=[_stats_trade("SELL", -1000.0)],
            equity_curve=[100_000.0, 90_000.0],
        )
        r.calculate_metrics()
        assert r.total_return == pytest.approx(-0.1)
        assert r.max_drawdown == pytest.approx(0.1)
        assert r.sharpe_ratio == 0.0
        assert r.annualized_return == 0.0


class TestStatsBacktestResultExport:
    def test_to_dict_includes_iso_dates_and_trades(self):
        r = StatsBacktestResult(
            initial_capital=100_000.0,
            final_capital=101_000.0,
            total_return=0.01,
            start_date=datetime.datetime(2024, 1, 1),
            end_date=datetime.datetime(2024, 1, 31),
            trades=[_stats_trade("SELL", 1000.0)],
        )
        d = r.to_dict()
        assert d["initial_capital"] == 100_000.0
        assert d["start_date"] == "2024-01-01T00:00:00"
        assert d["end_date"] == "2024-01-31T00:00:00"
        assert len(d["trades"]) == 1
        assert d["trades"][0]["action"] == "SELL"
        assert d["trades"][0]["pnl"] == 1000.0

    def test_to_dict_none_dates_serialise_to_none(self):
        d = StatsBacktestResult().to_dict()
        assert d["start_date"] is None
        assert d["end_date"] is None

    def test_to_dataframe_empty_returns_empty_frame(self):
        assert StatsBacktestResult().to_dataframe().empty

    def test_to_dataframe_with_trades_preserves_order(self):
        r = StatsBacktestResult(trades=[_stats_trade("SELL", 100.0), _stats_trade("BUY", 0.0)])
        df = r.to_dataframe()
        assert list(df["action"]) == ["SELL", "BUY"]

    def test_generate_report_contains_key_metrics(self):
        r = StatsBacktestResult(
            initial_capital=100_000.0,
            final_capital=105_000.0,
            total_return=0.05,
            annualized_return=0.6,
            max_drawdown=0.02,
            sharpe_ratio=1.5,
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            win_rate=0.6,
            profit_factor=2.0,
            avg_win=500.0,
            avg_loss=-250.0,
        )
        text = r.generate_report()
        assert "回测报告" in text
        assert "总收益率: 5.00%" in text
        assert "年化收益率: 60.00%" in text
        assert "夏普比率: 1.50" in text
        assert "胜率: 60.00%" in text
        assert "盈亏比: 2.00" in text


# ══════════════════════════════════════════════════════════════════════════
# unified_engine.BacktestResult — property guards + export
# ══════════════════════════════════════════════════════════════════════════

class TestEngineResultProperties:
    def test_total_trades_counts_all_records(self):
        r = BacktestResult(trades=[_engine_trade(), _engine_trade("SELL", 100.0)])
        assert r.total_trades == 2

    def test_total_return_zero_without_curve_or_capital(self):
        assert BacktestResult().total_return == 0.0
        assert BacktestResult(equity_curve=[100.0], initial_capital=0.0).total_return == 0.0

    def test_sharpe_ratio_aliases_sharpe(self):
        assert BacktestResult().sharpe_ratio == 0.0
        r = BacktestResult(daily_returns=[0.01, 0.02, -0.005])
        assert r.sharpe_ratio == r.sharpe
        assert r.sharpe_ratio != 0.0

    def test_annualized_return_zero_when_no_equity_curve(self):
        assert BacktestResult(daily_returns=[0.01]).annualized_return == 0.0

    def test_annualized_return_zero_when_no_daily_returns(self):
        assert BacktestResult(equity_curve=[110.0], initial_capital=100.0).annualized_return == 0.0

    def test_annualized_return_clamps_total_loss_to_minus_one(self):
        r = BacktestResult(
            equity_curve=[0.0],
            initial_capital=100_000.0,
            daily_returns=[0.0, 0.0],
        )
        assert r.annualized_return == -1.0

    def test_annualized_return_compounds_positive_gain(self):
        r = BacktestResult(
            equity_curve=[110.0],
            initial_capital=100.0,
            daily_returns=[0.0, 0.1],
        )
        assert r.annualized_return == pytest.approx((1.1) ** (252 / 2) - 1)

    def test_compare_non_finite_profit_factor_is_zeroed(self):
        # Both results have no losing trades => profit_factor == inf; inf - inf is
        # non-finite and must be guarded to 0.0 rather than leaking NaN.
        a = BacktestResult(trades=[_engine_trade("SELL", 100.0)])
        b = BacktestResult(trades=[_engine_trade("SELL", 50.0)])
        diff = a.compare(b)
        assert diff["profit_factor_diff"] == 0.0
        assert diff["total_trades_diff"] == 0

    def test_result_to_dict_serialises_metrics_and_trades(self):
        r = BacktestResult(
            trades=[_engine_trade("SELL", 250.0)],
            equity_curve=[100.0, 110.0],
            daily_returns=[0.1],
            initial_capital=100.0,
            final_cash=110.0,
            metadata={"symbol": "600000.SH"},
        )
        d = r.to_dict()
        assert d["initial_capital"] == 100.0
        assert d["final_cash"] == 110.0
        assert d["total_return"] == pytest.approx(0.1)
        assert d["total_trades"] == 1
        assert d["sharpe_ratio"] == r.sharpe
        assert d["trades"][0]["action"] == "SELL"
        assert d["trades"][0]["stamp_duty"] == 0.0
        assert d["trades"][0]["pnl"] == 250.0
        assert d["metadata"] == {"symbol": "600000.SH"}


# ══════════════════════════════════════════════════════════════════════════
# unified_engine.UnifiedBacktestEngine — run() + internals
# ══════════════════════════════════════════════════════════════════════════

class TestEngineLifecycleAndDataPrep:
    def test_reset_restores_initial_state(self):
        engine = _engine(initial_capital=100_000.0)
        engine.run(_basic_df(), [], symbol="600000.SH")
        engine.cash = 1.0
        engine.positions = {"600000.SH": 100}
        engine.trades = [_engine_trade()]
        engine.reset()
        assert engine.cash == engine.initial_capital == 100_000.0
        assert engine.positions == {}
        assert engine.trades == []

    def test_prepare_dataframe_raises_on_missing_columns(self):
        engine = _engine()
        bad = pd.DataFrame({"date": pd.to_datetime(["2024-01-02"]), "open": [1.0]})
        with pytest.raises(ValueError, match="缺少必需列"):
            engine._prepare_dataframe(bad)

    def test_index_signals_by_date_none_timestamp_buckets_unknown(self):
        sig = TradingSignal(action="BUY", timestamp=None)
        indexed = UnifiedBacktestEngine._index_signals_by_date([sig])
        assert list(indexed) == ["unknown"]
        assert indexed["unknown"][0] is sig

    def test_check_t1_none_buy_date_allows(self):
        engine = _engine()
        assert engine._check_t1(None, pd.Timestamp("2024-01-05")) is True

    def test_check_t1_sell_not_after_buy_is_rejected(self):
        engine = _engine()
        assert engine._check_t1(pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-04")) is False

    def test_next_trading_day_falls_back_after_ten_lookups(self):
        engine = _engine(trade_calendar=_NeverTradingCalendar())
        start = pd.Timestamp("2024-01-02")
        assert engine._next_trading_day(start) == start + pd.Timedelta(days=11)

    def test_check_limit_allows_when_pre_close_non_positive(self):
        engine = _engine()
        assert engine._check_limit(10.0, 0.0, "BUY", "600000.SH") is True

    def test_check_limit_rejects_limit_up_buy_and_limit_down_sell(self):
        engine = _engine()
        assert engine._check_limit(11.0, 10.0, "BUY", "600000.SH") is False
        assert engine._check_limit(9.0, 10.0, "SELL", "600000.SH") is False

    def test_calc_stamp_duty_without_timestamp_uses_configured_rate(self):
        engine = _engine(stamp_duty_rate=0.001)
        assert engine._calc_stamp_duty(1000.0) == pytest.approx(1.0)


class TestEngineRunArithmeticAndGuards:
    def test_run_buy_sell_round_trip_arithmetic(self):
        engine = _engine(initial_capital=100_000.0)
        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "open": [10.0, 10.0, 12.0],
            "high": [10.0, 10.0, 12.0],
            "low": [10.0, 10.0, 12.0],
            "close": [10.0, 10.0, 12.0],
            "volume": [1_000_000.0, 1_000_000.0, 1_000_000.0],
            "pre_close": [10.0, 10.0, 10.0],
            "avg_daily_volume": [0.0, 0.0, 0.0],
        })
        signals = [_buy(shares=1000, day=2), _sell(shares=1000, day=3)]

        result = engine.run(df, signals, symbol="600000.SH")

        buys = [t for t in result.trades if t.action == "BUY"]
        sells = [t for t in result.trades if t.action == "SELL"]
        assert len(buys) == 1 and len(sells) == 1
        buy, sell = buys[0], sells[0]

        # BUY: 1000 @ 10 => value 10000, commission max(3, 5)=5, transfer 0.1, no stamp.
        assert buy.price == pytest.approx(10.0)
        assert buy.shares == 1000
        assert buy.commission == pytest.approx(5.0)
        assert buy.transfer_fee == pytest.approx(0.1)
        assert buy.stamp_duty == 0.0

        # SELL: 1000 @ 12 => value 12000, commission 5, stamp 6, transfer 0.12.
        assert sell.price == pytest.approx(12.0)
        assert sell.commission == pytest.approx(5.0)
        assert sell.stamp_duty == pytest.approx(6.0)
        assert sell.transfer_fee == pytest.approx(0.12)
        # pnl = net proceeds (11988.88) - cost basis (10 * 1000) = 1988.88
        assert sell.pnl == pytest.approx(1988.88)

        assert result.final_cash == pytest.approx(101_983.78)
        assert result.metadata["max_position"] == 1000
        assert result.metadata["trading_days_count"] == 3
        assert result.metadata["final_equity"] == pytest.approx(101_983.78)
        assert engine.positions == {}
        assert engine.cash == pytest.approx(101_983.78)

    def test_non_trading_day_with_zero_capital_records_zero_return(self):
        engine = _engine(initial_capital=0.0, trade_calendar=_NeverTradingCalendar())
        result = engine.run(_basic_df(n=3), [], symbol="600000.SH")
        assert result.daily_returns == [0.0, 0.0, 0.0]
        assert result.metadata["trading_days_count"] == 0

    def test_trading_day_with_zero_capital_records_zero_return(self):
        engine = _engine(initial_capital=0.0)
        result = engine.run(_basic_df(n=3), [], symbol="600000.SH")
        assert result.daily_returns == [0.0, 0.0, 0.0]
        assert result.metadata["trading_days_count"] == 3

    def test_buy_pending_dropped_when_suspended(self):
        engine = _engine(initial_capital=100_000.0)
        df = _basic_df(n=2)
        df.loc[1, "volume"] = 0.0
        result = engine.run(df, [_buy(day=2)], symbol="600000.SH")
        assert result.trades == []
        assert result.final_cash == pytest.approx(100_000.0)

    def test_sell_pending_retries_while_suspended(self):
        engine = _engine(initial_capital=100_000.0)
        df = _basic_df(n=4)
        df.loc[2, "volume"] = 0.0  # bar2 suspended -> SELL rolls over to bar3
        signals = [_buy(day=2), _sell(day=3)]
        result = engine.run(df, signals, symbol="600000.SH")
        assert [t.action for t in result.trades] == ["BUY", "SELL"]

    def test_sell_pending_abandoned_after_thirty_suspension_days(self):
        engine = _engine(initial_capital=100_000.0)
        n = 32
        df = _basic_df(n=n)
        df.loc[2:, "volume"] = 0.0  # 30 suspended days after the SELL is queued
        signals = [_buy(day=2), _sell(day=3)]
        result = engine.run(df, signals, symbol="600000.SH")
        assert [t.action for t in result.trades] == ["BUY"]
        assert result.final_cash < 100_000.0

    def test_sell_t1_reject_is_rolled_over(self):
        engine = _engine(initial_capital=100_000.0)
        # Duplicate date on bars 1 & 2 => sell_date == buy_date => T+1 reject.
        df = _basic_df(n=4)
        df.loc[2, "date"] = df.loc[1, "date"]
        signals = [_buy(day=2), _sell(day=3)]
        result = engine.run(df, signals, symbol="600000.SH")
        assert [t.action for t in result.trades] == ["BUY", "SELL"]

    def test_position_sizer_recomputes_buy_shares(self):
        engine = _engine(initial_capital=100_000.0, sizer=_StubSizer(suggested=500))
        result = engine.run(_basic_df(n=2), [_buy(day=2)], symbol="600000.SH")
        assert result.trades[0].shares == 500

    def test_position_sizer_non_positive_falls_back_to_one_lot(self):
        engine = _engine(initial_capital=100_000.0, sizer=_StubSizer(suggested=0))
        result = engine.run(_basic_df(n=2), [_buy(day=2)], symbol="600000.SH")
        assert result.trades[0].shares == 100

    def test_position_sizer_exception_falls_back_to_one_lot(self):
        engine = _engine(
            initial_capital=100_000.0, sizer=_StubSizer(exc=ValueError("bad sizing"))
        )
        result = engine.run(_basic_df(n=2), [_buy(day=2)], symbol="600000.SH")
        assert result.trades[0].shares == 100

    def test_survivorship_lookup_failure_is_swallowed(self, monkeypatch):
        import uniquant.data.managers.stock_metadata_manager as smm

        def _boom():
            raise OSError("metadata unavailable")

        monkeypatch.setattr(smm, "StockMetadataManager", _boom)
        result = _engine().run(_basic_df(n=2), [], symbol="600000.SH")
        assert "survivorship_warning" not in result.metadata

    def test_survivorship_warning_when_delisted_within_window(self, monkeypatch):
        import uniquant.data.managers.stock_metadata_manager as smm

        class _DelistManager:
            def get_delist_date(self, code):  # noqa: D102
                return datetime.date(2024, 1, 5)

        monkeypatch.setattr(smm, "StockMetadataManager", _DelistManager)
        result = _engine().run(_basic_df(n=5), [], symbol="600000.SH")
        assert "survivorship_warning" in result.metadata
        assert "delisted" in result.metadata["survivorship_warning"]


class TestEngineExecutionInternals:
    def test_execute_buy_below_one_lot_returns_none(self):
        engine = _engine()
        rec, cash = engine._execute_buy(
            price_raw=10.0, shares_requested=50, cash_available=100_000.0,
            pre_close=10.0, timestamp=pd.Timestamp("2024-01-02"),
            symbol="600000.SH", name=None, trade_volume=50,
            avg_daily_volume=0.0, reason="t",
        )
        assert rec is None
        assert cash == 100_000.0

    def test_execute_buy_auto_reduces_to_affordable_lots(self):
        engine = _engine()
        rec, cash = engine._execute_buy(
            price_raw=10.0, shares_requested=1000, cash_available=5000.0,
            pre_close=10.0, timestamp=pd.Timestamp("2024-01-02"),
            symbol="600000.SH", name=None, trade_volume=1000,
            avg_daily_volume=0.0, reason="t",
        )
        assert rec is not None
        assert rec.shares == 400
        assert rec.price == pytest.approx(10.0)
        assert rec.commission == pytest.approx(5.0)
        # 5000 - (4000 value + 5 commission + 0.04 transfer)
        assert cash == pytest.approx(994.96)

    def test_execute_buy_auto_reduce_cannot_afford_a_lot_returns_none(self):
        engine = _engine()
        rec, cash = engine._execute_buy(
            price_raw=10.0, shares_requested=1000, cash_available=100.0,
            pre_close=10.0, timestamp=pd.Timestamp("2024-01-02"),
            symbol="600000.SH", name=None, trade_volume=1000,
            avg_daily_volume=0.0, reason="t",
        )
        assert rec is None
        assert cash == 100.0

    def test_execute_sell_zero_shares_returns_none(self):
        engine = _engine()
        rec, cash = engine._execute_sell(
            price_raw=10.0, shares_to_sell=0, cash=1000.0, position_cost=9.0,
            pre_close=10.0, timestamp=pd.Timestamp("2024-01-02"),
            symbol="600000.SH", name=None, trade_volume=0,
            avg_daily_volume=0.0, reason="t",
        )
        assert rec is None
        assert cash == 1000.0
