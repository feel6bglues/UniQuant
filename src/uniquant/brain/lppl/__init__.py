"""
LPPL 泡沫检测模块
"""
from .engine import LPPLConfig, LPPLEngine

try:
    from .calculator import LPPLCalculator, lppl_func
except ImportError:
    LPPLCalculator = None
    lppl_func = None

try:
    from .data_manager import LPPLDataManager
except ImportError:
    LPPLDataManager = None

try:
    from .visualizer import LPPLVisualizer
except ImportError:
    LPPLVisualizer = None

__all__ = [
    "LPPLConfig", "LPPLEngine",
    "LPPLCalculator", "LPPLDataManager", "LPPLVisualizer",
]
