"""
共享模块
"""

from .analysis_result import AnalysisResult, AnalysisResultBuilder, AnalysisStatus
from .market_rules import BOARD_RULES, BoardRule, BoardType, detect_board, get_board_rule
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

from .kill_switch import KillSwitchError, SharedKillSwitch, get_kill_switch
from .config_schema import AppConfig, ConfigValidationError
from .secret_manager import SecretManager, get_secret_manager
from .prometheus_metrics import MetricsRegistry, get_metrics, measure, ensure_prometheus_server

__all__ = [
    "KillSwitchError",
    "SharedKillSwitch",
    "get_kill_switch",
    "AppConfig",
    "ConfigValidationError",
    "SecretManager",
    "get_secret_manager",
    "MetricsRegistry",
    "get_metrics",
    "measure",
    "ensure_prometheus_server",
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
    # Market Rules
    "BoardType",
    "BoardRule",
    "BOARD_RULES",
    "detect_board",
    "get_board_rule",
]
