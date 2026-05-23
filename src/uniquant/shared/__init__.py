"""
共享模块
"""

from .analysis_result import AnalysisResult, AnalysisResultBuilder, AnalysisStatus
from .constants import (
    DataValidationConstants,
    IndicatorThresholds,
    MarketCapThresholds,
    MarketConstants,
    PerformanceConstants,
    PrecisionConstants,
    RiskThresholds,
    TimeWindows,
)
from .logger_factory import LoggerFactory, get_logger, setup_logger

# 移除 deprecated 的 cache_manager 导入
# from .cache_manager import CacheManager, cached, global_cache
from .retry_decorator import RetryConfig, retry, retry_with_fallback
from .utils import (
    fetch_with_timeout,
    normalize_dataframe,
    retry_on_failure,
    safe_execute,
    with_timeout,
)

__all__ = [
    # Utils
    "with_timeout",
    "safe_execute",
    "fetch_with_timeout",
    "normalize_dataframe",
    "retry_on_failure",
    # Constants
    "MarketCapThresholds",
    "TimeWindows",
    "IndicatorThresholds",
    "RiskThresholds",
    "DataValidationConstants",
    "PrecisionConstants",
    "PerformanceConstants",
    "MarketConstants",
    # Logger
    "get_logger",
    "setup_logger",
    "LoggerFactory",
    # Cache - 移除 deprecated API
    # "CacheManager",
    # "cached",
    # "global_cache",
    # Retry
    "retry",
    "retry_with_fallback",
    "RetryConfig",
    # Analysis Result
    "AnalysisResult",
    "AnalysisResultBuilder",
    "AnalysisStatus",
]
