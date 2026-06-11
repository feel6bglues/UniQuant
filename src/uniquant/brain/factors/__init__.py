"""
因子系统

包含: FactorRegistry, FactorAnalyzer, FactorComposer, CustomFactors
auto_mined/ 已于 2026-06-09 移除 (PBO=1.000 万箭穿心, 逻辑因子已取代)
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
