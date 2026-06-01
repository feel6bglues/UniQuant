from enum import Enum, auto
from dataclasses import dataclass


class BoardType(Enum):
    MAIN_SH = auto()
    MAIN_SZ = auto()
    GEM = auto()
    STAR = auto()
    BEIJING = auto()
    ST = auto()


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


def detect_board(symbol: str, name: str = "") -> BoardType:
    if name and ("ST" in name.upper()):
        return BoardType.ST
    upper = symbol.upper()
    if upper.endswith(".BJ"):
        return BoardType.BEIJING
    if upper.endswith(".SH"):
        code = upper.replace(".SH", "")
        if code.startswith(("688", "689")):
            return BoardType.STAR
        return BoardType.MAIN_SH
    if upper.endswith(".SZ"):
        code = upper.replace(".SZ", "")
        if code.startswith(("300", "301", "302")):
            return BoardType.GEM
        return BoardType.MAIN_SZ
    raise ValueError(f"Cannot detect board for {symbol!r}: unknown exchange suffix")


def get_board_rule(symbol: str) -> BoardRule:
    return BOARD_RULES[detect_board(symbol)]


def round_lot(shares: int, is_sell: bool = False, ceil: bool = False, symbol: str = "000001.SZ") -> int:
    rule = get_board_rule(symbol)
    return rule.round_lot(shares, is_sell=is_sell, ceil=ceil)
