"""Behavioural unit tests for the uncovered CFFEX engine paths (round-8 coverage lift).

Targets ``uniquant.hands.backtest.cffex_engine``:

* ``get_spec`` rejection of an unknown contract code;
* ``calculate_notional`` (multiplier × points × |contracts|);
* the daily-MTM ``CLOSE`` branch — realised P&L sign handling and the
  ``contracts <= 0`` roll-over/``continue`` guard.

Pure arithmetic on synthetic inputs: no network, no data lake, no ``czsc``.
"""

from __future__ import annotations

import pytest

from uniquant.hands.backtest.cffex_engine import (
    CFFEXMatchingAndRiskEngine,
    FuturesContractType,
)


class TestContractSpecLookup:
    def test_get_spec_unknown_contract_raises_value_error(self):
        with pytest.raises(ValueError, match="未知期货品种代码"):
            CFFEXMatchingAndRiskEngine.get_spec("XX")

    def test_calculate_notional_uses_multiplier_and_absolute_contracts(self):
        # IF multiplier = 300 元/点.
        assert CFFEXMatchingAndRiskEngine.calculate_notional(
            FuturesContractType.IF, 4000.0, 2
        ) == pytest.approx(4000.0 * 300.0 * 2)
        # Negative (short) contract counts are taken in absolute value.
        assert CFFEXMatchingAndRiskEngine.calculate_notional(
            FuturesContractType.IC, 5000.0, -3
        ) == pytest.approx(5000.0 * 200.0 * 3)

    def test_calculate_notional_zero_contracts_is_zero(self):
        assert CFFEXMatchingAndRiskEngine.calculate_notional(
            FuturesContractType.IM, 6000.0, 0
        ) == 0.0


class TestDailyMTMSettlementClose:
    def _open_long(self, engine, price=4000.0, contracts=10):
        return engine.perform_daily_mtm_settlement(
            date="2024-01-02",
            settlement_prices={"IF2401": price},
            intraday_trades=[
                {
                    "symbol": "IF2401",
                    "contract_type": "IF",
                    "side": "LONG",
                    "action": "OPEN",
                    "contracts": contracts,
                    "price": price,
                }
            ],
        )

    def test_close_long_realizes_profit_and_zeroes_position(self):
        engine = CFFEXMatchingAndRiskEngine(initial_cash=50_000_000.0)
        self._open_long(engine, price=4000.0, contracts=10)

        report = engine.perform_daily_mtm_settlement(
            date="2024-01-03",
            settlement_prices={"IF2401": 4050.0},
            intraday_trades=[
                {
                    "symbol": "IF2401",
                    "contract_type": "IF",
                    "side": "LONG",
                    "action": "CLOSE",
                    "contracts": 10,
                    "price": 4050.0,
                }
            ],
        )

        # LONG: sign=+1, pnl = (4050 - 4000) * 300 * 10 = 150_000.
        assert report.realized_trading_pnl == pytest.approx(150_000.0)
        # Closed position is clamped to zero and skipped in the holding loop.
        assert engine.positions["IF2401"].contracts == 0
        assert report.unrealized_holding_pnl == 0.0
        assert report.total_margin_used == 0.0

    def test_close_short_realizes_inverse_pnl(self):
        engine = CFFEXMatchingAndRiskEngine(initial_cash=50_000_000.0)
        engine.perform_daily_mtm_settlement(
            date="2024-01-02",
            settlement_prices={"IC2401": 5000.0},
            intraday_trades=[
                {
                    "symbol": "IC2401",
                    "contract_type": "IC",
                    "side": "SHORT",
                    "action": "OPEN",
                    "contracts": 5,
                    "price": 5000.0,
                }
            ],
        )

        report = engine.perform_daily_mtm_settlement(
            date="2024-01-03",
            settlement_prices={"IC2401": 4900.0},
            intraday_trades=[
                {
                    "symbol": "IC2401",
                    "contract_type": "IC",
                    "side": "SHORT",
                    "action": "CLOSE",
                    "contracts": 5,
                    "price": 4900.0,
                }
            ],
        )

        # SHORT: sign=-1, pnl = (4900 - 5000) * 200 * 5 * -1 = +100_000.
        assert report.realized_trading_pnl == pytest.approx(100_000.0)
        assert engine.positions["IC2401"].contracts == 0

    def test_close_without_prior_open_uses_created_position_baseline(self):
        engine = CFFEXMatchingAndRiskEngine(initial_cash=50_000_000.0)
        # A CLOSE on a symbol never opened creates the position with the trade
        # price as baseline, so its realised P&L is zero.
        report = engine.perform_daily_mtm_settlement(
            date="2024-01-02",
            settlement_prices={"IH2401": 3000.0},
            intraday_trades=[
                {
                    "symbol": "IH2401",
                    "contract_type": "IH",
                    "side": "LONG",
                    "action": "CLOSE",
                    "contracts": 4,
                    "price": 3000.0,
                }
            ],
        )
        assert report.realized_trading_pnl == 0.0
        assert engine.positions["IH2401"].contracts == 0
