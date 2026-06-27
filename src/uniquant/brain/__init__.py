"""
分析大脑模块

子包: CZSC (缠论), FSM (状态机), LPPL (泡沫检测), Wyckoff, NTF, Regime, AlphaDecoupler, Factors, Indicators, Screener
公开导出: DecisionBrain, FSM, FSMState, Indicators, NTFEngine, RegimeDetector, AlphaDecoupler, StockScreener, FactorRegistry, FactorAnalyzer, FactorComposer, FinancialFactorBridge
"""

from .fsm.fsm import DecisionBrain, FSM, FSMState

try:
    from .indicators.indicators import Indicators
except ImportError:
    Indicators = None

try:
    from .ntf import NTFEngine
except ImportError:
    NTFEngine = None

try:
    from .regime import RegimeDetector
except ImportError:
    RegimeDetector = None

try:
    from .alpha_decoupler.alpha_decoupler import AlphaDecoupler
except ImportError:
    AlphaDecoupler = None

try:
    from .screener.screener import StockScreener
except ImportError:
    StockScreener = None

try:
    from .factors import FactorRegistry, FactorAnalyzer, FactorComposer, FinancialFactorBridge
except ImportError:
    FactorRegistry = None
    FactorAnalyzer = None
    FactorComposer = None
    FinancialFactorBridge = None

__all__ = [
    "FSM",
    "FSMState",
    "DecisionBrain",
    "Indicators",
    "NTFEngine",
    "RegimeDetector",
    "AlphaDecoupler",
    "StockScreener",
    "FactorRegistry",
    "FactorAnalyzer",
    "FactorComposer",
    "FinancialFactorBridge",
]
