from dataclasses import dataclass

from .board_registry import BoardType, detect_board


@dataclass
class BoardRule:
    lot_size: int
    price_limit_pct: float
    price_collar_pct: float = 0.02

    def round_lot(self, shares: int, is_sell: bool = False, ceil: bool = False) -> int:
        if is_sell:
            return max(shares, 0)
        if ceil and shares > 0:
            return ((shares + self.lot_size - 1) // self.lot_size) * self.lot_size
        return (shares // self.lot_size) * self.lot_size


BOARD_RULES = {
    BoardType.MAIN_SH: BoardRule(lot_size=100, price_limit_pct=0.10, price_collar_pct=0.02),
    BoardType.MAIN_SZ: BoardRule(lot_size=100, price_limit_pct=0.10, price_collar_pct=0.02),
    BoardType.GEM:     BoardRule(lot_size=100, price_limit_pct=0.20, price_collar_pct=0.02),
    BoardType.STAR:    BoardRule(lot_size=200, price_limit_pct=0.20, price_collar_pct=0.02),
    BoardType.BEIJING: BoardRule(lot_size=100, price_limit_pct=0.30, price_collar_pct=0.05),
    BoardType.ST:      BoardRule(lot_size=100, price_limit_pct=0.05, price_collar_pct=0.01),
}


# Delegated to BoardTypeRegistry in board_registry.py
# (consolidated from the former parallel system with limit_checker.get_board_type())


def get_board_rule(symbol: str) -> BoardRule:
    return BOARD_RULES[detect_board(symbol)]


def round_lot(shares: int, is_sell: bool = False, ceil: bool = False, symbol: str = "000001.SZ") -> int:
    rule = get_board_rule(symbol)
    return rule.round_lot(shares, is_sell=is_sell, ceil=ceil)
