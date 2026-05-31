import pytest

try:
    from scripts.stock_list_cli import get_default_output, parse_args
    from scripts import get_a_stocks
except ImportError:
    pytest.skip("scripts/stock_list_cli.py not found", allow_module_level=True)


def test_parse_args_defaults():
    args = parse_args([])
    assert args.mode == "filtered"
    assert args.output is None


def test_parse_args_all_mode_with_output():
    args = parse_args(["--mode", "all", "--output", "tmp.csv"])
    assert args.mode == "all"
    assert args.output == "tmp.csv"


def test_default_outputs():
    assert str(get_default_output(True)).endswith("data/stock_list.csv")
    assert str(get_default_output(False)).endswith("data/all_stock_codes.csv")


def test_get_a_stocks_is_deprecated():
    with pytest.raises(SystemExit) as exc_info:
        get_a_stocks.main()

    assert "baostock_cache_manager" in str(exc_info.value)
