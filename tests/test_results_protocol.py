import json
import importlib.util
from types import SimpleNamespace
from pathlib import Path

import uniquant.services.analysis_service as analysis_service_module
from uniquant.hands.results_manager import ResultsManager
from uniquant.shared.constants import ResultsConstants


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding=ResultsConstants.ENCODING,
    )


class TestResultsManagerProtocolCompatibility:
    def test_list_results_supports_new_and_legacy_layouts(self, tmp_path):
        manager = ResultsManager(root_dir=tmp_path, use_date_folders=True)
        base = tmp_path / "hands" / "results"

        _write_json(base / "2026-04-01" / "000001.SZ.json", {"symbol": "000001.SZ"})
        _write_json(base / "20260401" / "000002.SZ_20260401.json", {"symbol": "000002.SZ"})
        _write_json(base / "000003.SZ_20260331.json", {"symbol": "000003.SZ"})

        results = manager.list_results()

        assert {(item["symbol"], item["date"]) for item in results} == {
            ("000001.SZ", "2026-04-01"),
            ("000002.SZ", "2026-04-01"),
            ("000003.SZ", "2026-03-31"),
        }

    def test_list_results_filters_symbol_and_date_across_layouts(self, tmp_path):
        manager = ResultsManager(root_dir=tmp_path, use_date_folders=True)
        base = tmp_path / "hands" / "results"

        _write_json(base / "20260401" / "000001.SZ_20260401.json", {"symbol": "000001.SZ"})
        _write_json(base / "2026-04-01" / "000002.SZ.json", {"symbol": "000002.SZ"})

        filtered = manager.list_results(symbol="000001.SZ", date="2026-04-01")

        assert len(filtered) == 1
        assert filtered[0]["symbol"] == "000001.SZ"
        assert filtered[0]["date"] == "2026-04-01"


def _load_chief_review_module():
    module_path = Path(__file__).resolve().parent.parent / "scripts" / "generate_chief_review.py"
    spec = importlib.util.spec_from_file_location("generate_chief_review", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestChiefReviewCompatibility:
    def test_analyze_single_date_folder_supports_new_result_schema(self, tmp_path, monkeypatch):
        module = _load_chief_review_module()
        results_dir = tmp_path / "hands" / "results"

        _write_json(
            results_dir / "2026-04-01" / "000001.SZ.json",
            {
                "symbol": "000001.SZ",
                "decision_result": {
                    "final_decision": "EXECUTE_BUY",
                    "final_score": 88,
                },
                "data_pack": {
                    "regime": "NORMAL",
                    "risk": "Safe",
                    "ntf_side": "LONG",
                    "is_3rd_buy": True,
                    "alpha_score": 0.03,
                    "ma_status": "MA20 > MA60",
                    "indicators": {
                        "macd": 1.2,
                        "macd_signal": 0.8,
                        "rsi": 28,
                        "vol_ratio": 1.8,
                    },
                },
            },
        )

        monkeypatch.setattr(module, "RESULTS_DIR", results_dir)

        stats = module.analyze_single_date_folder("2026-04-01")

        assert stats["parsed_count"] == 1
        assert stats["decisions"]["EXECUTE_BUY"] == 1
        assert stats["regimes"]["NORMAL"] == 1
        assert stats["lppl_risks"]["Safe"] == 1
        assert stats["ntf_sides"]["LONG"] == 1
        assert stats["czsc_3buy_count"] == 1
        assert stats["trend_bullish"] == 1
        assert stats["macd_golden_cross"] == 1
        assert stats["rsi_oversold"] == 1
        assert stats["volume_surge"] == 1


class TestAnalysisResultSchema:
    def test_save_analysis_result_writes_single_indicators_schema(self, tmp_path, monkeypatch):
        service = object.__new__(analysis_service_module.AnalysisService)
        monkeypatch.setattr(
            analysis_service_module,
            "get_config",
            lambda: SimpleNamespace(ROOT_DIR=tmp_path),
        )

        output = analysis_service_module.AnalysisService._save_analysis_result(
            service,
            "000001.SZ",
            {
                "regime": "NORMAL",
                "risk": "Safe",
                "ntf_side": "NONE",
                "alpha_score": 0.12,
                "ma_status": "MA20 > MA60",
                "indicators": {"rsi": 35.0},
            },
            {"final_decision": "EXECUTE_BUY", "final_score": 88},
        )

        assert output is not None
        payload = json.loads(Path(output).read_text(encoding=ResultsConstants.ENCODING))
        assert payload["indicators"] == {"rsi": 35.0}
        assert "indicators" not in payload["data_pack"]
