"""
缓存接口定义
Cache Interface Definition
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class CacheInterface(ABC):
    """
    缓存管理器统一接口
    所有缓存实现必须遵循此接口
    """

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存数据

        Args:
            key: 缓存键

        Returns:
            缓存的数据，如果不存在或已过期则返回 None
        """
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """
        设置缓存数据

        Args:
            key: 缓存键
            value: 要缓存的数据
            ttl: 缓存有效期（秒），默认 3600 秒（1小时）

        Returns:
            是否设置成功
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        删除指定缓存

        Args:
            key: 缓存键

        Returns:
            是否删除成功
        """
        pass

    @abstractmethod
    def clear(self, pattern: Optional[str] = None) -> int:
        """
        清空缓存

        Args:
            pattern: 可选的匹配模式，如果提供则只清除匹配的缓存

        Returns:
            清除的缓存项数量
        """
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息

        Returns:
            包含 hits, misses, size, files 等统计信息的字典
        """
        pass

    @abstractmethod
    def reset_stats(self) -> None:
        """
        重置缓存统计信息
        """
        pass

    @abstractmethod
    def cleanup(self) -> int:
        """
        清理过期缓存

        Returns:
            清理的缓存项数量
        """
        pass
