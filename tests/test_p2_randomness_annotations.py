from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NON_RESEARCH_MARKER = "NON_RESEARCH_RANDOMNESS"


def test_runtime_network_and_mock_randomness_is_annotated():
    # Step4 S4a & Step5+ 死源/死脚本已随爬虫链彻底清理
    files = [
        "src/uniquant/shared/error_handling.py",
        "src/uniquant/data/utils/akshare_wrapper.py",
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
