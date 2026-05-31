import pytest

try:
    from scripts.tdx_incremental import parse_args
except ImportError:
    pytest.skip("scripts/tdx_incremental.py not found", allow_module_level=True)


def test_parse_args_defaults():
    args = parse_args([])
    assert args.mode == "update-only"
    assert args.sample_size == 100
    assert args.max_workers == 8
    assert args.seed == 42


def test_parse_args_custom_values():
    args = parse_args(
        ["--mode", "update-and-random-validate", "--sample-size", "200", "--max-workers", "4", "--seed", "7"]
    )
    assert args.mode == "update-and-random-validate"
    assert args.sample_size == 200
    assert args.max_workers == 4
    assert args.seed == 7
