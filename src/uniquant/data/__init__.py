"""
数据模块初始化
Data Module Initialization

导出数据获取、存储、清洗、导入等核心功能
使用延迟导入避免循环依赖
"""

__all__ = [
    # 数据获取
    "DataFetcher",
    # 数据存储
    "StorageManager",
    # 数据管道
    "DataPipeline",
    # LPPL数据服务
    "LPPLDataService",
]

import typing
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from loguru import Logger as LoguruLogger
    except ImportError:
        LoguruLogger = None

try:
    from loguru import logger
except ImportError:
    from ..shared.logger_factory import get_logger
    logger = get_logger(__name__)


def __getattr__(name: str) -> typing.Any:
    """延迟导入，避免循环依赖"""
    if name == "DataFetcher":
        from .data_fetcher import DataFetcher

        return DataFetcher
    elif name == "StorageManager":
        from .lake.storage_manager import StorageManager

        return StorageManager
    elif name == "DataPipeline":
        from .data_pipeline_service import DataPipelineService

        return DataPipelineService
    elif name == "LPPLDataService":
        try:
            from .services.lppl_data_service import LPPLDataService

            return LPPLDataService
        except ImportError as e:
            logger.error(f"无法导入 LPPLDataService: {e}")
            return None
    raise AttributeError(f"module 'uniquant.data' has no attribute '{name}'")
