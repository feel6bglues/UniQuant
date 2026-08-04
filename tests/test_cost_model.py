"""Tests for cost_model — constants and sharpe ratio calculation.

These assertions double as documentation verification:
  - cost_model.RISK_FREE_RATE == 0.03 (refutes the P2.5 doc drift claim)
  - BacktestResult.sharpe uses RISK_FREE_RATE default (not 0)
"""

from __future__ import annotations

from numpy.testing import assert_almost_equal

from uniquant.shared.cost_model import (
    COMMISSION_PCT,
    MIN_COMMISSION,
    RISK_FREE_RATE,
    SLIPPAGE_PCT,
    STAMP_TAX_PCT,
    TRANSFER_FEE_PCT,
    calculate_sharpe_ratio,
)


class TestConstants:
    """Document-grounded constant verification (anti-drift assertions)."""

    def test_risk_free_rate_is_3pct(self):
        assert RISK_FREE_RATE == 0.03

    def test_slippage_is_0_05pct(self):
        assert SLIPPAGE_PCT == 0.0005

    def test_commission_is_0_03pct(self):
        assert COMMISSION_PCT == 0.0003

    def test_stamp_tax_is_0_05pct_sell_side(self):
        assert STAMP_TAX_PCT == 0.0005

    def test_min_commission_is_5_cny(self):
        assert MIN_COMMISSION == 5.0

    def test_transfer_fee_is_0_001pct(self):
        assert TRANSFER_FEE_PCT == 0.00001

    def test_cost_buy_commission_plus_transfer(self):
        from uniquant.shared.cost_model import COST_BUY
        assert_almost_equal(COST_BUY, 0.0003 + 0.00001)

    def test_cost_sell_commission_stamp_transfer(self):
        from uniquant.shared.cost_model import COST_SELL
        assert_almost_equal(COST_SELL, 0.0003 + 0.0005 + 0.00001)


class TestCalculateSharpeRatio:
    """Sharpe ratio calculation with RISK_FREE_RATE default."""

    def test_default_rfr_is_3pct(self):
        sig = calculate_sharpe_ratio.__defaults__
        assert sig is not None
        rfr_default = sig[0] if len(sig) >= 1 else None
        assert rfr_default == 0.03

    def test_sharpe_with_positive_returns(self):
        returns = [0.001, 0.002, 0.0015, -0.0005, 0.003]
        sr = calculate_sharpe_ratio(returns, risk_free_rate=0.0, period_days=1)
        assert sr > 0

    def test_sharpe_with_flat_returns(self):
        sr = calculate_sharpe_ratio([0.001, 0.001, 0.001], risk_free_rate=0.03, period_days=1)
        assert sr == 0.0

    def test_sharpe_insufficient_data(self):
        sr = calculate_sharpe_ratio([0.001], risk_free_rate=0.03, period_days=1)
        assert sr == 0.0

    def test_sharpe_empty_data(self):
        sr = calculate_sharpe_ratio([], risk_free_rate=0.03, period_days=1)
        assert sr == 0.0

    def test_sharpe_negative_returns(self):
        returns = [-0.001, -0.002, -0.0015]
        sr = calculate_sharpe_ratio(returns, risk_free_rate=0.0, period_days=1)
        assert sr < 0


class TestCalculateSharpeRatioDefault:
    """calculate_sharpe_ratio default risk_free_rate = RISK_FREE_RATE = 0.03.

    BacktestResult.calculate_metrics() calls calculate_sharpe_ratio(returns, period_days=1)
    without passing risk_free_rate → uses RISK_FREE_RATE default (= 0.03).
    """

    def test_backtest_result_sharpe_calls_calculate_sharpe(self):
        from inspect import signature
        from uniquant.shared.cost_model import calculate_sharpe_ratio as csr
        from uniquant.hands.backtest.result import BacktestResult

        sig = signature(BacktestResult.calculate_metrics)
        # calculate_metrics does NOT accept risk_free_rate param
        assert "risk_free_rate" not in sig.parameters
        # so it must use the default from calculate_sharpe_ratio
        assert csr.__defaults__ is not None
        assert csr.__defaults__[0] == 0.03

    def test_calculate_sharpe_ratio_default_parameter_is_rfr(self):
        from inspect import signature
        from uniquant.shared.cost_model import calculate_sharpe_ratio
        sig = signature(calculate_sharpe_ratio)
        assert sig.parameters["risk_free_rate"].default == 0.03


class TestCostConfig:
    """CostConfig dataclass factories."""

    def test_default_cost_config(self):
        from uniquant.shared.cost_model import CostConfig
        cfg = CostConfig()
        assert cfg.buy_fee_pct == COMMISSION_PCT
        assert cfg.sell_fee_pct == COMMISSION_PCT

    def test_cost_buy_property(self):
        from uniquant.shared.cost_model import CostConfig
        cfg = CostConfig(buy_fee_pct=0.0003, transfer_fee_pct=0.00001)
        assert_almost_equal(cfg.cost_buy, 0.00031)

    def test_cost_sell_property(self):
        from uniquant.shared.cost_model import CostConfig
        cfg = CostConfig(sell_fee_pct=0.0003, stamp_tax_pct=0.0005, transfer_fee_pct=0.00001)
        assert_almost_equal(cfg.cost_sell, 0.00081)
