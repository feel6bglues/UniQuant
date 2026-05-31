import pandas as pd

from uniquant.services.data_service import DataService
from uniquant.services.stock_query_service import StockQueryService


def test_stock_query_refresh_stock_map_falls_back_to_empty_on_value_error():
    class DummyFetcher:
        def fetch_stock_info(self):
            raise ValueError("source failed")

    service = StockQueryService(fetcher=DummyFetcher())

    result = service.refresh_stock_map()

    assert result == {}


def test_stock_query_get_stock_name_returns_symbol_on_source_error():
    class DummyFetcher:
        def fetch_stock_info(self):
            raise ValueError("source failed")

    service = StockQueryService(fetcher=DummyFetcher())

    result = service.get_stock_name("000001.SZ")

    assert result == "000001.SZ"


def test_data_service_load_data_with_fallback_returns_empty_on_lake_error():
    service = DataService()

    class DummyLake:
        def read_data(self, symbol, data_type="stock", market="cn"):
            raise ValueError("lake failed")

        def write_data(self, *args, **kwargs):
            raise AssertionError("should not write on failure")

    service.lake = DummyLake()
    service.fetcher.get_price = lambda symbol, adjust="qfq": None

    result = service._load_data_with_fallback("000001.SZ", "stock", "stock data")

    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_data_service_load_etf_data_returns_empty_on_fetch_error():
    service = DataService()

    class DummyLake:
        def read_data(self, symbol, data_type="stock", market="cn"):
            return pd.DataFrame()

        def write_data(self, *args, **kwargs):
            raise AssertionError("should not write on failure")

    class DummyFetcher:
        def get_price(self, symbol):
            raise ValueError("fetch failed")

    service.lake = DummyLake()
    service.fetcher = DummyFetcher()

    result = service._load_etf_data()

    assert isinstance(result, pd.DataFrame)
    assert result.empty
