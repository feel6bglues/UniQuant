"""
策略执行模块 (hands)

回测引擎、撮合引擎、组合引擎、策略框架、报告。

推荐使用 UnifiedBacktestEngine + UnifiedMatchingEngine (基于 typed TradingSignal)。
BacktestEngine (旧版) 保留兼容性但已弃用。
子模块: backtest (引擎/撮合/组合), strategies (策略), reporter (报告), results_manager (结果管理), robustness (稳健性分析)
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
