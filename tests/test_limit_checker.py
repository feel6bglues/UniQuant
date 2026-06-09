"""
Task-1.4: 涨跌停检查缺失修复测试
验证A股特有微观结构防御功能
"""


from uniquant.shared.limit_checker import (
    check_limit_status,
    check_limit_status_dict,
    get_board_type,
    validate_trade_action,
)
from uniquant.shared.constants import MarketConstants


class TestGetBoardType:
    """测试板块类型识别"""

    def test_main_board_sh(self):
        """测试上海主板"""
        assert get_board_type("600000.SH") == "main"
        assert get_board_type("601318.SH") == "main"

    def test_main_board_sz(self):
        """测试深圳主板"""
        assert get_board_type("000001.SZ") == "main"
        assert get_board_type("002415.SZ") == "main"

    def test_sci_tech_board(self):
        """测试科创板"""
        assert get_board_type("688981.SH") == "sci_tech"
        assert get_board_type("688001.SH") == "sci_tech"

    def test_gem_board(self):
        """测试创业板"""
        assert get_board_type("300750.SZ") == "gem"
        assert get_board_type("301001.SZ") == "gem"

    def test_beijing_board(self):
        """测试北交所"""
        assert get_board_type("830799.BJ") == "beijing"
        assert get_board_type("873001.BJ") == "beijing"

    def test_st_stock(self):
        """测试ST股"""
        assert get_board_type("000001.SZ", "ST某某") == "st"
        assert get_board_type("000001.SZ", "*ST某某") == "st"

    def test_empty_symbol(self):
        """测试空代码"""
        assert get_board_type("") == "main"
        assert get_board_type(None) == "main"


class TestCheckLimitStatus:
    """测试涨跌停状态检查"""

    def test_normal_price_main_board(self):
        """测试主板正常价格"""
        status = check_limit_status(10.50, 10.00, "600000.SH")
        
        assert status.is_limit_up is False
        assert status.is_limit_down is False
        assert status.can_buy is True
        assert status.can_sell is True
        assert status.board_type == "main"
        assert status.price_ratio == 1.05

    def test_limit_up_main_board(self):
        """测试主板涨停"""
        status = check_limit_status(11.00, 10.00, "600000.SH")
        
        assert status.is_limit_up is True
        assert status.is_limit_down is False
        assert status.can_buy is False
        assert status.can_sell is True

    def test_limit_down_main_board(self):
        """测试主板跌停"""
        status = check_limit_status(9.00, 10.00, "600000.SH")
        
        assert status.is_limit_up is False
        assert status.is_limit_down is True
        assert status.can_buy is True
        assert status.can_sell is False

    def test_limit_up_gem(self):
        """测试创业板涨停（±20%）"""
        status = check_limit_status(12.00, 10.00, "300750.SZ")
        
        assert status.is_limit_up is True
        assert status.board_type == "gem"

    def test_limit_down_gem(self):
        """测试创业板跌停"""
        status = check_limit_status(8.00, 10.00, "300750.SZ")
        
        assert status.is_limit_down is True
        assert status.can_sell is False

    def test_limit_up_sci_tech(self):
        """测试科创板涨停"""
        status = check_limit_status(12.00, 10.00, "688981.SH")
        
        assert status.is_limit_up is True
        assert status.board_type == "sci_tech"

    def test_limit_up_st(self):
        """测试ST股涨停（±5%）"""
        status = check_limit_status(10.50, 10.00, "000001.SZ", "ST某某")
        
        assert status.is_limit_up is True
        assert status.board_type == "st"

    def test_limit_down_st(self):
        """测试ST股跌停"""
        status = check_limit_status(9.50, 10.00, "000001.SZ", "ST某某")
        
        assert status.is_limit_down is True

    def test_limit_up_beijing(self):
        """测试北交所涨停（±30%）"""
        status = check_limit_status(13.00, 10.00, "830799.BJ")
        
        assert status.is_limit_up is True
        assert status.board_type == "beijing"

    def test_near_limit_up(self):
        """测试接近涨停但未涨停"""
        status = check_limit_status(10.99, 10.00, "600000.SH")
        
        assert status.is_limit_up is False
        assert status.can_buy is True

    def test_near_limit_down(self):
        """测试接近跌停但未跌停"""
        status = check_limit_status(9.02, 10.00, "600000.SH")
        
        assert status.is_limit_down is False
        assert status.can_sell is True

    def test_invalid_pre_close(self):
        """测试无效前收盘价"""
        status = check_limit_status(10.00, 0, "600000.SH")
        
        assert status.is_limit_up is False
        assert status.is_limit_down is False
        assert status.can_buy is True
        assert status.can_sell is True


class TestCheckLimitStatusDict:
    """测试字典格式返回"""

    def test_returns_dict(self):
        """测试返回字典格式"""
        result = check_limit_status_dict(11.00, 10.00, "600000.SH")
        
        assert isinstance(result, dict)
        assert result["is_limit_up"] is True
        assert result["board_type"] == "main"


class TestValidateTradeAction:
    """测试交易动作验证"""

    def test_buy_normal(self):
        """测试正常买入"""
        result = validate_trade_action("BUY", 10.50, 10.00, "600000.SH")
        
        assert result["allowed"] is True
        assert result["reason"] == ""

    def test_buy_at_limit_up(self):
        """测试涨停买入被阻止"""
        result = validate_trade_action("BUY", 11.00, 10.00, "600000.SH")
        
        assert result["allowed"] is False
        assert "涨停" in result["reason"]

    def test_sell_normal(self):
        """测试正常卖出"""
        result = validate_trade_action("SELL", 9.50, 10.00, "600000.SH")
        
        assert result["allowed"] is True

    def test_sell_at_limit_down(self):
        """测试跌停卖出被阻止"""
        result = validate_trade_action("SELL", 9.00, 10.00, "600000.SH")
        
        assert result["allowed"] is False
        assert "跌停" in result["reason"]

    def test_add_at_limit_up(self):
        """测试涨停加仓被阻止"""
        result = validate_trade_action("ADD", 11.00, 10.00, "600000.SH")
        
        assert result["allowed"] is False


class TestLimitRatioConstants:
    """测试涨跌停比例常量"""

    def test_limit_ratio_exists(self):
        """测试常量存在"""
        assert hasattr(MarketConstants, "LIMIT_RATIO")
        assert len(MarketConstants.LIMIT_RATIO) > 0

    def test_main_board_ratio(self):
        """测试主板比例"""
        up, down = MarketConstants.LIMIT_RATIO["main"]
        assert up == 1.10
        assert down == 0.90

    def test_gem_ratio(self):
        """测试创业板比例"""
        up, down = MarketConstants.LIMIT_RATIO["gem"]
        assert up == 1.20
        assert down == 0.80

    def test_st_ratio(self):
        """测试ST股比例"""
        up, down = MarketConstants.LIMIT_RATIO["st"]
        assert up == 1.05
        assert down == 0.95

    def test_board_prefix_exists(self):
        """测试板块前缀常量存在"""
        assert hasattr(MarketConstants, "BOARD_PREFIX")
        assert "sci_tech" in MarketConstants.BOARD_PREFIX
        assert "gem" in MarketConstants.BOARD_PREFIX
