import json
from pathlib import Path

from uniquant.hands.results_manager import ResultsManager
from uniquant.shared.constants import ResultsConstants


def _write_result(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding=ResultsConstants.ENCODING)


class TestResultsManagerAdditional:
    def test_read_latest_result_and_statistics(self, tmp_path):
        manager = ResultsManager(root_dir=tmp_path, use_date_folders=True)
        base = tmp_path / "hands" / "results"

        _write_result(
            base / "2026-04-01" / "000001.SZ.json",
            {"symbol": "000001.SZ", "date": "2026-04-01"},
        )
        _write_result(
            base / "2026-04-02" / "000001.SZ.json",
            {"symbol": "000001.SZ", "date": "2026-04-02"},
        )
        _write_result(
            base / "2026-04-02" / "000002.SZ.json",
            {"symbol": "000002.SZ", "date": "2026-04-02"},
        )

        latest = manager.get_latest_result("000001.SZ")
        stats = manager.get_statistics()

        assert latest["date"] == "2026-04-02"
        assert stats["total_results"] == 3
        assert stats["unique_symbols"] == 2
        assert stats["results_dir"].endswith("hands/results")
        assert stats["reports_dir"].endswith("hands/reports")

    def test_read_result_handles_missing_invalid_and_io_error(self, tmp_path, monkeypatch):
        manager = ResultsManager(root_dir=tmp_path, use_date_folders=True)
        missing = manager.read_result(str(tmp_path / "missing.json"))
        assert missing is None

        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("{bad json", encoding="utf-8")
        assert manager.read_result(str(invalid_file)) is None

        valid_file = tmp_path / "valid.json"
        valid_file.write_text('{"symbol": "000001.SZ"}', encoding=ResultsConstants.ENCODING)

        def broken_open(*args, **kwargs):
            raise OSError("open failed")

        monkeypatch.setattr("builtins.open", broken_open)
        assert manager.read_result(str(valid_file)) is None

    def test_generate_report_from_result_success_and_failure(self, tmp_path, monkeypatch):
        manager = ResultsManager(root_dir=tmp_path, use_date_folders=True)
        result_file = tmp_path / "hands" / "results" / "2026-04-02" / "000001.SZ.json"
        _write_result(
            result_file,
            {
                "symbol": "000001.SZ",
                "date": "2026-04-02",
                "decision_result": {"final_decision": "EXECUTE_BUY"},
                "data_pack": {"indicators": {"rsi": 30}},
            },
        )

        contexts = []

        class FakeReporter:
            def __init__(self, output_dir):
                self.output_dir = output_dir

            def generate_research_report(self, context):
                contexts.append(context)
                return True

        monkeypatch.setattr("uniquant.hands.reporter.Reporter", FakeReporter)
        assert manager.generate_report_from_result(str(result_file)) is True
        assert contexts[0]["symbol"] == "000001.SZ"
        assert contexts[0]["indicators"] == {"rsi": 30}
        assert contexts[0]["report_date"] == "2026-04-02"

        monkeypatch.setattr(manager, "read_result", lambda filepath: None)
        assert manager.generate_report_from_result(str(result_file)) is False

        monkeypatch.setattr(manager, "read_result", lambda filepath: {"symbol": "000002.SZ"})

        class BrokenReporter:
            def __init__(self, output_dir):
                self.output_dir = output_dir

            def generate_research_report(self, context):
                raise RuntimeError("boom")

        monkeypatch.setattr("uniquant.hands.reporter.Reporter", BrokenReporter)
        assert manager.generate_report_from_result(str(result_file)) is False

    def test_generate_reports_and_cleanup_old_results(self, tmp_path, monkeypatch):
        manager = ResultsManager(root_dir=tmp_path, use_date_folders=False)
        result_dir = tmp_path / "hands" / "results"
        old_file = result_dir / "000001.SZ_20260301.json"
        new_file = result_dir / "000002.SZ_20260402.json"
        _write_result(old_file, {"symbol": "000001.SZ"})
        _write_result(new_file, {"symbol": "000002.SZ"})

        old_ts = 1_700_000_000
        new_ts = 1_900_000_000

        def fake_stat(self):
            stat = Path.__dict__["stat"](self)
            if self == old_file:
                return type("Stat", (), {"st_size": stat.st_size, "st_mtime": old_ts})()
            if self == new_file:
                return type("Stat", (), {"st_size": stat.st_size, "st_mtime": new_ts})()
            return stat

        called = []
        monkeypatch.setattr(manager, "generate_report_from_result", lambda filepath: called.append(filepath) or filepath.endswith("000002.SZ_20260402.json"))
        results = manager.generate_reports_from_results(symbols=["000002.SZ"], force=True)

        assert list(results.keys()) == ["000002.SZ"]
        assert called == [str(new_file)]

        original_stat = Path.stat

        def patched_stat(self, *args, **kwargs):
            stat = original_stat(self, *args, **kwargs)
            if self == old_file:
                return type("Stat", (), {"st_size": stat.st_size, "st_mtime": old_ts})()
            if self == new_file:
                return type("Stat", (), {"st_size": stat.st_size, "st_mtime": new_ts})()
            return stat

        monkeypatch.setattr(Path, "stat", patched_stat)
        removed = manager.cleanup_old_results(days=365)
        assert removed == 1
        assert not old_file.exists()
        assert new_file.exists()
