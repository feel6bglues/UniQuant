"""
数据模块

多源数据摄取、数据湖存储、清洗、校验、复权。
数据源: TDX, BaoStock, Sina, Tencent, THS, Eastmoney, mootdx
子模块: sources (数据源), lake (数据湖), managers (管理器), pipeline (管道), services (服务), parsers (解析器), utils (工具), realtime (实时桥)
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
