"""
策略执行模块初始化
Strategy Execution Module Initialization

导出策略执行和报告生成等核心功能
"""

__all__ = [  # pylint: disable=undefined-all-variable
    "Reporter",
    "ResultsManager",
    "strategies",
]

from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


def __getattr__(name):
    """延迟导入，避免循环依赖"""
    if name == "Reporter":
        from uniquant.hands.reporter import Reporter

        return Reporter
    elif name == "ResultsManager":
        from uniquant.hands.results_manager import ResultsManager

        return ResultsManager
    elif name == "strategies":
        import uniquant.hands.strategies

        return uniquant.hands.strategies
    raise AttributeError(f"module 'src.hands' has no attribute '{name}'")
