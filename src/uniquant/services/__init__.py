"""
服务层模块

DAG 依赖注入 + 服务编排。
核心服务: ServiceContainer (DI容器), AnalysisService (分析编排), DataService (数据), HealthService (健康检查),
          CacheCoordinator (缓存), ScanPipeline (扫描), PortfolioService (组合), StockQueryService (股票查询),
          ValidationService (验证), ResearchPipeline (研究管道)
分析引擎 (analysis/): CZSC, FSM, LPPL, NTF, Regime, Wyckoff, Macro, Technical, ReportGenerator, SignalService
"""

__all__ = [
    "CacheCoordinator", "DataService", "HealthService",
    "PortfolioService", "ScanPipeline", "StockQueryService",
    "ValidationService", "AnalysisService", "ServiceContainer",
    "DataAccessService", "DataQualityService",
    "MarketRegimeService", "ReportService", "SignalGenerationService",
]


def __getattr__(name: str):
    """延迟导入，避免深层依赖链"""
    _imports = {
        "CacheCoordinator": ".cache_coordinator",
        "DataService": ".data_service",
        "HealthService": ".health_service",
        "PortfolioService": ".portfolio_service",
        "ScanPipeline": ".scan_service",
        "StockQueryService": ".stock_query_service",
        "ValidationService": ".validation_service",
        "AnalysisService": ".analysis_service_v2",
        "ServiceContainer": ".service_container",
        "DataAccessService": ".data_access_service",
        "DataQualityService": ".data_quality_service",
        "MarketRegimeService": ".market_regime_service",
        "ReportService": ".report_service",
        "SignalGenerationService": ".signal_generation_service",
    }

    if name in _imports:
        try:
            import importlib
            mod = importlib.import_module(_imports[name], package=__name__)
            return getattr(mod, name)
        except ImportError:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r} (dependency not installed)")

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
