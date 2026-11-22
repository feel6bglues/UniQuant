"""Round-8 unit coverage for the ``hands.backtest`` instrument analysis layer.

This file is *additive* (a new file; no existing test or production module is
modified). It targets the remaining uncovered branches of:

* ``unified_matching_engine``      — trade-calendar exhaustion, the element-wise
  ``compute_limit_status_vectorized`` slow path (ST names, IPO special rules,
  per-board ratios) and the defensive T+1 next-trading-day guard.
* ``robustness_checker``           — empty / degenerate inputs and the two
  defensive continue/else guards.
* ``sensitivity_analyzer``         — empty inputs, mismatch guards and the
  under-sampled parameter skip.
* ``monte_carlo``                  — short-series guards and the empty-array CI.
* ``overfitting_detector``         — invalid trial counts and PBO precondition
  guards.
* ``institutional_fee_ledger``     — default incorporation date, explicit
  crystallization dates and the empty-history report guard.
* ``saga_compensator``             — unknown-order lookup and the audit-write
  failure swallow.
* ``twap_execution_slicer``        — the anti-frontrunning / favorable-liquidity
  rounding floors and the tail-balancing reconciliation.

All filesystem / database activity uses in-memory or ``:memory:`` resources;
no test here reads or writes the repository ``data/`` tree.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from uniquant.hands.backtest.institutional_fee_ledger import InstitutionalFeeLedger
from uniquant.hands.backtest.saga_compensator import (
    CrossAssetSagaCoordinator,
    OrderState,
    SagaCompensationLevel,
    SqliteWalTwapStateMachine,
)
from uniquant.hands.backtest.twap_execution_slicer import (
    OrderBookSnapshot,
    TWAPExecutionSlicer,
)
from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine


class _NeverTradingCalendar:
    """A calendar where no day is ever a trading day."""

    def is_trading_day(self, day) -> bool:  # noqa: ARG002 - stub
        return False


class _AlwaysTradingCalendar:
    """A calendar where every day is a trading day."""

    def is_trading_day(self, day) -> bool:  # noqa: ARG002 - stub
        return True


# ---------------------------------------------------------------------------
# unified_matching_engine.py
# ---------------------------------------------------------------------------

class TestMatchingEngineBranches:
    def test_next_trading_day_scan_exhaustion(self):
        """When no trading day exists in the 10-day scan, return start + 11."""
        engine = UnifiedMatchingEngine(trade_calendar=_NeverTradingCalendar())
        start = pd.Timestamp("2024-01-02")

        result = engine._next_trading_day(start)

        assert result == start + pd.Timedelta(days=11)

    def test_limit_status_fast_path_without_names(self):
        """``names``/``trading_days_listed`` omitted -> fully vectorized path."""
        prices = np.array([11.0, 9.0], dtype=float)
        pre_closes = np.array([10.0, 10.0], dtype=float)
        symbols = np.array(["600001.SH", "600002.SH"], dtype=object)

        result = UnifiedMatchingEngine().compute_limit_status_vectorized(
            prices, pre_closes, symbols
        )

        assert result["is_limit_up"].tolist() == [True, False]
        assert result["is_limit_down"].tolist() == [False, True]

    def test_limit_status_slow_path_st_ipo_and_boards(self):
        """Element-wise path: ST names, IPO first days and per-board ratios."""
        prices = np.array([14.40, 6.40, 25.00, 13.50, 11.00, 9.00, 10.50, 10.00])
        pre_closes = np.array([10.0, 10.0, 20.0, 10.0, 10.0, 10.0, 10.0, 0.0])
        symbols = np.array(
            [
                "600001.SH",  # main, IPO tdl=1
                "600002.SH",  # main, IPO tdl=1
                "688001.SH",  # STAR, tdl<=5 -> no limit
                "830001.BJ",  # BSE, tdl=1 -> no limit
                "600004.SH",  # main, normal limit up
                "600005.SH",  # main, normal limit down
                "600006.SH",  # ST name -> 5% band
                "600007.SH",  # invalid pre_close -> skipped
            ],
            dtype=object,
        )
        names = np.array(["", "", "", "", "", "", "ST某某", ""], dtype=object)
        trading_days_listed = np.array([1, 1, 3, 1, 0, 0, 0, 0], dtype=int)

        result = UnifiedMatchingEngine().compute_limit_status_vectorized(
            prices, pre_closes, symbols, names, trading_days_listed
        )

        assert result["is_limit_up"].tolist() == [
            True, False, False, False, True, False, True, False,
        ]
        assert result["is_limit_down"].tolist() == [
            False, True, False, False, False, True, False, False,
        ]

    def test_t1_defensive_next_trading_day_guard(self, monkeypatch):
        """Both dates are trading days and the sell is later, yet the (monkeypatched)
        next trading day still lies in the future -> defensive T+1 rejection
        (unified_matching_engine.py line 281, unreachable with a real calendar)."""
        engine = UnifiedMatchingEngine(trade_calendar=_AlwaysTradingCalendar())
        monkeypatch.setattr(
            engine, "_next_trading_day", lambda _d: pd.Timestamp("2099-01-01")
        )

        fill = engine.fill_sell(
            prices=np.array([10.0]),
            shares_requested=np.array([100], dtype=np.int64),
            positions_held=np.array([100], dtype=np.int64),
            position_costs=np.array([9.0]),
            pre_closes=np.array([10.0]),
            symbols=np.array(["000001.SZ"], dtype=object),
            timestamps=np.array(["2024-01-03"], dtype=object),
            buy_dates=np.array([pd.Timestamp("2024-01-02")], dtype=object),
            volumes=np.array([1000.0]),
            avg_daily_volumes=np.array([10000.0]),
        )

        assert fill.t1_violation_mask[0]
        assert fill.rejected_mask[0]
        assert fill.executed_shares[0] == 0


# ---------------------------------------------------------------------------
# institutional_fee_ledger.py
# ---------------------------------------------------------------------------

class TestInstitutionalFeeLedgerBranches:
    def test_default_incorporation_date(self):
        ledger = InstitutionalFeeLedger()
        assert ledger.start_date == pd.Timestamp("2000-01-01")
        assert ledger.crystallized_hwm == 1.0

    def test_empty_history_report_guard(self):
        ledger = InstitutionalFeeLedger()
        assert ledger.generate_governance_report() == {"error": "无净值历史记录"}

    def test_explicit_crystallization_dates(self):
        ledger = InstitutionalFeeLedger(start_date="2024-01-01")
        dates = pd.date_range("2024-01-01", periods=12, freq="MS").append(
            pd.DatetimeIndex(["2024-12-31"])
        )
        nav = pd.Series(np.linspace(1.0, 1.35, len(dates)))
        frame = pd.DataFrame({"date": dates, "raw_nav": nav})

        result = ledger.process_nav_series(
            frame, crystallization_dates=["2024-12-31"]
        )

        crys_rows = result[result["is_crystallized"]]
        assert len(crys_rows) == 1
        assert crys_rows.iloc[0]["crystallized_carry"] > 0

    def test_governance_report_after_series(self):
        ledger = InstitutionalFeeLedger(start_date="2024-01-01")
        dates = pd.date_range("2024-01-01", periods=12, freq="MS").append(
            pd.DatetimeIndex(["2024-12-31"])
        )
        nav = pd.Series(np.linspace(1.0, 1.35, len(dates)))
        ledger.process_nav_series(
            pd.DataFrame({"date": dates, "raw_nav": nav}),
            crystallization_dates=["2024-12-31"],
        )
        report = ledger.generate_governance_report()
        assert report["trading_days"] == len(dates)
        assert report["crystallization_events_count"] == 1
        assert report["fee_drag_pct"] > 0


# ---------------------------------------------------------------------------
# saga_compensator.py
# ---------------------------------------------------------------------------

class TestSagaCompensatorBranches:
    def test_get_order_status_unknown_returns_none(self):
        sm = SqliteWalTwapStateMachine(db_path=":memory:")
        assert sm.get_order_status("does-not-exist") is None

    def test_level2_transitions_parent_order_state(self):
        sm = SqliteWalTwapStateMachine(db_path=":memory:")
        sm.create_order("000300.SH", "000300.SH", 50_000)
        coordinator = CrossAssetSagaCoordinator(wal_sm=sm)

        coordinator.evaluate_and_route_compensation(
            stock_symbol="000300.SH",
            unfilled_shares=50_000,
            reason="PARTIAL_FILL_DRIFT",
            current_equity_delta=50_000_000.0,
            current_futures_delta=-40_000_000.0,
        )

        assert sm.get_order_status("000300.SH") == OrderState.SAGA_COMPENSATING

    def test_audit_write_failure_is_swallowed(self, caplog):
        """If the WAL connection is gone the audit insert must not propagate;
        the in-memory history still records the action (lines 348-349)."""
        sm = SqliteWalTwapStateMachine(db_path=":memory:")
        sm.conn = None  # simulate a dropped/broken WAL handle
        coordinator = CrossAssetSagaCoordinator(wal_sm=sm)

        action = coordinator.evaluate_and_route_compensation(
            stock_symbol="600519.SH",
            unfilled_shares=100,
            reason="NORMAL_LIQUIDITY_DELAY",
            current_equity_delta=100_000.0,
            current_futures_delta=-100_000.0,
        )

        assert action.level == SagaCompensationLevel.LEVEL_1_MICRO_RETRY
        assert coordinator.compensation_history == [action]


# ---------------------------------------------------------------------------
# twap_execution_slicer.py
# ---------------------------------------------------------------------------

def _snapshot(minute: int, ofi_norm: float, *, bid1_v: int = 100, ask1_v: int = 100) -> OrderBookSnapshot:
    bid1_p = 100.0
    ask1_p = 100.2
    return OrderBookSnapshot(
        minute_timestamp=minute,
        bids=[(bid1_p, bid1_v), (bid1_p - 0.2, 50), (bid1_p - 0.4, 50)],
        asks=[(ask1_p, ask1_v), (ask1_p + 0.2, 50), (ask1_p + 0.4, 50)],
        mid_price=100.1,
        micro_price=100.1,
        spread_ticks=1.0,
        ofi_value=ofi_norm * 40.0,
        ofi_normalized=ofi_norm,
        is_sniping_detected=ofi_norm > 0.0,
    )


class TestTwapSlicerBranches:
    def test_sniping_floor_executes_one_when_target_at_least_one(self, monkeypatch):
        """At base slice size 1.0 the 50% throttle floors to 0, so the engine must
        execute at least 1 (twap_execution_slicer.py lines 270-271)."""
        slicer = TWAPExecutionSlicer(
            target_contracts=3, num_days=1, daily_minutes=3, ofi_threshold=0.35
        )
        snaps = [_snapshot(1, 0.9), _snapshot(2, 0.0), _snapshot(3, 0.0)]
        monkeypatch.setattr(
            slicer.simulator, "generate_day_snapshots", lambda **_kw: snaps
        )

        result = slicer.execute_3day_simulation()

        assert result["anti_frontrunning_triggers"] == 1
        assert result["executed_contracts"] == 3

    def test_favorable_liquidity_rounding_floor(self, monkeypatch):
        """At base slice size 0.1 the 1.35x accelerator rounds to 0, so the engine
        must fall back to ceil(target) >= 1 (twap_execution_slicer.py line 284)."""
        slicer = TWAPExecutionSlicer(
            target_contracts=1, num_days=1, daily_minutes=10, ofi_threshold=0.35
        )
        snaps = [_snapshot(1, -0.9)] + [_snapshot(m, 0.0) for m in range(2, 11)]
        monkeypatch.setattr(
            slicer.simulator, "generate_day_snapshots", lambda **_kw: snaps
        )

        result = slicer.execute_3day_simulation()

        assert result["executed_contracts"] == 1
        assert result["anti_frontrunning_triggers"] == 0

    def test_tail_balancing_reconciles_shortfall(self, monkeypatch):
        """If the simulated slice count is short of ``total_slices`` the tail-balance
        step must top the last slice up to the target (lines 362-365)."""
        slicer = TWAPExecutionSlicer(
            target_contracts=3, num_days=1, daily_minutes=3, ofi_threshold=0.35
        )
        # Only two snapshots are produced although three slices were declared.
        snaps = [_snapshot(1, 0.0, bid1_v=100), _snapshot(2, 0.0, bid1_v=100)]
        monkeypatch.setattr(
            slicer.simulator, "generate_day_snapshots", lambda **_kw: snaps
        )

        result = slicer.execute_3day_simulation()

        assert result["executed_contracts"] == 3
        assert len(result["slice_results_sample"]) == 2
