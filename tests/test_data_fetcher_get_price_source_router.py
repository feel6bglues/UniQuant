"""get_price 湖优先契约 (Step3 WS-A).

旧语义 (作废): get_price 走 source_router.fetch_with_fallback — 该调用位置参数
误传恒 TypeError, 被 except 吞掉后恒返回空表 (预注册裁决 D1)。

新语义: 湖优先单源 — StorageManager.read_data -> MootdxLocalSource 本地兜底 ->
仍缺失返回空表 (不 raise)。
"""

from unittest.mock import MagicMock, patch

import pandas as pd


def _write_min_all_stock_codes(data_dir) -> None:
    """Step4 (D5 R-5): DataFetcher 构造触发 StorageManager 主数据硬失败 → 提供最小主数据表。"""
    from pathlib import Path
    import pandas as pd

    path = Path(data_dir) / "all_stock_codes.csv"
    if not path.exists():
        pd.DataFrame({
            "code": ["sh.600000"], "name": ["浦发银行"], "代码": ["600000"],
            "ipoDate": ["1999-11-10"], "outDate": [""], "type": ["1"], "status": ["1"],
        }).to_csv(path, index=False, encoding="utf-8-sig")


from uniquant.data.data_fetcher import GET_PRICE_LAKE_COLUMNS, DataFetcher  # noqa: E402

SYMBOL = "000001.SZ"


def _raw_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "open": [10.0, 11.0],
            "high": [12.0, 13.0],
            "low": [9.0, 10.0],
            "close": [11.0, 12.0],
            "amount": [11000.0, 12000.0],
            "volume": [1000, 2000],
            "reserved": [0, 0],
            "code": [SYMBOL, SYMBOL],
        }
    )


class TestDataFetcherGetPriceLakeFirstRouter:
    def test_get_price_reads_from_lake(self, tmp_path):
        _write_min_all_stock_codes(tmp_path)
        fetcher = DataFetcher(data_dir=str(tmp_path))
        fetcher.storage_manager.write_data(SYMBOL, _raw_df(), data_type="daily")
        fetcher.clear_price_cache()

        spy_read_data = MagicMock(wraps=fetcher.storage_manager.read_data)
        fetcher.storage_manager.read_data = spy_read_data
        spy_fallback = MagicMock()
        fetcher.source_router.fetch_with_fallback = spy_fallback

        result = fetcher.get_price(SYMBOL)

        assert not result.empty
        assert len(result) == 2
        assert list(result.columns) == GET_PRICE_LAKE_COLUMNS
        spy_read_data.assert_called_with(SYMBOL, "daily")
        spy_fallback.assert_not_called()

    def test_get_price_falls_back_to_local_source_on_lake_miss(self, tmp_path):
        with patch("uniquant.data.data_fetcher.MootdxLocalSource") as local_cls:
            local_cls.return_value.fetch_daily.return_value = _raw_df()
            # 构造须在 patch 内: DataFetcher __init__ 即挂载本地源
            _write_min_all_stock_codes(tmp_path)
            fetcher = DataFetcher(data_dir=str(tmp_path))
            result = fetcher.get_price(SYMBOL)

        local_cls.return_value.fetch_daily.assert_called_once()
        assert local_cls.return_value.fetch_daily.call_args[0][0] == SYMBOL
        assert not result.empty
        assert len(result) == 2

    def test_get_price_returns_empty_without_router_on_double_miss(self, tmp_path):
        with patch("uniquant.data.data_fetcher.MootdxLocalSource") as local_cls:
            local_cls.return_value.fetch_daily.return_value = pd.DataFrame()
            _write_min_all_stock_codes(tmp_path)
            fetcher = DataFetcher(data_dir=str(tmp_path))
            spy_fallback = MagicMock(
                side_effect=AssertionError("get_price 不得走 source_router 爬虫链")
            )
            fetcher.source_router.fetch_with_fallback = spy_fallback
            fetcher.source_router.fetch_data = spy_fallback

            result = fetcher.get_price(SYMBOL)

        assert result.empty
        assert list(result.columns) == GET_PRICE_LAKE_COLUMNS
        spy_fallback.assert_not_called()

    def test_get_price_returns_raw_prices_when_adjust_empty(self, tmp_path):
        """adjust="" 返回湖原始价 (等价于旧 "same data as ingestion path" 语义)。"""
        _write_min_all_stock_codes(tmp_path)
        fetcher = DataFetcher(data_dir=str(tmp_path))
        raw = _raw_df()
        fetcher.storage_manager.write_data(SYMBOL, raw, data_type="daily")
        fetcher.clear_price_cache()

        with patch(
            "uniquant.data.data_fetcher.get_corporate_action_adjuster"
        ) as factory:
            result = fetcher.get_price(SYMBOL, adjust="")

        factory.assert_not_called()
        assert not result.empty
        assert result["close"].iloc[0] == 11.0
        assert result["close"].iloc[1] == 12.0
        assert "adj_factor" not in result.columns
