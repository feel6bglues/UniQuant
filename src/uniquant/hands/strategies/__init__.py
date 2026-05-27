"""
策略模块初始化

导出策略的基类和具体实现:
- FSMStrategy: 有限状态机策略 (MA20/MA60 趋势跟踪)
- WyckoffStrategy: 威科夫量价分析策略
- RegimeStrategy: 市场状态驱动策略
- ReversalStrategy: 短期超卖反弹策略
- MaAtrStrategy: 均线交叉 + ATR 止损策略
"""

__all__ = [
    "BaseStrategy",
    "FSMStrategy",
    "WyckoffStrategy",
    "RegimeStrategy",
    "ReversalStrategy",
    "MaAtrStrategy",
    "STRATEGY_MAP",
]

# 策略注册表: 名称 → 懒加载路径
STRATEGY_MAP = {
    "fsm": "uniquant.hands.strategies.fsm_strategy.FSMStrategy",
    "wyckoff": "uniquant.hands.strategies.wyckoff_strategy.WyckoffStrategy",
    "regime": "uniquant.hands.strategies.regime_strategy.RegimeStrategy",
    "reversal": "uniquant.hands.strategies.reversal_strategy.ReversalStrategy",
    "ma_atr": "uniquant.hands.strategies.ma_atr_strategy.MaAtrStrategy",
}


def __getattr__(name: str):
    """延迟导入，避免循环依赖"""
    _imports = {
        "BaseStrategy": ".base",
        "FSMStrategy": ".fsm_strategy",
        "WyckoffStrategy": ".wyckoff_strategy",
        "RegimeStrategy": ".regime_strategy",
        "ReversalStrategy": ".reversal_strategy",
        "MaAtrStrategy": ".ma_atr_strategy",
    }

    if name in _imports:
        try:
            import importlib
            mod = importlib.import_module(_imports[name], package=__name__)
            return getattr(mod, name)
        except ImportError as e:
            raise AttributeError(f"module {__name__!r} cannot import {name}: {e}")

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
