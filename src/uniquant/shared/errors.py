"""
Alpha-Tactician Legacy Errors Module

此模块已废弃，保留仅用于向后兼容。
所有新代码应该使用 exceptions.py 中的异常类。

This module is deprecated and kept only for backward compatibility.
All new code should use exceptions from exceptions.py instead.
"""

# Import all exceptions from the new unified exceptions module
from .exceptions import AlphaTacticianError as AlphaError  # Legacy name
from .exceptions import DataFetchError as DataError  # Legacy mapping
from .exceptions import EngineError

# Re-export for backward compatibility
__all__ = [
    "AlphaError",
    "DataError",
    "EngineError",
]
