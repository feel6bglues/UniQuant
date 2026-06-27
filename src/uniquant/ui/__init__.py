"""
用户界面模块

基于 Streamlit 构建的交互式量化分析仪表盘。
包含: 主仪表盘 (dashboard), LPPL 可视化 (lppl_visualizer), 系统健康检查 (health_check),
      资产管理逻辑 (manager_logic), 可复用组件 (components), 报告服务 (report_service),
      组合分析 (portfolio_analytics)
"""

import typing

__all__ = [
    "AssetManager", "FSMStateInfo", "LPPLVisualizer",
    "ManagerPortfolioAnalyticsService", "ManagerReportService",
    "ModuleHealthChecker", "run_dashboard",
]


def __getattr__(name: str) -> typing.Any:
    if name == "run_dashboard":
        from .dashboard import main as run_dashboard
        return run_dashboard
    elif name == "ModuleHealthChecker":
        from .health_check import ModuleHealthChecker
        return ModuleHealthChecker
    elif name == "LPPLVisualizer":
        from .lppl_visualizer import LPPLVisualizer
        return LPPLVisualizer
    elif name == "AssetManager":
        from .manager_logic import AssetManager
        return AssetManager
    elif name == "FSMStateInfo":
        from .manager_logic import FSMStateInfo
        return FSMStateInfo
    elif name == "ManagerReportService":
        from .manager_report_service import ManagerReportService
        return ManagerReportService
    elif name == "ManagerPortfolioAnalyticsService":
        from .manager_portfolio_analytics_service import ManagerPortfolioAnalyticsService
        return ManagerPortfolioAnalyticsService
    raise AttributeError(f"module 'uniquant.ui' has no attribute '{name}'")
