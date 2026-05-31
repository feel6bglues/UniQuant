from ..shared.market_rules import get_board_rule


def validate_order_price(
    symbol: str,
    price: float,
    direction: str,
    ref_price: float,
    trading_phase: str = "continuous",
) -> bool:
    if trading_phase == "call_auction":
        return True
    rule = get_board_rule(symbol)
    if direction.lower() == "buy":
        return price <= ref_price * (1 + rule.price_collar_pct)
    else:
        return price >= ref_price * (1 - rule.price_collar_pct)


def get_allowable_price_range(
    symbol: str,
    ref_price: float,
    trading_phase: str = "continuous",
):
    if trading_phase == "call_auction":
        return (0, float("inf"))
    rule = get_board_rule(symbol)
    lower = ref_price * (1 - rule.price_collar_pct)
    upper = ref_price * (1 + rule.price_collar_pct)
    return (lower, upper)
