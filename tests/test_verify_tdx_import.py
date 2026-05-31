import pytest

pytest.importorskip("pytdx")

from scripts.verify_tdx_import import parse_args


def test_parse_args_defaults():
    args = parse_args([])
    assert args.mode == "sample"
    assert args.sample_size == 200
    assert args.seed == 42


def test_parse_args_custom_mode_and_symbols():
    args = parse_args(["--mode", "latest", "--symbols", "000001.SZ,600000.SH"])
    assert args.mode == "latest"
    assert args.symbols == "000001.SZ,600000.SH"
