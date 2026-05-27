"""
数据管理器模块
"""

from .standard_adapter import DataSourceAdapter, StandardAdapter
from .source_router import SourceRouter
from .stock_metadata_manager import StockMetadataManager, StockMetadata
from .factor_manager import FactorManager
from .mootdx_factor_manager import MootdxFactorManager

__all__ = [
    "DataSourceAdapter", 
    "StandardAdapter", 
    "SourceRouter",
    "StockMetadataManager",
    "StockMetadata",
    "FactorManager",
    "MootdxFactorManager",
]
