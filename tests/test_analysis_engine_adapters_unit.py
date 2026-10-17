"""Unit tests for the live per-engine adapters under ``services/analysis/``.

These tests target the *adapter* layer (thin services wrappers around brain/data
engines). They mirror the orchestrator-stub pattern used by the existing
regression suites (``test_more_analysis_engine_regressions.py``,
``test_macro_and_fsm_engine_regressions.py``, ``test_report_and_ntf_regressions.py``)
but exercise the cache/degradation branches those suites do not.

CI-safe: no network, no ``data/`` access (``tmp_path`` only). CZSC tests that
require the optional ``czsc`` dependency are guarded with ``pytest.importorskip``.
"""

from __future__ import annotations

import sys
from unittest.mock import Mock

import pandas as pd
import pytest

from uniquant.shared.interfaces import CZSCOutput, LPPLOutput, NtfOutput
from uniquant.services.analysis.czsc_analysis_engine import CzscAnalysisEngine
from uniquant.services.analysis.fsm_analysis_engine import FsmAnalysisEngine
from uniquant.services.analysis.lppl_analysis_engine import (
    LpplAnalysisEngine,
    create_lppl_data_service,
    create_lppl_engine,
)
from uniquant.services.analysis.macro_analysis_engine import MacroAnalysisEngine
from uniquant.services.analysis.ntf_analysis_engine import NtfAnalysisEngine
from uniquant.services.analysis.regime_analysis_engine import RegimeAnalysisEngine
from uniquant.services.analysis.report_generator_engine import ReportGeneratorEngine


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _sample_ohlc_df(rows: int = 80) -> pd.DataFrame:
    base = list(range(100, 100 + rows))
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "open": base,
            "high": [x + 1 for x in base],
            "low": [x - 1 for x in base],
            "close": [x + 0.5 for x in base],
            "volume": [1000 + i for i in range(rows)],
        }
    )


def _ohlc_from_closes(closes, last_open=None) -> pd.DataFrame:
    """Build a minimal OHLCV frame where only ``close`` drives behaviour."""
    n = len(closes)
    last_open = closes[-1] if last_open is None else last_open
    opens = list(closes[:-1]) + [last_open]
    return pd.DataFrame(
        {
            "open": [float(o) for o in opens],
            "high": [float(c) + 1 for c in closes],
            "low": [float(c) - 1 for c in closes],
            "close": [float(c) for c in closes],
            "volume": [1000.0] * n,
        }
    )


class _DummyLake:
    def __init__(self, df):
        self._df = df

    def read_data(self, symbol, data_type="stock", market="cn"):
        return self._df.copy()


class _DummyFetcher:
    def __init__(self, df):
        self._df = df

    def fetch_index_daily(self, symbol, start_date, end_date):
        return None if self._df is None else self._df.copy()


class _Orchestrator:
    """Fresh, per-test orchestrator stub (no shared mutable state)."""

    def __init__(self, df=None, *, cached=None, report_root=None, reporter=...):
        self.data_service = Mock()
        self.data_service.lake = _DummyLake(df if df is not None else pd.DataFrame())
        self.data_service.fetcher = _DummyFetcher(df if df is not None else pd.DataFrame())
        self.data_service.get_stock_name = Mock(return_value="Test Corp")
        self.report_root = report_root
        self.reporter = None if reporter is ... else reporter
        self._market_cache = {}
        self._market_cache_date = "2026-04-04"
        self.evt_risk = None
        self.sizer = None
        self.brain = None
        self.validation_service = None
        self._cached = cached

    def _generate_cache_key(self, prefix, **kwargs):
        return f"{prefix}:{kwargs}"

    def _get_cached_result(self, cache_key, use_disk=False):
        return self._cached

    def _set_cached_result(self, cache_key, result, use_disk=False, ttl=None):
        self._last_set = (cache_key, result, use_disk, ttl)
        return True

    def _optimize_dataframe(self, df):
        return df

    def _sample_data(self, df, max_rows):
        return df

    def ensure_precision_consistency(self, result):
        return result

    def validate_risk_metrics(self, metrics):
        return True


# ---------------------------------------------------------------------------
# RegimeAnalysisEngine._run_regime_detection
# ---------------------------------------------------------------------------

def test_regime_market_cache_hit_short_circuits():
    orch = _Orchestrator(_sample_ohlc_df())
    orch._market_cache["regime"] = "BULL"
    engine = RegimeAnalysisEngine(orch)
    data_pack = {}

    engine._run_regime_detection("000001.SZ", data_pack)

    assert data_pack["regime"] == {"status": "success", "regime": "BULL"}


def test_regime_disk_cache_hit_populates_market_cache():
    orch = _Orchestrator(_sample_ohlc_df(), cached="NORMAL")
    engine = RegimeAnalysisEngine(orch)
    data_pack = {}

    engine._run_regime_detection("000001.SZ", data_pack)

    assert orch._market_cache["regime"] == "NORMAL"
    assert data_pack["regime"] == {"status": "success", "regime": "NORMAL"}


def test_regime_compute_success_persists_to_caches(monkeypatch):
    orch = _Orchestrator(_sample_ohlc_df())
    engine = RegimeAnalysisEngine(orch)
    monkeypatch.setattr(
        engine,
        "run_regime_detection",
        lambda symbol, df=None: {"symbol": symbol, "status": "success", "regime": "BULL"},
    )
    data_pack = {}

    engine._run_regime_detection("000001.SZ", data_pack)

    assert data_pack["regime"] == {"symbol": "000300.SH", "status": "success", "regime": "BULL"}
    assert orch._market_cache["regime"] == "BULL"
    assert orch._last_set[1] == "BULL"


def test_regime_recoverable_error_is_swallowed(monkeypatch):
    orch = _Orchestrator(_sample_ohlc_df())
    engine = RegimeAnalysisEngine(orch)

    def boom(prefix, **kwargs):
        raise ValueError("cache key exploded")

    monkeypatch.setattr(orch, "_generate_cache_key", boom)
    data_pack = {}

    # Must not raise — recoverable path logs and returns None.
    assert engine._run_regime_detection("000001.SZ", data_pack) is None
    assert "regime" not in data_pack


# ---------------------------------------------------------------------------
# NtfAnalysisEngine._run_ntf_detection
# ---------------------------------------------------------------------------

def test_ntf_market_cache_hit_short_circuits():
    orch = _Orchestrator(_sample_ohlc_df())
    orch._market_cache["ntf_signals"] = {"side": "MEM", "intensity": 0.1}
    engine = NtfAnalysisEngine(orch)
    data_pack = {}

    engine._run_ntf_detection("000001.SZ", data_pack)

    assert data_pack["ntf"] == {"side": "MEM", "intensity": 0.1}


def test_ntf_disk_cache_hit_populates_market_cache():
    orch = _Orchestrator(_sample_ohlc_df(), cached={"side": "DISK", "intensity": 0.2})
    engine = NtfAnalysisEngine(orch)
    data_pack = {}

    engine._run_ntf_detection("000001.SZ", data_pack)

    assert orch._market_cache["ntf_signals"] == {"side": "DISK", "intensity": 0.2}
    assert data_pack["ntf"] == {"side": "DISK", "intensity": 0.2}


def test_ntf_compute_success_populates_and_caches(monkeypatch):
    orch = _Orchestrator(_sample_ohlc_df())
    engine = NtfAnalysisEngine(orch)
    monkeypatch.setattr(
        engine,
        "run_ntf_detection",
        lambda symbol, df=None: NtfOutput(side="SUPPORT", intensity=0.7),
    )
    data_pack = {}

    engine._run_ntf_detection("000001.SZ", data_pack)

    assert data_pack["ntf"] == {"side": "SUPPORT", "intensity": 0.7}
    assert orch._market_cache["ntf_signals"] == {"side": "SUPPORT", "intensity": 0.7}
    assert orch._last_set[1] == {"side": "SUPPORT", "intensity": 0.7}


def test_ntf_recoverable_error_is_swallowed(monkeypatch):
    orch = _Orchestrator(_sample_ohlc_df())
    engine = NtfAnalysisEngine(orch)
    monkeypatch.setattr(
        orch, "_generate_cache_key", lambda prefix, **kwargs: (_ for _ in ()).throw(ValueError("x"))
    )
    data_pack = {}

    assert engine._run_ntf_detection("000001.SZ", data_pack) is None
    assert "ntf" not in data_pack


# ---------------------------------------------------------------------------
# LpplAnalysisEngine
# ---------------------------------------------------------------------------

def test_lppl_factories_return_real_engines():
    assert type(create_lppl_engine()).__name__ == "LPPLEngine"
    assert type(create_lppl_data_service()).__name__ == "LPPLDataService"


def test_lppl_empty_lake_data_falls_back_to_safe():
    orch = _Orchestrator(pd.DataFrame())
    engine = LpplAnalysisEngine(orch)

    result = engine.run_lppl_analysis("000001.SZ", df=None)

    assert isinstance(result, LPPLOutput)
    assert result.risk_level == "Safe"
    assert result.confidence == 0.0


def test_lppl_outer_recoverable_error_returns_engine_failed():
    orch = _Orchestrator(_sample_ohlc_df())

    def boom(symbol, data_type="stock", market="cn"):
        raise ValueError("lake unavailable")

    orch.data_service.lake.read_data = boom
    engine = LpplAnalysisEngine(orch)

    result = engine.run_lppl_analysis("000001.SZ", df=None)

    assert result.risk_level == "ENGINE_FAILED"
    assert result.confidence == 0.0


def test_lppl_fallback_single_row_yields_safe_zero_confidence():
    engine = LpplAnalysisEngine(_Orchestrator(_sample_ohlc_df()))
    one_row = pd.DataFrame({"close": [10.0]})

    result = engine._fallback_lppl_analysis("000001.SZ", one_row)

    assert result.risk_level == "Safe"
    assert result.confidence == 0.0
    assert result.price == 0.0


def test_lppl_fallback_non_numeric_close_returns_engine_failed():
    engine = LpplAnalysisEngine(_Orchestrator(_sample_ohlc_df()))
    strings = pd.DataFrame({"close": ["a", "b", "c"]})

    result = engine._fallback_lppl_analysis("000001.SZ", strings)

    assert result.risk_level == "ENGINE_FAILED"
    assert result.confidence == 0.0


def test_lppl_fallback_detects_large_jump_as_warning():
    engine = LpplAnalysisEngine(_Orchestrator(_sample_ohlc_df()))
    closes = [10.0, 10.1, 10.2, 13.0]  # final daily jump > 20%
    df = pd.DataFrame({"close": closes})

    result = engine._fallback_lppl_analysis("000001.SZ", df)

    assert result.risk_level == "Warning"
    assert result.confidence > 0.0


# ---------------------------------------------------------------------------
# FsmAnalysisEngine
# ---------------------------------------------------------------------------

def test_fsm_returns_cached_result_when_present():
    orch = _Orchestrator(_sample_ohlc_df(), cached={"status": "success", "current_state": "buy"})
    engine = FsmAnalysisEngine(orch)

    result = engine.run_fsm_analysis("000001.SZ", df=None)

    assert result == {"status": "success", "current_state": "buy"}


def test_fsm_lake_empty_returns_data_failed():
    orch = _Orchestrator(pd.DataFrame())
    engine = FsmAnalysisEngine(orch)

    result = engine.run_fsm_analysis("000001.SZ", df=None)

    assert result == {"error": "数据不足", "status": "failed"}


def test_fsm_uses_orchestrator_brain_when_available():
    orch = _Orchestrator(_sample_ohlc_df())
    brain = Mock()
    brain.make_decision = Mock(
        return_value={"decision": "buy", "score": 80.0, "summary": "strong buy"}
    )
    orch.brain = brain
    engine = FsmAnalysisEngine(orch)

    result = engine.run_fsm_analysis("000001.SZ", _sample_ohlc_df())

    assert result["status"] == "success"
    assert result["symbol"] == "000001.SZ"
    assert result["current_state"] == "buy"
    assert result["recommendation"] == "买入"
    assert result["signal_strength"] == pytest.approx(0.8)
    assert result["summary"] == "strong buy"
    brain.make_decision.assert_called_once()


def test_fsm_import_error_triggers_fallback(monkeypatch):
    orch = _Orchestrator(_sample_ohlc_df())
    orch.brain = None
    engine = FsmAnalysisEngine(orch)
    # Halting the module in sys.modules forces ``from ...brain.fsm import ...``
    # to raise ImportError.
    monkeypatch.setitem(sys.modules, "uniquant.brain.fsm", None)

    result = engine.run_fsm_analysis("000001.SZ", _sample_ohlc_df())

    assert result["status"] == "success"
    assert result["summary"] == "使用基本交易逻辑进行判断"


def test_fsm_outer_recoverable_error_returns_failed(monkeypatch):
    orch = _Orchestrator(_sample_ohlc_df())
    engine = FsmAnalysisEngine(orch)
    monkeypatch.setattr(
        orch, "_generate_cache_key", lambda prefix, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    result = engine.run_fsm_analysis("000001.SZ", _sample_ohlc_df())

    assert result == {"error": "boom", "status": "failed"}


def test_fsm_fallback_bullish_ordering_is_buy():
    engine = FsmAnalysisEngine(_Orchestrator(_sample_ohlc_df()))
    df = _ohlc_from_closes([100.0 + i for i in range(60)])

    result = engine._fallback_fsm_analysis("000001.SZ", df)

    assert result["current_state"] == "buy"
    assert result["recommendation"] == "买入"


def test_fsm_fallback_bearish_ordering_is_sell():
    engine = FsmAnalysisEngine(_Orchestrator(_sample_ohlc_df()))
    df = _ohlc_from_closes([200.0 - i for i in range(60)])

    result = engine._fallback_fsm_analysis("000001.SZ", df)

    assert result["current_state"] == "sell"
    assert result["recommendation"] == "卖出"


def test_fsm_fallback_hold_branch():
    engine = FsmAnalysisEngine(_Orchestrator(_sample_ohlc_df()))
    closes = [90.0 + i for i in range(55)] + [144.0 - 5 * j for j in range(5)]
    df = _ohlc_from_closes(closes)

    result = engine._fallback_fsm_analysis("000001.SZ", df)

    assert result["current_state"] == "hold"
    assert result["recommendation"] == "持有"
    assert result["signal_strength"] == pytest.approx(0.5)


def test_fsm_fallback_wait_branch():
    engine = FsmAnalysisEngine(_Orchestrator(_sample_ohlc_df()))
    closes = [190.0 - i for i in range(55)] + [136.0 + 4 * j for j in range(5)]
    df = _ohlc_from_closes(closes)

    result = engine._fallback_fsm_analysis("000001.SZ", df)

    assert result["current_state"] == "wait"
    assert result["recommendation"] == "等待"
    assert result["signal_strength"] == pytest.approx(0.3)


def test_fsm_fallback_short_history_is_unknown():
    engine = FsmAnalysisEngine(_Orchestrator(_sample_ohlc_df()))
    df = _ohlc_from_closes([10.0, 11.0, 12.0])

    result = engine._fallback_fsm_analysis("000001.SZ", df)

    assert result["current_state"] == "UNKNOWN"
    assert result["signal_strength"] == 0.0


def test_fsm_fallback_exception_returns_default():
    engine = FsmAnalysisEngine(_Orchestrator(_sample_ohlc_df()))

    # A plain dict has no ``.columns`` → AttributeError inside the fallback.
    result = engine._fallback_fsm_analysis("000001.SZ", {"close": [1.0, 2.0]})

    assert result["status"] == "success"
    assert result["current_state"] == "UNKNOWN"
    assert result["summary"] == "FSM分析失败，使用默认结果"


# ---------------------------------------------------------------------------
# ReportGeneratorEngine
# ---------------------------------------------------------------------------

class _FakeReporter:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def generate_research_report(self, context):
        self.calls.append(context)
        return self.ok


def test_report_generate_analysis_report_with_filepath(tmp_path):
    reporter = _FakeReporter(ok=True)
    orch = _Orchestrator(_sample_ohlc_df(), report_root=tmp_path, reporter=reporter)
    engine = ReportGeneratorEngine(orch)
    data_pack = {"stock": pd.DataFrame({"close": [10.5]})}

    ok = engine._generate_analysis_report("000001.SZ", data_pack, {"final": "BUY"}, "/tmp/r.md")

    assert ok is True
    assert reporter.calls[0]["result_file"] == "/tmp/r.md"
    assert reporter.calls[0]["symbol"] == "000001.SZ"
    assert reporter.calls[0]["name"] == "Test Corp"


def test_report_generate_analysis_report_without_reporter_returns_true(tmp_path):
    orch = _Orchestrator(_sample_ohlc_df(), report_root=tmp_path, reporter=None)
    engine = ReportGeneratorEngine(orch)
    data_pack = {"stock": pd.DataFrame({"close": [10.5]})}

    assert engine._generate_analysis_report("000001.SZ", data_pack, {}, None) is True


def test_report_list_reports_reads_markdown_files(tmp_path):
    (tmp_path / "Report_A.md").write_text("hello", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "Report_B.md").write_text("world", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("nope", encoding="utf-8")
    orch = _Orchestrator(report_root=tmp_path)
    engine = ReportGeneratorEngine(orch)

    reports = engine.list_reports()

    names = {r["Filename"] for r in reports}
    assert names == {"Report_A.md", "Report_B.md"}
    assert all("Size (KB)" in r and "Path" in r for r in reports)


def test_report_read_report_success_and_missing(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("content-body", encoding="utf-8")
    engine = ReportGeneratorEngine(_Orchestrator(report_root=tmp_path))

    assert engine.read_report(str(p)) == "content-body"
    assert engine.read_report(str(tmp_path / "nope.md")) == "Report not found."


def test_report_read_report_invalid_input_returns_error():
    engine = ReportGeneratorEngine(_Orchestrator())

    out = engine.read_report("")

    assert out.startswith("Error reading report:")


def test_report_read_report_oserror_path(monkeypatch):
    engine = ReportGeneratorEngine(_Orchestrator())

    class FakePath:
        def __init__(self, _):
            pass

        def exists(self):
            return True

        def read_text(self, encoding="utf-8"):
            raise OSError("disk gone")

    monkeypatch.setattr(
        "uniquant.services.analysis.report_generator_engine.Path", FakePath
    )

    out = engine.read_report("/whatever.md")

    assert out == "Error reading report: disk gone"


def test_report_read_report_unexpected_type_error_path(monkeypatch):
    engine = ReportGeneratorEngine(_Orchestrator())

    class FakePath:
        def __init__(self, _):
            pass

        def exists(self):
            return True

        def read_text(self, encoding="utf-8"):
            raise TypeError("bad decode")

    monkeypatch.setattr(
        "uniquant.services.analysis.report_generator_engine.Path", FakePath
    )

    out = engine.read_report("/whatever.md")

    assert out == "Error reading report: bad decode"


def test_report_generate_report_delegates_to_analyze_ticker():
    orch = _Orchestrator()
    orch.analyze_ticker = Mock(return_value=True)
    engine = ReportGeneratorEngine(orch)

    assert engine.generate_report("600000.SH") is True
    orch.analyze_ticker.assert_called_once_with("600000.SH")


def test_report_generate_report_rejects_blank_ticker():
    engine = ReportGeneratorEngine(_Orchestrator())

    with pytest.raises(ValueError):
        engine.generate_report("   ")


def test_report_generate_reports_from_results_success(monkeypatch):
    engine = ReportGeneratorEngine(_Orchestrator())

    class DummyResultsManager:
        def generate_reports_from_results(self, symbols=None, date=None, force=False):
            return {"000001.SZ": True, "600000.SH": False}

    monkeypatch.setattr(
        "uniquant.hands.results_manager.ResultsManager", DummyResultsManager
    )

    assert engine.generate_reports_from_results() == {"000001.SZ": True, "600000.SH": False}


def test_report_generate_reports_from_results_import_error(monkeypatch):
    engine = ReportGeneratorEngine(_Orchestrator())
    monkeypatch.setitem(sys.modules, "uniquant.hands.results_manager", None)

    assert engine.generate_reports_from_results() == {}


def test_report_list_available_results_success(monkeypatch):
    engine = ReportGeneratorEngine(_Orchestrator())

    class DummyResultsManager:
        def list_results(self, symbol=None):
            return [{"symbol": symbol or "000001.SZ"}]

    monkeypatch.setattr(
        "uniquant.hands.results_manager.ResultsManager", DummyResultsManager
    )

    assert engine.list_available_results("600000.SH") == [{"symbol": "600000.SH"}]


def test_report_list_available_results_import_error(monkeypatch):
    engine = ReportGeneratorEngine(_Orchestrator())
    monkeypatch.setitem(sys.modules, "uniquant.hands.results_manager", None)

    assert engine.list_available_results() == []


# ---------------------------------------------------------------------------
# MacroAnalysisEngine
# ---------------------------------------------------------------------------

def _macro_orchestrator(*, evt_metrics=None, validation_service=None, metrics_valid=True, cached=None):
    orch = _Orchestrator(_sample_ohlc_df(), cached=cached)
    orch.evt_risk = Mock()
    orch.evt_risk.calculate_metrics = Mock(
        return_value=evt_metrics
        if evt_metrics is not None
        else {
            "var_95": 0.01,
            "var_99": 0.02,
            "cvar_95": 0.03,
            "cvar_99": 0.04,
            "max_drawdown": 0.05,
        }
    )
    orch.validation_service = validation_service
    orch.validate_risk_metrics = Mock(return_value=metrics_valid)
    return orch


def test_macro_cache_hit_returns_cached_result():
    cached = {"var_95": 0.11, "regime": "NORMAL"}
    engine = MacroAnalysisEngine(_macro_orchestrator(cached=cached))

    assert engine.analyze_macro_health() is cached


def test_macro_mock_generates_random_returns_when_empty(monkeypatch):
    orch = _macro_orchestrator()
    engine = MacroAnalysisEngine(orch)
    monkeypatch.setattr(engine, "get_macro_returns", lambda window=200: pd.Series(dtype=float))

    result = engine.analyze_macro_health(mock=True, seed=7)

    assert result["var_95"] == 0.01
    # The random path must feed a non-empty series to evt_risk.
    fed = orch.evt_risk.calculate_metrics.call_args[0][0]
    assert len(fed) == 252


def test_macro_invalid_metrics_returns_defaults(monkeypatch):
    orch = _macro_orchestrator(metrics_valid=False)
    engine = MacroAnalysisEngine(orch)
    monkeypatch.setattr(
        engine, "get_macro_returns", lambda window=200: pd.Series([0.01, -0.02, 0.03])
    )

    result = engine.analyze_macro_health()

    assert result["var_95"] == pytest.approx(0.05)
    assert result["max_drawdown"] == pytest.approx(0.15)
    assert result["regime"] == "NORMAL"
    assert orch._last_set[1] is result


def test_macro_validation_against_standards_logged(monkeypatch):
    validation = Mock()
    validation.calculate_standard_var = Mock(return_value=0.01)
    validation.calculate_standard_cvar = Mock(return_value=0.02)
    validation.calculate_standard_max_drawdown = Mock(return_value=0.03)
    validation.validate_risk_metrics = Mock(return_value={"all_valid": False})
    validation.generate_validation_report = Mock(return_value="report-body")
    orch = _macro_orchestrator(validation_service=validation)
    engine = MacroAnalysisEngine(orch)
    monkeypatch.setattr(
        engine, "get_macro_returns", lambda window=200: pd.Series([0.01, -0.02, 0.03])
    )

    result = engine.analyze_macro_health()

    validation.validate_risk_metrics.assert_called_once()
    validation.generate_validation_report.assert_called_once()
    assert result["var_95"] == 0.01


def test_macro_validation_service_error_is_swallowed(monkeypatch):
    validation = Mock()
    validation.calculate_standard_var = Mock(side_effect=ValueError("std failed"))
    orch = _macro_orchestrator(validation_service=validation)
    engine = MacroAnalysisEngine(orch)
    monkeypatch.setattr(
        engine, "get_macro_returns", lambda window=200: pd.Series([0.01, -0.02, 0.03])
    )

    result = engine.analyze_macro_health()

    assert result["var_95"] == 0.01


def test_macro_get_returns_empty_when_pct_change_drops_out(monkeypatch):
    single_row = pd.DataFrame(
        {"close": [100.0]},
        index=pd.date_range("2024-01-01", periods=1),
    )
    orch = _macro_orchestrator()
    orch.data_service.fetcher = _DummyFetcher(single_row)
    engine = MacroAnalysisEngine(orch)

    returns = engine.get_macro_returns(window=10)

    assert returns.empty


def test_macro_get_returns_empty_when_fetcher_returns_none():
    orch = _macro_orchestrator()
    orch.data_service.fetcher = _DummyFetcher(None)
    engine = MacroAnalysisEngine(orch)

    assert engine.get_macro_returns(window=10).empty


# ---------------------------------------------------------------------------
# CzscAnalysisEngine (adapter-level; engine paths guarded by czsc)
# ---------------------------------------------------------------------------

def test_czsc_cache_hit_returns_from_dict():
    cached = {"is_3rd_buy": True, "bi_count": 3, "price": 12.5}
    orch = _Orchestrator(_sample_ohlc_df(), cached=cached)
    engine = CzscAnalysisEngine(orch)

    result = engine.run_czsc_analysis("000001.SZ", df=None)

    assert isinstance(result, CZSCOutput)
    assert result.is_3rd_buy is True
    assert result.bi_count == 3
    assert result.price == 12.5


def test_czsc_lake_empty_returns_default_output():
    orch = _Orchestrator(pd.DataFrame())
    engine = CzscAnalysisEngine(orch)

    result = engine.run_czsc_analysis("000001.SZ", df=None)

    assert result == CZSCOutput()


def test_czsc_import_error_falls_back(monkeypatch):
    orch = _Orchestrator(_sample_ohlc_df())
    engine = CzscAnalysisEngine(orch)
    monkeypatch.setitem(sys.modules, "uniquant.brain.czsc.czsc_engine", None)

    result = engine.run_czsc_analysis("000001.SZ", _sample_ohlc_df())

    assert isinstance(result, CZSCOutput)


def test_czsc_happy_path_with_real_engine():
    pytest.importorskip("czsc")
    orch = _Orchestrator(_sample_ohlc_df())
    engine = CzscAnalysisEngine(orch)

    result = engine.run_czsc_analysis("000001.SZ", _sample_ohlc_df())

    assert isinstance(result, CZSCOutput)
    assert isinstance(result.is_3rd_buy, bool)
    assert isinstance(result.bi_count, int)
    assert isinstance(result.price, float)


def test_czsc_engine_recoverable_error_falls_back(monkeypatch):
    pytest.importorskip("czsc")
    orch = _Orchestrator(_sample_ohlc_df())
    engine = CzscAnalysisEngine(orch)

    def boom(self, df):
        raise RuntimeError("czsc engine broke")

    monkeypatch.setattr(
        "uniquant.brain.czsc.czsc_engine.CZSCEngine.get_czsc_signals", boom
    )

    result = engine.run_czsc_analysis("000001.SZ", _sample_ohlc_df())

    assert isinstance(result, CZSCOutput)


def test_czsc_outer_recoverable_error_returns_default(monkeypatch):
    orch = _Orchestrator(_sample_ohlc_df())
    engine = CzscAnalysisEngine(orch)
    monkeypatch.setattr(
        orch, "_generate_cache_key", lambda prefix, **kwargs: (_ for _ in ()).throw(ValueError("bad"))
    )

    result = engine.run_czsc_analysis("000001.SZ", _sample_ohlc_df())

    assert result == CZSCOutput()


def test_czsc_fallback_trend_and_state_branches():
    engine = CzscAnalysisEngine(_Orchestrator(pd.DataFrame()))

    rising_closes = [100.0 + i for i in range(30)]
    rising = _ohlc_from_closes(rising_closes, last_open=rising_closes[-1] * 0.99)
    up = engine._fallback_czsc_analysis("000001.SZ", rising)
    assert up.trend == "上升"
    assert up.current_state == "BUY"  # close > open but not > 1.05x → BUY branch

    falling = _ohlc_from_closes([200.0 - i for i in range(30)])
    down = engine._fallback_czsc_analysis("000001.SZ", falling)
    assert down.trend == "下降"

    flat = _ohlc_from_closes([50.0] * 30)
    flat_res = engine._fallback_czsc_analysis("000001.SZ", flat)
    assert flat_res.trend == "震荡"


def test_czsc_fallback_strong_move_states():
    engine = CzscAnalysisEngine(_Orchestrator(pd.DataFrame()))
    closes = [100.0 + i for i in range(30)]

    strong_up = _ohlc_from_closes(closes, last_open=closes[-1] / 1.10)
    assert engine._fallback_czsc_analysis("X", strong_up).current_state == "STRONG_BUY"

    sell = _ohlc_from_closes(closes, last_open=closes[-1] * 1.005)
    assert engine._fallback_czsc_analysis("X", sell).current_state == "SELL"

    strong_down = _ohlc_from_closes(closes, last_open=closes[-1] * 1.20)
    assert engine._fallback_czsc_analysis("X", strong_down).current_state == "STRONG_SELL"


def test_czsc_fallback_short_history_unknown_trend():
    engine = CzscAnalysisEngine(_Orchestrator(pd.DataFrame()))
    df = _ohlc_from_closes([10.0, 10.5, 11.0])

    result = engine._fallback_czsc_analysis("000001.SZ", df)

    assert result.trend == "未知"


def test_czsc_fallback_missing_columns_returns_default():
    engine = CzscAnalysisEngine(_Orchestrator(pd.DataFrame()))
    df = pd.DataFrame({"close": [10.0, 11.0]})

    result = engine._fallback_czsc_analysis("000001.SZ", df)

    assert result == CZSCOutput()


def test_czsc_fallback_exception_returns_default():
    engine = CzscAnalysisEngine(_Orchestrator(pd.DataFrame()))

    result = engine._fallback_czsc_analysis("000001.SZ", {"close": [1.0]})

    assert result == CZSCOutput()
