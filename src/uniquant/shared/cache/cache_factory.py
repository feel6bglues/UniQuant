"""
缓存工厂
Cache Factory
"""

from typing import Literal, Optional

from ..logger_factory import get_logger
from .backends import DiskCacheBackend, MemoryCacheBackend
from .cache_interface import CacheInterface

logger = get_logger(__name__)


class CacheFactory:
    """
    缓存工厂类
    用于创建不同类型的缓存实例
    """

    @staticmethod
    def create(backend: Literal["memory", "disk"] = "disk", **kwargs) -> CacheInterface:
        """
        创建缓存实例

        Args:
            backend: 缓存后端类型，'memory' 或 'disk'
            **kwargs: 后端特定的参数

                Memory 后端参数:
                    - max_size: 最大缓存项数量，默认 100

                Disk 后端参数:
                    - cache_dir: 缓存目录，默认 'data/cache'
                    - max_cache_age: 最大缓存天数，默认 7
                    - max_cache_size: 最大缓存大小（字节），默认 500MB

        Returns:
            CacheInterface: 缓存实例

        Raises:
            ValueError: 如果 backend 类型不支持

        Examples:
            >>> # 创建内存缓存
            >>> cache = CacheFactory.create('memory', max_size=200)

            >>> # 创建磁盘缓存
            >>> cache = CacheFactory.create('disk', cache_dir='data/my_cache')
        """
        if backend == "memory":
            from ..constants import PerformanceConstants

            max_size = kwargs.get("max_size", PerformanceConstants.CACHE_MAX_SIZE)
            logger.info(f"Creating MemoryCacheBackend with max_size={max_size}")
            return MemoryCacheBackend(max_size=max_size)

        elif backend == "disk":
            from ..constants import CacheConstants, PerformanceConstants

            cache_dir = kwargs.get("cache_dir", "data/cache")
            max_cache_age = kwargs.get("max_cache_age", CacheConstants.MAX_CACHE_AGE)
            max_cache_size = kwargs.get(
                "max_cache_size", CacheConstants.DEFAULT_MAX_CACHE_SIZE
            )

            logger.info(f"Creating DiskCacheBackend at {cache_dir}")
            return DiskCacheBackend(
                cache_dir=cache_dir,
                max_cache_age=max_cache_age,
                max_cache_size=max_cache_size,
            )

        else:
            raise ValueError(
                f"Unsupported backend type: {backend}. Must be 'memory' or 'disk'"
            )

    @staticmethod
    def create_default() -> CacheInterface:
        """
        创建默认缓存实例（磁盘缓存）

        Returns:
            CacheInterface: 默认的磁盘缓存实例
        """
        logger.info("Creating default DiskCacheBackend")
        return CacheFactory.create("disk")
