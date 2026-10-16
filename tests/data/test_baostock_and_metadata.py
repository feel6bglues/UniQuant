"""Behaviour tests for four live but undertested data-layer managers.

Covered modules (complementing, not duplicating, the existing tests
``tests/test_baostock_decouple.py`` / ``tests/test_trade_calendar_manager.py`` /
``tests/test_storage_freshness_sla.py``):

* ``uniquant.data.managers._baostock_client``        — protected D5 production asset.
  ``baostock`` is always mocked; the module is never modified.
* ``uniquant.data.managers.baostock_cache_manager`` — ``create_baostock_cache`` write path.
* ``uniquant.data.managers.trade_calendar_manager`` — create/generate/get/builtin paths.
* ``uniquant.data.managers.stock_metadata_manager`` — normalise/parse/infer + delist/IPO logic.

Rules honoured: no network (``baostock``/``akshare`` mocked), all file I/O in
``tmp_path``, nothing under the repo ``data/`` is touched.
"""

from __future__ import annotations

import contextlib
import datetime
import logging
import os
import sys
import time
import types
from datetime import date, datetime as dt
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

import uniquant.data.managers.baostock_cache_manager as bcm
import uniquant.data.managers.stock_metadata_manager as smm
import uniquant.data.managers.trade_calendar_manager as tcm
from uniquant.data.managers import _baostock_client as client
from uniquant.data.managers.stock_metadata_manager import (
    StockMetadata,
    StockMetadataManager,
)
from uniquant.shared.time_provider import FrozenTimeProvider

FROZEN_NOW = dt(2026, 10, 16, 9, 30)


# ════════════════════════════════════════════════════════════════════════════
# shared fixtures / helpers
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Neutralise ``time.sleep`` so retry/backoff paths run instantly."""
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)


@contextlib.contextmanager
def _capture(logger_name: str):
    """Temporarily let a factory logger propagate so ``caplog`` can see it."""
    lg = logging.getLogger(logger_name)
    old_propagate, old_level = lg.propagate, lg.level
    lg.propagate = True
    lg.setLevel(logging.DEBUG)
    try:
        yield lg
    finally:
        lg.propagate = old_propagate
        lg.setLevel(old_level)


# ════════════════════════════════════════════════════════════════════════════
# _baostock_client  (mocked baostock only — never touches the network)
# ════════════════════════════════════════════════════════════════════════════

class _FakeResult:
    """Minimal stand-in for a baostock query result (``next``/``get_row_data``)."""

    def __init__(self, rows=None, fields=None, error_code="0", error_msg=""):
        self._rows = list(rows or [])
        self.fields = list(fields or [])
        self.error_code = error_code
        self.error_msg = error_msg
        self._idx = -1

    def next(self):
        self._idx += 1
        return self._idx < len(self._rows)

    def get_row_data(self):
        return self._rows[self._idx]


def _fake_baostock(*, login_error_code="0", login_error_msg="", login_exc=None,
                   stock_result=None, calendar_result=None):
    fake = types.ModuleType("baostock")
    if login_exc is not None:
        fake.login = MagicMock(side_effect=login_exc)
    else:
        fake.login = MagicMock(
            return_value=SimpleNamespace(error_code=login_error_code, error_msg=login_error_msg)
        )
    fake.logout = MagicMock()
    fake.query_stock_basic = MagicMock(
        return_value=stock_result if stock_result is not None else _FakeResult()
    )
    fake.query_trade_dates = MagicMock(
        return_value=calendar_result if calendar_result is not None else _FakeResult()
    )
    return fake


def _install_baostock(monkeypatch, fake):
    monkeypatch.setitem(sys.modules, "baostock", fake)
    return fake


@pytest.fixture(autouse=True)
def _reset_client_state(monkeypatch):
    """Reset the module-level login singleton so tests cannot leak state."""
    monkeypatch.setattr(client, "_logged_in", False)
    monkeypatch.setattr(client, "_bs", None)
    yield


def _client_logged_in(monkeypatch, fake):
    monkeypatch.setattr(client, "_logged_in", True)
    monkeypatch.setattr(client, "_bs", fake)
    return fake


class TestBaostockClientLogin:
    def test_login_success_sets_singleton_state(self, monkeypatch):
        fake = _install_baostock(monkeypatch, _fake_baostock())
        assert client.login() is True
        assert client._logged_in is True
        assert client._bs is fake
        fake.login.assert_called_once_with()

    def test_login_cached_short_circuits_without_import(self, monkeypatch):
        # sys.modules['baostock'] = None makes any subsequent ``import baostock`` raise.
        monkeypatch.setitem(sys.modules, "baostock", None)
        monkeypatch.setattr(client, "_logged_in", True)
        monkeypatch.setattr(client, "_bs", object())
        assert client.login() is True

    def test_login_reports_non_zero_error_code(self, monkeypatch):
        _install_baostock(
            monkeypatch,
            _fake_baostock(login_error_code="10001", login_error_msg="bad credentials"),
        )
        assert client.login() is False
        assert client._logged_in is False

    def test_login_import_error_returns_false(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "baostock", None)
        assert client.login() is False

    def test_login_runtime_error_returns_false(self, monkeypatch):
        _install_baostock(monkeypatch, _fake_baostock(login_exc=RuntimeError("boom")))
        assert client.login() is False
        assert client._logged_in is False

    def test_login_connection_error_returns_false(self, monkeypatch):
        _install_baostock(monkeypatch, _fake_baostock(login_exc=ConnectionError("net down")))
        assert client.login() is False


class TestBaostockClientLogout:
    def test_logout_when_logged_in_calls_client(self, monkeypatch):
        fake = _fake_baostock()
        monkeypatch.setattr(client, "_logged_in", True)
        monkeypatch.setattr(client, "_bs", fake)
        client.logout()
        fake.logout.assert_called_once_with()
        assert client._logged_in is False

    def test_logout_noop_when_not_logged_in(self, monkeypatch):
        fake = _fake_baostock()
        monkeypatch.setattr(client, "_logged_in", False)
        monkeypatch.setattr(client, "_bs", fake)
        client.logout()
        fake.logout.assert_not_called()

    def test_logout_swallows_transport_errors_and_keeps_flag(self, monkeypatch):
        fake = _fake_baostock()
        fake.logout.side_effect = RuntimeError("already gone")
        monkeypatch.setattr(client, "_logged_in", True)
        monkeypatch.setattr(client, "_bs", fake)
        client.logout()  # must not raise
        assert client._logged_in is True


class TestBaostockClientFetchStockList:
    FIELDS = ["code", "code_name", "ipoDate", "outDate", "type", "status"]

    def test_returns_empty_when_login_fails(self, monkeypatch):
        monkeypatch.setattr(client, "login", lambda: False)
        out = client.fetch_stock_list()
        assert isinstance(out, pd.DataFrame)
        assert out.empty

    def test_success_builds_dataframe_from_rows(self, monkeypatch):
        rows = [
            ["sh.600519", "贵州茅台", "2001-08-27", "", "1", "1"],
            ["sz.000001", "平安银行", "1991-04-03", "", "1", "1"],
        ]
        fake = _install_baostock(
            monkeypatch,
            _fake_baostock(stock_result=_FakeResult(rows=rows, fields=self.FIELDS)),
        )
        _client_logged_in(monkeypatch, fake)
        out = client.fetch_stock_list()
        assert list(out.columns) == self.FIELDS
        assert len(out) == 2
        assert out.iloc[0]["code_name"] == "贵州茅台"
        fake.query_stock_basic.assert_called_once_with()

    def test_query_error_code_returns_empty(self, monkeypatch):
        fake = _install_baostock(
            monkeypatch,
            _fake_baostock(stock_result=_FakeResult(error_code="1", error_msg="server error")),
        )
        _client_logged_in(monkeypatch, fake)
        assert client.fetch_stock_list().empty

    def test_empty_result_set_returns_empty(self, monkeypatch):
        fake = _install_baostock(
            monkeypatch, _fake_baostock(stock_result=_FakeResult(rows=[], fields=self.FIELDS))
        )
        _client_logged_in(monkeypatch, fake)
        assert client.fetch_stock_list().empty

    def test_include_delisted_false_filters_status(self, monkeypatch):
        rows = [
            ["sh.600519", "上市", "", "", "1", "1"],
            ["sz.400001", "退市", "", "2020-01-01", "1", "0"],
        ]
        fake = _install_baostock(
            monkeypatch,
            _fake_baostock(stock_result=_FakeResult(rows=rows, fields=self.FIELDS)),
        )
        _client_logged_in(monkeypatch, fake)
        out = client.fetch_stock_list(include_delisted=False)
        assert list(out["code"]) == ["sh.600519"]
        assert set(out["status"]) == {"1"}

    def test_include_delisted_true_keeps_all(self, monkeypatch):
        rows = [
            ["sh.600519", "上市", "", "", "1", "1"],
            ["sz.400001", "退市", "", "2020-01-01", "1", "0"],
        ]
        fake = _install_baostock(
            monkeypatch,
            _fake_baostock(stock_result=_FakeResult(rows=rows, fields=self.FIELDS)),
        )
        _client_logged_in(monkeypatch, fake)
        assert len(client.fetch_stock_list(include_delisted=True)) == 2

    def test_internal_value_error_is_swallowed_to_empty(self, monkeypatch):
        fake = _fake_baostock()
        fake.query_stock_basic.side_effect = ValueError("bad payload")
        _client_logged_in(monkeypatch, fake)
        assert client.fetch_stock_list().empty

    def test_unexpected_error_retries_then_raises(self, monkeypatch):
        """`@handle_errors(reraise=True)` + `@retry(max_retries=3)` re-raise after 4 attempts."""
        fake = _fake_baostock()
        fake.query_stock_basic.side_effect = AttributeError("unexpected")
        _client_logged_in(monkeypatch, fake)
        with pytest.raises(AttributeError):
            client.fetch_stock_list(date="2024-01-02")
        assert fake.query_stock_basic.call_count == 4


class TestBaostockClientFetchCalendar:
    FIELDS = ["calendar_date", "is_trading_day"]

    def test_returns_empty_when_login_fails(self, monkeypatch):
        monkeypatch.setattr(client, "login", lambda: False)
        assert client.fetch_calendar("2026-01-01", "2026-12-31").empty

    def test_success_renames_and_casts_trading_flag(self, monkeypatch):
        rows = [["2026-01-05", "1"], ["2026-01-01", "0"]]
        fake = _install_baostock(
            monkeypatch,
            _fake_baostock(calendar_result=_FakeResult(rows=rows, fields=self.FIELDS)),
        )
        _client_logged_in(monkeypatch, fake)
        out = client.fetch_calendar(start_date="2026-01-01", end_date="2026-01-05")
        assert list(out.columns) == ["trade_date", "is_trading_day"]
        assert out["is_trading_day"].dtype == bool
        assert list(out["is_trading_day"]) == [True, False]
        fake.query_trade_dates.assert_called_once_with(
            start_date="2026-01-01", end_date="2026-01-05"
        )

    def test_query_error_code_returns_empty(self, monkeypatch):
        fake = _install_baostock(
            monkeypatch,
            _fake_baostock(calendar_result=_FakeResult(error_code="1", error_msg="bad")),
        )
        _client_logged_in(monkeypatch, fake)
        assert client.fetch_calendar("2026-01-01", "2026-01-05").empty

    def test_empty_result_set_returns_empty(self, monkeypatch):
        fake = _install_baostock(
            monkeypatch, _fake_baostock(calendar_result=_FakeResult(rows=[], fields=self.FIELDS))
        )
        _client_logged_in(monkeypatch, fake)
        assert client.fetch_calendar("2026-01-01", "2026-01-05").empty

    def test_missing_calendar_date_column_is_not_renamed(self, monkeypatch):
        rows = [["2026-01-05", "1"]]
        fake = _install_baostock(
            monkeypatch,
            _fake_baostock(
                calendar_result=_FakeResult(rows=rows, fields=["some_date", "is_trading_day"])
            ),
        )
        _client_logged_in(monkeypatch, fake)
        out = client.fetch_calendar("2026-01-01", "2026-01-05")
        assert "trade_date" not in out.columns
        assert list(out.columns) == ["some_date", "is_trading_day"]

    def test_internal_type_error_is_swallowed_to_empty(self, monkeypatch):
        fake = _fake_baostock()
        fake.query_trade_dates.side_effect = TypeError("bad payload")
        _client_logged_in(monkeypatch, fake)
        assert client.fetch_calendar("2026-01-01", "2026-01-05").empty


# ════════════════════════════════════════════════════════════════════════════
# baostock_cache_manager
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def cache_env(tmp_path, monkeypatch):
    """Isolated output paths + mocked baostock.

    §7.4 #7: ``create_baostock_cache`` now writes to the absolute SSOT constant
    ``bcm.OUTPUT_PATH`` (no CWD dependence), so the fixture must retarget it onto
    ``tmp_path`` — otherwise these tests would overwrite the real, tracked
    ``data/all_stock_codes.csv``. ``chdir`` is kept so any *other* accidental
    relative write still lands inside tmp.
    """
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(bcm, "OUTPUT_PATH", data_dir / "all_stock_codes.csv")
    monkeypatch.setattr(bcm, "TEMP_PATH", data_dir / "all_stock_codes_temp.csv")
    monkeypatch.setattr(bcm, "get_time_provider", lambda: FrozenTimeProvider(FROZEN_NOW))
    monkeypatch.setattr(bcm.baostock, "login", MagicMock(return_value=True))
    monkeypatch.setattr(bcm.baostock, "logout", MagicMock())
    return tmp_path


def test_cache_output_paths_are_absolute_ssot():
    """§7.4 #7: cache output must be the absolute SSOT, never CWD-relative."""
    from uniquant.shared.constants.path import STOCK_LIST_FILE

    assert bcm.OUTPUT_PATH.is_absolute()
    assert bcm.OUTPUT_PATH == STOCK_LIST_FILE
    assert bcm.TEMP_PATH.is_absolute()
    assert bcm.TEMP_PATH != bcm.OUTPUT_PATH


def test_cache_writes_to_absolute_path_not_cwd(tmp_path, monkeypatch):
    """§7.4 #7 regression: running from an unrelated CWD writes to the configured
    absolute path and creates no ``data/`` directory in the current directory."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    outdir = tmp_path / "elsewhere"
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(bcm, "OUTPUT_PATH", outdir / "all_stock_codes.csv")
    monkeypatch.setattr(bcm, "TEMP_PATH", outdir / "all_stock_codes_temp.csv")
    monkeypatch.setattr(bcm, "get_time_provider", lambda: FrozenTimeProvider(FROZEN_NOW))
    monkeypatch.setattr(bcm.baostock, "login", MagicMock(return_value=True))
    monkeypatch.setattr(bcm.baostock, "logout", MagicMock())
    monkeypatch.setattr(bcm.baostock, "fetch_stock_list", MagicMock(return_value=_stock_list_df()))

    bcm.create_baostock_cache()

    assert (outdir / "all_stock_codes.csv").exists()
    assert not (cwd / "data").exists()


def _stock_list_df():
    return pd.DataFrame(
        {
            "code": ["sh.600519", "sz.000001"],
            "code_name": ["贵州茅台", "平安银行"],
            "ipoDate": ["2001-08-27", "1991-04-03"],
            "outDate": ["", ""],
            "type": ["1", "1"],
            "status": ["1", "1"],
        }
    )


class TestBaostockCacheManager:
    def test_happy_path_writes_csv_with_code_and_name(self, cache_env, monkeypatch):
        fetch = MagicMock(return_value=_stock_list_df())
        monkeypatch.setattr(bcm.baostock, "fetch_stock_list", fetch)

        bcm.create_baostock_cache()

        out = cache_env / "data" / "all_stock_codes.csv"
        assert out.exists()
        # read as raw strings: default dtype inference would turn "000001" into int 1
        written = pd.read_csv(out, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        assert list(written["代码"]) == ["600519", "000001"]
        assert list(written["name"]) == ["贵州茅台", "平安银行"]
        # optional columns carried through
        assert {"ipoDate", "outDate", "type", "status"}.issubset(written.columns)
        # query date comes from the (patched) time provider
        fetch.assert_called_once_with(date="2026-10-16")
        # temp file is cleaned up by the finally block
        assert not (cache_env / "data" / "all_stock_codes_temp.csv").exists()
        bcm.baostock.logout.assert_called_once_with()

    def test_login_failure_skips_fetch_and_write(self, cache_env, monkeypatch):
        monkeypatch.setattr(bcm.baostock, "login", MagicMock(return_value=False))
        fetch = MagicMock(return_value=_stock_list_df())
        monkeypatch.setattr(bcm.baostock, "fetch_stock_list", fetch)

        bcm.create_baostock_cache()

        assert not (cache_env / "data" / "all_stock_codes.csv").exists()
        fetch.assert_not_called()
        bcm.baostock.logout.assert_called_once_with()

    def test_empty_stock_list_does_not_write(self, cache_env, monkeypatch):
        monkeypatch.setattr(bcm.baostock, "fetch_stock_list", MagicMock(return_value=pd.DataFrame()))
        bcm.create_baostock_cache()
        assert not (cache_env / "data" / "all_stock_codes.csv").exists()
        bcm.baostock.logout.assert_called_once_with()

    def test_missing_code_column_does_not_write(self, cache_env, monkeypatch):
        df = pd.DataFrame({"foo": ["bar"], "code_name": ["x"]})
        monkeypatch.setattr(bcm.baostock, "fetch_stock_list", MagicMock(return_value=df))
        bcm.create_baostock_cache()
        assert not (cache_env / "data" / "all_stock_codes.csv").exists()
        bcm.baostock.logout.assert_called_once_with()

    def test_existing_name_column_is_preserved(self, cache_env, monkeypatch):
        df = pd.DataFrame({"code": ["sh.600519"], "name": ["贵州茅台"]})
        monkeypatch.setattr(bcm.baostock, "fetch_stock_list", MagicMock(return_value=df))
        bcm.create_baostock_cache()
        written = pd.read_csv(cache_env / "data" / "all_stock_codes.csv", encoding="utf-8-sig")
        assert list(written["name"]) == ["贵州茅台"]

    def test_missing_name_columns_falls_back_to_empty_string(self, cache_env, monkeypatch):
        df = pd.DataFrame({"code": ["sh.600519"]})
        monkeypatch.setattr(bcm.baostock, "fetch_stock_list", MagicMock(return_value=df))
        bcm.create_baostock_cache()
        written = pd.read_csv(
            cache_env / "data" / "all_stock_codes.csv",
            encoding="utf-8-sig",
            keep_default_na=False,
        )
        assert list(written["name"]) == [""]

    def test_outer_exception_is_contained_and_logs_out(self, cache_env, monkeypatch):
        monkeypatch.setattr(
            bcm.baostock, "fetch_stock_list", MagicMock(side_effect=ValueError("boom"))
        )
        bcm.create_baostock_cache()  # must not raise
        assert not (cache_env / "data" / "all_stock_codes.csv").exists()
        bcm.baostock.logout.assert_called_once_with()

    def test_save_failure_cleans_temp_file(self, cache_env, monkeypatch):
        monkeypatch.setattr(bcm.baostock, "fetch_stock_list", MagicMock(return_value=_stock_list_df()))
        monkeypatch.setattr("shutil.move", MagicMock(side_effect=OSError("disk full")))

        bcm.create_baostock_cache()

        assert not (cache_env / "data" / "all_stock_codes.csv").exists()
        assert not (cache_env / "data" / "all_stock_codes_temp.csv").exists()
        bcm.baostock.logout.assert_called_once_with()

    def test_verification_getsize_error_is_logged(self, cache_env, monkeypatch, caplog):
        # Pre-existing output + a frame without "code" => save block skipped,
        # only the verification ``os.path.getsize`` runs and must be guarded.
        data_dir = cache_env / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "all_stock_codes.csv").write_text("stale", encoding="utf-8")
        monkeypatch.setattr(bcm.baostock, "fetch_stock_list",
                            MagicMock(return_value=pd.DataFrame({"foo": [1]})))
        monkeypatch.setattr(os.path, "getsize", MagicMock(side_effect=OSError("stat failed")))

        with _capture("BaostockCacheManager"):
            with caplog.at_level(logging.ERROR):
                bcm.create_baostock_cache()

        assert (data_dir / "all_stock_codes.csv").exists()
        assert any("验证文件失败" in r.message for r in caplog.records)


# ════════════════════════════════════════════════════════════════════════════
# trade_calendar_manager
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def calendar_env(tmp_path, monkeypatch):
    """Isolated data dir; akshare neutralised so construction never hits the network."""
    import akshare

    monkeypatch.setattr(akshare, "tool_trade_date_hist_sina", lambda: pd.DataFrame())
    monkeypatch.setattr(tcm, "get_time_provider", lambda: FrozenTimeProvider(FROZEN_NOW))
    monkeypatch.setattr(tcm.baostock, "logout", MagicMock())
    return tmp_path


def _calendar_manager(data_dir, monkeypatch, *, akshare_df=None):
    import akshare

    monkeypatch.setattr(
        akshare,
        "tool_trade_date_hist_sina",
        lambda: (akshare_df if akshare_df is not None else pd.DataFrame()),
    )
    return tcm.TradeCalendarManager(data_dir=str(data_dir))


def _write_year_file(data_dir, year, dates):
    pd.DataFrame({"trade_date": pd.to_datetime(dates)}).to_csv(
        Path(data_dir) / f"trade_calendar_{year}.csv", index=False, encoding="utf-8-sig"
    )


def _patch_baostock_calendar(monkeypatch, *, login=True, calendar=None):
    monkeypatch.setattr(tcm.baostock, "login", MagicMock(return_value=login))
    logout = MagicMock()
    monkeypatch.setattr(tcm.baostock, "logout", logout)
    fetch = MagicMock(return_value=calendar if calendar is not None else pd.DataFrame())
    monkeypatch.setattr(tcm.baostock, "fetch_calendar", fetch)
    return fetch, logout


class TestTradeCalendarAutoUpdate:
    def test_corrupt_local_cache_falls_through_to_akshare(self, calendar_env, monkeypatch, caplog):
        (calendar_env / "trade_calendar.csv").write_bytes(b"\x00\x01garbage\xff")
        with _capture("TradeCalendarManager"):
            with caplog.at_level(logging.WARNING):
                mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        assert mgr._akshare_calendar is None
        assert any("加载本地交易日历失败" in r.message for r in caplog.records)

    def test_akshare_success_writes_main_and_year_files(self, calendar_env, monkeypatch):
        df = pd.DataFrame({"trade_date": pd.to_datetime(["2026-01-05", "2026-01-06"])})
        mgr = _calendar_manager(calendar_env, monkeypatch, akshare_df=df)

        assert mgr._akshare_calendar == {"2026-01-05", "2026-01-06"}
        assert (calendar_env / "trade_calendar.csv").exists()
        assert (calendar_env / "trade_calendar_2026.csv").exists()

    def test_fresh_local_cache_skips_akshare(self, calendar_env, monkeypatch):
        _write_year_file(calendar_env, 2026, ["2026-01-05"])
        pd.DataFrame({"trade_date": ["2026-01-05"]}).to_csv(
            calendar_env / "trade_calendar.csv", index=False, encoding="utf-8-sig"
        )
        spy = MagicMock(return_value=pd.DataFrame())
        import akshare

        monkeypatch.setattr(akshare, "tool_trade_date_hist_sina", spy)

        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))

        spy.assert_not_called()
        assert mgr._akshare_calendar == {"2026-01-05"}


class TestTradeCalendarCreate:
    def test_create_writes_per_year_files_and_calls_calendar(self, calendar_env, monkeypatch):
        cal = pd.DataFrame({"trade_date": pd.to_datetime(["2025-12-31", "2026-01-05"])})
        fetch, logout = _patch_baostock_calendar(monkeypatch, calendar=cal)
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))

        mgr.create_trade_calendar()

        assert (calendar_env / "trade_calendar_2025.csv").exists()
        assert (calendar_env / "trade_calendar_2026.csv").exists()
        written = pd.read_csv(calendar_env / "trade_calendar_2025.csv", encoding="utf-8-sig")
        assert list(written["trade_date"]) == ["2025-12-31"]
        fetch.assert_called_once_with(start_date="2000-01-01", end_date="2026-10-16")
        logout.assert_called_once_with()

    def test_create_login_failure_skips_fetch(self, calendar_env, monkeypatch):
        fetch, logout = _patch_baostock_calendar(monkeypatch, login=False)
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))

        mgr.create_trade_calendar()

        fetch.assert_not_called()
        logout.assert_called_once_with()
        assert not (calendar_env / "trade_calendar_2025.csv").exists()

    def test_create_empty_calendar_writes_nothing(self, calendar_env, monkeypatch):
        fetch, logout = _patch_baostock_calendar(monkeypatch, calendar=pd.DataFrame())
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))

        mgr.create_trade_calendar()

        assert not list(Path(calendar_env).glob("trade_calendar_2*.csv"))
        logout.assert_called_once_with()

    def test_create_missing_trade_date_column_writes_nothing(self, calendar_env, monkeypatch):
        cal = pd.DataFrame({"foo": [1, 2]})
        _fetch, logout = _patch_baostock_calendar(monkeypatch, calendar=cal)
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))

        mgr.create_trade_calendar()

        assert not list(Path(calendar_env).glob("trade_calendar_2*.csv"))
        logout.assert_called_once_with()

    def test_create_contained_exception_still_logs_out(self, calendar_env, monkeypatch):
        monkeypatch.setattr(tcm.baostock, "login", MagicMock(return_value=True))
        logout = MagicMock()
        monkeypatch.setattr(tcm.baostock, "logout", logout)
        monkeypatch.setattr(
            tcm.baostock, "fetch_calendar", MagicMock(side_effect=ValueError("boom"))
        )
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))

        mgr.create_trade_calendar()  # must not raise

        logout.assert_called_once_with()


class TestTradeCalendarGenerate:
    def test_reads_existing_year_file(self, calendar_env):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        _write_year_file(calendar_env, 2026, ["2026-01-05", "2026-01-06"])

        df = mgr.generate_trade_calendar(2026)

        assert len(df) == 2
        assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])

    def test_missing_year_file_returns_empty(self, calendar_env):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        assert mgr.generate_trade_calendar(2099).empty

    def test_force_update_skips_existing_file(self, calendar_env):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        _write_year_file(calendar_env, 2026, ["2026-01-05"])
        assert mgr.generate_trade_calendar(2026, force_update=True).empty

    def test_corrupt_year_file_returns_empty(self, calendar_env):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        (calendar_env / "trade_calendar_2026.csv").write_bytes(b"\x00\xff not a csv")
        assert mgr.generate_trade_calendar(2026).empty

    def test_file_without_trade_date_column_returned_as_is(self, calendar_env):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        pd.DataFrame({"foo": [1]}).to_csv(
            calendar_env / "trade_calendar_2026.csv", index=False
        )
        df = mgr.generate_trade_calendar(2026)
        assert list(df.columns) == ["foo"]


class TestTradeCalendarIsTradingDay:
    def test_prefers_year_file_membership(self, calendar_env):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        _write_year_file(calendar_env, 2026, ["2026-01-05"])

        assert mgr.is_trading_day(datetime.date(2026, 1, 5)) is True
        assert mgr.is_trading_day(datetime.date(2026, 1, 6)) is False

    def test_uses_akshare_calendar_when_year_file_missing(self, calendar_env, monkeypatch):
        df = pd.DataFrame({"trade_date": pd.to_datetime(["2026-01-05", "2026-01-06"])})
        mgr = _calendar_manager(calendar_env, monkeypatch, akshare_df=df)
        (calendar_env / "trade_calendar_2026.csv").unlink()

        assert mgr.is_trading_day(datetime.date(2026, 1, 5)) is True
        # year data exists but date is absent => non-trading, no hardcoded fallback
        assert mgr.is_trading_day(datetime.date(2026, 1, 7)) is False

    def test_corrupt_year_file_falls_back_to_hardcoded_table(self, calendar_env):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        (calendar_env / "trade_calendar_2026.csv").write_bytes(b"\x00\x01garbage\xff")

        assert mgr.is_trading_day(datetime.date(2026, 1, 5)) is True   # Monday, not a holiday
        assert mgr.is_trading_day(datetime.date(2026, 1, 1)) is False  # New Year
        assert mgr.is_trading_day(datetime.date(2026, 1, 3)) is False  # Saturday

    def test_bad_input_type_returns_false(self, calendar_env):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        assert mgr.is_trading_day("not-a-date") is False


class TestTradeCalendarGetAndBuiltin:
    def test_get_trade_calendar_concatenates_and_filters(self, calendar_env):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        _write_year_file(calendar_env, 2025, ["2025-05-06", "2025-12-31"])
        _write_year_file(calendar_env, 2026, ["2026-01-05", "2026-06-01"])

        out = mgr.get_trade_calendar("2025-12-01", "2026-03-01")

        assert list(out["trade_date"].dt.strftime("%Y-%m-%d")) == ["2025-12-31", "2026-01-05"]

    def test_get_trade_calendar_uses_builtin_when_no_files(self, calendar_env):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        out = mgr.get_trade_calendar("2025-05-01", "2025-05-06")
        # 05-01..05-05 are hardcoded holidays, 05-06 is the only trading day
        assert list(out["trade_date"].dt.strftime("%Y-%m-%d")) == ["2025-05-06"]

    def test_get_trade_calendar_falls_back_on_internal_error(self, calendar_env, monkeypatch):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        monkeypatch.setattr(
            mgr, "generate_trade_calendar", MagicMock(side_effect=RuntimeError("boom"))
        )
        out = mgr.get_trade_calendar("2025-05-01", "2025-05-06")
        assert list(out["trade_date"].dt.strftime("%Y-%m-%d")) == ["2025-05-06"]

    def test_get_trade_calendar_invalid_dates_propagate_from_fallback(self, calendar_env):
        """Pins current behaviour: the 'graceful' fallback re-parses the bad dates and raises."""
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        with pytest.raises(ValueError):
            mgr.get_trade_calendar("not-a-date", "also-bad")

    def test_builtin_calendar_empty_when_range_is_only_weekend(self, calendar_env):
        mgr = tcm.TradeCalendarManager(data_dir=str(calendar_env))
        df = mgr._builtin_trade_calendar("2025-05-03", "2025-05-03")
        assert df.empty


# ════════════════════════════════════════════════════════════════════════════
# stock_metadata_manager
# ════════════════════════════════════════════════════════════════════════════

def _write_metadata_csv(data_dir, df=None):
    if df is None:
        df = pd.DataFrame(
            {
                "code": ["sh.600519", "sz.000001", "bj.430047"],
                "code_name": ["贵州茅台", "平安银行", "诺思兰德"],
                "代码": ["600519", "000001", "430047"],
                "ipoDate": ["2001-08-27", "1991-04-03", ""],
                "outDate": ["", "2023-05-10", ""],
                "type": ["1", "1", "1"],
                "status": ["1", "0", "1"],
            }
        )
    path = Path(data_dir) / "all_stock_codes.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


class TestNormalizeStockCode:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("sh.600519", "600519.SH"),
            ("sz.000001", "000001.SZ"),
            ("sz.300750", "300750.SZ"),
            ("bj.430047", "430047.BJ"),
            ("600519.SH", "600519.SH"),
            ("688981", "688981.SH"),
            ("000001", "000001.SZ"),
            ("300750", "300750.SZ"),
            ("830799", "830799.BJ"),
            ("870508", "870508.BJ"),
            ("430047", "430047.BJ"),
            ("200011", "200011.SH"),  # unmatched prefix -> default .SH
        ],
    )
    def test_maps_to_suffix_form(self, raw, expected):
        assert smm._normalize_stock_code(raw) == expected

    @pytest.mark.parametrize("raw", ["", None, float("nan"), ".SH", "  "])
    def test_unresolvable_returns_empty(self, raw):
        assert smm._normalize_stock_code(raw) == ""


class TestInferMarket:
    @pytest.mark.parametrize(
        ("code", "market"),
        [
            ("600519.SH", "SH"),
            ("688981.SH", "SH"),
            ("000001.SZ", "SZ"),
            ("300750.SZ", "SZ"),
            ("430047.BJ", "BJ"),
            ("830799.BJ", "BJ"),
            ("870508.BJ", "BJ"),
            ("200011.SZ", ""),
        ],
    )
    def test_market_inference(self, tmp_path, code, market):
        mgr = StockMetadataManager(str(tmp_path))
        assert mgr._infer_market(code) == market


class TestParseDate:
    def test_nat_and_none_return_none(self, tmp_path):
        mgr = StockMetadataManager(str(tmp_path))
        assert mgr._parse_date(float("nan")) is None
        assert mgr._parse_date(pd.NaT) is None

    def test_date_instance_passthrough(self, tmp_path):
        mgr = StockMetadataManager(str(tmp_path))
        value = date(2020, 1, 1)
        assert mgr._parse_date(value) == value

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("-", None),
            ("None", None),
            ("nan", None),
            ("NaT", None),
            ("", None),
            ("2001-08-27", date(2001, 8, 27)),   # ISO-10
            ("20240102", date(2024, 1, 2)),      # compact 8-digit
            ("2024/01/02", date(2024, 1, 2)),    # parsed by pandas
        ],
    )
    def test_string_forms(self, tmp_path, value, expected):
        mgr = StockMetadataManager(str(tmp_path))
        assert mgr._parse_date(value) == expected

    def test_timestamp_is_a_date_subclass_and_passes_through(self, tmp_path):
        mgr = StockMetadataManager(str(tmp_path))
        ts = pd.Timestamp("2024-01-02")
        # pd.Timestamp IS a datetime.date subclass -> returned unchanged
        assert mgr._parse_date(ts) is ts

    def test_non_date_like_value_parsed_by_pandas(self, tmp_path):
        import numpy as np

        mgr = StockMetadataManager(str(tmp_path))
        assert mgr._parse_date(np.datetime64("2024-01-02")) == date(2024, 1, 2)

    def test_invalid_values_return_none(self, tmp_path):
        mgr = StockMetadataManager(str(tmp_path))
        assert mgr._parse_date("totally-invalid") is None
        assert mgr._parse_date(object()) is None


class TestNormalizeColumns:
    def test_alias_columns_are_renamed(self, tmp_path):
        mgr = StockMetadataManager(str(tmp_path))
        df = pd.DataFrame(
            columns=["ipoDate", "outDate", "type", "status", "code_name", "板块",
                     "volunit", "decimal_point"]
        )
        out = mgr._normalize_columns(df)
        assert set(out.columns) == {
            "ipo_date",
            "delist_date",
            "stock_type",
            "stock_status",
            "name",
            "sector",
            "vol_unit",
            "decimal_point",
        }

    def test_unknown_columns_are_untouched(self, tmp_path):
        mgr = StockMetadataManager(str(tmp_path))
        out = mgr._normalize_columns(pd.DataFrame(columns=["code", "weird"]))
        assert list(out.columns) == ["code", "weird"]


class TestStockMetadataLoad:
    def test_load_parses_rows_and_delist_dates(self, tmp_path):
        _write_metadata_csv(tmp_path)
        mgr = StockMetadataManager(str(tmp_path))

        assert mgr.load() is True

        assert mgr.get_all_codes() == ["600519.SH", "000001.SZ", "430047.BJ"]
        info = mgr.get_stock_info("000001.SZ")
        assert info.name == "平安银行"
        assert info.market == "SZ"
        assert info.ipo_date == date(1991, 4, 3)
        assert info.delist_date == date(2023, 5, 10)
        assert info.stock_type == "1"
        # BJ code with no IPO/outDate -> both None
        assert mgr.get_ipo_date("430047.BJ") is None

    def test_populated_status_column_is_loaded(self, tmp_path):
        """§7.4 #4: the loader used to read ``getattr(row, 'status', ...)`` although
        ``_normalize_columns`` had already renamed ``status``→``stock_status``, so the
        field was always None (which silently disabled the退市状态 signal). The guard
        now uses the normalised column name and the value is loaded."""
        _write_metadata_csv(tmp_path)
        mgr = StockMetadataManager(str(tmp_path))
        mgr.load()
        assert mgr.get_stock_info("000001.SZ").stock_status == "0"
        assert mgr.get_stock_info("600519.SH").stock_status == "1"

    def test_load_skips_empty_and_unresolvable_codes(self, tmp_path, monkeypatch):
        (tmp_path / "all_stock_codes.csv").write_text("code,name\n", encoding="utf-8-sig")
        crafted = pd.DataFrame(
            {"code": ["", ".SH", "sh.600519"], "name": ["x", "y", "贵州茅台"]}
        )
        monkeypatch.setattr(smm.pd, "read_csv", lambda *a, **k: crafted.copy())

        mgr = StockMetadataManager(str(tmp_path))
        assert mgr.load() is True
        assert mgr.get_all_codes() == ["600519.SH"]

    def test_load_returns_false_on_corrupt_file(self, tmp_path):
        (tmp_path / "all_stock_codes.csv").write_bytes(b"\x00\x01garbage\xff")
        mgr = StockMetadataManager(str(tmp_path))
        assert mgr.load() is False

    def test_get_stock_info_unknown_returns_none_and_lazy_loads(self, tmp_path):
        _write_metadata_csv(tmp_path)
        mgr = StockMetadataManager(str(tmp_path))
        assert mgr._loaded is False
        assert mgr.get_stock_info("999999.SH") is None
        assert mgr._loaded is True  # lazy load triggered


class TestStockMetadataAccessors:
    def _manager(self, tmp_path):
        _write_metadata_csv(tmp_path)
        mgr = StockMetadataManager(str(tmp_path))
        mgr.load()
        return mgr

    @pytest.mark.parametrize("code", ["600519.SH", "600519"])
    def test_get_stock_info_accepts_suffix_variants(self, tmp_path, code):
        mgr = self._manager(tmp_path)
        assert mgr.get_stock_info(code).code == "600519.SH"

    def test_get_stock_info_accepts_baostock_prefix(self, tmp_path):
        """§7.4 #5: ``get_stock_info`` now normalises the lookup code the same way the
        cache keys are built, so the baostock ``sh.600519`` form resolves instead of
        silently missing (a miss disables the退市 guard in ``storage_manager``)."""
        mgr = self._manager(tmp_path)
        assert mgr.get_stock_info("sh.600519").code == "600519.SH"
        assert mgr.get_name("sh.600519") == "贵州茅台"
        assert mgr.get_stock_info("sz.000001").code == "000001.SZ"
        assert mgr.get_stock_info("bj.430047").code == "430047.BJ"

    def test_get_name_and_ipo_date_none_for_unknown(self, tmp_path):
        mgr = self._manager(tmp_path)
        assert mgr.get_name("999999.SH") is None
        assert mgr.get_ipo_date("999999.SH") is None
        assert mgr.get_delist_date("999999.SH") is None

    def test_get_name_and_ipo_date_values(self, tmp_path):
        mgr = self._manager(tmp_path)
        assert mgr.get_name("600519.SH") == "贵州茅台"
        assert mgr.get_ipo_date("600519.SH") == date(2001, 8, 27)
        assert mgr.get_delist_date("000001.SZ") == date(2023, 5, 10)

    def test_is_delisted_semantics(self, tmp_path, monkeypatch):
        mgr = self._manager(tmp_path)
        assert mgr.is_delisted("600519.SH") is False          # no delist date
        assert mgr.is_delisted("999999.SH") is False          # unknown
        assert mgr.is_delisted("000001.SZ", as_of=date(2022, 1, 1)) is False
        assert mgr.is_delisted("000001.SZ", as_of=date(2024, 1, 1)) is True
        # default ``as_of`` uses the injected time provider
        monkeypatch.setattr(smm, "get_time_provider", lambda: FrozenTimeProvider(FROZEN_NOW))
        assert mgr.is_delisted("000001.SZ") is True

    def test_is_ipo_semantics(self, tmp_path, monkeypatch):
        mgr = self._manager(tmp_path)
        assert mgr.is_ipo("999999.SH") is True                # unknown => treated as listed
        assert mgr.is_ipo("430047.BJ") is True                # no ipo_date => listed
        assert mgr.is_ipo("600519.SH", as_of=date(1990, 1, 1)) is False
        assert mgr.is_ipo("600519.SH", as_of=date(2020, 1, 1)) is True
        monkeypatch.setattr(smm, "get_time_provider", lambda: FrozenTimeProvider(FROZEN_NOW))
        assert mgr.is_ipo("600519.SH") is True

    def test_get_all_codes_lazy_loads(self, tmp_path):
        _write_metadata_csv(tmp_path)
        mgr = StockMetadataManager(str(tmp_path))
        assert mgr.get_all_codes() == ["600519.SH", "000001.SZ", "430047.BJ"]

    def test_get_active_stocks_filters_delisted(self, tmp_path, monkeypatch):
        _write_metadata_csv(tmp_path)
        mgr = StockMetadataManager(str(tmp_path))
        monkeypatch.setattr(smm, "get_time_provider", lambda: FrozenTimeProvider(FROZEN_NOW))

        active = mgr.get_active_stocks()  # lazy load + default as_of
        assert "000001.SZ" not in active  # delisted 2023
        assert active == ["600519.SH", "430047.BJ"]

        active_2022 = mgr.get_active_stocks(as_of=date(2022, 1, 1))
        assert "000001.SZ" in active_2022

    def test_stock_metadata_dataclass_defaults(self):
        meta = StockMetadata(code="600519.SH", name="贵州茅台", market="SH")
        assert meta.sector is None
        assert meta.ipo_date is None
        assert meta.delist_date is None
        assert meta.stock_type is None
        assert meta.stock_status is None
