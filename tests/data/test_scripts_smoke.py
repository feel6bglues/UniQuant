"""Smoke tests for data scripts with 0% coverage."""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_PACKAGE = "uniquant.data.scripts"

SCRIPT_NAMES = [
    "sync_minute_mootdx",
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