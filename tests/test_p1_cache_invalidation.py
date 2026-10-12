from __future__ import annotations

from collections import OrderedDict

import pandas as pd

from uniquant.data.data_fetcher import DataFetcher
from uniquant.services.data_service import DataService
from uniquant.services.market_cache import MarketLevelCache


def _sample_df(close: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"]),
            "open": [close],
            "high": [close + 0.1],
            "low": [close - 0.1],
            "close": [close],
            "volume": [1000],
        }
    )


class _DummyFetcher:
    def __init__(self) -> None:
        self.cleared_before_fetch = False
        self.clear_calls = []
        self.get_price_calls = []

    def clear_price_cache(self, symbol=None, adjust=None):
        self.clear_calls.append((symbol, adjust))
        self.cleared_before_fetch = True
        return 1

    def get_price(self, symbol: str, adjust: str = ""):
        assert self.cleared_before_fetch, "stale price cache was not invalidated before fetch"
        self.get_price_calls.append((symbol, adjust))
        return _sample_df()


class _DummyStorage:
    base_dir = "."

    def __init__(self) -> None:
        self.writes = []
        self.reads = []

    def read_data(self, symbol, data_type="stock", market="cn"):
        # Step3 (§8 #16): rebuild_cache stock 分支直读湖, 不再走源取数
        self.reads.append((symbol, data_type, market))
        return _sample_df()

    def write_data(self, symbol, df, data_type, market="cn", overwrite=False):
        self.writes.append((symbol, data_type, market, overwrite, df.copy()))


class _DummyCleaner:
    def clean_stock_daily(self, df):
        return df.copy()


def test_data_fetcher_can_clear_symbol_price_cache_without_full_clear():
    fetcher = object.__new__(DataFetcher)
    fetcher._price_cache = OrderedDict(
        {
            ("600000.SH", ""): _sample_df(10.0),
            ("600000.SH", "qfq"): _sample_df(10.1),
            ("000001.SZ", ""): _sample_df(20.0),
        }
    )

    removed = fetcher.clear_price_cache("600000.SH")

    assert removed == 2
    assert ("600000.SH", "") not in fetcher._price_cache
    assert ("600000.SH", "qfq") not in fetcher._price_cache
    assert ("000001.SZ", "") in fetcher._price_cache


def test_rebuild_cache_invalidates_fetcher_cache_before_fetch():
    fetcher = _DummyFetcher()
    storage = _DummyStorage()
    service = DataService(
        fetcher=fetcher,
        storage_manager=storage,
        cleaner=_DummyCleaner(),
    )

    assert service.rebuild_cache("600000.SH", data_type="stock") is True

    # Step3 (§8 #16): 写湖回填前先失效 fetcher 缓存, 再直读湖 (不走源取数)
    assert fetcher.clear_calls[0] == ("600000.SH", None)
    assert storage.reads == [("600000.SH", "stock", "cn")]
    assert fetcher.get_price_calls == []
    assert storage.writes[0][0] == "600000.SH"


def test_rebuild_index_cache_clears_market_level_cache():
    fetcher = _DummyFetcher()
    storage = _DummyStorage()
    market_cache = MarketLevelCache()
    market_cache.set_regime("NORMAL", {"entropy": 0.1})
    market_cache.set_ntf({"side": "SUPPORT", "intensity": 0.7})
    market_cache.set_benchmark(_sample_df())

    service = DataService(
        fetcher=fetcher,
        storage_manager=storage,
        cleaner=_DummyCleaner(),
    )
    service.attach_market_cache(market_cache)

    assert service.rebuild_cache("000300.SH", data_type="index") is True

    status = market_cache.status()
    assert status["has_regime"] is False
    assert status["has_ntf"] is False
    assert status["has_benchmark"] is False

    # Step3 (§8 #17): index 分支保持显式 adjust=""
    assert fetcher.get_price_calls == [("000300.SH", "")]
