from pathlib import Path

from uniquant.hands.reporter import Reporter
from uniquant.hands.results_manager import ResultsManager
from uniquant.services.analysis.report_generator_engine import ReportGeneratorEngine


class _FakeOrchestrator:
    def __init__(self, report_root: Path):
        self.report_root = report_root


class TestReportPathConventions:
    def test_reporter_writes_to_date_folder_when_report_date_provided(self, tmp_path):
        reporter = Reporter(output_dir=str(tmp_path), use_date_folders=True)

        ok = reporter.generate_research_report(
            {
                "symbol": "000001.SZ",
                "decision_packet": {"final_decision": "EXECUTE_BUY", "final_score": 88},
                "indicators": {"rsi": 30},
                "report_date": "2026-04-01",
            }
        )

        assert ok is True
        assert (tmp_path / "2026-04-01" / "Report_000001.SZ.md").exists()

    def test_report_generator_engine_lists_nested_reports(self, tmp_path):
        report_root = tmp_path / "hands" / "reports"
        report_root.mkdir(parents=True, exist_ok=True)
        nested_report = report_root / "2026-04-01" / "Report_000001.SZ.md"
        nested_report.parent.mkdir(parents=True, exist_ok=True)
        nested_report.write_text("# test", encoding="utf-8")

        engine = ReportGeneratorEngine(_FakeOrchestrator(report_root))
        reports = engine.list_reports()

        assert len(reports) == 1
        assert reports[0]["Filename"] == "Report_000001.SZ.md"

    def test_results_manager_detects_existing_date_folder_report(self, tmp_path, monkeypatch):
        manager = ResultsManager(root_dir=tmp_path, use_date_folders=True)
        report_path = tmp_path / "hands" / "reports" / "2026-04-01" / "Report_000001.SZ.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("# report", encoding="utf-8")

        monkeypatch.setattr(manager, "list_results", lambda date=None: [{"symbol": "000001.SZ", "date": "2026-04-01", "filepath": "dummy"}])
        monkeypatch.setattr(manager, "generate_report_from_result", lambda filepath: (_ for _ in ()).throw(AssertionError("should skip existing report")))

        results = manager.generate_reports_from_results(date="2026-04-01", force=False)

        assert results == {"000001.SZ": True}
