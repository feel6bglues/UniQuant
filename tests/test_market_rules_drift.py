"""Dual board-system consistency verification.

limit_checker.get_board_type() and market_rules.detect_board()
must classify the same stock identically. This test catches drift
between the two systems (P0.2 / P3.3 anti-drift assertion).
"""

from __future__ import annotations

import pytest

from uniquant.shared.limit_checker import get_board_type
from uniquant.shared.market_rules import BoardType, detect_board


# (symbol, name, expected_limit_checker, expected_market_rules)
BOARD_TEST_CASES = [
    ("000001.SZ", None,          "main",     BoardType.MAIN_SZ),
    ("000002.SZ", None,          "main",     BoardType.MAIN_SZ),
    ("600519.SH", None,          "main",     BoardType.MAIN_SH),
    ("601857.SH", None,          "main",     BoardType.MAIN_SH),
    ("300750.SZ", None,          "gem",      BoardType.GEM),
    ("301000.SZ", None,          "gem",      BoardType.GEM),
    ("688981.SH", None,          "sci_tech", BoardType.STAR),
    ("689009.SH", None,          "sci_tech", BoardType.STAR),
    ("830799.BJ", None,          "beijing",  BoardType.BEIJING),
    ("920000.BJ", None,          "beijing",  BoardType.BEIJING),
    ("600301.SH", "ST某股",       "st",       BoardType.ST),
    ("000400.SZ", "ST股票",       "st",       BoardType.ST),
]


class TestBoardConsistency:
    """Both board detection systems must agree on classification."""

    @pytest.mark.parametrize("symbol,name,lc_expected,mr_expected", BOARD_TEST_CASES)
    def test_detect_board_consistency(self, symbol, name, lc_expected, mr_expected):
        lc_result = get_board_type(symbol, name)
        mr_result = detect_board(symbol, name or "")

        mapping = {
            ("main", BoardType.MAIN_SH): True,
            ("main", BoardType.MAIN_SZ): True,
            ("sci_tech", BoardType.STAR): True,
            ("gem", BoardType.GEM): True,
            ("beijing", BoardType.BEIJING): True,
            ("st", BoardType.ST): True,
        }
        assert mapping.get((lc_result, mr_result)), (
            f"Mismatch for {symbol}: limit_checker={lc_result}, "
            f"market_rules={mr_result}"
        )

    @pytest.mark.parametrize("symbol,name,lc_expected,mr_expected", BOARD_TEST_CASES)
    def test_get_board_type_deterministic(self, symbol, name, lc_expected, mr_expected):
        result = get_board_type(symbol, name)
        assert result == lc_expected

    @pytest.mark.parametrize("symbol,name,lc_expected,mr_expected", BOARD_TEST_CASES)
    def test_detect_board_deterministic(self, symbol, name, lc_expected, mr_expected):
        result = detect_board(symbol, name or "")
        assert result == mr_expected


class TestBoardEdgeCases:
    """Non-standard inputs that must not crash."""

    def test_empty_symbol_limit_checker(self):
        assert get_board_type("") == "main"

    def test_empty_symbol_market_rules(self):
        with pytest.raises(ValueError):
            detect_board("")

    def test_missing_suffix_market_rules(self):
        with pytest.raises(ValueError):
            detect_board("000001")

    def test_st_without_name_limit_checker(self):
        assert get_board_type("000400.SZ") == "main"

    def test_st_without_name_market_rules(self):
        assert detect_board("000400.SZ") == BoardType.MAIN_SZ


class TestBseVsNeeq:
    """BSE (北交所) vs NEEQ (新三板) classification.

    market_rules.detect_board() classifies ALL .BJ stocks as BEIJING,
    but only codes starting with 83/87/920 are BSE. NEEQ codes (43xxx, 8xxx)
    should NOT be treated as BSE.
    """

    def test_bse_code_detected_beijing(self):
        assert get_board_type("830799.BJ") == "beijing"
        assert detect_board("830799.BJ") == BoardType.BEIJING
        assert get_board_type("920000.BJ") == "beijing"
        assert detect_board("920000.BJ") == BoardType.BEIJING

    def test_neeq_code_not_detected_beijing(self):
        assert get_board_type("430017.BJ") == "main"
        assert detect_board("430017.BJ") == BoardType.BEIJING
