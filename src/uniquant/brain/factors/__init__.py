"""
因子系统

包含: FactorRegistry, FactorAnalyzer, FactorComposer, CustomFactors
GP 因子挖掘引擎已迁至 experiments/gp_factor_mining/ (2026-06-17).
"""
from .registry import FactorRegistry
from .analyzer import FactorAnalyzer
from .composer import FactorComposer
from .financial_bridge import FinancialFactorBridge
from . import custom_factors   # noqa: F401 - 导入以注册基础因子

__all__ = [
    "FactorRegistry",
    "FactorAnalyzer",
    "FactorComposer",
    "FinancialFactorBridge",
]
