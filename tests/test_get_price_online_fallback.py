"""get_price 在线第三跳 (第二十轮) — tdxdata_online 兜底契约 TDD。

链路: 湖 miss -> 本地 mootdx miss -> TdxDataOnlineSource.fetch_daily (tdxdata
新协议, 需出网) -> 三重 miss 返回带合同列空表。本文件全部注入 mock 在线源,
不触真网、不读真实湖; DataFetcher 以 ``enable_online_fallback=True`` 构造后
替换 ``tdxdata_online_source`` 属性为 mock。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from uniquant.data.data_fetcher import (
    GET_PRICE_LAKE_COLUMNS,
    GET_PRICE_RETURN_CONTRACT,
    DataFetcher,
)

SYMBOL = "600519.SH"


def _write_min_all_stock_codes(tmp_path) -> None:
    """Step4 (D5 R-5): 主数据缺文件硬失败 → 提供最小主数据表。"""
    pd.DataFrame(
        {
            "code": ["sh.600519"],
            "name": ["贵州茅台"],
            "代码": ["600519"],
            "ipoDate": ["2001-08-27"],
            "outDate": [""],
            "type": ["1"],
            "status": ["1"],
        }
    ).to_csv(tmp_path / "all_stock_codes.csv", index=False, encoding="utf-8-sig")


def _online_frame(symbol: str = SYMBOL) -> pd.DataFrame:
    """在线源 8 列输出 (volume 已是股; 无 reserved 列)。"""
    dates = pd.bdate_range("2026-11-17", periods=3)
    close = [1485.75, 1460.21, 1442.66]
    return pd.DataFrame(
        {
            "date": dates,
            "open": [c + 2.0 for c in close],
            "high": [c + 5.0 for c in close],
            "low": [c - 5.0 for c in close],
            "close": close,
            "volume": [6_722_900.0, 4_269_100.0, 2_984_600.0],
            "amount": [c * v for c, v in zip(close, [67229.0, 42691.0, 29846.0])],
            "code": symbol,
        }
    )


class _MockOnlineSource:
    def __init__(self, frame: pd.DataFrame | None | Exception = None):
        self.frame = frame
        self.calls = []

    def fetch_daily(self, symbol, start_date, end_date):
        self.calls.append((symbol, start_date, end_date))
        if isinstance(self.frame, Exception):
            raise self.frame
        return self.frame if self.frame is not None else pd.DataFrame()


def _make_fetcher(tmp_path, online) -> DataFetcher:
    _write_min_all_stock_codes(tmp_path)
    fetcher = DataFetcher(data_dir=str(tmp_path), enable_online_fallback=True)
    # 开发机装有本地通达信 → 本地兜底会命中真数据; 中和后才能穿透到在线 mock
    fetcher.mootdx_local_source = None
    fetcher.tdxdata_online_source = online
    fetcher.clear_price_cache()
    return fetcher


class TestOnlineThirdHop:
    def test_triple_miss_returns_empty_with_contract_columns(self, tmp_path):
        fetcher = _make_fetcher(tmp_path, _MockOnlineSource(frame=None))
        result = fetcher.get_price(SYMBOL)
        assert result.empty
        assert list(result.columns) == GET_PRICE_LAKE_COLUMNS
        assert len(fetcher.tdxdata_online_source.calls) == 1

    def test_triple_miss_calls_online_with_range(self, tmp_path):
        fetcher = _make_fetcher(tmp_path, _MockOnlineSource(frame=None))
        fetcher.get_price(SYMBOL, start_date="2026-11-01", end_date="2026-11-20")
        symbol, start, end = fetcher.tdxdata_online_source.calls[0]
        assert symbol == SYMBOL
        assert start == "2026-11-01"
        assert end == "2026-11-20"

    def test_online_hit_returns_contract_columns_with_reserved_nan(self, tmp_path):
        fetcher = _make_fetcher(tmp_path, _MockOnlineSource(frame=_online_frame()))
        result = fetcher.get_price(SYMBOL)
        assert not result.empty
        assert list(result.columns) == GET_PRICE_LAKE_COLUMNS
        assert result["reserved"].isna().all()
        assert result["date"].is_monotonic_increasing
        assert (result["code"] == SYMBOL).all()

    def test_online_hit_volume_not_rescaled(self, tmp_path):
        """在线源 volume 已是股: 不得再被 手->股 自校准放大。"""
        fetcher = _make_fetcher(tmp_path, _MockOnlineSource(frame=_online_frame()))
        result = fetcher.get_price(SYMBOL)
        assert result["volume"].iloc[0] == pytest.approx(6_722_900.0)

    def test_online_source_exception_returns_empty(self, tmp_path):
        fetcher = _make_fetcher(
            tmp_path, _MockOnlineSource(frame=ConnectionError("network down"))
        )
        result = fetcher.get_price(SYMBOL)
        assert result.empty
        assert list(result.columns) == GET_PRICE_LAKE_COLUMNS

    def test_online_disabled_constructor_returns_empty(self, tmp_path):
        _write_min_all_stock_codes(tmp_path)
        fetcher = DataFetcher(data_dir=str(tmp_path), enable_online_fallback=False)
        assert fetcher.tdxdata_online_source is None
        # 中和本地源 (开发机装有真通达信), 才能钉死"三重 miss → 空"语义
        fetcher.mootdx_local_source = None
        result = fetcher.get_price(SYMBOL)
        assert result.empty

    def test_online_hit_never_writes_back_to_lake(self, tmp_path):
        fetcher = _make_fetcher(tmp_path, _MockOnlineSource(frame=_online_frame()))
        spy = MagicMock(side_effect=AssertionError("get_price 禁止回写数据湖"))
        fetcher.storage_manager.write_data = spy
        fetcher.get_price(SYMBOL)
        spy.assert_not_called()

    def test_lake_hit_skips_online_hop(self, tmp_path):
        online = _MockOnlineSource(frame=_online_frame())
        fetcher = _make_fetcher(tmp_path, online)
        lake = _online_frame()
        fetcher.storage_manager.write_data(SYMBOL, lake, data_type="daily")
        fetcher.clear_price_cache()
        result = fetcher.get_price(SYMBOL)
        assert not result.empty
        assert online.calls == []  # 湖命中 → 在线零调用

    def test_local_hit_skips_online_hop(self, tmp_path):
        online = _MockOnlineSource(frame=_online_frame())
        local = SimpleNamespace(
            fetch_daily=lambda symbol, start, end: _online_frame()
        )
        _write_min_all_stock_codes(tmp_path)
        fetcher = DataFetcher(data_dir=str(tmp_path), enable_online_fallback=True)
        fetcher.mootdx_local_source = local
        fetcher.tdxdata_online_source = online
        fetcher.clear_price_cache()
        result = fetcher.get_price(SYMBOL)
        assert not result.empty
        assert online.calls == []  # 本地命中 → 在线零调用

    def test_market_cap_falls_through_to_online(self, tmp_path):
        online = _MockOnlineSource()
        online.fetch_market_cap = lambda symbol: 1.857e12
        _write_min_all_stock_codes(tmp_path)
        fetcher = DataFetcher(data_dir=str(tmp_path), enable_online_fallback=True)
        fetcher.mootdx_local_source = SimpleNamespace(
            fetch_market_cap=lambda symbol: 0.0
        )
        fetcher.data_sources = [fetcher.mootdx_local_source, online]
        cap = fetcher.fetch_stock_market_cap(SYMBOL)
        assert cap == pytest.approx(1.857e12)


class TestContractConstant:
    def test_sources_include_online_third_hop(self):
        assert GET_PRICE_RETURN_CONTRACT["sources"] == (
            "lake",
            "mootdx_local",
            "tdxdata_online",
        )
