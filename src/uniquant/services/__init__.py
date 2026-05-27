"""
服务层模块

Phase 1C 迁移完成。使用 try/except 容错处理深层第三方依赖。
"""

try:
    from .cache_coordinator import CacheCoordinator
except ImportError:
    CacheCoordinator = None

try:
    from .data_service import DataService
except ImportError:
    DataService = None

try:
    from .health_service import HealthService
except ImportError:
    HealthService = None

try:
    from .portfolio_service import PortfolioService
except ImportError:
    PortfolioService = None

try:
    from .scan_service import ScanPipeline
except ImportError:
    ScanPipeline = None

try:
    from .stock_query_service import StockQueryService
except ImportError:
    StockQueryService = None

try:
    from .validation_service import ValidationService
except ImportError:
    ValidationService = None

try:
    from .analysis_service import AnalysisService
except ImportError:
    AnalysisService = None

try:
    from .service_container import ServiceContainer
except ImportError:
    ServiceContainer = None

__all__ = [
    "CacheCoordinator", "DataService", "HealthService",
    "PortfolioService", "ScanPipeline", "StockQueryService",
    "ValidationService", "AnalysisService", "ServiceContainer",
]
