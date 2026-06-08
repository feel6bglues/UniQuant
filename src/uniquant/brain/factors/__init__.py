"""
因子系统

包含: FactorRegistry, FactorAnalyzer, FactorComposer, CustomFactors
"""
from .registry import FactorRegistry
from .analyzer import FactorAnalyzer
from .composer import FactorComposer
from .financial_bridge import FinancialFactorBridge
from . import custom_factors   # noqa: F401 - 导入以注册基础因子
from . import auto_mined       # noqa: F401 - 导入以注册 auto-mined 因子

__all__ = [
    "FactorRegistry",
    "FactorAnalyzer",
    "FactorComposer",
    "FinancialFactorBridge",
]
