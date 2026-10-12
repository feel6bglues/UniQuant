"""R2 污染通道护栏: 复权数据禁写 data/lake (DATA_SOURCE_MIGRATION_PLAN §5 Step 0).

背景: `data_access_service.load_data_with_fallback` 在湖缺数据时以
`adjust="qfq"` 调 `get_price` → cleaner → `write_data(overwrite=True)` 回写湖
(计划 §5 F2 / Bug3)。湖必须保持不复权 raw SSOT，故写湖前需硬断言:
`adjust` 非空 (qfq/hfq) 或 df 含复权因子列 → 不写湖, df 原样返回调用方
(读数行为不变), 并记录模块级计数/最近事件供断言。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pandas as pd
import pytest

from uniquant.services import data_access_service as das
from uniquant.services.data_access_service import DataAccessService


@pytest.fixture(autouse=True)
def _reset_guard_stats():
    das.LAKE_WRITE_GUARD_STATS["blocked_count"] = 0
    das.LAKE_WRITE_GUARD_STATS["last_blocked"] = None
    yield
    das.LAKE_WRITE_GUARD_STATS["blocked_count"] = 0
    das.LAKE_WRITE_GUARD_STATS["last_blocked"] = None


@pytest.fixture()
def guard_logs():
    """捕获护栏 logger 的报文, 断言 R-c 提示语存在。"""
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


def _make_service(fetched: pd.DataFrame):
    """构造 load_data_with_fallback 所需的最小 stub service + 写入记录。"""
    written = []

    def _write(symbol, df, **kwargs):
        written.append({"symbol": symbol, "df": df, "kwargs": kwargs})
        return True

    lake = SimpleNamespace(
        read_data=lambda symbol, data_type="daily", market="cn": pd.DataFrame(),
        write_data=_write,
    )
    service = SimpleNamespace(
        lake=lake,
        _clone_dataframe=lambda df: None if df is None else df.copy(deep=True),
        fetcher=SimpleNamespace(get_price=lambda symbol, adjust="": fetched.copy(deep=True)),
        cleaner=SimpleNamespace(clean_stock_daily=lambda df: df),
    )
    return service, written


def test_qfq_adjusted_fallback_is_blocked_from_lake_write():
    fetched = pd.DataFrame({"date": pd.to_datetime(["2026-04-24"]), "close": [10.0]})
    service, written = _make_service(fetched)

    result = DataAccessService(service).load_data_with_fallback(
        "600519.SH", "stock", "stock daily"
    )

    assert written == []
    pd.testing.assert_frame_equal(result, fetched)
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 1
    last = das.LAKE_WRITE_GUARD_STATS["last_blocked"]
    assert last is not None
    assert last["symbol"] == "600519.SH"
    assert last["adjust"] == "qfq"


def test_clean_unadjusted_data_is_written_to_lake():
    fetched = pd.DataFrame({"date": pd.to_datetime(["2026-04-24"]), "close": [300.0]})
    service, written = _make_service(fetched)

    result = DataAccessService(service).load_data_with_fallback(
        "000300.SH", "index", "index daily"
    )

    assert len(written) == 1
    assert written[0]["symbol"] == "000300.SH"
    assert written[0]["kwargs"]["data_type"] == "index"
    pd.testing.assert_frame_equal(result, fetched)
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 0
    assert das.LAKE_WRITE_GUARD_STATS["last_blocked"] is None


def test_df_containing_adj_factor_column_is_blocked():
    fetched = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-24"]),
            "close": [1.0],
            "adj_factor": [0.95],
        }
    )
    service, written = _make_service(fetched)

    result = DataAccessService(service).load_data_with_fallback(
        "000300.SH", "index", "index daily"
    )

    assert written == []
    pd.testing.assert_frame_equal(result, fetched)
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 1
    last = das.LAKE_WRITE_GUARD_STATS["last_blocked"]
    assert last is not None
    assert last["columns"] == ["adj_factor"]


def test_fetch_and_save_dataset_raw_write_goes_through_guard(monkeypatch):
    """写湖点 :125 (fetch_and_save_dataset → _fetch_and_filter_price):

    raw 语义必须显式以 ``adjust=""`` 过护栏并放行 (禁止漏传)。
    """
    fetched = pd.DataFrame({"date": pd.to_datetime(["2026-04-24"]), "close": [10.0]})
    service, written = _make_service(fetched)

    guard_calls: list[dict] = []
    original = DataAccessService._assert_unadjusted_for_lake

    def _spy(self, df, adjust, symbol):
        guard_calls.append({"symbol": symbol, "adjust": adjust})
        return original(self, df, adjust, symbol)

    monkeypatch.setattr(DataAccessService, "_assert_unadjusted_for_lake", _spy)

    DataAccessService(service).fetch_and_save_dataset(
        "600519.SH", "2026-04-01", "2026-04-24", data_type="stock"
    )

    assert len(written) == 1
    assert written[0]["symbol"] == "600519.SH"
    assert guard_calls == [{"symbol": "600519.SH", "adjust": ""}]
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 0


def test_adjust_semantics_write_is_blocked_with_hint_and_df_returned_unchanged(
    guard_logs,
):
    """任何 write 路径传 qfq → 拦截、df 原样返回, 且报文含 R-c 提示语。"""
    fetched = pd.DataFrame({"date": pd.to_datetime(["2026-04-24"]), "close": [10.0]})
    service, written = _make_service(fetched)

    result = DataAccessService(service).load_data_with_fallback(
        "600519.SH", "stock", "stock daily"
    )

    assert written == []
    pd.testing.assert_frame_equal(result, fetched)
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 1
    hint = "复权输出必须带 adj_factor 列且禁止写湖"
    assert any(hint in msg for msg in guard_logs), guard_logs

    # 护栏本身: 任意非空 adjust 语义 (hfq 等) 一律拦截, 且不改写入参 df
    probe = fetched.copy(deep=True)
    allowed = DataAccessService(service)._assert_unadjusted_for_lake(
        probe, "hfq", "600519.SH"
    )
    assert allowed is False
    pd.testing.assert_frame_equal(probe, fetched)
    assert das.LAKE_WRITE_GUARD_STATS["last_blocked"]["adjust"] == "hfq"


def test_etf_write_path_with_adj_factor_frame_is_blocked():
    """写湖点 :236 (load_etf_data): 携带复权因子列的 df 同样被拦, 读数行为不变。"""
    fetched = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-24"]),
            "close": [1.0],
            "adj_factor": [0.95],
        }
    )
    service, written = _make_service(fetched)

    result = DataAccessService(service).load_etf_data()

    assert written == []
    pd.testing.assert_frame_equal(result, fetched)
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 1
    last = das.LAKE_WRITE_GUARD_STATS["last_blocked"]
    assert last is not None
    assert last["symbol"] == "510300"
    assert last["columns"] == ["adj_factor"]


def test_fetch_and_save_dataset_factor_frame_is_blocked():
    """写湖点 :125: 携带复权因子列的 df 被拦 (R-b 覆盖该路径)。"""
    fetched = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-24"]),
            "close": [10.0],
            "qfq_factor": [1.02],
        }
    )
    service, written = _make_service(fetched)

    DataAccessService(service).fetch_and_save_dataset(
        "600519.SH", "2026-04-01", "2026-04-24", data_type="stock"
    )

    assert written == []
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 1
    last = das.LAKE_WRITE_GUARD_STATS["last_blocked"]
    assert last is not None
    assert last["columns"] == ["qfq_factor"]
