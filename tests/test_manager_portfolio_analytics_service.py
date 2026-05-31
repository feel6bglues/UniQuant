import pandas as pd

from uniquant.ui.manager_portfolio_analytics_service import ManagerPortfolioAnalyticsService


def test_manager_portfolio_analytics_service_returns_error_without_enough_data():
    manager = type("Manager", (), {"get_real_kline_data": lambda *args, **kwargs: pd.DataFrame()})()

    result = ManagerPortfolioAnalyticsService(manager).calculate_portfolio_risk_metrics(
        ["000001.SZ"]
    )

    assert result == {"error": "无法获取足够的股票数据"}


def test_manager_portfolio_analytics_service_builds_stress_test_result(monkeypatch):
    class FakeEVTRisk:
        def calculate_stress_test(self, returns, scenarios):
            return {"count": len(returns), "scenarios": scenarios}

    class Manager:
        def get_real_kline_data(self, *args, **kwargs):
            return pd.DataFrame({"close": list(range(100, 180))})

    monkeypatch.setattr("uniquant.risk.evt_risk.EVTRisk", FakeEVTRisk)

    result = ManagerPortfolioAnalyticsService(Manager()).run_stress_test(
        ["000001.SZ"], scenarios=["flash_crash"]
    )

    assert result["status"] == "success"
    assert result["scenario_results"]["scenarios"] == ["flash_crash"]


def test_manager_portfolio_analytics_service_rejects_unknown_optimize_method():
    class Manager:
        def get_real_kline_data(self, *args, **kwargs):
            return pd.DataFrame({"close": list(range(100, 180))})

    result = ManagerPortfolioAnalyticsService(Manager()).optimize_portfolio(
        ["000001.SZ", "600519.SH"], method="unknown"
    )

    assert result == {"error": "未知的优化方法: unknown"}
