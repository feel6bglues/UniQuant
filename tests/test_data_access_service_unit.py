"""Unit tests for ``services.data_access_service.DataAccessService``.

Complements ``tests/test_data_access_service.py`` and
``tests/test_data_lake_write_guard.py`` by covering the cache/source/lake read
fan-out, the per-data-type fetch branches, the ETF path and the R2 lake
write-guard rules (allowed path + each reject rule) without weakening the guard.

All dependencies are lightweight ``SimpleNamespace`` stubs — no data lake, no
network, no ``data/`` access.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from uniquant.services import data_access_service as das
from uniquant.services.data_access_service import DataAccessService
from uniquant.shared.exceptions import CacheError, DataFetchError


def _clone(df):
    return None if df is None else df.copy(deep=True)


def _daily(close=1.0, dates=("2026-04-10",)):
    return pd.DataFrame({"date": pd.to_datetime(list(dates)), "close": [close] * len(dates)})


def _base(**over):
    stub = {
        "_get_cache_key": lambda *a, **k: "k",
        "_clone_dataframe": _clone,
        "_get_cached": lambda key: None,
        "_set_cache": lambda key, df: None,
        "fetcher": SimpleNamespace(),
        "cleaner": SimpleNamespace(clean_stock_daily=lambda df: df),
        "lake": SimpleNamespace(
            read_data=lambda symbol, **k: pd.DataFrame(),
            write_data=lambda *a, **k: True,
        ),
    }
    stub.update(over)
    return SimpleNamespace(**stub)


@pytest.fixture(autouse=True)
def _reset_guard_stats():
    das.LAKE_WRITE_GUARD_STATS["blocked_count"] = 0
    das.LAKE_WRITE_GUARD_STATS["last_blocked"] = None
    yield
    das.LAKE_WRITE_GUARD_STATS["blocked_count"] = 0
    das.LAKE_WRITE_GUARD_STATS["last_blocked"] = None


# ── fetch_data fan-out ────────────────────────────────────────────────────────


def test_fetch_data_cache_miss_falls_to_source():
    svc = _base(fetcher=SimpleNamespace(fetch_stock_daily=lambda s, a, b, adjust="": _daily(1.0)))
    result = DataAccessService(svc).fetch_data("000001.SZ", "2026-04-01", "2026-04-30")
    assert result.iloc[0]["close"] == 1.0


def test_fetch_data_source_miss_falls_to_lake():
    svc = _base(
        fetcher=SimpleNamespace(get_price=lambda s, adjust="": None),
        lake=SimpleNamespace(read_data=lambda symbol, **k: _daily(2.0)),
    )
    result = DataAccessService(svc).fetch_data("000001.SZ", "2026-04-01", "2026-04-30")
    assert result.iloc[0]["close"] == 2.0


# ── fetch_from_cache ──────────────────────────────────────────────────────────


def test_fetch_from_cache_returns_none_on_cache_error():
    def _raise(key):
        raise CacheError("cache down")

    assert DataAccessService(_base(_get_cached=_raise)).fetch_from_cache("k", "s") is None


# ── fetch_from_source ─────────────────────────────────────────────────────────


def test_fetch_from_source_swallows_cache_write_failure():
    def _raise(key, df):
        raise ValueError("write boom")

    svc = _base(
        fetcher=SimpleNamespace(fetch_stock_daily=lambda s, a, b, adjust="": _daily(4.0)),
        _set_cache=_raise,
    )
    result = DataAccessService(svc).fetch_from_source(
        "000001.SZ", "2026-04-01", "2026-04-30", "k", True
    )
    assert result.iloc[0]["close"] == 4.0


def test_fetch_from_source_returns_none_on_data_fetch_error():
    def _raise(*a, **k):
        raise DataFetchError("source down")

    svc = _base(fetcher=SimpleNamespace(fetch_stock_daily=_raise))
    assert (
        DataAccessService(svc).fetch_from_source(
            "000001.SZ", "2026-04-01", "2026-04-30", "k", True
        )
        is None
    )


def test_fetch_from_source_falls_back_to_get_price_when_empty():
    svc = _base(
        fetcher=SimpleNamespace(
            fetch_stock_daily=lambda s, a, b, adjust="": pd.DataFrame(),
            get_price=lambda s, adjust="": _daily(3.0),
        )
    )
    result = DataAccessService(svc).fetch_from_source(
        "000001.SZ", "2026-04-01", "2026-04-30", "k", False
    )
    assert result.iloc[0]["close"] == 3.0


# ── fetch_from_lake ───────────────────────────────────────────────────────────


def test_fetch_from_lake_miss_returns_none():
    svc = _base(lake=SimpleNamespace(read_data=lambda symbol, **k: pd.DataFrame()))
    assert DataAccessService(svc).fetch_from_lake("000001.SZ", "2026-04-01", "2026-04-30") is None


def test_fetch_from_lake_error_returns_none():
    def _raise(*a, **k):
        raise RuntimeError("lake read boom")

    svc = _base(lake=SimpleNamespace(read_data=_raise))
    assert DataAccessService(svc).fetch_from_lake("000001.SZ", "2026-04-01", "2026-04-30") is None


# ── fetch_and_save_dataset branches ───────────────────────────────────────────


def _recording_lake(frame):
    written = []

    def _write(symbol, df, **kwargs):
        written.append({"symbol": symbol, "df": df, "kwargs": kwargs})
        return True

    lake = SimpleNamespace(
        read_data=lambda symbol, data_type="stock", market="cn": frame,
        write_data=_write,
    )
    return lake, written


def test_fetch_and_save_dataset_stock_empty_falls_back_to_price():
    lake, written = _recording_lake(_daily(5.0))
    svc = _base(
        fetcher=SimpleNamespace(
            fetch_stock_daily=lambda *a, **k: pd.DataFrame(),
            get_price=lambda s, adjust="": _daily(5.0),
        ),
        lake=lake,
    )
    result = DataAccessService(svc).fetch_and_save_dataset(
        "000001.SZ", "2026-04-01", "2026-04-30", data_type="stock"
    )
    assert result.iloc[0]["close"] == 5.0
    assert len(written) == 1 and written[0]["symbol"] == "000001.SZ"


def test_fetch_and_save_dataset_index_via_fetch_index_daily():
    lake, written = _recording_lake(_daily(6.0))
    svc = _base(
        fetcher=SimpleNamespace(fetch_index_daily=lambda s, a, b: _daily(6.0)),
        lake=lake,
    )
    result = DataAccessService(svc).fetch_and_save_dataset(
        "000300.SH", "2026-04-01", "2026-04-30", data_type="index"
    )
    assert result.iloc[0]["close"] == 6.0
    assert written[0]["kwargs"]["data_type"] == "index"


def test_fetch_and_save_dataset_index_empty_falls_back_to_price():
    lake, _ = _recording_lake(_daily(7.0))
    svc = _base(
        fetcher=SimpleNamespace(
            fetch_index_daily=lambda s, a, b: pd.DataFrame(),
            get_price=lambda s, adjust="": _daily(7.0),
        ),
        lake=lake,
    )
    result = DataAccessService(svc).fetch_and_save_dataset(
        "000300.SH", "2026-04-01", "2026-04-30", data_type="index"
    )
    assert result.iloc[0]["close"] == 7.0


def test_fetch_and_save_dataset_index_without_fetch_index_daily():
    lake, _ = _recording_lake(_daily(8.0))
    svc = _base(
        fetcher=SimpleNamespace(get_price=lambda s, adjust="": _daily(8.0)),
        lake=lake,
    )
    result = DataAccessService(svc).fetch_and_save_dataset(
        "000300.SH", "2026-04-01", "2026-04-30", data_type="index"
    )
    assert result.iloc[0]["close"] == 8.0


def test_fetch_and_save_dataset_returns_none_when_no_data():
    svc = _base(
        fetcher=SimpleNamespace(
            fetch_stock_daily=lambda *a, **k: pd.DataFrame(),
            get_price=lambda s, adjust="": pd.DataFrame(),
        )
    )
    assert (
        DataAccessService(svc).fetch_and_save_dataset(
            "000001.SZ", "2026-04-01", "2026-04-30", data_type="stock"
        )
        is None
    )


def test_fetch_and_save_dataset_returns_none_on_fetch_error():
    def _raise(*a, **k):
        raise RuntimeError("fetch boom")

    svc = _base(fetcher=SimpleNamespace(fetch_stock_daily=_raise))
    assert (
        DataAccessService(svc).fetch_and_save_dataset(
            "000001.SZ", "2026-04-01", "2026-04-30", data_type="stock"
        )
        is None
    )


# ── get_from_lake ─────────────────────────────────────────────────────────────


def test_get_from_lake_hit_and_miss():
    hit_svc = _base(lake=SimpleNamespace(read_data=lambda symbol, **k: _daily(9.0)))
    result = DataAccessService(hit_svc).get_from_lake("600519.SH", "stock")
    assert result.iloc[0]["close"] == 9.0

    miss_svc = _base(lake=SimpleNamespace(read_data=lambda symbol, **k: pd.DataFrame()))
    assert DataAccessService(miss_svc).get_from_lake("600519.SH", "stock") is None


# ── load_data_with_fallback ───────────────────────────────────────────────────


def test_load_data_with_fallback_direct_lake_hit():
    svc = _base(lake=SimpleNamespace(read_data=lambda symbol, **k: _daily(11.0)))
    result = DataAccessService(svc).load_data_with_fallback("600519.SH", "stock", "stock daily")
    assert result.iloc[0]["close"] == 11.0


def test_load_data_with_fallback_empty_source_returns_empty_frame():
    svc = _base(
        lake=SimpleNamespace(read_data=lambda symbol, **k: pd.DataFrame()),
        fetcher=SimpleNamespace(get_price=lambda s, adjust="": pd.DataFrame()),
    )
    result = DataAccessService(svc).load_data_with_fallback("600519.SH", "stock", "stock daily")
    assert result.empty


def test_load_data_with_fallback_empty_cleaned_returns_empty_frame():
    svc = _base(
        lake=SimpleNamespace(read_data=lambda symbol, **k: pd.DataFrame()),
        fetcher=SimpleNamespace(get_price=lambda s, adjust="": _daily(12.0)),
        cleaner=SimpleNamespace(clean_stock_daily=lambda df: pd.DataFrame()),
    )
    result = DataAccessService(svc).load_data_with_fallback("600519.SH", "stock", "stock daily")
    assert result.empty


# ── load_etf_data ─────────────────────────────────────────────────────────────


def test_load_etf_data_lake_hit():
    svc = _base(lake=SimpleNamespace(read_data=lambda symbol, **k: _daily(13.0)))
    result = DataAccessService(svc).load_etf_data()
    assert result.iloc[0]["close"] == 13.0


def test_load_etf_data_empty_source_returns_empty_frame():
    svc = _base(
        lake=SimpleNamespace(read_data=lambda symbol, **k: pd.DataFrame()),
        fetcher=SimpleNamespace(get_price=lambda s, adjust="": pd.DataFrame()),
    )
    assert DataAccessService(svc).load_etf_data().empty


def test_load_etf_data_empty_cleaned_returns_empty_frame():
    svc = _base(
        lake=SimpleNamespace(read_data=lambda symbol, **k: pd.DataFrame()),
        fetcher=SimpleNamespace(get_price=lambda s, adjust="": _daily(14.0)),
        cleaner=SimpleNamespace(clean_stock_daily=lambda df: pd.DataFrame()),
    )
    assert DataAccessService(svc).load_etf_data().empty


def test_load_etf_data_error_returns_empty_frame():
    def _raise(*a, **k):
        raise RuntimeError("lake boom")

    svc = _base(lake=SimpleNamespace(read_data=_raise))
    assert DataAccessService(svc).load_etf_data().empty


def test_load_etf_data_writes_through_guard():
    lake, written = _recording_lake(pd.DataFrame())
    svc = _base(
        lake=lake,
        fetcher=SimpleNamespace(get_price=lambda s, adjust="": _daily(15.0)),
    )
    result = DataAccessService(svc).load_etf_data()
    assert result.iloc[0]["close"] == 15.0
    assert len(written) == 1
    assert written[0]["symbol"] == "510300"
    assert written[0]["kwargs"]["data_type"] == "stock"
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 0


def test_load_data_with_fallback_returns_empty_on_unexpected_error():
    def _raise(*a, **k):
        raise RuntimeError("lake boom")

    svc = _base(lake=SimpleNamespace(read_data=_raise))
    result = DataAccessService(svc).load_data_with_fallback("600519.SH", "stock", "stock daily")
    assert result.empty


# ── private fetch helpers ─────────────────────────────────────────────────────


def test_fetch_and_filter_index_none_when_price_empty():
    svc = _base(fetcher=SimpleNamespace(get_price=lambda s, adjust="": pd.DataFrame()))
    assert (
        DataAccessService(svc)._fetch_and_filter_index("000300.SH", "2026-04-01", "2026-04-30")
        is None
    )


def test_filter_by_date_passthrough_without_date_column():
    df = pd.DataFrame({"close": [1.0, 2.0]})
    out = DataAccessService._filter_by_date(df, "2026-04-01", "2026-04-30")
    pd.testing.assert_frame_equal(out, df)


# ── R2 lake write-guard (additional cases) ────────────────────────────────────


def test_guard_allows_unadjusted_raw_frame():
    svc = _base()
    df = _daily(1.0)
    assert DataAccessService(svc)._assert_unadjusted_for_lake(df, "", "600519.SH") is True
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 0
    assert das.LAKE_WRITE_GUARD_STATS["last_blocked"] is None


def test_guard_blocks_factor_column_only_with_rb_rule():
    svc = _base()
    df = _daily(1.0).assign(hfq_factor=1.1)
    assert DataAccessService(svc)._assert_unadjusted_for_lake(df, "", "600519.SH") is False
    last = das.LAKE_WRITE_GUARD_STATS["last_blocked"]
    assert last["rules"] == ["R-b"]
    assert last["columns"] == ["hfq_factor"]
    assert last["adjust"] == ""


def test_guard_flags_all_three_rules_and_leaves_frame_unchanged():
    svc = _base()
    df = _daily(1.0).assign(adj_factor=0.95, qfq_factor=1.0)
    original = df.copy(deep=True)
    assert DataAccessService(svc)._assert_unadjusted_for_lake(df, "qfq", "600519.SH") is False
    pd.testing.assert_frame_equal(df, original)
    last = das.LAKE_WRITE_GUARD_STATS["last_blocked"]
    assert last["rules"] == ["R-a", "R-b", "R-c"]
    assert set(last["columns"]) == {"adj_factor", "qfq_factor"}
    assert das.LAKE_WRITE_GUARD_STATS["blocked_count"] == 1


def test_guard_adjust_only_without_factor_column_blocks():
    svc = _base()
    df = _daily(1.0)
    assert DataAccessService(svc)._assert_unadjusted_for_lake(df, "hfq", "000001.SZ") is False
    assert das.LAKE_WRITE_GUARD_STATS["last_blocked"]["rules"] == ["R-a", "R-c"]
