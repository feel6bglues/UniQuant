from uniquant.services.cache_coordinator import CacheCoordinator
from uniquant.services.data_quality_service import DataQualityService
from uniquant.services.portfolio_service import PortfolioService


def test_cache_coordinator_health_returns_error_payload_on_stats_failure():
    coordinator = CacheCoordinator()

    class DummyCacheManager:
        def get_stats(self):
            raise ValueError("stats failed")

    coordinator.cache_manager = DummyCacheManager()

    result = coordinator.check_health()

    assert result["status"] == "error"
    assert "stats failed" in result["error"]


def test_data_quality_report_returns_error_payload_on_invalid_health_result(monkeypatch):
    service = DataQualityService()

    def raise_value_error(data_items):
        raise ValueError("quality failed")

    monkeypatch.setattr(service, "check_data_health", raise_value_error)

    result = service.generate_data_quality_report([{"symbol": "000001.SZ"}])

    assert "error" in result
    assert "quality failed" in result["error"]


def test_portfolio_rebalance_portfolio_returns_empty_on_unexpected_error(monkeypatch):
    service = PortfolioService()

    class BrokenDict(dict):
        def copy(self):
            raise RuntimeError("copy failed")

    result = service.rebalance_portfolio(BrokenDict({"weights": {}}), {"000001.SZ": 1.0})

    assert result == {}


def test_portfolio_generate_rebalancing_signals_returns_empty_on_unexpected_error():
    service = PortfolioService()

    class BrokenPortfolio(dict):
        def get(self, key, default=None):
            raise RuntimeError("signal failed")

    result = service.generate_rebalancing_signals(BrokenPortfolio())

    assert result == {}
