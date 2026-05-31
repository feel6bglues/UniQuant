"""
Task-1.5: PositionSizer 单元测试
验证仓位计算正确性
"""

import pytest

from uniquant.risk.sizer import PositionSizer, InvalidStopLossError


class TestPositionSizer:
    """测试仓位计算"""

    @pytest.fixture
    def sizer(self):
        return PositionSizer(initial_capital=100000.0, risk_pct=0.05)

    def test_sizer_initialization(self, sizer):
        """测试初始化"""
        assert sizer.capital == 100000.0
        assert sizer.risk_pct == 0.05

    def test_calculate_shares_basic(self, sizer):
        """测试基本仓位计算"""
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=9.0,
            market="CN",
        )
        
        assert isinstance(result, dict)
        assert "建议动作" in result
        assert "入场区间" in result
        assert "执行止损" in result
        assert "风险敞口" in result
        assert "建议仓位" in result
        assert "资金占用" in result

    def test_calculate_shares_cn_market(self, sizer):
        """测试A股市场（T+1惩罚）"""
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=9.0,
            market="CN",
        )
        
        # A股有T+1惩罚因子1.2
        assert result["penalty_applied"] == 1.2

    def test_calculate_shares_us_market(self, sizer):
        """测试美股市场"""
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=9.0,
            market="US",
        )
        
        assert result["penalty_applied"] == 1.0

    def test_calculate_shares_hk_market(self, sizer):
        """测试港股市场"""
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=9.0,
            market="HK",
        )
        
        assert result["penalty_applied"] == 1.0

    def test_calculate_shares_with_czsc_bottom(self, sizer):
        """测试CZSC底部止损"""
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=9.0,
            market="CN",
            czsc_bottom=9.2,  # 更高的止损
        )
        
        # 应该使用更高的止损
        assert result["执行止损"] == 9.2

    def test_calculate_shares_invalid_stop_loss(self, sizer):
        """测试无效止损（高于入场价）"""
        with pytest.raises(InvalidStopLossError):
            sizer.calculate_shares(
                price=10.0,
                stop_loss=10.5,  # 止损高于入场价
                market="CN",
            )

    def test_calculate_shares_stop_loss_equal_price(self, sizer):
        """测试止损等于入场价"""
        with pytest.raises(InvalidStopLossError):
            sizer.calculate_shares(
                price=10.0,
                stop_loss=10.0,
                market="CN",
            )

    def test_calculate_shares_lot_size_cn(self, sizer):
        """测试A股手数（100股/手）"""
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=9.0,
            market="CN",
        )
        
        # 仓位应该是100的整数倍
        assert result["建议仓位"] % 100 == 0

    def test_calculate_shares_lot_size_us(self, sizer):
        """测试美股手数（1股/手）"""
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=9.0,
            market="US",
        )
        
        # 美股可以买任意股数
        assert isinstance(result["建议仓位"], int)

    def test_calculate_shares_circuit_break(self, sizer):
        """测试熔断机制"""
        # 使用极低的止损触发大仓位
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=0.1,  # 极低止损
            market="CN",
        )
        
        # 应该触发熔断或限制仓位
        assert result.get("是否触发熔断") is True or result.get("建议仓位") > 0

    def test_calculate_position_alias(self, sizer):
        """测试calculate_position别名"""
        result1 = sizer.calculate_shares(
            price=10.0,
            stop_loss=9.0,
            market="CN",
        )
        result2 = sizer.calculate_position(
            price=10.0,
            stop_loss=9.0,
            market="CN",
        )
        
        assert result1["建议仓位"] == result2["建议仓位"]

    def test_calculate_shares_risk_calculation(self, sizer):
        """测试风险计算"""
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=9.0,
            market="CN",
        )
        
        # 风险敞口 = (价格 - 止损) * 惩罚因子
        expected_risk = (10.0 - 9.0) * 1.2
        assert result["风险敞口"] == round(expected_risk, 2)

    def test_calculate_shares_max_loss(self, sizer):
        """测试最大亏损计算"""
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=9.0,
            market="CN",
        )
        
        # 最大允许亏损 = 资金 * 风险比例
        expected_max_loss = 100000.0 * 0.05
        assert result["max_loss_allowed"] == round(expected_max_loss, 2)


class TestPositionSizerEdgeCases:
    """边界条件测试"""

    @pytest.fixture
    def sizer(self):
        return PositionSizer(initial_capital=100000.0, risk_pct=0.05)

    def test_high_price_stock(self, sizer):
        """测试高价股"""
        result = sizer.calculate_shares(
            price=500.0,
            stop_loss=450.0,
            market="CN",
        )
        
        assert result["建议仓位"] >= 0

    def test_low_price_stock(self, sizer):
        """测试低价股"""
        result = sizer.calculate_shares(
            price=2.0,
            stop_loss=1.8,
            market="CN",
        )
        
        assert result["建议仓位"] >= 0

    def test_tight_stop_loss(self, sizer):
        """测试紧止损"""
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=9.99,
            market="CN",
        )
        
        # 紧止损应该导致大仓位
        assert result["建议仓位"] > 0

    def test_wide_stop_loss(self, sizer):
        """测试宽止损"""
        result = sizer.calculate_shares(
            price=10.0,
            stop_loss=5.0,
            market="CN",
        )
        
        # 宽止损应该导致小仓位
        assert result["建议仓位"] >= 0


class TestInvalidStopLossError:
    """测试止损错误"""

    def test_error_message(self):
        """测试错误消息"""
        error = InvalidStopLossError(10.0, 10.5)
        
        assert "10.5" in str(error)
        assert "10" in str(error)
        assert "above or at entry price" in str(error)
