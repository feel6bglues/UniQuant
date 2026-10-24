#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNMM-QAR 生产级实盘风控对账监控器单元与集成测试 (test_reconcile_qar.py)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.monitoring.reconcile_qar import (
    build_qar_reconciliation,
    load_equity_positions,
    load_futures_positions,
    load_qar_signal,
    reconcile_equity_holdings,
    reconcile_futures_hedging,
    reconcile_nav_custodian,
    reconcile_risk_and_exposure,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def sample_signal_json(tmp_path: Path) -> Path:
    """构造标准 daily_signal_qar.py 输出的目标信号切片"""
    payload = {
        "as_of_date": "2024-05-06",
        "strategy_track": "75/25-IH",
        "aum_rmb": 50_000_000.0,
        "capital_allocation": {
            "equity_long_value": 37_500_000.0,
            "futures_short_notional": -37_500_000.0,
            "cash_reserve": 12_500_000.0,
            "leverage_ratio": 1.5,
            "effective_net_exposure": 0.0,
        },
        "universe_summary": {
            "eligible_candidates_count": 100,
            "selected_stocks_count": 3,
            "governance_compliant": True,
        },
        "target_stock_weights": {
            "600519": 0.25,
            "000858": 0.25,
            "601318": 0.25,
        },
        "futures_hedging_orders": {
            "target_contracts": 30,
            "unit_contract_value": 1_250_000.0,
            "total_notional": 37_500_000.0,
            "accounts_allocation": {
                "PB_ACCOUNT_1": {"contracts": 10},
                "PB_ACCOUNT_2": {"contracts": 10},
                "PB_ACCOUNT_3": {"contracts": 10},
            },
        },
    }
    p = tmp_path / "target_signal.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


@pytest.fixture
def sample_positions_csv(tmp_path: Path) -> Path:
    """构造标准股票持仓 CSV"""
    # 600519: 12500 股 * 1000 元 = 12,500,000 元 (25%)
    # 000858: 125000 股 * 100 元 = 12,500,000 元 (25%)
    # 601318: 250000 股 * 50 元 = 12,500,000 元 (25%)
    # 现金: 12,500,000 元 (25%)
    # 总 AUM = 50,000,000 元
    lines = [
        "code,shares,price,cash",
        "600519,12500,1000.0,12500000.0",
        "000858,125000,100.0,",
        "601318,250000,50.0,",
    ]
    p = tmp_path / "actual_positions.csv"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


@pytest.fixture
def sample_futures_csv(tmp_path: Path) -> Path:
    """构造标准中金所期货持仓 CSV"""
    lines = [
        "account,contract,contracts,direction",
        "PB_ACCOUNT_1,IF_MAIN,10,SHORT",
        "PB_ACCOUNT_2,IF_MAIN,10,SHORT",
        "PB_ACCOUNT_3,IF_MAIN,10,SHORT",
    ]
    p = tmp_path / "actual_futures.csv"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


class TestReconcileQARCore:
    """对账监控器核心函数测试"""

    def test_load_signal_and_positions(self, sample_signal_json, sample_positions_csv):
        sig = load_qar_signal(sample_signal_json)
        assert sig["strategy_track"] == "75/25-IH"
        assert sig["aum_rmb"] == 50_000_000.0

        df_pos = load_equity_positions(sample_positions_csv)
        assert len(df_pos) == 3
        assert "600519" in df_pos["code"].values

    def test_reconcile_equity_holdings_clean_match(self, sample_positions_csv):
        target_weights = {"600519": 0.25, "000858": 0.25, "601318": 0.25}
        df_pos = load_equity_positions(sample_positions_csv)
        price_map = {"600519": 1000.0, "000858": 100.0, "601318": 50.0}

        recon = reconcile_equity_holdings(
            target_weights=target_weights,
            actual_positions=df_pos,
            price_map=price_map,
            total_aum_rmb=50_000_000.0,
            drift_tol_pp=0.50,
        )

        assert recon["summary"]["is_clean"] is True
        assert recon["summary"]["n_match"] == 3
        assert recon["summary"]["n_drift"] == 0
        assert recon["summary"]["n_missing"] == 0
        assert recon["summary"]["n_extra"] == 0
        assert recon["summary"]["total_actual_equity_value_rmb"] == 37_500_000.0

    def test_reconcile_equity_holdings_drift_missing_extra(self, tmp_path):
        target_weights = {
            "600519": 0.30,  # 目标 30%, 实际 25% (漂移 -5 pp)
            "000858": 0.25,  # 目标 25%, 实际 0 (MISSING)
        }
        # 实际持仓有 600519 和额外的 600036 (EXTRA)
        lines = [
            "code,shares,price",
            "600519,12500,1000.0",
            "600036,100000,40.0",
        ]
        p = tmp_path / "drift_positions.csv"
        p.write_text("\n".join(lines), encoding="utf-8")
        df_pos = load_equity_positions(p)
        price_map = {"600519": 1000.0, "000858": 100.0, "600036": 40.0}

        recon = reconcile_equity_holdings(
            target_weights=target_weights,
            actual_positions=df_pos,
            price_map=price_map,
            total_aum_rmb=50_000_000.0,
            drift_tol_pp=0.50,
        )

        assert recon["summary"]["is_clean"] is False
        assert recon["summary"]["n_drift"] == 1  # 600519 权重 25% vs 30%
        assert recon["summary"]["n_missing"] == 1  # 000858
        assert recon["summary"]["n_extra"] == 1  # 600036

    def test_reconcile_futures_hedging(self, sample_futures_csv):
        target_orders = {
            "target_contracts": 30,
            "unit_contract_value": 1_250_000.0,
            "accounts_allocation": {
                "PB_ACCOUNT_1": {"contracts": 10},
                "PB_ACCOUNT_2": {"contracts": 10},
                "PB_ACCOUNT_3": {"contracts": 10},
            },
        }
        df_fut = load_futures_positions(sample_futures_csv)
        recon = reconcile_futures_hedging(
            target_hedging_orders=target_orders,
            actual_futures=df_fut,
            unit_contract_value=1_250_000.0,
        )

        assert recon["is_hedged_compliant"] is True
        assert recon["target_contracts"] == 30
        assert recon["actual_contracts"] == 30
        assert recon["contract_discrepancy"] == 0

    def test_reconcile_risk_and_exposure_compliant(self):
        # 现货多头 37.5M, 期指空头 37.5M, 现金 12.5M, 总 AUM 50M
        recon = reconcile_risk_and_exposure(
            total_actual_equity_value=37_500_000.0,
            actual_futures_notional=37_500_000.0,
            actual_cash_rmb=12_500_000.0,
            total_aum_rmb=50_000_000.0,
            target_track="75/25-IH",
        )

        assert recon["is_beta_neutral"] is True
        assert recon["net_beta"] == 0.0
        assert recon["is_cash_adequate"] is True
        assert len(recon["risk_breaches"]) == 0

    def test_reconcile_risk_exposure_net_beta_breach(self):
        # 现货多头 45M, 期指空头仅 30M (敞口超标 +15M / 50M = +0.30 Net Beta)
        recon = reconcile_risk_and_exposure(
            total_actual_equity_value=45_000_000.0,
            actual_futures_notional=30_000_000.0,
            actual_cash_rmb=5_000_000.0,  # 现金仅 10% (< 12%)
            total_aum_rmb=50_000_000.0,
            target_track="75/25-IH",
            max_net_beta=0.10,
        )

        assert recon["is_beta_neutral"] is False
        assert recon["net_beta"] == 0.30
        assert recon["is_cash_adequate"] is False
        assert len(recon["risk_breaches"]) >= 2

    def test_reconcile_nav_custodian(self):
        # 1. 正常容差内 (偏差 2 bps <= 5 bps)
        r_ok = reconcile_nav_custodian(custodian_nav=1.0002, theoretical_nav=1.0000, bps_tol=5.0)
        assert r_ok["is_within_tolerance"] is True
        assert r_ok["drift_bps"] == 2.0

        # 2. 超标报警 (偏差 8 bps > 5 bps)
        r_err = reconcile_nav_custodian(custodian_nav=1.0008, theoretical_nav=1.0000, bps_tol=5.0)
        assert r_err["is_within_tolerance"] is False
        assert r_err["drift_bps"] == 8.0

        # 3. 未提供跳过
        r_skip = reconcile_nav_custodian(custodian_nav=None, theoretical_nav=1.0)
        assert r_skip["nav_reconciled"] is False


class TestBuildQARReconciliationIntegration:
    """端到端对账流水线集成测试"""

    def test_end_to_end_green_status(
        self,
        sample_signal_json,
        sample_positions_csv,
        sample_futures_csv,
        tmp_path,
    ):
        explicit_px = {"600519": 1000.0, "000858": 100.0, "601318": 50.0}
        report = build_qar_reconciliation(
            signal_path=sample_signal_json,
            positions_path=sample_positions_csv,
            futures_path=sample_futures_csv,
            cash_rmb=12_500_000.0,
            custodian_nav=1.0001,
            theoretical_nav=1.0000,
            explicit_prices=explicit_px,
        )

        assert report["overall_status"] == "GREEN"
        assert report["exit_code"] == 0
        assert len(report["critical_breaches"]) == 0
        assert report["risk_reconciliation"]["is_beta_neutral"] is True

    def test_end_to_end_red_status_on_naked_unhedged(
        self,
        sample_signal_json,
        sample_positions_csv,
        tmp_path,
    ):
        # 裸多头未对冲 (未提供期货持仓)
        explicit_px = {"600519": 1000.0, "000858": 100.0, "601318": 50.0}
        report = build_qar_reconciliation(
            signal_path=sample_signal_json,
            positions_path=sample_positions_csv,
            futures_path=None,  # 期货空头为 0
            cash_rmb=12_500_000.0,
            custodian_nav=1.0000,
            theoretical_nav=1.0000,
            explicit_prices=explicit_px,
        )

        assert report["overall_status"] == "RED"
        assert report["exit_code"] == 1
        assert len(report["critical_breaches"]) > 0
        assert any("期指对冲合约偏差" in b or "净市场敞口" in b for b in report["critical_breaches"])

    def test_cli_execution_with_output_file(
        self,
        sample_signal_json,
        sample_positions_csv,
        sample_futures_csv,
        tmp_path,
    ):
        import subprocess
        import sys

        cli_script = PROJECT_ROOT / "scripts" / "monitoring" / "reconcile_qar.py"
        out_json = tmp_path / "recon_out.json"

        cmd = [
            sys.executable,
            str(cli_script),
            "--signal", str(sample_signal_json),
            "--positions", str(sample_positions_csv),
            "--futures", str(sample_futures_csv),
            "--cash", "12500000.0",
            "--custodian-nav", "1.0001",
            "--theoretical-nav", "1.0000",
            "--output", str(out_json),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0, f"CLI 执行失败: {res.stderr}"
        assert out_json.exists(), "CLI 应正确生成输出 JSON 报告"

        data = json.loads(out_json.read_text(encoding="utf-8"))
        assert data["overall_status"] == "GREEN"
        assert data["exit_code"] == 0
