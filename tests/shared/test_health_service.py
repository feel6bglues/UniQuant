"""
Tests for HealthService — liveness/readiness/diagnostics three-layer checks.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from uniquant.services.health_service import HealthService


@pytest.fixture
def health_service():
    with patch("uniquant.services.health_service.DataService") as mock_ds, \
         patch("uniquant.services.health_service.AnalysisService"), \
         patch("uniquant.services.health_service.DecisionBrain"), \
         patch("uniquant.services.health_service.get_config") as mock_config:
        cfg = MagicMock()
        cfg._config = {"base": {}, "cache": {}, "brain": {}}
        cfg.LAKE_DIR = MagicMock()
        cfg.LAKE_DIR.exists.return_value = True
        cfg.CACHE_DIR = MagicMock()
        cfg.CACHE_DIR.exists.return_value = True
        cfg.get.return_value = True
        cfg.validate_config.return_value = True
        mock_config.return_value = cfg

        mock_ds_instance = MagicMock()
        mock_ds_instance.cache_manager.get_stats.return_value = {"total_items": 42}
        mock_ds.return_value = mock_ds_instance

        svc = HealthService()
        svc.config = cfg
        svc.data_service = mock_ds_instance
        return svc


class TestLiveness:
    def test_liveness_returns_alive(self, health_service):
        result = health_service.liveness()
        assert result["status"] == "alive"
        assert "timestamp" in result
        assert result["config_loaded"] is True

    def test_liveness_config_sections(self, health_service):
        result = health_service.liveness()
        assert "base" in result["config_sections"]
        assert "cache" in result["config_sections"]


class TestReadiness:
    def test_readiness_ready(self, health_service):
        result = health_service.readiness()
        assert result["status"] == "ready"
        assert result["issues"] == []

    def test_readiness_not_ready_when_lake_missing(self, health_service):
        health_service.config.LAKE_DIR.exists.return_value = False
        result = health_service.readiness()
        assert result["status"] == "not_ready"
        assert any("Data lake path not found" in i for i in result["issues"])

    def test_readiness_not_ready_when_cache_missing(self, health_service):
        health_service.config.CACHE_DIR.exists.return_value = False
        result = health_service.readiness()
        assert result["status"] == "not_ready"
        assert any("Cache path not found" in i for i in result["issues"])

    def test_readiness_includes_cache_hit_ratio(self, health_service):
        result = health_service.readiness()
        assert "cache_hit_ratio" in result

    def test_readiness_includes_last_fetch_times(self, health_service):
        result = health_service.readiness()
        assert "last_fetch_times" in result


class TestDiagnostics:
    def test_diagnostics_delegates_to_get_system_health(self, health_service):
        with patch.object(health_service, "get_system_health",
                          return_value={"overall_status": "healthy"}):
            result = health_service.diagnostics()
            assert result["overall_status"] == "healthy"


class TestDataTracking:
    def test_record_cache_hit_miss(self, health_service):
        health_service.record_cache_hit("source_a")
        health_service.record_cache_hit("source_a")
        health_service.record_cache_miss("source_a")
        assert health_service._cache_hit_count == 2
        assert health_service._cache_miss_count == 1
        assert health_service._cache_hit_ratio() == 2 / 3

    def test_cache_hit_ratio_zero_when_no_data(self, health_service):
        assert health_service._cache_hit_ratio() == 0.0

    def test_record_fetch_tracks_source(self, health_service):
        health_service.record_fetch("tdx", success=True)
        health_service.record_fetch("online", success=False)
        assert "tdx" in health_service._last_fetch_time
        assert "online" in health_service._last_fetch_time
        assert health_service._last_fetch_success["tdx"] is True
        assert health_service._last_fetch_success["online"] is False

    def test_get_system_metrics_includes_cache_hit_ratio(self, health_service):
        health_service.record_cache_hit()
        health_service.record_cache_miss()
        metrics = health_service._get_system_metrics()
        assert "cache_hit_ratio" in metrics
        assert metrics["cache_hit_ratio"] == 0.5

    def test_get_system_metrics_includes_data_freshness(self, health_service):
        health_service.record_fetch("tdx", success=True)
        metrics = health_service._get_system_metrics()
        assert "data_freshness" in metrics
        assert "tdx" in metrics["data_freshness"]
        assert metrics["data_freshness"]["tdx"]["last_success"] is True
