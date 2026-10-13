"""
数据管理器模块
"""

from .standard_adapter import DataSourceAdapter, StandardAdapter
from .source_router import SourceRouter
from .stock_metadata_manager import StockMetadataManager, StockMetadata

__all__ = [
    "DataSourceAdapter", 
    "StandardAdapter", 
    "SourceRouter",
    "StockMetadataManager",
    "StockMetadata",
]
