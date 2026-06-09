import pandas as pd

from uniquant.ui.manager_portfolio_analytics_service import ManagerPortfolioAnalyticsService


def test_manager_portfolio_analytics_service_returns_error_without_enough_data():
    manager = type("Manager", (), {"get_real_kline_data": lambda *args, **kwargs: pd.DataFrame()})()

    result = ManagerPortfolioAnalyticsService(manager).calculate_portfolio_risk_metrics(
        ["000001.SZ"]
    )

    assert result == {"error": "无法获取足够的股票数据"}


def test_manager_portfolio_analytics_service_builds_stress_test_result():
    class FakePortfolioService:
        def __init__(self):
            self.received_returns_len = None
            self.received_scenarios = None

        def run_evt_stress_test(self, returns, scenarios):
            self.received_returns_len = len(returns)
            self.received_scenarios = scenarios
            return {"count": len(returns), "scenarios": scenarios}

    class Manager:
        def __init__(self):
            self.portfolio_service = FakePortfolioService()

        def get_real_kline_data(self, *args, **kwargs):
            return pd.DataFrame({"close": list(range(100, 180))})

    manager = Manager()

    result = ManagerPortfolioAnalyticsService(manager).run_stress_test(
        ["000001.SZ"], scenarios=["flash_crash"]
    )

    assert result["status"] == "success"
    assert result["scenario_results"]["scenarios"] == ["flash_crash"]
    assert manager.portfolio_service.received_returns_len == 79
    assert manager.portfolio_service.received_scenarios == ["flash_crash"]


def test_manager_portfolio_analytics_service_rejects_unknown_optimize_method():
    class Manager:
        def get_real_kline_data(self, *args, **kwargs):
            return pd.DataFrame({"close": list(range(100, 180))})

    result = ManagerPortfolioAnalyticsService(Manager()).optimize_portfolio(
        ["000001.SZ", "600519.SH"], method="unknown"
    )

    assert result == {"error": "未知的优化方法: unknown"}


def test_manager_portfolio_analytics_service_does_not_import_risk_layer():
    source = ManagerPortfolioAnalyticsService.__module__
    module = __import__(source, fromlist=["__file__"])

    with open(module.__file__, encoding="utf-8") as file:
        content = file.read()

    assert "..risk" not in content
    assert "uniquant.risk" not in content
