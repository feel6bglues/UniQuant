"""
CZSC 缠论分析模块

基于 czsc 库的笔段中枢识别和买卖信号生成。
需要安装: pip install czsc
"""

try:
    from .czsc_engine import CZSCEngine
except ImportError:
    CZSCEngine = None  # 需要安装 czsc 库: pip install czsc

__all__ = [
    "CZSCEngine",
]
