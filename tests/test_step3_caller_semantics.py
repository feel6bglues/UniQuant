"""Step3 调用点 ``adjust`` 语义显式化 (预注册 §8 调用点迁移表).

背景: ``DataFetcher.get_price`` 历史断链 (恒返回空表), 上述调用点的 ``adjust``
语义从未真正生效; Step3 打通"湖优先返回真实数据"后, 这些路径会被**首次激活**。
本文件按迁移表逐点钉住:

- 湖为不复权 raw SSOT → 除 LPPL (§8 #18) 显式请求 qfq 外, 调用点一律显式 ``adjust=""``;
- ``load_data_with_fallback`` 的 qfq 分支 (§8 #9) 取数后**只返回不写湖**;
- 全部写湖点 (§8 #14/#16) 写入前必须过 ``_assert_unadjusted_for_lake`` R2 护栏;
- ``get_price`` 可能真返回空表 → 空数据防御, 不再把空 df 往下传 (§8 #6/#7)。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pandas as pd
import pytest

from uniquant.brain.lppl import data_manager as lppl_data_manager
from uniquant.data.managers.market_data_coordinator import MarketDataCoordinator
from uniquant.services import data_access_service as das
from uniquant.services.cache_coordinator import CacheCoordinator
from uniquant.services.data_access_service import DataAccessService
from uniquant.services.data_service import DataService


# ─────────────────────────── 共用桩件 ───────────────────────────


def _frame(close: float = 10.0, dates=("2026-04-23", "2026-04-24")) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(list(dates)),
            "open": [close] * len(dates),
            "high": [close] * len(dates),
            "low": [close] * len(dates),
            "close": [close] * len(dates),
            "volume": [1000] * len(dates),
            "amount": [close * 1000] * len(dates),
        }
    )


class _LakeStub:
    """湖桩: read_data 返回预置 df, write_data 记录写入事件。"""

    def __init__(self, read_df: pd.DataFrame | None = None) -> None:
        self.read_df = pd.DataFrame() if read_df is None else read_df
        self.writes: list[dict] = []
        self.read_calls: list[tuple] = []

    def read_data(self, symbol, data_type="stock", market="cn"):
        self.read_calls.append((symbol, data_type, market))
        return self.read_df.copy(deep=True)

    def write_data(self, symbol, df, data_type, market="cn", overwrite=False):
        self.writes.append(
            {
                "symbol": symbol,
                "data_type": data_type,
                "market": market,
                "overwrite": overwrite,
                "rows": len(df),
            }
        )
        return True


class _PriceFetcherStub:
    """get_price 桩: 记录调用 kwargs (可断言 adjust 是否**显式**传入) 并返回预置 df。"""

    def __init__(self, df: pd.DataFrame | None = None) -> None:
        self.df = pd.DataFrame() if df is None else df
        self.calls: list[dict] = []

    def get_price(self, symbol, **kwargs):
        self.calls.append({"symbol": symbol, **kwargs})
        return self.df.copy(deep=True)


def _access_service(fetcher, lake=None, cleaner=None) -> DataAccessService:
    service = SimpleNamespace(
        lake=lake if lake is not None else _LakeStub(),
        fetcher=fetcher,
        cleaner=cleaner
        if cleaner is not None
        else SimpleNamespace(clean_stock_daily=lambda df: df.copy(deep=True)),
        _clone_dataframe=lambda df: None if df is None else df.copy(deep=True),
        _get_cached=lambda key: None,
        _set_cache=lambda *a, **k: None,
    )
    return DataAccessService(service)


@pytest.fixture()
def das_log_records():
    """捕获 data_access_service logger 报文, 断言 qfq 只读策略日志存在。"""
    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _Capture()
    das.logger.addHandler(handler)
    try:
        yield records
    finally:
        das.logger.removeHandler(handler)


@pytest.fixture(autouse=True)
def _reset_guard_stats():
    das.LAKE_WRITE_GUARD_STATS["blocked_count"] = 0
    das.LAKE_WRITE_GUARD_STATS["last_blocked"] = None
    yield
    das.LAKE_WRITE_GUARD_STATS["blocked_count"] = 0
    das.LAKE_WRITE_GUARD_STATS["last_blocked"] = None


# ─────────────── ① load_data_with_fallback: qfq 分支只返回不写湖 (§8 #9)


def test_load_data_with_fallback_qfq_branch_returns_without_lake_write(
    das_log_records,
):
    fetched = _frame()
    lake = _LakeStub(read_df=pd.DataFrame())
    fetcher = _PriceFetcherStub(fetched)
    access = _access_service(fetcher, lake=lake)

    result = access.load_data_with_fallback("600519.SH", "stock", "stock daily")

    # 取数语义: stock 走 qfq (研究/展示口径), 显式传参
    assert fetcher.calls == [{"symbol": "600519.SH", "adjust": "qfq"}]
    # qfq 复权结果只返回不写湖
    assert lake.writes == []
    pd.testing.assert_frame_equal(result, fetched)
    assert any("只返回不写湖" in msg for msg in das_log_records), das_log_records
    # 护栏仍复核 (写湖必须过护栏, 保留现有接线): qfq 被 R-a 拦截并计数
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 1
    assert das.LAKE_WRITE_GUARD_STATS["last_blocked"]["adjust"] == "qfq"


# ─────────────── ② raw 分支写湖且过护栏 (§8 #9 index 分支)


def test_load_data_with_fallback_raw_branch_writes_through_guard(monkeypatch):
    fetched = _frame(close=300.0)
    lake = _LakeStub(read_df=pd.DataFrame())
    fetcher = _PriceFetcherStub(fetched)
    access = _access_service(fetcher, lake=lake)

    guard_calls: list[dict] = []
    original = DataAccessService._assert_unadjusted_for_lake

    def _spy(self, df, adjust, symbol):
        guard_calls.append({"symbol": symbol, "adjust": adjust})
        return original(self, df, adjust, symbol)

    monkeypatch.setattr(DataAccessService, "_assert_unadjusted_for_lake", _spy)

    result = access.load_data_with_fallback("000300.SH", "index", "index daily")

    assert fetcher.calls == [{"symbol": "000300.SH", "adjust": ""}]
    assert guard_calls == [{"symbol": "000300.SH", "adjust": ""}]
    assert len(lake.writes) == 1
    assert lake.writes[0]["overwrite"] is True
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 0
    pd.testing.assert_frame_equal(result, fetched)


# ─────────────── ③ _fetch_and_filter_price 显式 adjust="" (§8 #11)


def test_fetch_and_filter_price_requests_explicit_raw_adjust():
    fetcher = _PriceFetcherStub(_frame())
    access = _access_service(fetcher)

    result = access._fetch_and_filter_price("600519.SH", "2026-04-01", "2026-04-24")

    # 个股路径语义 = 原始价 (湖不复权, 研究/展示统一 raw), 不得继承 qfq 默认
    assert fetcher.calls == [{"symbol": "600519.SH", "adjust": ""}]
    assert not result.empty


def test_fetch_and_filter_index_keeps_explicit_raw_adjust():
    fetcher = _PriceFetcherStub(_frame())
    access = _access_service(fetcher)

    access._fetch_and_filter_index("000300.SH", "2026-04-01", "2026-04-24")

    assert fetcher.calls == [{"symbol": "000300.SH", "adjust": ""}]


# ─────────────── ④ fetch_from_source / fetch_and_save_dataset 显式 raw (§8 #13/#14)


class _DailyFetcherStub:
    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df
        self.calls: dict = {}

    def fetch_stock_daily(self, symbol, start_date, end_date, **kwargs):
        self.calls = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            **kwargs,
        }
        return self.df.copy(deep=True)


def test_fetch_from_source_passes_explicit_raw_adjust():
    fetcher = _DailyFetcherStub(_frame())
    access = _access_service(fetcher)

    result = access.fetch_from_source(
        "600519.SH", "2026-04-01", "2026-04-24", "cache-key", use_cache=False
    )

    assert fetcher.calls["adjust"] == ""
    assert result is not None and not result.empty


def test_fetch_and_save_dataset_passes_explicit_raw_adjust(monkeypatch):
    fetcher = _DailyFetcherStub(_frame())
    lake = _LakeStub(read_df=_frame())
    access = _access_service(fetcher, lake=lake)

    events: list[str] = []
    original = DataAccessService._assert_unadjusted_for_lake

    def _spy(self, df, adjust, symbol):
        events.append(f"guard:{adjust}")
        return original(self, df, adjust, symbol)

    monkeypatch.setattr(DataAccessService, "_assert_unadjusted_for_lake", _spy)

    def _write(symbol, df, data_type, market="cn", overwrite=False):
        events.append(f"write:{data_type}")
        lake.writes.append({"symbol": symbol, "data_type": data_type})
        return True

    lake.write_data = _write  # type: ignore[method-assign]

    access.fetch_and_save_dataset(
        "600519.SH", "2026-04-01", "2026-04-24", data_type="stock"
    )

    # §8 #14: 不得继承 fetch_stock_daily 的 qfq 默认值
    assert fetcher.calls["adjust"] == ""
    # 写入前必须已过护栏, 且顺序为 guard → write
    assert events == ["guard:", "write:stock"]


def test_load_etf_data_requests_explicit_raw_adjust():
    fetcher = _PriceFetcherStub(_frame(close=4.0))
    lake = _LakeStub(read_df=pd.DataFrame())
    access = _access_service(fetcher, lake=lake)

    result = access.load_etf_data()

    # §8 #10: ETF 读湖原始价, 源兜底同样显式 raw
    assert fetcher.calls == [{"symbol": "510300", "adjust": ""}]
    assert len(lake.writes) == 1
    assert not result.empty


# ─────────────── ⑥ rebuild_cache / check_cache_consistency (§8 #15/#16/#17)


class _ServiceLakeStub(_LakeStub):
    """DataService 用湖桩: 额外支持 delete_data / data_types 等属性。"""

    data_types = ["daily", "factor", "index", "1mins", "5mins"]
    base_dir = "."


class _MemCacheCoordinator(CacheCoordinator):
    """内存缓存协调器桩: 避免测试读写共享磁盘缓存 data/service_cache。"""

    def __init__(self) -> None:
        # 跳过磁盘后端构造 (不触碰 data/service_cache)
        self.store: dict = {}
        self.cache_manager = SimpleNamespace(delete=lambda key: False)

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None, data_type: str = "general") -> None:
        self.store[key] = value


def _data_service(lake, fetcher_get_price) -> DataService:
    storage = lake
    storage.base_dir = "."  # type: ignore[attr-defined]
    fetcher = SimpleNamespace(
        get_price=fetcher_get_price,
        clear_price_cache=lambda symbol=None, adjust=None: 0,
    )
    service = DataService(
        fetcher=fetcher,
        storage_manager=storage,
        cleaner=SimpleNamespace(clean_stock_daily=lambda df: df.copy(deep=True)),
    )
    service._cache_coordinator = _MemCacheCoordinator()
    service.cache_manager = service._cache_coordinator.cache_manager
    return service


def test_rebuild_cache_reads_lake_and_guards_write(monkeypatch):
    lake = _ServiceLakeStub(read_df=_frame())

    def _no_source(symbol, adjust=""):
        raise AssertionError("stock 分支必须直读湖, 不得走源取数")

    service = _data_service(lake, _no_source)

    events: list[str] = []
    original = DataAccessService._assert_unadjusted_for_lake

    def _spy(self, df, adjust, symbol):
        events.append(f"guard:{adjust}")
        return original(self, df, adjust, symbol)

    monkeypatch.setattr(DataAccessService, "_assert_unadjusted_for_lake", _spy)

    def _write(symbol, df, data_type, market="cn", overwrite=False):
        events.append(f"write:{data_type}")
        lake.writes.append({"symbol": symbol, "data_type": data_type})
        return True

    lake.write_data = _write  # type: ignore[method-assign]

    assert service.rebuild_cache("600000.SH", data_type="stock") is True

    assert lake.read_calls == [("600000.SH", "stock", "cn")]
    # 写湖前必须过 R2 护栏, 顺序 guard → write
    assert events == ["guard:", "write:stock"]
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 0


def test_rebuild_cache_index_keeps_explicit_raw_adjust(monkeypatch):
    lake = _ServiceLakeStub(read_df=pd.DataFrame())
    fetched = _frame()

    def _get_price(symbol, adjust=""):
        return fetched

    service = _data_service(lake, _get_price)

    guard_calls: list[dict] = []
    original = DataAccessService._assert_unadjusted_for_lake

    def _spy(self, df, adjust, symbol):
        guard_calls.append({"symbol": symbol, "adjust": adjust})
        return original(self, df, adjust, symbol)

    monkeypatch.setattr(DataAccessService, "_assert_unadjusted_for_lake", _spy)

    assert service.rebuild_cache("000300.SH", data_type="index") is True
    assert guard_calls == [{"symbol": "000300.SH", "adjust": ""}]
    assert lake.writes == [] or lake.writes[0]["data_type"] == "index"


def test_check_cache_consistency_compares_lake_against_cache(monkeypatch):
    lake = _ServiceLakeStub(read_df=_frame())

    def _no_source(symbol, adjust=""):
        raise AssertionError("一致性检查不得依赖源取数 (get_price 断链期恒空)")

    service = _data_service(lake, _no_source)

    guard_calls: list[dict] = []
    original = DataAccessService._assert_unadjusted_for_lake

    def _spy(self, df, adjust, symbol):
        guard_calls.append({"symbol": symbol, "adjust": adjust})
        return original(self, df, adjust, symbol)

    monkeypatch.setattr(DataAccessService, "_assert_unadjusted_for_lake", _spy)

    cache_key = service._get_cache_key(
        "stock", "600519.SH", "cn", namespace="datalake"
    )
    service._set_cache(cache_key, _frame(), data_type="stock")

    # 湖与缓存最新日一致 → 一致
    assert service.check_cache_consistency("600519.SH") is True
    assert guard_calls == [], "读数路径不应触发写湖护栏"

    # 湖更新 → 缓存过期
    lake.read_df = _frame(dates=("2026-04-24", "2026-04-25"))
    assert service.check_cache_consistency("600519.SH") is False


# ─────────────── ⑦ market_data_coordinator 保持显式 raw (§8 #8)


def test_market_data_coordinator_etf_fetch_keeps_explicit_raw_adjust():
    calls: list[dict] = {}

    def _fetch_stock_daily(symbol, start_date, end_date, adjust=""):
        calls.update({"symbol": symbol, "adjust": adjust})
        return _frame()

    coordinator = MarketDataCoordinator(SimpleNamespace(fetch_stock_daily=_fetch_stock_daily))

    result = coordinator.fetch_etf_daily_robust("510300", "2026-04-01", "2026-04-24")

    assert calls["adjust"] == ""
    assert not result.empty


# ─────────────── ⑧ LPPL 保持显式 qfq (§8 #18, 研究侧唯一 qfq 消费者)


def test_lppl_data_manager_keeps_explicit_qfq(monkeypatch, tmp_path):
    captured: dict = {}

    class _FakeFetcher:
        def fetch_stock_daily(self, symbol, start_date, end_date, adjust=""):
            captured.update({"symbol": symbol, "adjust": adjust})
            return _frame()

    monkeypatch.setattr(lppl_data_manager, "LPPLDataService", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "uniquant.data.data_fetcher.DataFetcher", _FakeFetcher, raising=True
    )

    manager = lppl_data_manager.LPPLDataManager(data_dir=str(tmp_path))
    df = manager.fetch_data("600519.SH", "贵州茅台")

    # 研究侧唯一 qfq 显式消费者, Step3 后此处首次真正拿到 qfq 数据
    assert captured["adjust"] == "qfq"
    assert df is not None and not df.empty


def test_lppl_data_manager_empty_response_returns_none(monkeypatch, tmp_path):
    class _EmptyFetcher:
        def fetch_stock_daily(self, symbol, start_date, end_date, adjust=""):
            return pd.DataFrame()

    monkeypatch.setattr(lppl_data_manager, "LPPLDataService", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "uniquant.data.data_fetcher.DataFetcher", _EmptyFetcher, raising=True
    )

    manager = lppl_data_manager.LPPLDataManager(data_dir=str(tmp_path))

    # 空表路径不崩 (LPPL 对空 df 的既有防御)
    assert manager.fetch_data("600519.SH", "贵州茅台") is None
