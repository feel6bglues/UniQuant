"""
涨跌停检查模块
A股特有微观结构防御：检查涨停/跌停状态
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .constants import MarketConstants
from .logger_factory import get_logger

logger = get_logger(__name__)


@dataclass
class LimitStatus:
    """涨跌停状态"""
    is_limit_up: bool
    is_limit_down: bool
    can_buy: bool
    can_sell: bool
    board_type: str
    up_limit_price: float
    down_limit_price: float
    price_ratio: float


def get_board_type(symbol: str, name: Optional[str] = None) -> str:
    """
    根据股票代码和名称识别板块类型
    
    Args:
        symbol: 股票代码（如 "000001.SZ"）
        name: 股票名称（可选，用于识别ST股）
    
    Returns:
        str: 板块类型 ("main", "sci_tech", "gem", "st", "beijing")
    """
    if not symbol:
        return "main"
    
    code = symbol.split(".")[0] if "." in symbol else symbol
    
    # 检查ST股（优先级最高）
    if name:
        name_upper = name.upper()
        for st_prefix in MarketConstants.BOARD_PREFIX["st"]:
            if name_upper.startswith(st_prefix):
                return "st"
    
    # 检查科创板
    for prefix in MarketConstants.BOARD_PREFIX["sci_tech"]:
        if code.startswith(prefix):
            return "sci_tech"
    
    # 检查创业板
    for prefix in MarketConstants.BOARD_PREFIX["gem"]:
        if code.startswith(prefix):
            return "gem"
    
    # 检查北交所
    for prefix in MarketConstants.BOARD_PREFIX["beijing"]:
        if code.startswith(prefix):
            return "beijing"
    
    return "main"


def _round_limit_price(price: float, tick_size: float = 0.01) -> float:
    return round(price / tick_size) * tick_size


def check_limit_status(
    current_price: float,
    pre_close: float,
    symbol: str = "",
    name: Optional[str] = None,
    board_type: Optional[str] = None,
    trading_days_listed: int = 0,
) -> LimitStatus:
    """
    检查涨跌停状态
    
    Args:
        current_price: 当前价格
        pre_close: 前收盘价
        symbol: 股票代码
        name: 股票名称（可选）
        board_type: 板块类型（可选，自动识别）
        trading_days_listed: 上市以来的交易日数（0=非IPO，>0=IPO期间）
    
    Returns:
        LimitStatus: 涨跌停状态对象
    """
    if pre_close <= 0:
        logger.warning(f"Invalid pre_close: {pre_close}, symbol: {symbol}")
        return LimitStatus(
            is_limit_up=False,
            is_limit_down=False,
            can_buy=True,
            can_sell=True,
            board_type="main",
            up_limit_price=0.0,
            down_limit_price=0.0,
            price_ratio=1.0,
        )
    
    # 自动识别板块类型
    if board_type is None:
        board_type = get_board_type(symbol, name)
    
    # IPO涨跌停规则
    if trading_days_listed > 0:
        if board_type in ("sci_tech", "gem"):
            if trading_days_listed <= 5:
                # 科创板/创业板前5个交易日无涨跌停限制
                return LimitStatus(
                    is_limit_up=False, is_limit_down=False,
                    can_buy=True, can_sell=True,
                    board_type=board_type,
                    up_limit_price=float('inf'), down_limit_price=0.0,
                    price_ratio=current_price / pre_close if pre_close > 0 else 1.0,
                )
        elif board_type == "beijing":
            if trading_days_listed <= 1:
                # 北交所首个交易日无涨跌停限制
                return LimitStatus(
                    is_limit_up=False, is_limit_down=False,
                    can_buy=True, can_sell=True,
                    board_type=board_type,
                    up_limit_price=float('inf'), down_limit_price=0.0,
                    price_ratio=current_price / pre_close if pre_close > 0 else 1.0,
                )
        else:
            # 主板IPO首日: +44%/-36%
            if trading_days_listed == 1:
                up_limit_ratio = 1.44
                down_limit_ratio = 0.64
                price_tick = 0.01 if pre_close >= 1.0 else 0.001
                up_limit_price = _round_limit_price(pre_close * up_limit_ratio, price_tick)
                down_limit_price = _round_limit_price(pre_close * down_limit_ratio, price_tick)
                price_ratio = current_price / pre_close
                tolerance = MarketConstants.PRICE_TOLERANCE
                return LimitStatus(
                    is_limit_up=price_ratio >= up_limit_ratio - tolerance,
                    is_limit_down=price_ratio <= down_limit_ratio + tolerance,
                    can_buy=price_ratio < up_limit_ratio - tolerance,
                    can_sell=price_ratio > down_limit_ratio + tolerance,
                    board_type=board_type,
                    up_limit_price=up_limit_price,
                    down_limit_price=down_limit_price,
                    price_ratio=price_ratio,
                )
    
    # 获取涨跌停比例
    limit_ratios = MarketConstants.LIMIT_RATIO.get(board_type, MarketConstants.LIMIT_RATIO["main"])
    up_limit_ratio, down_limit_ratio = limit_ratios
    
    # 计算涨跌停价格
    price_tick = 0.01 if pre_close >= 1.0 else 0.001
    up_limit_price = _round_limit_price(pre_close * up_limit_ratio, price_tick)
    down_limit_price = _round_limit_price(pre_close * down_limit_ratio, price_tick)

    # 计算当前价格比例
    price_ratio = current_price / pre_close

    # 判断涨跌停状态（使用比例 + 舍入价格双重保障）
    tolerance = MarketConstants.PRICE_TOLERANCE
    is_limit_up = price_ratio >= up_limit_ratio - tolerance
    is_limit_down = price_ratio <= down_limit_ratio + tolerance

    # 判断是否可以买卖
    can_buy = not is_limit_up
    can_sell = not is_limit_down

    return LimitStatus(
        is_limit_up=is_limit_up,
        is_limit_down=is_limit_down,
        can_buy=can_buy,
        can_sell=can_sell,
        board_type=board_type,
        up_limit_price=up_limit_price,
        down_limit_price=down_limit_price,
        price_ratio=round(price_ratio, 4),
    )


def check_limit_status_dict(
    current_price: float,
    pre_close: float,
    symbol: str = "",
    name: Optional[str] = None,
    board_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    检查涨跌停状态（返回字典格式，兼容旧代码）
    
    Args:
        current_price: 当前价格
        pre_close: 前收盘价
        symbol: 股票代码
        name: 股票名称（可选）
        board_type: 板块类型（可选）
    
    Returns:
        Dict[str, Any]: 涨跌停状态字典
    """
    status = check_limit_status(current_price, pre_close, symbol, name, board_type)
    return {
        "is_limit_up": status.is_limit_up,
        "is_limit_down": status.is_limit_down,
        "can_buy": status.can_buy,
        "can_sell": status.can_sell,
        "board_type": status.board_type,
        "up_limit_price": status.up_limit_price,
        "down_limit_price": status.down_limit_price,
        "price_ratio": status.price_ratio,
    }


def validate_trade_action(
    action: str,
    current_price: float,
    pre_close: float,
    symbol: str = "",
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    验证交易动作是否可行
    
    Args:
        action: 交易动作 ("BUY", "SELL", "ADD")
        current_price: 当前价格
        pre_close: 前收盘价
        symbol: 股票代码
        name: 股票名称
    
    Returns:
        Dict: 验证结果
    """
    status = check_limit_status(current_price, pre_close, symbol, name)
    
    result = {
        "action": action,
        "allowed": True,
        "reason": "",
        "limit_status": status,
    }
    
    action_upper = action.upper()
    
    if action_upper in ["BUY", "ADD"]:
        if status.is_limit_up:
            result["allowed"] = False
            result["reason"] = f"涨停无法买入，当前价格比例: {status.price_ratio:.2%}"
    
    elif action_upper == "SELL":
        if status.is_limit_down:
            result["allowed"] = False
            result["reason"] = f"跌停无法卖出，当前价格比例: {status.price_ratio:.2%}"
    
    return result


def is_limit_up(
    current: Dict[str, Any],
    pre_close: float,
    symbol: str = "",
    is_st: bool = False,
) -> bool:
    """兼容接口：判断是否涨停

    Args:
        current: 包含 'close' 键的字典
        pre_close: 前收盘价
        symbol: 股票代码
        is_st: 是否 ST 股

    Returns:
        是否涨停
    """
    close_price = float(current.get("close", 0))
    name = "ST" if is_st else None
    status = check_limit_status(close_price, pre_close, symbol, name)
    return status.is_limit_up


def is_limit_down(
    current: Dict[str, Any],
    pre_close: float,
    symbol: str = "",
    is_st: bool = False,
) -> bool:
    """兼容接口：判断是否跌停

    Args:
        current: 包含 'close' 键的字典
        pre_close: 前收盘价
        symbol: 股票代码
        is_st: 是否 ST 股

    Returns:
        是否跌停
    """
    close_price = float(current.get("close", 0))
    name = "ST" if is_st else None
    status = check_limit_status(close_price, pre_close, symbol, name)
    return status.is_limit_down
