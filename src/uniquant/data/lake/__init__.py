"""
数据湖模块初始化
Data Lake Module Initialization

导出数据湖核心功能，包括数据存储、验证和管理等
"""

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)

__all__ = ["StorageManager"]


def __getattr__(name):
    """延迟导入，避免循环依赖"""
    if name == "StorageManager":
        from .storage_manager import StorageManager
        return StorageManager
    raise AttributeError(f"module 'uniquant.data.lake' has no attribute '{name}'")
