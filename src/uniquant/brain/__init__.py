"""
分析大脑模块

包含: CZSC 缠论、FSM 状态机、LPPL 泡沫检测、Indicators、NTF、Regime、AlphaDecoupler
待迁移: Wyckoff、Factors、Screener
"""

from .fsm.fsm import DecisionBrain, FSM, FSMState

try:
    from .indicators import Indicators
except ImportError:
    Indicators = None

try:
    from .ntf_engine import NTFEngine
except ImportError:
    NTFEngine = None

try:
    from .regime_detector import RegimeDetector
except ImportError:
    RegimeDetector = None

try:
    from .alpha_decoupler import AlphaDecoupler
except ImportError:
    AlphaDecoupler = None

__all__ = [
    "FSM",
    "FSMState",
    "DecisionBrain",
    "Indicators",
    "NTFEngine",
    "RegimeDetector",
    "AlphaDecoupler",
]
