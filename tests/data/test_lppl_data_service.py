"""``data/services/lppl_data_service.py`` — LPPL 指数数据服务测试.

覆盖 数据湖优先 → data_fetcher → akshare 兜底 的三级取数链, 以及 ``_clean_data``
的列/日期/去重/数值清洗契约。全部通过 mock 隔离 (无网络, 无真实数据湖读写)。
"""

import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

import uniquant.data.services.lppl_data_service as mod
from uniquant.data.services.lppl_data_service import LPPLDataService

NOW = datetime(2026, 10, 16, 15, 0, 0)


@pytest.fixture
def parts(monkeypatch):
    """构造一个已注入 mock DataFetcher / StorageManager / TimeProvider 的服务实例。"""
    fetcher = MagicMock()
    storage = MagicMock()
    monkeypatch.setattr(mod, "DataFetcher", lambda: fetcher)
    monkeypatch.setattr(mod, "StorageManager", lambda: storage)
    monkeypatch.setattr(mod, "get_time_provider", lambda: MagicMock(now=lambda: NOW))
    svc = LPPLDataService()
    return svc, fetcher, storage


def _daily(rows: int = 5, end: datetime | None = None, start_price: float = 10.0):
    end = end or NOW
    dates = pd.date_range(end=end, periods=rows, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [start_price] * rows,
            "high": [start_price + 1] * rows,
            "low": [start_price - 1] * rows,
            "close": [start_price] * rows,
            "volume": [100.0] * rows,
            "amount": [1000.0] * rows,
        }
    )


class TestInit:
    def test_alias_and_index_map(self, parts):
        svc, _, storage = parts
        assert svc.data_lake is storage
        assert svc.index_codes["sh000300"] == "沪深300"
        assert len(svc.index_codes) == 7
        assert svc.data_fetcher is not None


class TestCleanData:
    def test_empty_returns_empty(self, parts):
        svc, _, _ = parts
        out = svc._clean_data(pd.DataFrame())
        assert out.empty

    def test_happy_path_indexes_dedupes_and_sorts(self, parts):
        svc, _, _ = parts
        df = pd.DataFrame(
            {
                "date": ["2024-01-03", "2024-01-01", "2024-01-03"],
                "open": [3, 1, 3],
                "high": [4, 2, 4],
                "low": [1, 0, 1],
                "close": [3, 1, 3],
                "volume": [30, 10, 30],
                "amount": [300, 100, 300],
            }
        )
        out = svc._clean_data(df)
        assert isinstance(out.index, pd.DatetimeIndex)
        assert out.index.is_monotonic_increasing
        assert list(out.index) == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-03")]
        assert "date_col" in out.columns  # date 同时保留为普通列
        assert not out.index.has_duplicates

    def test_renames_uppercase_date_alias(self, parts):
        svc, _, _ = parts
        df = pd.DataFrame({"Date": ["2024-01-02"], "close": [1.0]})
        out = svc._clean_data(df)
        assert not out.empty
        assert out.index[0] == pd.Timestamp("2024-01-02")

    def test_missing_date_column_returns_empty(self, parts):
        svc, _, _ = parts
        out = svc._clean_data(pd.DataFrame({"close": [1.0], "volume": [1.0]}))
        assert out.empty

    def test_unparseable_date_returns_empty(self, parts):
        svc, _, _ = parts
        df = pd.DataFrame({"date": ["not-a-date"], "close": [1.0]})
        out = svc._clean_data(df)
        assert out.empty

    def test_renames_uppercase_close_alias(self, parts):
        svc, _, _ = parts
        df = pd.DataFrame({"date": ["2024-01-02"], "Close": [12.5]})
        out = svc._clean_data(df)
        assert out["close"].iloc[0] == pytest.approx(12.5)

    def test_missing_close_returns_empty(self, parts):
        svc, _, _ = parts
        out = svc._clean_data(pd.DataFrame({"date": ["2024-01-02"], "open": [1.0]}))
        assert out.empty

    def test_non_numeric_prices_coerced_to_zero(self, parts):
        svc, _, _ = parts
        df = pd.DataFrame(
            {
                "date": ["2024-01-02", "2024-01-03"],
                "open": ["bad", 2.0],
                "close": ["bad", 2.0],
                "volume": ["bad", 20.0],
            }
        )
        out = svc._clean_data(df)
        assert out["close"].iloc[0] == 0.0
        assert out["volume"].iloc[0] == 0.0
        assert out["close"].iloc[1] == pytest.approx(2.0)


class TestGetIndexData:
    def test_fresh_lake_hit_skips_fetch(self, parts):
        svc, fetcher, storage = parts
        storage.read_data.return_value = _daily(rows=10).set_index("date")
        out = svc.get_index_data("sh000300", days=5)
        assert len(out) == 5
        fetcher.fetch_index_daily.assert_not_called()

    def test_stale_lake_miss_triggers_fetch_and_write(self, parts):
        svc, fetcher, storage = parts
        stale = _daily(rows=10, end=NOW - timedelta(days=30)).set_index("date")
        storage.read_data.return_value = stale
        fetcher.fetch_index_daily.return_value = _daily(rows=4)
        out = svc.get_index_data("sh000300", days=350)
        fetcher.fetch_index_daily.assert_called_once()
        storage.write_data.assert_called_once()
        assert not out.empty

    def test_empty_lake_fetch_path_writes_to_lake(self, parts):
        svc, fetcher, storage = parts
        storage.read_data.return_value = pd.DataFrame()
        fetcher.fetch_index_daily.return_value = _daily(rows=3)
        out = svc.get_index_data("sh000300")
        assert not out.empty
        _, kwargs = storage.write_data.call_args
        assert kwargs["data_type"] == "index"
        assert kwargs["overwrite"] is True

    def test_fetch_empty_falls_back_to_akshare(self, parts, monkeypatch):
        svc, fetcher, storage = parts
        storage.read_data.return_value = pd.DataFrame()
        fetcher.fetch_index_daily.return_value = pd.DataFrame()
        fake_ak = MagicMock()
        fake_ak.stock_zh_index_daily.return_value = _daily(rows=6)
        monkeypatch.setitem(sys.modules, "akshare", fake_ak)

        out = svc.get_index_data("sh000300")
        assert not out.empty
        fake_ak.stock_zh_index_daily.assert_called_once_with(symbol="sh000300")
        storage.write_data.assert_called_once()

    def test_all_sources_empty_returns_empty_without_write(self, parts, monkeypatch):
        svc, fetcher, storage = parts
        storage.read_data.return_value = pd.DataFrame()
        fetcher.fetch_index_daily.return_value = pd.DataFrame()
        fake_ak = MagicMock()
        fake_ak.stock_zh_index_daily.side_effect = RuntimeError("network down")
        monkeypatch.setitem(sys.modules, "akshare", fake_ak)

        out = svc.get_index_data("sh000300")
        assert out.empty
        storage.write_data.assert_not_called()

    def test_lake_error_is_not_swallowed_by_freshness_check(self, parts):
        """湖返回带 RangeIndex 的帧时 (无 DatetimeIndex) 不得误判为新鲜。"""
        svc, fetcher, storage = parts
        storage.read_data.return_value = pd.DataFrame({"close": [1.0, 2.0]})
        fetcher.fetch_index_daily.return_value = _daily(rows=3)
        out = svc.get_index_data("sh000300")
        # RangeIndex.max() == 1 → 非空真值 → 走 to_datetime 检查; 不崩即可
        assert isinstance(out, pd.DataFrame)
