from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NON_RESEARCH_MARKER = "NON_RESEARCH_RANDOMNESS"


def test_runtime_network_and_mock_randomness_is_annotated():
    files = [
        "src/uniquant/shared/error_handling.py",
        "src/uniquant/data/utils/request_utils.py",
        "src/uniquant/data/utils/akshare_wrapper.py",
        "src/uniquant/data/sources/eastmoney.py",
        "src/uniquant/data/sources/sina.py",
        "src/uniquant/data/sources/tencent.py",
        "src/uniquant/data/sources/realtime_bridge.py",
        "src/uniquant/data/scripts/update_daily_data_akshare.py",
        "src/uniquant/data/scripts/update_daily_incremental.py",
        "src/uniquant/data/utils/js_executor.py",
    ]

    missing = [
        path
        for path in files
        if NON_RESEARCH_MARKER
        not in (PROJECT_ROOT / path).read_text(encoding="utf-8")
    ]

    assert missing == []


def test_macro_mock_randomness_remains_seeded_and_explicit():
    files = [
        "src/uniquant/services/analysis/macro_service.py",
        "src/uniquant/services/analysis/macro_analysis_engine.py",
    ]

    for path in files:
        source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
        assert "mock: bool = False" in source
        assert "seed: int = 42" in source
        assert "np.random.default_rng(seed)" in source
