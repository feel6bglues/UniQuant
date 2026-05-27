"""
策略执行模块初始化
Strategy Execution Module Initialization

导出策略执行和报告生成等核心功能
"""

__all__ = [  # pylint: disable=undefined-all-variable
    "Reporter",
    "ResultsManager",
    "BacktestEngine",
    "BacktestResult",
    "TradeRecord",
    "backtest",
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
    elif name == "BacktestEngine":
        from uniquant.hands.backtest.engine import BacktestEngine

        return BacktestEngine
    elif name == "BacktestResult":
        from uniquant.hands.backtest.result import BacktestResult

        return BacktestResult
    elif name == "TradeRecord":
        from uniquant.hands.backtest.result import TradeRecord

        return TradeRecord
    elif name == "backtest":
        import uniquant.hands.backtest

        return uniquant.hands.backtest
    elif name == "strategies":
        import uniquant.hands.strategies

        return uniquant.hands.strategies
    raise AttributeError(f"module 'uniquant.hands' has no attribute '{name}'")
