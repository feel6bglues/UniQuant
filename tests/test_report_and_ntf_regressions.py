from pathlib import Path
from types import SimpleNamespace

from uniquant.services.analysis.ntf_analysis_engine import NtfAnalysisEngine
from uniquant.services.analysis.report_generator_engine import ReportGeneratorEngine


class _FakeReporter:
    def generate_research_report(self, context):
        raise ValueError("report failed")


class _FakeDataService:
    def get_stock_name(self, ticker):
        return "Ping An Bank"


class _FakeOrchestrator:
    def __init__(self, report_root: Path):
        self.report_root = report_root
        self.data_service = _FakeDataService()
        self.reporter = _FakeReporter()
        self._market_cache = {}
        self._market_cache_date = "2026-04-04"

    def _generate_cache_key(self, prefix: str, **kwargs) -> str:
        return f"{prefix}:{kwargs}"

    def _get_cached_result(self, cache_key: str, use_disk: bool = False):
        return None

    def _set_cached_result(self, cache_key: str, result, use_disk: bool = False, ttl=None):
        return True


def test_run_ntf_detection_returns_failed_result_on_attribute_error(monkeypatch, tmp_path):
    engine = NtfAnalysisEngine(_FakeOrchestrator(tmp_path))

    def raise_attribute_error(self, symbol):
        raise AttributeError("bad ntf engine")

    monkeypatch.setattr(
        "uniquant.brain.ntf.ntf_engine.NTFEngine.detect_intervention",
        raise_attribute_error,
    )

    result = engine.run_ntf_detection("510300.SH")

    assert result.side == "NONE"
    assert result.intensity == 0.0


def test_generate_analysis_report_returns_false_on_reporter_error(tmp_path):
    engine = ReportGeneratorEngine(_FakeOrchestrator(tmp_path))
    data_pack = {"stock": SimpleNamespace(iloc=[{"close": 10.5}])}
    decision_result = {"final_decision": "BUY"}

    ok = engine._generate_analysis_report("000001.SZ", data_pack, decision_result, None)

    assert ok is False


def test_generate_reports_from_results_returns_empty_on_value_error(monkeypatch, tmp_path):
    engine = ReportGeneratorEngine(_FakeOrchestrator(tmp_path))

    class DummyResultsManager:
        def generate_reports_from_results(self, symbols=None, date=None, force=False):
            raise ValueError("batch failed")

    monkeypatch.setattr(
        "uniquant.hands.results_manager.ResultsManager",
        DummyResultsManager,
    )

    result = engine.generate_reports_from_results()

    assert result == {}


def test_list_available_results_returns_empty_on_value_error(monkeypatch, tmp_path):
    engine = ReportGeneratorEngine(_FakeOrchestrator(tmp_path))

    class DummyResultsManager:
        def list_results(self, symbol=None):
            raise ValueError("list failed")

    monkeypatch.setattr(
        "uniquant.hands.results_manager.ResultsManager",
        DummyResultsManager,
    )

    result = engine.list_available_results()

    assert result == []
