# -*- coding: utf-8 -*-
"""
Unit and Integration Tests for ManifestGenerator & PreTradeComplianceEngine
=============================================================================
"""

import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from uniquant.risk.compliance_engine import (
    ComplianceReport,
    PreTradeComplianceEngine,
)
from uniquant.services.manifest_generator import ManifestGenerator, ManifestPack


@pytest.fixture
def sample_universe():
    prices = {
        "600519.SH": 1292.01,
        "300750.SZ": 385.99,
        "002594.SZ": 92.65,
        "600036.SH": 36.85,
        "601318.SH": 46.20,
    }
    industries = {
        "600519.SH": "食品饮料",
        "300750.SZ": "电力设备",
        "002594.SZ": "汽车",
        "600036.SH": "银行",
        "601318.SH": "非银金融",
    }
    weights = {s: 0.15 for s in prices}  # 5 * 0.15 = 0.75
    return prices, industries, weights


@pytest.fixture
def temp_output_dir():
    d = tempfile.mkdtemp(prefix="uniquant_manifest_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestPreTradeComplianceEngine:
    def test_clean_pass(self, sample_universe):
        prices, industries, weights = sample_universe
        aum = 100_000_000.0  # 1亿 AUM

        engine = PreTradeComplianceEngine(
            max_single_stock_weight=0.20,  # 宽限用于测试
            max_industry_weight=0.20,
            max_industry_stock_count=4,
        )

        orders = pd.DataFrame([
            {"symbol": "600519.SH", "trade_shares": 11600, "ref_price": 1292.01, "est_amount": 14987316.0, "industry_l1": "食品饮料"},
            {"symbol": "300750.SZ", "trade_shares": 38800, "ref_price": 385.99, "est_amount": 14976412.0, "industry_l1": "电力设备"},
        ])

        futures = pd.DataFrame([{
            "contract_symbol": "IF2610.CFX",
            "notional_cny": 29963728.0,
            "pb_citic_contracts": 10,
            "pb_gtja_contracts": 10,
            "pb_htsc_contracts": 5,
        }])

        report = engine.audit(
            manifest_id="TEST_PASS_001",
            aum_cny=aum,
            equity_orders=orders,
            futures_hedging=futures,
            industry_mapping=industries,
        )

        assert report.passed is True
        assert report.verdict == "APPROVED_PASS"
        assert len(report.breaches) == 0
        assert len(report.manifest_hash) == 64  # SHA-256 length

    def test_single_stock_weight_breach(self):
        engine = PreTradeComplianceEngine(max_single_stock_weight=0.025)
        aum = 100_000_000.0

        orders = pd.DataFrame([
            {"symbol": "600519.SH", "trade_shares": 50000, "ref_price": 100.0, "est_amount": 5_000_000.0, "industry_l1": "食品饮料"}
        ])  # 5% weight > 2.5%

        futures = pd.DataFrame([{"contract_symbol": "IF", "notional_cny": 5_000_000.0}])

        report = engine.audit(
            manifest_id="TEST_BREACH_STOCK",
            aum_cny=aum,
            equity_orders=orders,
            futures_hedging=futures,
        )

        assert report.passed is False
        assert report.verdict == "REJECTED_BREACH"
        assert any("单票持仓集中度超限" in b for b in report.breaches)

    def test_industry_count_breach(self):
        engine = PreTradeComplianceEngine(max_industry_stock_count=4)
        aum = 100_000_000.0

        orders = pd.DataFrame([
            {"symbol": f"60000{i}.SH", "trade_shares": 100, "ref_price": 10.0, "est_amount": 1000.0, "industry_l1": "银行"}
            for i in range(5)  # 5 stocks in same industry > 4 limit
        ])
        futures = pd.DataFrame([{"contract_symbol": "IF", "notional_cny": 5000.0}])

        report = engine.audit(
            manifest_id="TEST_BREACH_IND_COUNT",
            aum_cny=aum,
            equity_orders=orders,
            futures_hedging=futures,
        )

        assert report.passed is False
        assert any("行业持股数量超限" in b for b in report.breaches)

    def test_pb_contract_limit_breach(self):
        engine = PreTradeComplianceEngine(max_pb_contract_limit=1200)
        aum = 100_000_000.0

        orders = pd.DataFrame([
            {"symbol": "600519.SH", "trade_shares": 100, "ref_price": 100.0, "est_amount": 10000.0, "industry_l1": "综合"}
        ])
        futures = pd.DataFrame([{
            "contract_symbol": "IF",
            "notional_cny": 10000.0,
            "pb_citic_contracts": 1250,  # 1250 > 1200
        }])

        report = engine.audit(
            manifest_id="TEST_BREACH_PB",
            aum_cny=aum,
            equity_orders=orders,
            futures_hedging=futures,
        )

        assert report.passed is False
        assert any("中金所主经纪商(PB)持仓超限" in b for b in report.breaches)

    def test_lot_sizing_breach(self):
        engine = PreTradeComplianceEngine()
        aum = 100_000_000.0

        orders = pd.DataFrame([
            {"symbol": "600519.SH", "trade_shares": 150, "ref_price": 100.0, "est_amount": 15000.0, "industry_l1": "综合"}
        ])  # 150 % 100 != 0
        futures = pd.DataFrame([{"contract_symbol": "IF", "notional_cny": 15000.0}])

        report = engine.audit(
            manifest_id="TEST_BREACH_LOT",
            aum_cny=aum,
            equity_orders=orders,
            futures_hedging=futures,
        )

        assert report.passed is False
        assert any("整百股合规违背" in b for b in report.breaches)


class TestManifestGenerator:
    def test_round_to_lot_100_and_greedy_balance(self, sample_universe):
        prices, industries, weights = sample_universe
        aum = 5_000_000_000.0  # 50 亿 AUM

        generator = ManifestGenerator(max_single_stock_weight=0.20)
        df = generator.round_to_lot_100_and_greedy_balance(
            target_weights=weights,
            stock_prices=prices,
            aum_cny=aum,
            stock_industries=industries,
        )

        assert not df.empty
        # 1. 验证整百股
        for _, row in df.iterrows():
            assert row["target_shares"] % 100 == 0
            assert row["trade_shares"] % 100 == 0

        # 2. 验证多头总额接近 75% AUM
        target_equity = aum * 0.75
        allocated = df["est_amount"].sum()
        residual = target_equity - allocated
        assert 0 <= residual < target_equity * 0.0005  # 残差小于 0.05%

    def test_allocate_pb_futures_hedging(self):
        generator = ManifestGenerator()
        aum = 5_000_000_000.0
        index_quote = 4000.0  # IF 每手 = 4000 * 300 = 1,200,000 CNY

        df = generator.allocate_pb_futures_hedging(
            aum_cny=aum,
            index_quote=index_quote,
            trade_date="2026-09-25",
        )

        row = df.iloc[0]
        assert row["total_contracts"] == 3125
        # 3 PB 分仓: 3125 = 1042 + 1042 + 1041
        assert row["pb_citic_pb_contracts"] == 1042
        assert row["pb_gtja_pb_contracts"] == 1042
        assert row["pb_htsc_pb_contracts"] == 1041
        # 所有 PB 均不超过 1200 手限制
        assert row["pb_citic_pb_contracts"] <= 1200
        assert row["pb_gtja_pb_contracts"] <= 1200
        assert row["pb_htsc_pb_contracts"] <= 1200

    def test_5day_rollover_schedule(self):
        generator = ManifestGenerator()
        schedule = generator.generate_5day_rollover_schedule(
            total_contracts=3125,
            start_date="2026-09-25",
        )

        assert len(schedule) == 5
        total_rolled = schedule["contracts_to_roll"].sum()
        assert total_rolled == 3125
        assert schedule.iloc[0]["contracts_to_roll"] == 312   # ~10%
        assert schedule.iloc[1]["contracts_to_roll"] == 625   # ~20%
        assert schedule.iloc[2]["contracts_to_roll"] == 625   # ~20%
        assert schedule.iloc[3]["contracts_to_roll"] == 781   # ~25%
        assert schedule.iloc[4]["contracts_to_roll"] == 782   # ~25% balance

    def test_generate_manifest_end_to_end(self, sample_universe, temp_output_dir):
        prices, industries, weights = sample_universe
        aum = 1_000_000_000.0  # 10亿 AUM (标杆私募机构级规模)

        compliance = PreTradeComplianceEngine(
            max_single_stock_weight=0.20,
            max_industry_weight=0.20,
            max_industry_stock_count=4,
        )
        generator = ManifestGenerator(
            compliance_engine=compliance,
            output_dir=temp_output_dir,
            max_single_stock_weight=0.20,
        )

        pack = generator.generate_manifest(
            trade_date="2026-09-25",
            aum_cny=aum,
            target_weights=weights,
            stock_prices=prices,
            index_quote=4000.0,
            stock_industries=industries,
        )

        assert isinstance(pack, ManifestPack)
        assert pack.compliance_report.passed is True
        assert pack.compliance_report.verdict == "APPROVED_PASS"

        # 验证落盘文件真实存在
        out_dir = Path(pack.output_dir)
        assert (out_dir / "equity_orders_20260925.csv").exists()
        assert (out_dir / "futures_hedging_20260925.csv").exists()
        assert (out_dir / "rollover_schedule_20260925.csv").exists()
        assert (out_dir / "compliance_audit_20260925.json").exists()

        # 检查 JSON 反序列化有效性
        with open(out_dir / "compliance_audit_20260925.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["manifest_id"] == pack.manifest_id
        assert data["verdict"] == "APPROVED_PASS"
        assert len(data["manifest_hash"]) == 64
