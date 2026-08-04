"""Smoke tests for data scripts with 0% coverage."""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_PACKAGE = "uniquant.data.scripts"

SCRIPT_NAMES = [
    "download_baostock_factors",
    "download_baostock_pro",
    "sync_daily_mootdx",
    "sync_factors_mootdx",
    "sync_financial_mootdx",
    "sync_minute_mootdx",
    "update_daily_data_akshare",
    "update_daily_incremental",
]


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    for name in list(sys.modules):
        if name.startswith(SCRIPTS_PACKAGE):
            del sys.modules[name]


def _import_script(name: str):
    return importlib.import_module(f"{SCRIPTS_PACKAGE}.{name}")


@pytest.mark.parametrize("name", SCRIPT_NAMES)
def test_import(name: str):
    mod = _import_script(name)
    assert mod is not None


@pytest.mark.parametrize("name", SCRIPT_NAMES)
def test_main_function_exists(name: str):
    mod = _import_script(name)
    assert hasattr(mod, "main")
    assert callable(mod.main)


# --- download_baostock_factors ---

@pytest.fixture
def mock_baostock():
    def make_adjust_mock():
        return MagicMock(
            error_code="0",
            fields=["code", "dividOperateDate", "foreAdjustFactor", "backAdjustFactor", "adjustFactor"],
            next=MagicMock(side_effect=[True, False]),
            get_row_data=MagicMock(return_value=["sh.600000", "2024-01-01", "1.0", "1.0", "1.0"]),
        )

    with patch(f"{SCRIPTS_PACKAGE}.download_baostock_factors.bs") as mock:
        mock.login.return_value = MagicMock(error_code="0", error_msg="ok")
        mock.query_stock_basic.return_value = MagicMock(
            error_code="0",
            fields=["code", "name"],
            next=MagicMock(side_effect=[True, True, False]),
            get_row_data=MagicMock(side_effect=[["sh.600000", "浦发银行"], ["sz.000001", "平安银行"]]),
        )
        mock.query_adjust_factor.side_effect = [make_adjust_mock(), make_adjust_mock()]
        mock.__version__ = "0.9.0"
        yield mock


def test_download_baostock_factors_main_flow(mock_baostock):
    from uniquant.data.scripts.download_baostock_factors import main

    with patch("pathlib.Path.exists", return_value=False):
        with patch("pathlib.Path.mkdir"):
            with patch("os.path.exists", return_value=False):
                with patch("os.makedirs"):
                    with patch("pandas.DataFrame.to_csv"):
                        main()

    mock_baostock.login.assert_called_once()
    mock_baostock.logout.assert_called_once()


# --- download_baostock_pro ---

@pytest.fixture
def mock_baostock_pro():
    with patch(f"{SCRIPTS_PACKAGE}.download_baostock_pro.bs") as mock:
        mock.login.return_value.error_code = "0"
        mock.query_all_stock.return_value.error_code = "0"
        mock.query_all_stock.return_value.fields = ["code", "name"]
        mock.query_all_stock.return_value.next.side_effect = [True, True, False]
        mock.query_all_stock.return_value.get_row_data.side_effect = [
            ["sh.600000", "浦发银行"], ["sz.000001", "平安银行"],
        ]
        adj_mock = MagicMock()
        adj_mock.error_code = "0"
        adj_mock.fields = ["code", "dividOperateDate", "foreAdjustFactor", "backAdjustFactor", "adjustFactor"]
        adj_mock.next.side_effect = [True, False]
        adj_mock.get_row_data.return_value = ["sh.600000", "2024-01-01", "1.0", "1.0", "1.0"]
        mock.query_adjust_factor.side_effect = [adj_mock, adj_mock]
        yield mock


def test_download_baostock_pro_main_flow(mock_baostock_pro):
    from uniquant.data.scripts.download_baostock_pro import main

    with patch("pandas.read_csv") as mock_csv:
        import pandas as pd
        mock_df = pd.DataFrame({
            "code": ["sh.600000", "sh.600001"],
            "status": [1, 1],
            "name": ["浦发银行", "邯郸钢铁"],
        })
        mock_csv.return_value = mock_df

        with patch("os.path.exists", return_value=False):
            with patch("os.makedirs"):
                with patch("pandas.DataFrame.to_csv"):
                    main()

    # Verify main executed without error
    assert mock_baostock_pro.login.called
    assert mock_baostock_pro.logout.called


# --- sync_daily_mootdx ---

def test_sync_daily_mootdx_get_market_suffix():
    from uniquant.data.scripts.sync_daily_mootdx import get_market_suffix
    assert get_market_suffix("600000") == "SH"
    assert get_market_suffix("000001") == "SZ"
    assert get_market_suffix("300001") == "SZ"
    assert get_market_suffix("430001") == "BJ"


@pytest.fixture
def mock_mootdx_daily():
    with patch(f"{SCRIPTS_PACKAGE}.sync_daily_mootdx.sync_daily") as mock:
        yield mock


def test_sync_daily_mootdx_main_calls_sync(mock_mootdx_daily):
    from uniquant.data.scripts.sync_daily_mootdx import main

    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_parse.return_value = MagicMock(tdx_dir="/fake/tdx", output_dir="/fake/out", symbols=None)
        main()

    mock_mootdx_daily.assert_called_once_with("/fake/tdx", "/fake/out", None)


# --- sync_factors_mootdx ---

def test_sync_factors_mootdx_normalize_code():
    from uniquant.data.scripts.sync_factors_mootdx import normalize_code
    assert normalize_code("600000") == "600000.SH"
    assert normalize_code("000001") == "000001.SZ"
    assert normalize_code("300750") == "300750.SZ"
    assert normalize_code("") is None


@pytest.fixture
def mock_factors_sync():
    with patch(f"{SCRIPTS_PACKAGE}.sync_factors_mootdx.sync_factors") as mock:
        yield mock


def test_sync_factors_mootdx_main_calls_sync(mock_factors_sync):
    from uniquant.data.scripts.sync_factors_mootdx import main

    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_parse.return_value = MagicMock(tdx_dir="/fake/tdx", output_dir="/fake/out", symbols=None)
        main()

    mock_factors_sync.assert_called_once_with("/fake/tdx", "/fake/out", None)


# --- sync_financial_mootdx ---

def test_sync_financial_mootdx_normalize_code():
    from uniquant.data.scripts.sync_financial_mootdx import normalize_code
    assert normalize_code("600000") == "600000.SH"
    assert normalize_code("000001") == "000001.SZ"
    import math
    assert normalize_code(math.nan) is None


@pytest.fixture
def mock_financial_sync():
    with patch(f"{SCRIPTS_PACKAGE}.sync_financial_mootdx.sync_financial") as mock:
        yield mock


def test_sync_financial_mootdx_main_calls_sync(mock_financial_sync):
    from uniquant.data.scripts.sync_financial_mootdx import main

    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_parse.return_value = MagicMock(tdx_dir="/fake/tdx", output_dir="/fake/out", limit=0, symbols=None)
        main()

    mock_financial_sync.assert_called_once_with("/fake/tdx", "/fake/out", 0, None)


# --- sync_minute_mootdx ---

def test_sync_minute_mootdx_get_market_suffix():
    from uniquant.data.scripts.sync_minute_mootdx import get_market_suffix
    assert get_market_suffix("688001") == "SH"
    assert get_market_suffix("000001") == "SZ"


@pytest.fixture
def mock_minute_sync():
    with patch(f"{SCRIPTS_PACKAGE}.sync_minute_mootdx.sync_minute") as mock:
        yield mock


def test_sync_minute_mootdx_main_calls_sync(mock_minute_sync):
    from uniquant.data.scripts.sync_minute_mootdx import main

    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_parse.return_value = MagicMock(tdx_dir="/fake/tdx", output_dir="/fake/out", frequency="5min", symbols=None)
        main()

    mock_minute_sync.assert_called_once_with("/fake/tdx", "/fake/out", "5min", None)


# --- update_daily_data_akshare ---

def test_update_daily_data_akshare_load_stock_list():
    from uniquant.data.scripts.update_daily_data_akshare import load_stock_list

    import pandas as pd
    df = pd.DataFrame({
        "code": ["sh.600000", "sz.000001", "bj.430001", "sh.999999"],
        "status": [1, 1, 1, 1],
        "name": ["a", "b", "c", "d"],
    })
    with patch.object(Path, "exists", return_value=True):
        with patch("pandas.read_csv", return_value=df):
            result = load_stock_list()
    assert len(result) == 3


@pytest.fixture
def mock_akshare_load():
    with patch(f"{SCRIPTS_PACKAGE}.update_daily_data_akshare.load_stock_list") as mock:
        mock.return_value = [("600000", "600000.SH")]
        yield mock


def test_update_daily_data_akshare_main_empty_stock_list():
    from uniquant.data.scripts.update_daily_data_akshare import main

    with patch(f"{SCRIPTS_PACKAGE}.update_daily_data_akshare.load_stock_list", return_value=[]):
        main()


def test_update_daily_data_akshare_main_flow(mock_akshare_load):
    from uniquant.data.scripts.update_daily_data_akshare import main

    with patch(f"{SCRIPTS_PACKAGE}.update_daily_data_akshare.load_progress", return_value=set()):
        with patch(f"{SCRIPTS_PACKAGE}.update_daily_data_akshare.fetch_data") as mock_fetch:
            import pandas as pd
            raw = pd.DataFrame({"日期": ["2024-01-02"], "开盘": [10.0], "收盘": [11.0], "最高": [12.0], "最低": [9.0], "成交量": [1000], "成交额": [10000], "振幅": [1.0], "涨跌幅": [0.1], "换手率": [0.5]})
            qfq = pd.DataFrame({"日期": ["2024-01-02"], "开盘": [10.5], "收盘": [11.5], "最高": [12.5], "最低": [9.5]})
            mock_fetch.return_value = {"raw": raw, "qfq": qfq}
            with patch(f"{SCRIPTS_PACKAGE}.update_daily_data_akshare.save_data", return_value=True):
                with patch("time.sleep"):
                    main()


# --- update_daily_incremental (complex flow tests) ---

@pytest.fixture
def mock_incremental_deps():
    with (
        patch("pathlib.Path.exists") as mock_exists,
        patch("pandas.read_csv") as mock_csv,
        patch("pandas.read_parquet") as mock_parquet,
    ):
        import pandas as pd
        mock_exists.return_value = True
        mock_csv.return_value = pd.DataFrame({
            "code": ["sh.600000"],
            "status": [1],
        })
        mock_parquet.return_value = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-02"]),
            "open": [10.0], "close": [11.0], "high": [12.0], "low": [9.0], "vol": [1000], "amount": [10000],
        })
        yield {"exists": mock_exists, "csv": mock_csv, "parquet": mock_parquet}


def test_incremental_updater_determine_mode_no_local():
    from uniquant.data.scripts.update_daily_incremental import IncrementalUpdater, UpdateMode

    updater = IncrementalUpdater()
    with patch.object(updater, "_get_local_latest_date", return_value=None):
        mode, date = updater._determine_update_mode("600000.SH")
    assert mode == UpdateMode.FULL
    assert date is None


def test_incremental_updater_determine_mode_skip():
    from datetime import datetime
    from unittest.mock import patch as mp
    from uniquant.data.scripts.update_daily_incremental import IncrementalUpdater, UpdateMode

    updater = IncrementalUpdater()
    with patch.object(updater, "_get_local_latest_date") as mock_date:
        mock_date.return_value = datetime(2099, 1, 1)
        with mp("uniquant.data.scripts.update_daily_incremental.get_time_provider") as mock_tp:
            mock_tp.return_value.now.return_value = datetime(2099, 1, 1)
            mode, date = updater._determine_update_mode("600000.SH")

    assert mode == UpdateMode.SKIP


def test_incremental_updater_determine_mode_incremental():
    from datetime import datetime
    from unittest.mock import patch as mp
    from uniquant.data.scripts.update_daily_incremental import IncrementalUpdater, UpdateMode

    updater = IncrementalUpdater()
    with patch.object(updater, "_get_local_latest_date") as mock_date:
        mock_date.return_value = datetime(2024, 6, 1)
        with mp("uniquant.data.scripts.update_daily_incremental.get_time_provider") as mock_tp:
            mock_tp.return_value.now.return_value = datetime(2024, 7, 1)
            mode, date = updater._determine_update_mode("600000.SH")

    assert mode == UpdateMode.INCREMENTAL
    assert date == datetime(2024, 6, 1)


def test_incremental_updater_determine_mode_full():
    from datetime import datetime
    from unittest.mock import patch as mp
    from uniquant.data.scripts.update_daily_incremental import IncrementalUpdater, UpdateMode

    updater = IncrementalUpdater()
    with patch.object(updater, "_get_local_latest_date") as mock_date:
        mock_date.return_value = datetime(2020, 1, 1)
        with mp("uniquant.data.scripts.update_daily_incremental.get_time_provider") as mock_tp:
            mock_tp.return_value.now.return_value = datetime(2024, 7, 1)
            mode, date = updater._determine_update_mode("600000.SH")

    assert mode == UpdateMode.FULL


def test_incremental_updater_update_single_stock_skip():
    from uniquant.data.scripts.update_daily_incremental import (
        IncrementalUpdater,
        UpdateMode,
        UpdateResult,
    )

    updater = IncrementalUpdater()
    with patch.object(updater, "_determine_update_mode", return_value=(UpdateMode.SKIP, None)):
        result = updater.update_single_stock("600000", "600000.SH")
    assert result == UpdateResult.SKIPPED


def test_incremental_updater_update_single_stock_no_new_data():
    from datetime import datetime
    from unittest.mock import patch as mp
    from uniquant.data.scripts.update_daily_incremental import (
        IncrementalUpdater,
        UpdateMode,
        UpdateResult,
    )

    updater = IncrementalUpdater()
    local_date = datetime(2024, 6, 1)
    with patch.object(updater, "_determine_update_mode", return_value=(UpdateMode.INCREMENTAL, local_date)):
        with patch.object(updater, "_fetch_all_adjust_types", return_value=(None, False)):
            with mp("uniquant.data.scripts.update_daily_incremental.get_time_provider") as mock_tp:
                mock_tp.return_value.now.return_value = datetime(2024, 7, 1)
                result = updater.update_single_stock("600000", "600000.SH")
    assert result == UpdateResult.NO_NEW_DATA


def test_incremental_updater_run_empty_stock_list():
    from uniquant.data.scripts.update_daily_incremental import IncrementalUpdater

    updater = IncrementalUpdater()
    with patch.object(updater, "_load_stock_list", return_value=[]):
        updater.run()
    assert updater.stats["total"] == 0


def test_incremental_updater_run_full_flow():
    from uniquant.data.scripts.update_daily_incremental import IncrementalUpdater, UpdateResult

    updater = IncrementalUpdater()
    with patch.object(updater, "_load_stock_list", return_value=[("600000", "600000.SH")]):
        with patch.object(updater, "update_single_stock", return_value=UpdateResult.SUCCESS):
            with patch("time.sleep"):
                updater.run()

    assert updater.stats["total"] == 1
    assert updater.stats["success"] == 1


def test_incremental_updater_run_full_flow_failure():
    from uniquant.data.scripts.update_daily_incremental import IncrementalUpdater, UpdateResult

    updater = IncrementalUpdater()
    with patch.object(updater, "_load_stock_list", return_value=[("600000", "600000.SH")]):
        with patch.object(updater, "update_single_stock", return_value=UpdateResult.FAILED):
            with patch("time.sleep"):
                updater.run()

    assert updater.stats["total"] == 1
    assert updater.stats["failed"] == 1


def test_incremental_main_creates_updater_and_runs():
    from unittest.mock import patch as mp
    from uniquant.data.scripts.update_daily_incremental import main

    mock_updater = MagicMock()
    with mp("uniquant.data.scripts.update_daily_incremental.IncrementalUpdater", return_value=mock_updater):
        with mp("argparse.ArgumentParser.parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(force_full=False, symbols=None)
            main()

    mock_updater.run.assert_called_once_with(force_full=False, symbols_only=None)