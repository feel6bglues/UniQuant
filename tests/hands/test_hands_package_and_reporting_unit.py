"""Round-8 unit coverage for the ``hands`` package shim and the reporting layer.

This file is *additive* (new file, no existing test is modified) and targets the
previously-uncovered branches of three modules:

* ``uniquant.hands``            — the lazy ``__getattr__`` import shim (incl. the
  deprecated ``BacktestEngine`` alias and the unknown-attribute error).
* ``uniquant.hands.reporter``   — default config-driven output dir, stock-name
  loading (success / missing / unreadable), flat (non date-folder) output, and the
  ``generate_research_report`` guard rails.
* ``uniquant.hands.results_manager`` — default root resolution, date-folder
  helpers, tolerant listing (date filters, defensive parse guards) and cleanup.

All filesystem activity is confined to ``tmp_path``; the global stock-name SSOT
(``data/all_stock_codes.csv``) is monkeypatched so no test ever touches the
repository ``data/`` tree.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import uniquant.hands as hands
from uniquant.hands.reporter import Reporter
from uniquant.hands.results_manager import ResultsManager
from uniquant.shared.constants import ResultsConstants


def _patch_root_config(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Make the default ``get_config().ROOT_DIR`` resolve to a tmp directory."""
    monkeypatch.setattr(
        "uniquant.shared.config_loader.get_config",
        lambda: SimpleNamespace(ROOT_DIR=root),
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# hands/__init__.py — lazy import shim
# ---------------------------------------------------------------------------

class TestHandsPackageLazyImports:
    """Exercise every branch of ``uniquant.hands.__getattr__``."""

    def test_getattr_reporter_and_results_manager(self):
        from uniquant.hands.reporter import Reporter as RealReporter
        from uniquant.hands.results_manager import ResultsManager as RealResultsManager

        assert hands.__getattr__("Reporter") is RealReporter
        assert hands.__getattr__("ResultsManager") is RealResultsManager

    def test_getattr_engine_and_result_types(self):
        from uniquant.hands.backtest.unified_engine import (
            BacktestResult,
            TradeRecord,
            UnifiedBacktestEngine,
        )

        assert hands.__getattr__("UnifiedBacktestEngine") is UnifiedBacktestEngine
        assert hands.__getattr__("BacktestResult") is BacktestResult
        assert hands.__getattr__("TradeRecord") is TradeRecord

    def test_getattr_backtest_engine_is_deprecated_alias(self):
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine

        with pytest.warns(DeprecationWarning, match="BacktestEngine has been retired"):
            resolved = hands.__getattr__("BacktestEngine")
        assert resolved is UnifiedBacktestEngine

    def test_getattr_submodules(self):
        import uniquant.hands.backtest as backtest_module
        import uniquant.hands.strategies as strategies_module

        assert hands.__getattr__("backtest") is backtest_module
        assert hands.__getattr__("strategies") is strategies_module

    def test_getattr_unknown_raises_attribute_error(self):
        with pytest.raises(AttributeError, match="has no attribute 'definitely_missing'"):
            hands.__getattr__("definitely_missing")


# ---------------------------------------------------------------------------
# hands/reporter.py
# ---------------------------------------------------------------------------

class TestReporterUnit:
    def test_default_output_dir_resolves_from_config(self, tmp_path, monkeypatch):
        _patch_root_config(monkeypatch, tmp_path)
        # Point the SSOT constant at a missing file so the loader takes the
        # "file not found" warning branch without touching the repo data tree.
        monkeypatch.setattr(
            "uniquant.hands.reporter.STOCK_LIST_FILE", tmp_path / "does_not_exist.csv"
        )

        reporter = Reporter()

        expected = (
            tmp_path / ResultsConstants.HANDS_DIR_NAME / ResultsConstants.REPORTS_DIR_NAME
        )
        assert reporter.output_root == expected
        assert reporter.output_root.exists()
        assert reporter.stock_name_map == {}

    def test_load_stock_names_success_and_unreadable(self, tmp_path, monkeypatch):
        csv = tmp_path / "codes.csv"
        csv.write_text("code,code_name\n000001.SZ,平安银行\n", encoding="utf-8")
        monkeypatch.setattr("uniquant.hands.reporter.STOCK_LIST_FILE", csv)

        reporter = Reporter(output_dir=str(tmp_path / "out"))
        assert reporter.stock_name_map == {"000001.SZ": "平安银行"}

        # A directory is not a readable CSV: pandas raises, the loader logs and
        # returns an empty map instead of propagating.
        unreadable = tmp_path / "not_a_csv"
        unreadable.mkdir()
        monkeypatch.setattr("uniquant.hands.reporter.STOCK_LIST_FILE", unreadable)
        reporter_failed = Reporter(output_dir=str(tmp_path / "out2"))
        assert reporter_failed.stock_name_map == {}

    def test_load_stock_names_falls_back_to_name_column(self, tmp_path, monkeypatch):
        csv = tmp_path / "codes_name_col.csv"
        csv.write_text("code,name\n600000.SH,浦发银行\n", encoding="utf-8")
        monkeypatch.setattr("uniquant.hands.reporter.STOCK_LIST_FILE", csv)

        reporter = Reporter(output_dir=str(tmp_path / "out"))
        assert reporter.stock_name_map == {"600000.SH": "浦发银行"}

    def test_get_output_dir_without_date_folders(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "uniquant.hands.reporter.STOCK_LIST_FILE", tmp_path / "missing.csv"
        )
        reporter = Reporter(output_dir=str(tmp_path / "flat"), use_date_folders=False)

        assert reporter._get_output_dir("2026-01-02") == tmp_path / "flat"
        assert reporter.generate("000001.SZ", {"price": 1.0}).parent == tmp_path / "flat"

    def test_generate_research_report_missing_symbol(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "uniquant.hands.reporter.STOCK_LIST_FILE", tmp_path / "missing.csv"
        )
        reporter = Reporter(output_dir=str(tmp_path / "out"))

        assert reporter.generate_research_report({"current_price": 10.0}) is False
        assert reporter.generate_research_report({}) is False

    def test_generate_research_report_success_with_score(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "uniquant.hands.reporter.STOCK_LIST_FILE", tmp_path / "missing.csv"
        )
        reporter = Reporter(output_dir=str(tmp_path / "out"), use_date_folders=True)

        ok = reporter.generate_research_report(
            {
                "symbol": "000001.SZ",
                "decision_packet": {
                    "final_decision": "EXECUTE_BUY",
                    "regime": "BULL",
                    "final_score": 88,
                },
                "current_price": 10.0,
                "indicators": {"rsi": 30},
                "report_date": "2026-01-02",
            }
        )

        assert ok is True
        report = tmp_path / "out" / "2026-01-02" / "Report_000001.SZ.md"
        assert report.exists()
        content = report.read_text(encoding="utf-8")
        assert "final_score: 88" in content
        assert "regime: BULL" in content

    def test_generate_research_report_swallows_generate_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "uniquant.hands.reporter.STOCK_LIST_FILE", tmp_path / "missing.csv"
        )
        reporter = Reporter(output_dir=str(tmp_path / "out"))

        def _boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(reporter, "generate", _boom)
        assert reporter.generate_research_report({"symbol": "000001.SZ"}) is False

    def test_generate_writes_report_including_change(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "uniquant.hands.reporter.STOCK_LIST_FILE", tmp_path / "missing.csv"
        )
        reporter = Reporter(output_dir=str(tmp_path / "out"), use_date_folders=False)

        report_path = reporter.generate(
            "000001.SZ",
            {
                "price": 10.5,
                "change": 1.5,
                "indicators": {"rsi": 30},
                "signals": ["buy"],
                "analysis": "looks fine",
            },
        )

        assert report_path.name == "Report_000001.SZ.md"
        content = report_path.read_text(encoding="utf-8")
        assert "涨跌幅: 1.5%" in content
        assert "looks fine" in content


# ---------------------------------------------------------------------------
# hands/results_manager.py
# ---------------------------------------------------------------------------

class TestResultsManagerUnit:
    def test_default_root_dir_resolves_from_config(self, tmp_path, monkeypatch):
        _patch_root_config(monkeypatch, tmp_path)

        manager = ResultsManager()

        assert manager.root_dir == tmp_path
        assert manager.results_dir == tmp_path / "hands" / "results"
        assert manager.reports_dir.exists()
        assert manager.review_dir.exists()

    def test_results_dir_for_date_both_modes(self, tmp_path):
        flat = ResultsManager(root_dir=tmp_path / "flat", use_date_folders=False)
        assert flat._get_results_dir_for_date("2026-01-02") == flat.results_dir

        dated = ResultsManager(root_dir=tmp_path / "dated", use_date_folders=True)
        explicit = dated._get_results_dir_for_date("2026-01-02")
        assert explicit == dated.results_dir / "2026-01-02"
        assert explicit.exists()

        default = dated._get_results_dir_for_date(None)
        assert default.parent == dated.results_dir
        assert default.exists()

    def test_normalize_and_sortable_dates(self, tmp_path):
        manager = ResultsManager(root_dir=tmp_path)

        assert manager._normalize_result_date(None) is None
        assert manager._normalize_result_date("") == ""
        assert manager._normalize_result_date("20260102") == "2026-01-02"
        assert manager._normalize_result_date("2026-01-02") == "2026-01-02"

        assert manager._sortable_result_date(None) == ""
        assert manager._sortable_result_date("") == ""
        assert manager._sortable_result_date("not-a-date") == ""
        assert manager._sortable_result_date("20260102") == "2026-01-02"

    def test_extract_symbol_and_date_variants(self, tmp_path):
        manager = ResultsManager(root_dir=tmp_path, use_date_folders=False)

        bare = manager.results_dir / "000001.SZ.json"
        _write_json(bare, {"symbol": "000001.SZ"})
        # No underscore separator -> symbol only, empty date (line 113).
        assert manager._extract_symbol_and_date(bare) == {"symbol": "000001.SZ", "date": ""}

        legacy = manager.results_dir / "000002.SZ_20260102.json"
        _write_json(legacy, {"symbol": "000002.SZ"})
        assert manager._extract_symbol_and_date(legacy) == {
            "symbol": "000002.SZ",
            "date": "2026-01-02",
        }

        nested = manager.results_dir / "2026-01-03" / "600000.SH_adhoc.json"
        _write_json(nested, {"symbol": "600000.SH"})
        assert manager._extract_symbol_and_date(nested) == {
            "symbol": "600000.SH",
            "date": "2026-01-03",
        }

    def test_list_results_missing_dir_and_parse_failure(self, tmp_path, monkeypatch):
        manager = ResultsManager(root_dir=tmp_path)

        # Missing results dir -> early empty return (line 143).
        shutil.rmtree(manager.results_dir)
        assert manager.list_results() == []

        manager._ensure_directories()
        _write_json(manager.results_dir / "2026-01-02" / "000001.SZ.json", {"symbol": "000001.SZ"})

        def _boom(_filepath):
            raise ValueError("bad filename protocol")

        monkeypatch.setattr(manager, "_extract_symbol_and_date", _boom)
        # Parse failure is logged and skipped (lines 176-178) rather than raised.
        assert manager.list_results() == []

    def test_list_results_skips_none_parse(self, tmp_path, monkeypatch):
        """Defensive guard: ``_extract_symbol_and_date`` never returns ``None`` in
        production, but the listing loop must tolerate it (line 154)."""
        manager = ResultsManager(root_dir=tmp_path)
        _write_json(manager.results_dir / "000001.SZ.json", {"symbol": "000001.SZ"})
        monkeypatch.setattr(manager, "_extract_symbol_and_date", lambda _filepath: None)

        assert manager.list_results() == []

    def test_list_results_date_filter(self, tmp_path):
        manager = ResultsManager(root_dir=tmp_path)
        _write_json(manager.results_dir / "2026-04-01" / "000001.SZ.json", {"symbol": "000001.SZ"})
        _write_json(manager.results_dir / "2026-04-02" / "000002.SZ.json", {"symbol": "000002.SZ"})

        # Compact (YYYYMMDD) filter form is normalized before comparison.
        matched = manager.list_results(date="20260401")
        assert [r["symbol"] for r in matched] == ["000001.SZ"]

        assert manager.list_results(date="2026-05-01") == []

    def test_get_latest_result_absent(self, tmp_path):
        manager = ResultsManager(root_dir=tmp_path)
        assert manager.get_latest_result("000001.SZ") is None

    def test_generate_report_from_result_reports_false(self, tmp_path, monkeypatch):
        manager = ResultsManager(root_dir=tmp_path)
        result_file = manager.results_dir / "2026-01-02" / "000001.SZ.json"
        _write_json(result_file, {"symbol": "000001.SZ"})

        class FalseReporter:
            def __init__(self, output_dir):
                self.output_dir = output_dir

            def generate_research_report(self, context):  # noqa: ARG002 - interface
                return False

        monkeypatch.setattr("uniquant.hands.reporter.Reporter", FalseReporter)
        # Reporter returned False -> manager propagates False (line 269).
        assert manager.generate_report_from_result(str(result_file)) is False

    def test_cleanup_default_days_and_missing_dir(self, tmp_path):
        manager = ResultsManager(root_dir=tmp_path)
        recent = manager.results_dir / "000001.SZ.json"
        _write_json(recent, {"symbol": "000001.SZ"})

        # days=None -> default CLEANUP_THRESHOLD_DAYS; recent file is retained.
        assert manager.cleanup_old_results() == 0
        assert recent.exists()

        shutil.rmtree(manager.results_dir)
        # Missing results dir -> early zero return (line 329).
        assert manager.cleanup_old_results(days=1) == 0

    def test_cleanup_handles_stat_exception(self, tmp_path, monkeypatch):
        manager = ResultsManager(root_dir=tmp_path)
        result_file = manager.results_dir / "000001.SZ.json"
        _write_json(result_file, {"symbol": "000001.SZ"})

        real_stat = Path.stat

        def _boom(self, *args, **kwargs):
            # Only the individual result file "fails"; directory probing in
            # cleanup_old_results must keep working.
            if self == result_file:
                raise OSError("stat denied")
            return real_stat(self, *args, **kwargs)

        # A stat failure on one file is logged and skipped (lines 340-341).
        monkeypatch.setattr(Path, "stat", _boom)
        assert manager.cleanup_old_results(days=1) == 0
