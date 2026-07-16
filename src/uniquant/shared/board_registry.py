"""
Unified board type registry — single source of truth for A-share board detection.

Consolidates two parallel systems:
- limit_checker.get_board_type()  → string  ('main'/'sci_tech'/'gem'/'beijing'/'st')
- market_rules.detect_board()     → BoardType enum

The two APIs intentionally diverge on edge cases:
- get_board_type is prefix-based (ignores exchange suffix)
- detect_board is exchange-suffix-based (raises ValueError for bare codes)
"""

from enum import Enum, auto
from typing import Optional


class BoardType(Enum):
    MAIN_SH = auto()
    MAIN_SZ = auto()
    GEM = auto()
    STAR = auto()
    BEIJING = auto()
    ST = auto()


# Canonical code-prefix → BoardType mapping (used by both APIs)
_CODE_PREFIX_MAP: dict[tuple[str, ...], BoardType] = {
    ("83", "87", "920"): BoardType.BEIJING,
    ("300", "301", "302"): BoardType.GEM,
    ("688", "689"): BoardType.STAR,
}

# Name-based ST prefixes (limit_checker compat)
_ST_NAME_PREFIXES = ("ST", "*ST")

STRING_BOARD_MAP: dict[BoardType, str] = {
    BoardType.ST: "st",
    BoardType.STAR: "sci_tech",
    BoardType.GEM: "gem",
    BoardType.BEIJING: "beijing",
    BoardType.MAIN_SH: "main",
    BoardType.MAIN_SZ: "main",
}


def _extract_code(symbol: str) -> str:
    return symbol.split(".")[0] if "." in symbol else symbol


def _get_exchange(symbol: str) -> Optional[str]:
    if "." in symbol:
        return symbol.split(".")[1].upper()
    return None


class BoardTypeRegistry:
    """Unified board type registry.

    Exposes both APIs:
    - get_board_type(symbol, name) → str     (limit_checker compat)
    - detect_board(symbol, name)   → BoardType  (market_rules compat)
    """

    def get_board_type(self, symbol: str, name: Optional[str] = None) -> str:
        """Prefix-based detection (ignores exchange suffix).

        Returns 'main' for empty/missing symbols.
        """
        if not symbol:
            return "main"
        code = _extract_code(symbol)
        if name:
            if any(name.upper().startswith(p) for p in _ST_NAME_PREFIXES):
                return "st"
        for prefixes, board_type in _CODE_PREFIX_MAP.items():
            if code.startswith(prefixes):
                return STRING_BOARD_MAP[board_type]
        return "main"

    def detect_board(self, symbol: str, name: Optional[str] = None) -> BoardType:
        """Exchange-suffix-based detection.

        Raises ValueError for empty symbols or bare codes without .SH/.SZ/.BJ.
        """
        if not symbol:
            raise ValueError(f"Cannot detect board for {symbol!r}: empty symbol")
        code = _extract_code(symbol)
        exchange = _get_exchange(symbol)

        # ST check (market_rules compat: "ST" anywhere in name)
        if name and "ST" in name.upper():
            return BoardType.ST

        if exchange == "BJ":
            return BoardType.BEIJING
        if exchange == "SH":
            if code.startswith(("688", "689")):
                return BoardType.STAR
            return BoardType.MAIN_SH
        if exchange == "SZ":
            if code.startswith(("300", "301", "302")):
                return BoardType.GEM
            return BoardType.MAIN_SZ

        raise ValueError(f"Cannot detect board for {symbol!r}: unknown exchange suffix")


# Module-level convenience singleton
_registry = BoardTypeRegistry()


def get_board_type(symbol: str, name: Optional[str] = None) -> str:
    return _registry.get_board_type(symbol, name)


def detect_board(symbol: str, name: str = "") -> BoardType:
    return _registry.detect_board(symbol, name)