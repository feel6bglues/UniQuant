"""Unit tests for uniquant.services.stock_query_service.

Covers symbol->name mapping (direct/suffix/base/source), ETF scanning,
market classification and error fallbacks. All fetchers are in-memory
stubs; no network or ``data/`` access.
"""

import pytest

from uniquant.services.stock_query_service import StockQueryService


class _Fetcher:
    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else {}
        self.error = error

    def fetch_stock_info(self):
        if self.error is not None:
            raise self.error
        return self.payload


# --------------------------------------------------------------------------
# properties / refresh_stock_map
# --------------------------------------------------------------------------

def test_properties_return_internal_state():
    service = StockQueryService()
    service._stock_map = {"600519.SH": "贵州茅台"}
    service._etf_list = ["510300"]

    assert service.stock_map == {"600519.SH": "贵州茅台"}
    assert service.etf_list == ["510300"]


def test_refresh_stock_map_without_fetcher_returns_existing():
    service = StockQueryService(fetcher=None)
    service._stock_map = {"A": "B"}
    assert service.refresh_stock_map() == {"A": "B"}


def test_refresh_stock_map_populates_from_fetcher():
    service = StockQueryService(fetcher=_Fetcher({"600519.SH": "贵州茅台"}))
    result = service.refresh_stock_map()

    assert result == {"600519.SH": "贵州茅台"}
    assert service.stock_map == {"600519.SH": "贵州茅台"}


def test_refresh_stock_map_error_resets_to_empty():
    service = StockQueryService(fetcher=_Fetcher(error=ValueError("down")))
    service._stock_map = {"stale": "value"}

    assert service.refresh_stock_map() == {}
    assert service.stock_map == {}


# --------------------------------------------------------------------------
# get_stock_name
# --------------------------------------------------------------------------

def test_get_stock_name_direct_hit():
    service = StockQueryService()
    service._stock_map = {"600519.SH": "贵州茅台"}
    assert service.get_stock_name("600519.SH") == "贵州茅台"


def test_get_stock_name_refreshes_empty_map():
    service = StockQueryService(fetcher=_Fetcher({"000001.SZ": "平安银行"}))
    assert service.get_stock_name("000001.SZ") == "平安银行"


def test_get_stock_name_sz_suffix_lookup():
    service = StockQueryService()
    service._stock_map = {"000001.SZ": "平安银行"}
    assert service.get_stock_name("000001") == "平安银行"


def test_get_stock_name_sh_suffix_lookup():
    service = StockQueryService()
    service._stock_map = {"600519.SH": "贵州茅台"}
    assert service.get_stock_name("600519") == "贵州茅台"


def test_get_stock_name_uses_base_symbol_for_dotted_code():
    service = StockQueryService()
    service._stock_map = {"000001": "平安银行"}
    assert service.get_stock_name("000001.SZ") == "平安银行"


def test_get_stock_name_falls_back_to_source():
    service = StockQueryService(fetcher=_Fetcher({"999999": "SomeName"}))
    service._stock_map = {"dummy": "dummy"}
    assert service.get_stock_name("999999") == "SomeName"
    assert service.stock_map["999999"] == "SomeName"


# --------------------------------------------------------------------------
# _get_with_suffix
# --------------------------------------------------------------------------

def test_get_with_suffix_sz_and_sh():
    service = StockQueryService()
    service._stock_map = {"000001.SZ": "平安", "600519.SH": "茅台"}
    assert service._get_with_suffix("000001") == "平安"
    assert service._get_with_suffix("600519") == "茅台"


def test_get_with_suffix_no_match_returns_none():
    service = StockQueryService()
    service._stock_map = {"000001.SZ": "平安"}
    assert service._get_with_suffix("999999") is None
    assert service._get_with_suffix("000002") is None


# --------------------------------------------------------------------------
# _get_from_source
# --------------------------------------------------------------------------

def test_get_from_source_without_fetcher_returns_symbol():
    service = StockQueryService(fetcher=None)
    assert service._get_from_source("600519") == "600519"


def test_get_from_source_direct_hit_caches_symbol():
    service = StockQueryService(fetcher=_Fetcher({"600519": "贵州茅台"}))
    assert service._get_from_source("600519") == "贵州茅台"
    assert service.stock_map["600519"] == "贵州茅台"


def test_get_from_source_sh_suffix_lookup():
    service = StockQueryService(fetcher=_Fetcher({"600519.SH": "贵州茅台"}))
    assert service._get_from_source("600519") == "贵州茅台"
    assert service.stock_map["600519"] == "贵州茅台"


def test_get_from_source_sz_suffix_lookup():
    service = StockQueryService(fetcher=_Fetcher({"000002.SZ": "万科A"}))
    assert service._get_from_source("000002") == "万科A"
    assert service.stock_map["000002"] == "万科A"


def test_get_from_source_not_found_returns_symbol():
    service = StockQueryService(fetcher=_Fetcher({"600519.SH": "贵州茅台"}))
    assert service._get_from_source("999999") == "999999"


def test_get_from_source_error_returns_symbol():
    service = StockQueryService(fetcher=_Fetcher(error=ValueError("boom")))
    assert service._get_from_source("600519") == "600519"


# --------------------------------------------------------------------------
# scan_etfs
# --------------------------------------------------------------------------

def test_scan_etfs_without_fetcher_returns_existing():
    service = StockQueryService(fetcher=None)
    service._etf_list = ["510300"]
    assert service.scan_etfs() == ["510300"]


def test_scan_etfs_filters_51_prefix():
    service = StockQueryService(
        fetcher=_Fetcher({"510300": "沪深300ETF", "159915": "创业板", "600000": "浦发"})
    )
    result = service.scan_etfs()

    assert result == ["510300"]
    assert service.etf_list == ["510300"]


def test_scan_etfs_error_returns_empty():
    service = StockQueryService(fetcher=_Fetcher(error=ValueError("down")))
    assert service.scan_etfs() == []


# --------------------------------------------------------------------------
# get_stock_info
# --------------------------------------------------------------------------

def test_get_stock_info_without_fetcher_returns_cached():
    service = StockQueryService(fetcher=None)
    service._stock_map = {"A": "B"}
    assert service.get_stock_info() == {"A": "B"}


def test_get_stock_info_from_fetcher():
    service = StockQueryService(fetcher=_Fetcher({"600519.SH": "贵州茅台"}))
    assert service.get_stock_info() == {"600519.SH": "贵州茅台"}


def test_get_stock_info_error_returns_cached():
    service = StockQueryService(fetcher=_Fetcher(error=ValueError("down")))
    service._stock_map = {"cached": "yes"}
    assert service.get_stock_info() == {"cached": "yes"}


# --------------------------------------------------------------------------
# is_etf / get_market
# --------------------------------------------------------------------------

def test_is_etf_by_prefix_and_list():
    service = StockQueryService()
    service._etf_list = ["510500"]
    assert service.is_etf("510300") is True
    assert service.is_etf("510500") is True
    assert service.is_etf("600000") is False


@pytest.mark.parametrize(
    "symbol, expected",
    [
        ("600519.SH", "SH"),
        ("000001.SZ", "SZ"),
        ("600519", "SH"),
        ("000001", "SZ"),
        ("002001", "SZ"),
        ("300750", "SZ"),
        ("430047", "UNKNOWN"),
    ],
)
def test_get_market_classification(symbol, expected):
    service = StockQueryService()
    assert service.get_market(symbol) == expected
