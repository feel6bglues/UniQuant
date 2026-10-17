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


class TestTransferFeeUnified:
    """过户费全市场统一口径（2022-04-29 中国结算新规）。

    沪深北 A 股统一 0.01‰ 双向收取；修复历史缺陷：漏 688（科创板），且误判深市免收。
    """

    def test_sh_main_and_star_charge_fee(self):
        from uniquant.shared.cost_model import _has_transfer_fee
        assert _has_transfer_fee("600519.SH") is True       # 沪市主板
        assert _has_transfer_fee("688981.SH") is True       # 科创板（历史遗漏）
        assert _has_transfer_fee("689009.SH") is True

    def test_sz_boards_charge_fee(self):
        from uniquant.shared.cost_model import _has_transfer_fee
        assert _has_transfer_fee("000001.SZ") is True       # 深市主板
        assert _has_transfer_fee("002594.SZ") is True       # 中小板
        assert _has_transfer_fee("300750.SZ") is True       # 创业板
        assert _has_transfer_fee("301001.SZ") is True

    def test_bj_boards_charge_fee(self):
        from uniquant.shared.cost_model import _has_transfer_fee
        assert _has_transfer_fee("832000.BJ") is True
        assert _has_transfer_fee("920001.BJ") is True

    def test_non_stock_instruments_exempt(self):
        from uniquant.shared.cost_model import _has_transfer_fee
        assert _has_transfer_fee("510300.SH") is False      # 沪市 ETF
        assert _has_transfer_fee("159915.SZ") is False      # 深市 ETF
        assert _has_transfer_fee("000001.SH") is False      # 上证指数
        assert _has_transfer_fee("399001.SZ") is False      # 深证成指
        assert _has_transfer_fee("") is False

    def test_vectorized_mask_matches_scalar(self):
        from uniquant.shared.cost_model import _has_transfer_fee, has_transfer_fee_mask
        symbols = ["600519.SH", "688981.SH", "000001.SZ", "510300.SH", "920001.BJ", ""]
        mask = has_transfer_fee_mask(symbols)
        assert list(mask) == [_has_transfer_fee(s) for s in symbols]

    def test_calculate_total_cost_includes_fee_for_star(self):
        from uniquant.shared.cost_model import calculate_total_cost
        # 深市与科创板现在均含过户费（此前为 0）
        assert calculate_total_cost(100000.0, is_sell=False, symbol="688981.SH") > calculate_total_cost(
            100000.0, is_sell=False, symbol="510300.SH"
        )


# ── CostConfig.from_yaml default-path resolution (round-8 regression guard) ──


class TestCostConfigFromYamlDefaultPath:
    """第八轮修复回归守卫：``from_yaml()`` 默认路径原为
    ``Path(__file__).parents[2]`` → ``src/config/trading.yaml``（不存在）
    → 异常被 ``except Exception`` 吞掉 → 静默退回硬编码默认值。
    现改为仓库根 SSOT ``PROJECT_ROOT``。"""

    def test_default_path_uses_project_root(self, tmp_path, monkeypatch):
        import uniquant.shared.cost_model as cm

        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "trading.yaml").write_text(
            "execution:\n"
            "  buy_fee_pct: 0.001\n"
            "  sell_fee_pct: 0.002\n"
            "  stamp_tax_pct: 0.003\n"
            "  slippage_pct: 0.004\n"
            "  min_commission: 7.0\n"
            "  transfer_fee_pct: 0.00005\n"
        )
        monkeypatch.setattr(cm, "PROJECT_ROOT", tmp_path)

        cfg = cm.CostConfig.from_yaml()
        assert cfg.buy_fee_pct == 0.001
        assert cfg.sell_fee_pct == 0.002
        assert cfg.stamp_tax_pct == 0.003
        assert cfg.slippage_pct == 0.004
        assert cfg.min_commission == 7.0
        assert cfg.transfer_fee_pct == 0.00005

    def test_default_path_reads_real_repo_execution_section(self):
        import pytest

        import uniquant.shared.cost_model as cm
        from uniquant.shared.constants.path import PROJECT_ROOT

        assert cm.PROJECT_ROOT == PROJECT_ROOT
        assert (PROJECT_ROOT / "config" / "trading.yaml").exists()

        cfg = cm.CostConfig.from_yaml()
        assert cfg.buy_fee_pct == pytest.approx(0.0003)
        assert cfg.sell_fee_pct == pytest.approx(0.0003)
        assert cfg.stamp_tax_pct == pytest.approx(0.0005)
        assert cfg.slippage_pct == pytest.approx(0.0005)
        assert cfg.transfer_fee_pct == pytest.approx(0.00001)
