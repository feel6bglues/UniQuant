"""
策略模块初始化
Strategy Module Initialization

导出策略的基类和具体实现，如状态机策略等
"""

__all__ = [  # pylint: disable=undefined-all-variable
    "BaseStrategy",
    "FSMStrategy",
]

try:
    from loguru import logger
except ImportError:
    from uniquant.shared.logger_factory import get_logger

    logger = get_logger(__name__)


def __getattr__(name):
    """延迟导入，避免循环依赖"""
    if name == "BaseStrategy":
        from uniquant.hands.strategies.base import BaseStrategy

        return BaseStrategy
    elif name == "FSMStrategy":
        from uniquant.hands.strategies.fsm_strategy import FSMStrategy

        return FSMStrategy
    raise AttributeError(f"module 'uniquant.hands.strategies' has no attribute '{name}'")
