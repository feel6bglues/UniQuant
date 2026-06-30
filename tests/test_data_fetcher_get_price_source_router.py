from unittest.mock import MagicMock, PropertyMock
import pandas as pd
import pytest


class TestDataFetcherGetPriceUsesOwnSourceRouter:
    def test_get_price_works_when_ingestion_is_broken(self):
        from uniquant.data.data_fetcher import DataFetcher

        fetcher = DataFetcher(data_dir="/tmp/test_df_get_price")

        mock_df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "open": [10.0, 11.0],
            "high": [12.0, 13.0],
            "low": [9.0, 10.0],
            "close": [11.0, 12.0],
            "volume": [1000, 2000],
        })
        fetcher.source_router.fetch_with_fallback = MagicMock(return_value=mock_df)

        fetcher.ingestion.fetch_price = MagicMock(side_effect=Exception("ingestion broken"))

        result = fetcher.get_price("000001.SZ")

        assert not result.empty
        assert len(result) == 2
        fetcher.source_router.fetch_with_fallback.assert_called_once_with("000001.SZ", "fetch")

    def test_get_price_returns_same_data_as_ingestion_path(self):
        from uniquant.data.data_fetcher import DataFetcher

        fetcher = DataFetcher(data_dir="/tmp/test_df_get_price_same")

        raw_df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "open": [10.0, 11.0],
            "high": [12.0, 13.0],
            "low": [9.0, 10.0],
            "close": [11.0, 12.0],
            "volume": [1000, 2000],
        })
        fetcher.source_router.fetch_with_fallback = MagicMock(return_value=raw_df.copy())

        result = fetcher.get_price("000001.SZ", adjust="qfq")

        assert not result.empty
        assert result["close"].iloc[0] == 11.0
        assert result["close"].iloc[1] == 12.0

    def test_get_price_returns_empty_when_no_data(self):
        from uniquant.data.data_fetcher import DataFetcher

        fetcher = DataFetcher(data_dir="/tmp/test_df_get_price_empty")

        fetcher.source_router.fetch_with_fallback = MagicMock(return_value=pd.DataFrame())

        result = fetcher.get_price("000001.SZ")

        assert result.empty

    def test_get_price_returns_empty_when_exception(self):
        from uniquant.data.data_fetcher import DataFetcher

        fetcher = DataFetcher(data_dir="/tmp/test_df_get_price_exc")

        fetcher.source_router.fetch_with_fallback = MagicMock(side_effect=RuntimeError("network failure"))

        result = fetcher.get_price("000001.SZ")

        assert result.empty
