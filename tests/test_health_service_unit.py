"""Unit tests for ``services.health_service.HealthService``.

Complements ``tests/shared/test_health_service.py`` (which covers the three-layer
probe wrappers + data-source tracking) by exercising every per-component health
probe, the recommendation engine, history/summary/reporting helpers and the
module-level singleton accessor.

All constructor dependencies are patched so the module is testable in CI with
no data lake, no network and no contents under ``data/``.
"""

from __future__ import annotations

import importlib
import json
import sys
from types import SimpleNamespace

import pandas as pd
import pytest


hs_mod = importlib.import_module("uniquant.services.health_service")


class _BadLen:
    def __len__(self):
        raise RuntimeError("boom-len")

    def keys(self):
        raise RuntimeError("boom-len")


class _FakePsutil:
    """Minimal psutil stand-in for resource-based branches."""

    def __init__(self, cpu=1.0, mem=10.0, disk=10.0, boot=0.0):
        self._cpu, self._mem, self._disk, self._boot = cpu, mem, disk, boot

    def cpu_percent(self):
        return self._cpu

    def virtual_memory(self):
        return SimpleNamespace(percent=self._mem)

    def disk_usage(self, path):
        return SimpleNamespace(percent=self._disk)

    def boot_time(self):
        return self._boot


@pytest.fixture
def service(monkeypatch):
    cfg = SimpleNamespace()
    cfg._config = {"base": {}, "cache": {}, "brain": {}}
    cfg.LAKE_DIR = SimpleNamespace(exists=lambda: True)
    cfg.CACHE_DIR = SimpleNamespace(exists=lambda: True)
    cfg.get = lambda key: {"x": 1} if key == "brain" else None
    cfg.validate_config = lambda: True

    ds = SimpleNamespace()
    ds.list_data_files = lambda: ["f"] * 20
    ds.cache_manager = SimpleNamespace(get_stats=lambda: {"total_items": 5})
    ds.fetch_data = lambda *a, **k: pd.DataFrame({"date": ["2026-04-10"], "close": [1.0]})
    ds.fetch_for_brain = lambda symbol: {"stock": pd.DataFrame({"close": [1.0]})}

    monkeypatch.setattr(hs_mod, "get_config", lambda: cfg)
    monkeypatch.setattr(
        hs_mod, "get_kill_switch", lambda: SimpleNamespace(is_killed=False, reason="")
    )
    monkeypatch.setattr(hs_mod, "DataService", lambda: ds)
    monkeypatch.setattr(hs_mod, "AnalysisService", lambda **k: SimpleNamespace())
    monkeypatch.setattr(hs_mod, "DecisionBrain", lambda **k: SimpleNamespace())
    monkeypatch.setattr(hs_mod, "EVTRisk", lambda: SimpleNamespace())
    monkeypatch.setattr(hs_mod, "PositionSizer", lambda: SimpleNamespace())

    svc = hs_mod.HealthService()
    svc.config = cfg
    svc.data_service = ds
    return svc


# ── liveness / readiness error paths ──────────────────────────────────────────


def test_liveness_dead_when_config_unreadable(service):
    service.config._config = _BadLen()
    result = service.liveness()
    assert result["status"] == "dead"
    assert "boom-len" in result["error"]
    assert "timestamp" in result


def test_readiness_reports_lake_and_cache_check_exceptions(service):
    def _raise(*_a, **_k):
        raise OSError("no path")

    service.config.LAKE_DIR = SimpleNamespace(exists=_raise)
    service.config.CACHE_DIR = SimpleNamespace(exists=_raise)
    result = service.readiness()
    assert result["status"] == "not_ready"
    assert any("Data lake check failed: no path" in i for i in result["issues"])
    assert any("Cache check failed: no path" in i for i in result["issues"])


def test_readiness_config_validation_false_and_error(service):
    service.config.validate_config = lambda: False
    assert "Config validation failed" in service.readiness()["issues"]

    def _raise():
        raise ValueError("cfg boom")

    service.config.validate_config = _raise
    issues = service.readiness()["issues"]
    assert any("Config validation error: cfg boom" in i for i in issues)


def test_readiness_reports_kill_switch(service, monkeypatch):
    monkeypatch.setattr(
        hs_mod,
        "get_kill_switch",
        lambda: SimpleNamespace(is_killed=True, reason="manual halt"),
    )
    result = service.readiness()
    assert result["status"] == "not_ready"
    assert result["trading_enabled"] is False
    assert result["kill_switch_active"] is True
    assert result["kill_switch_reason"] == "manual halt"
    assert any("Trading stopped by kill switch: manual halt" in i for i in result["issues"])


# ── get_system_health ─────────────────────────────────────────────────────────


def test_get_system_health_healthy(service):
    result = service.get_system_health()
    assert result["status"] == "healthy"
    assert result["overall_status"] == "healthy"
    assert result["details"]["validation_passed"] is True
    assert result["details"]["brain_config_loaded"] is True
    assert set(result["components"]) == {"config", "lake", "cache"}
    assert result["components"]["lake"]["status"] == "healthy"
    assert "cache_hit_ratio" in result["metrics"]


def test_get_system_health_lake_and_cache_warning(service):
    service.config.LAKE_DIR = SimpleNamespace(exists=lambda: False)
    service.config.CACHE_DIR = SimpleNamespace(exists=lambda: False)
    result = service.get_system_health()
    assert result["components"]["lake"]["status"] == "warning"
    assert result["components"]["cache"]["status"] == "warning"


def test_get_system_health_recovers_from_config_error(service):
    def _raise():
        raise ValueError("validated badly")

    service.config.validate_config = _raise
    result = service.get_system_health()
    assert result["status"] == "unhealthy"
    assert result["error"] == "validated badly"
    assert result["components"]["config"]["status"] == "unhealthy"


# ── per-component probes ──────────────────────────────────────────────────────


def test_check_data_service_health_healthy(service):
    result = service._check_data_service_health()
    assert result["status"] == "healthy"
    assert result["details"]["data_fetched"] is True
    assert result["details"]["data_shape"] == (1, 2)
    assert result["details"]["cache_stats"] == {"total_items": 5}


def test_check_data_service_health_error(service):
    def _raise(*_a, **_k):
        raise KeyError("no fetch")

    service.data_service.fetch_data = _raise
    result = service._check_data_service_health()
    assert result["status"] == "unhealthy"
    assert "no fetch" in result["error"]


def test_check_data_service_health_unhealthy_when_none(service):
    service.data_service.fetch_data = lambda *a, **k: None
    result = service._check_data_service_health()
    assert result["status"] == "unhealthy"
    assert result["details"]["data_fetched"] is False
    assert result["details"]["data_shape"] is None


def test_check_analysis_service_health_healthy_and_error(service):
    service.analysis_service = SimpleNamespace(
        analyze_macro_health=lambda: {"var_95": -0.03}
    )
    result = service._check_analysis_service_health()
    assert result["status"] == "healthy"
    assert result["details"]["macro_health_analyzed"] is True
    assert result["details"]["risk_metrics_calculated"] is True

    def _raise():
        raise TypeError("macro boom")

    service.analysis_service = SimpleNamespace(analyze_macro_health=_raise)
    result = service._check_analysis_service_health()
    assert result["status"] == "unhealthy"
    assert "macro boom" in result["error"]


def test_check_analysis_service_health_non_dict(service):
    service.analysis_service = SimpleNamespace(analyze_macro_health=lambda: 42)
    result = service._check_analysis_service_health()
    assert result["status"] == "unhealthy"
    assert result["details"]["risk_metrics_calculated"] is False


def test_check_brain_health_healthy(service):
    service.brain = SimpleNamespace(make_decision=lambda pack: {"action": "BUY"})
    result = service._check_brain_health()
    assert result["status"] == "healthy"
    assert result["details"]["decision_made"] is True
    assert result["details"]["action_in_decision"] is True


def test_check_brain_health_degraded_without_data(service):
    service.data_service.fetch_for_brain = lambda symbol: {
        "stock": pd.DataFrame()
    }
    result = service._check_brain_health()
    assert result["status"] == "degraded"
    assert result["details"]["data_available"] is False
    assert "No data available" in result["details"]["reason"]


def test_check_brain_health_error(service):
    def _raise(symbol):
        raise RuntimeError("brain boom")

    service.data_service.fetch_for_brain = _raise
    result = service._check_brain_health()
    assert result["status"] == "unhealthy"
    assert "brain boom" in result["error"]


def test_check_risk_health_healthy_and_error(service):
    service.evt_risk = SimpleNamespace(calculate_metrics=lambda r: {"var_q": -0.05})
    result = service._check_risk_health()
    assert result["status"] == "healthy"
    assert result["details"]["var_calculated"] is True

    def _raise(_r):
        raise OSError("evt boom")

    service.evt_risk = SimpleNamespace(calculate_metrics=_raise)
    result = service._check_risk_health()
    assert result["status"] == "unhealthy"
    assert "evt boom" in result["error"]


def test_check_cache_health_healthy_and_error(service):
    result = service._check_cache_health()
    assert result["status"] == "healthy"
    assert result["details"]["cache_enabled"] is True
    assert result["details"]["cache_stats"] == {"total_items": 5}

    def _raise():
        raise AttributeError("no cache")

    service.data_service.cache_manager = SimpleNamespace(get_stats=_raise)
    result = service._check_cache_health()
    assert result["status"] == "unhealthy"
    assert "no cache" in result["error"]


def test_check_data_lake_health_healthy_and_error(service):
    service.data_service.list_data_files = lambda: ["a", "b", "c"]
    result = service._check_data_lake_health()
    assert result["status"] == "healthy"
    assert result["details"]["lake_dir_exists"] is True
    assert result["details"]["data_files_count"] == 3

    def _raise():
        raise ValueError("lake boom")

    service.data_service.list_data_files = _raise
    result = service._check_data_lake_health()
    assert result["status"] == "unhealthy"
    assert "lake boom" in result["error"]


def test_check_system_health_with_psutil(service, monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil(cpu=7.5, mem=33.0, disk=44.0))
    result = service._check_system_health()
    assert result["status"] == "healthy"
    assert result["details"] == {
        "cpu_usage": 7.5,
        "memory_usage": 33.0,
        "disk_usage": 44.0,
    }


def test_check_system_health_without_psutil(service, monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)
    result = service._check_system_health()
    assert result["status"] == "healthy"
    assert result["details"] == {"psutil_not_installed": True}


def test_check_system_health_recovers_from_psutil_error(service, monkeypatch):
    class _BrokenPsutil(_FakePsutil):
        def cpu_percent(self):
            raise OSError("cpu read failed")

    monkeypatch.setitem(sys.modules, "psutil", _BrokenPsutil())
    result = service._check_system_health()
    assert result["status"] == "unhealthy"
    assert "cpu read failed" in result["error"]


# ── metrics / uptime ──────────────────────────────────────────────────────────


def test_get_system_metrics_tolerates_cache_stats_failure(service):
    def _raise():
        raise RuntimeError("stats boom")

    service.data_service.cache_manager = SimpleNamespace(get_stats=_raise)
    metrics = service._get_system_metrics()
    assert metrics["cache_size"] == 0
    assert metrics["cache_hit_ratio"] == 0.0


def test_get_system_metrics_outer_error(service):
    service.config._config = _BadLen()
    assert service._get_system_metrics() == {"error": "boom-len"}


def test_get_uptime_with_psutil(service, monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil(boot=0.0))
    uptime = service._get_uptime()
    assert uptime.endswith(" hours")


def test_get_uptime_without_psutil(service, monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert service._get_uptime() == "Unknown"


# ── recommendations ───────────────────────────────────────────────────────────


def test_recommendations_optimal_when_all_healthy(service, monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil(mem=10.0, disk=10.0))
    assert service._get_health_recommendations() == ["System health is optimal"]


def test_recommendations_flag_missing_brain_and_sparse_data(service, monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil(mem=10.0, disk=10.0))
    service.config.get = lambda key: None
    service.data_service.list_data_files = lambda: ["only_one"]
    service.data_service.cache_manager = SimpleNamespace(get_stats=lambda: {"total_items": 0})
    recs = service._get_health_recommendations()
    assert any("brain.yaml" in r for r in recs)
    assert any("more historical data" in r for r in recs)
    assert any("Cache is empty" in r for r in recs)


def test_recommendations_flag_high_memory_and_disk(service, monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil(mem=95.0, disk=90.0))
    recs = service._get_health_recommendations()
    assert any("High memory usage" in r for r in recs)
    assert any("Low disk space" in r for r in recs)


def test_recommendations_tolerate_psutil_failure(service, monkeypatch):
    class _BrokenPsutil(_FakePsutil):
        def virtual_memory(self):
            raise OSError("no mem")

    monkeypatch.setitem(sys.modules, "psutil", _BrokenPsutil())
    recs = service._get_health_recommendations()
    assert recs  # still returns, psutil block skipped


def test_recommendations_outer_error(service):
    def _raise():
        raise ValueError("list boom")

    service.data_service.list_data_files = _raise
    recs = service._get_health_recommendations()
    assert recs == ["Error generating recommendations"]


# ── history / summary / report ────────────────────────────────────────────────


def test_add_to_history_evicts_oldest(service):
    service.max_history_size = 2
    service._add_to_history({"id": 1})
    service._add_to_history({"id": 2})
    service._add_to_history({"id": 3})
    assert [h["id"] for h in service.health_check_history] == [2, 3]
    assert service.get_health_history() == service.health_check_history


def test_add_to_history_swallows_error(service):
    service.health_check_history = object()
    service._add_to_history({"id": 1})  # no raise


def test_get_health_summary_without_history(service):
    assert service.get_health_summary() == {"error": "No health check history available"}


def test_get_health_summary_aggregates(service):
    service._add_to_history(
        {
            "overall_status": "healthy",
            "timestamp": "t1",
            "components": {"config": {"status": "healthy"}},
        }
    )
    service._add_to_history(
        {
            "overall_status": "unhealthy",
            "timestamp": "t2",
            "components": {"config": {"status": "unhealthy"}},
        }
    )
    summary = service.get_health_summary()
    assert summary["latest_status"] == "unhealthy"
    assert summary["status_trend"] == {"healthy": 1, "unhealthy": 1}
    assert summary["check_count"] == 2
    assert summary["latest_check"] == "t2"
    assert summary["components_status"] == {"config": "unhealthy"}


def test_get_health_summary_error(service):
    service.health_check_history = ["not-a-dict"]
    assert "error" in service.get_health_summary()


def test_export_health_report_json(service):
    payload = json.loads(service.export_health_report("json"))
    assert payload["overall_status"] == "healthy"


def test_export_health_report_txt(service):
    report = service.export_health_report("txt")
    assert report.startswith("Alpha-Tactician Health Report")
    assert "Overall Status: healthy" in report
    assert "Components:" in report
    assert "config: healthy" in report
    assert "Metrics:" in report
    assert "cache_hit_ratio:" in report
    assert "Recommendations:" in report


def test_export_health_report_unsupported_format(service):
    assert service.export_health_report("xml") == "Unsupported format: xml"


def test_export_health_report_error(service):
    def _raise():
        raise ValueError("export boom")

    service.get_system_health = _raise
    assert service.export_health_report("json") == "Error exporting report: export boom"


def test_save_health_report_writes_file(service, tmp_path):
    out = tmp_path / "health.json"
    assert service.save_health_report(str(out), "json") is True
    assert json.loads(out.read_text(encoding="utf-8"))["overall_status"] == "healthy"


def test_save_health_report_returns_false_on_oserror(service, tmp_path):
    # Passing a directory as the target path triggers OSError on open().
    assert service.save_health_report(str(tmp_path), "json") is False


# ── module singleton ──────────────────────────────────────────────────────────


def test_get_health_service_singleton(monkeypatch):
    sentinel = object()
    calls = {"n": 0}

    def _factory():
        calls["n"] += 1
        return sentinel

    monkeypatch.setattr(hs_mod, "health_service", None)
    monkeypatch.setattr(hs_mod, "HealthService", _factory)

    first = hs_mod.get_health_service()
    second = hs_mod.get_health_service()
    assert first is sentinel
    assert second is sentinel
    assert calls["n"] == 1
