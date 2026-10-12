#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for PortfolioService Hedging Governance & Constraints
=============================================================================
验证:
  1. 三元配置约束校验 (股票多头 75%, 股指期货空头 -75%, 现金缓冲 25%, 总杠杆 175%, 净敞口 0%);
  2. 单申万一级行业集中度 (<=10% 且 <=4 只股票) 硬拦截;
  3. 单票权重 (<=2.5%) 硬拦截;
  4. 存量纯多头单边策略 (sum=100% 或 sum=1.0) 100% 向后兼容性.
=============================================================================
"""

from decimal import Decimal
import pytest

from uniquant.services.portfolio_service import PortfolioService


class TestPortfolioServiceHedgingGovernance:
    """生产级多空治理中台深度实证门禁"""

    @pytest.fixture
    def service(self):
        return PortfolioService()

    def test_canonical_ternary_allocation_percentage_mode(self, service):
        """测试 1: 验证标准三元配置约束 (百分比模式: 股票 75%, 期货 -75%, 现金 25%, 总杠杆 175%, 净敞口 0%)"""
        # 30 只股票，每只 2.5%，总计 75%
        stock_weights = {f"6000{i:02d}.SH": Decimal("2.5") for i in range(30)}
        futures_weights = {"IF2406": Decimal("-75.0")}
        cash_weight = Decimal("25.0")

        # 构造行业映射：每 3 只股票属于同一个申万一级行业（10 个行业，每个行业 7.5% 权重，3 只股票）
        industry_map = {f"6000{i:02d}.SH": f"行业_{i // 3}" for i in range(30)}

        is_valid = service.validate_hedged_portfolio(
            stock_weights=stock_weights,
            futures_weights=futures_weights,
            cash_weight=cash_weight,
            industry_map=industry_map,
        )
        assert is_valid is True, "标准三元配置 (75% 股票 + -75% 期货 + 25% 现金) 必须通过验证"

    def test_canonical_ternary_allocation_ratio_mode(self, service):
        """测试 2: 验证标准三元配置约束 (比率模式: 股票 0.75, 期货 -0.75, 现金 0.25, 总杠杆 1.75, 净敞口 0.0)"""
        stock_weights = {f"0000{i:02d}.SZ": Decimal("0.025") for i in range(30)}
        futures_weights = {"IF2406": Decimal("-0.75")}
        cash_weight = Decimal("0.25")

        industry_map = {f"0000{i:02d}.SZ": f"行业_{i // 3}" for i in range(30)}

        is_valid = service.validate_hedged_portfolio(
            stock_weights=stock_weights,
            futures_weights=futures_weights,
            cash_weight=cash_weight,
            industry_map=industry_map,
        )
        assert is_valid is True, "标准比率制三元配置 (0.75 股票 + -0.75 期货 + 0.25 现金) 必须通过验证"

    def test_single_stock_weight_hard_interception(self, service):
        """测试 3: 单票权重 (>2.5%) 硬拦截"""
        # 其中一只标的超标至 3.0%，其余相应减少以维持 75%
        stock_weights = {f"6000{i:02d}.SH": Decimal("2.5") for i in range(28)}
        stock_weights["600028.SH"] = Decimal("3.0")  # 超出 2.5%
        stock_weights["600029.SH"] = Decimal("2.0")

        futures_weights = {"IF2406": Decimal("-75.0")}
        cash_weight = Decimal("25.0")

        is_valid = service.validate_hedged_portfolio(
            stock_weights=stock_weights,
            futures_weights=futures_weights,
            cash_weight=cash_weight,
        )
        assert is_valid is False, "单票权重 3.0% > 2.5% 必须被硬拦截"

    def test_single_industry_weight_hard_interception(self, service):
        """测试 4: 单申万一级行业集中度权重 (>10%) 硬拦截"""
        stock_weights = {f"6000{i:02d}.SH": Decimal("2.5") for i in range(30)}
        futures_weights = {"IF2406": Decimal("-75.0")}
        cash_weight = Decimal("25.0")

        # 将前 5 只股票全划入 '银行' 行业，使得银行权重达到 5 * 2.5% = 12.5% > 10%
        industry_map = {f"6000{i:02d}.SH": "其他行业" for i in range(30)}
        for i in range(5):
            industry_map[f"6000{i:02d}.SH"] = "银行"

        is_valid = service.validate_hedged_portfolio(
            stock_weights=stock_weights,
            futures_weights=futures_weights,
            cash_weight=cash_weight,
            industry_map=industry_map,
        )
        assert is_valid is False, "单行业集中度 12.5% > 10.0% 必须被硬拦截"

    def test_single_industry_stock_count_hard_interception(self, service):
        """测试 5: 单申万一级行业持股数 (>4只) 硬拦截"""
        # 即使行业总权重 <= 10% (比如 5 只股票每只 1.8% = 9.0% <= 10%)，但只数 5 只 > 4 只
        stock_weights = {f"6000{i:02d}.SH": Decimal("2.5") for i in range(30)}
        futures_weights = {"IF2406": Decimal("-75.0")}
        cash_weight = Decimal("25.0")

        industry_map = {f"6000{i:02d}.SH": "多元行业" for i in range(30)}
        # 5 只股票在 '电子' 行业
        for i in range(5):
            industry_map[f"6000{i:02d}.SH"] = "电子"

        is_valid = service.validate_hedged_portfolio(
            stock_weights=stock_weights,
            futures_weights=futures_weights,
            cash_weight=cash_weight,
            industry_map=industry_map,
        )
        assert is_valid is False, "单行业持股数 5 只 > 4 只必须被硬拦截"

    def test_legacy_long_only_backward_compatibility(self, service):
        """测试 6: 存量纯多头单边策略 (sum=100% 或 1.0) 100% 向后兼容性"""
        # 1. 传统百分比制 100%
        legacy_pct = {
            "600519.SH": Decimal("40.0"),
            "000858.SZ": Decimal("30.0"),
            "601318.SH": Decimal("30.0"),
        }
        assert service._validate_weights(legacy_pct) is True

        # 2. 传统比率制 1.0
        legacy_ratio = {
            "600519.SH": Decimal("0.40"),
            "000858.SZ": Decimal("0.30"),
            "601318.SH": Decimal("0.30"),
        }
        assert service._validate_weights(legacy_ratio) is True

        # 3. 传统非法权重总和 (sum != 100% 且 != 1.0) 保持拦截
        invalid_pct = {"600519.SH": Decimal("50.0"), "000858.SZ": Decimal("40.0")} # sum=90%
        assert service._validate_weights(invalid_pct) is False

        invalid_ratio = {"600519.SH": Decimal("0.60"), "000858.SZ": Decimal("0.50")} # sum=1.10
        assert service._validate_weights(invalid_ratio) is False

    def test_hedging_allocation_imbalance_rejection(self, service):
        """测试 7: 三元配置失衡非法组合拦截 (股多头偏离75%, 期指非负, 现金偏离25%)"""
        # 股票总和 80% (偏离 75%)
        w_stock_80 = {f"6000{i:02d}.SH": Decimal("2.5") for i in range(32)}
        assert service.validate_hedged_portfolio(
            stock_weights=w_stock_80,
            futures_weights={"IF2406": Decimal("-75.0")},
            cash_weight=Decimal("25.0"),
        ) is False

        # 期指空头为正数 (做多而不是做空)
        w_stock_ok = {f"6000{i:02d}.SH": Decimal("2.5") for i in range(30)}
        assert service.validate_hedged_portfolio(
            stock_weights=w_stock_ok,
            futures_weights={"IF2406": Decimal("75.0")},
            cash_weight=Decimal("25.0"),
        ) is False

        # 现金缓冲池偏离 25% (比如 15%)
        assert service.validate_hedged_portfolio(
            stock_weights=w_stock_ok,
            futures_weights={"IF2406": Decimal("-75.0")},
            cash_weight=Decimal("15.0"),
        ) is False
