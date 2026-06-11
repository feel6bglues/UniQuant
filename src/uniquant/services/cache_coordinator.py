"""
缓存协调器
负责缓存一致性、健康管理和缓存操作
"""
from typing import Any, Dict, Optional

import pandas as pd

from ..shared.time_provider import get_time_provider
from ..shared.cache import CacheFactory
from ..shared.constants import DataServiceConstants
from ..shared.logger_factory import get_logger

logger = get_logger("CacheCoordinator")

CACHE_RECOVERABLE_ERRORS = (
    AttributeError,
    KeyError,
    OSError,
    TypeError,
    ValueError,
)


class CacheCoordinator:
    """
    缓存协调器
    
    职责：
    - 缓存键生成和管理
    - 缓存一致性检查
    - 缓存健康状态监控
    - 缓存数据读写
    """
    
    def __init__(self, cache_dir: str = "data/service_cache"):
        """
        初始化缓存协调器
        
        Args:
            cache_dir: 缓存目录
        """
        self.cache_manager = CacheFactory.create("disk", cache_dir=cache_dir)
        logger.info("CacheCoordinator initialized")
    
    def generate_cache_key(
        self, 
        prefix: str, 
        *args, 
        namespace: str = "default"
    ) -> str:
        """
        生成缓存键
        
        Args:
            prefix: 前缀
            *args: 参数
            namespace: 命名空间
            
        Returns:
            str: 缓存键
        """
        safe_args = [
            str(a).replace(":", "-").replace("/", "-").replace("\\", "-") 
            for a in args
        ]
        args_str = "_".join(safe_args)
        return f"{namespace}:{prefix}:{args_str}"
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存数据
        
        Args:
            key: 缓存键
            
        Returns:
            缓存数据或None
        """
        return self.cache_manager.get(key)
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        data_type: str = "general",
    ) -> None:
        """
        设置缓存
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
            data_type: 数据类型
        """
        if ttl is None:
            ttl = self._get_ttl_by_data_type(data_type)
        
        self.cache_manager.set(key, value, ttl=ttl)
    
    def _get_ttl_by_data_type(self, data_type: str) -> int:
        """根据数据类型获取TTL"""
        ttl_map = {
            "stock": DataServiceConstants.CACHE_TTL_STOCK,
            "index": DataServiceConstants.CACHE_TTL_INDEX,
            "etf": DataServiceConstants.CACHE_TTL_ETF,
            "realtime": DataServiceConstants.CACHE_TTL_REALTIME,
            "industry": DataServiceConstants.CACHE_TTL_INDUSTRY,
            "concept": DataServiceConstants.CACHE_TTL_CONCEPT,
            "general": DataServiceConstants.CACHE_TTL_GENERAL,
        }
        return ttl_map.get(data_type, DataServiceConstants.CACHE_TTL_GENERAL)
    
    def clear(self) -> None:
        """清除所有缓存"""
        self.cache_manager.clear()
        logger.info("Cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            Dict: 缓存统计
        """
        return self.cache_manager.get_stats()
    
    def check_health(self) -> Dict[str, Any]:
        """
        检查缓存健康状态
        
        Returns:
            Dict: 缓存健康状态
        """
        try:
            stats = self.cache_manager.get_stats()
            
            health_status = {
                "total_items": stats.get("total_items", 0),
                "hit_rate": stats.get("hit_rate", 0.0),
                "miss_rate": stats.get("miss_rate", 0.0),
                "cache_size": stats.get("cache_size", 0),
                "status": "healthy" if stats.get("total_items", 0) > 0 else "empty",
                "last_check": pd.Timestamp(get_time_provider().now()).strftime("%Y-%m-%d %H:%M:%S"),
            }
            
            logger.info("Cache health check: %s", health_status)
            return health_status
        except CACHE_RECOVERABLE_ERRORS as e:
            logger.error("Cache health check failed: %s", e)
            return {
                "status": "error",
                "error": str(e),
                "last_check": pd.Timestamp(get_time_provider().now()).strftime("%Y-%m-%d %H:%M:%S"),
            }
    
    def check_consistency(
        self,
        symbol: str,
        cached_data: Optional[pd.DataFrame],
        source_data: Optional[pd.DataFrame],
    ) -> bool:
        """
        检查缓存与数据源的一致性
        
        Args:
            symbol: 证券代码
            cached_data: 缓存数据
            source_data: 数据源数据
            
        Returns:
            bool: 缓存是否一致
        """
        if cached_data is None or cached_data.empty:
            logger.info("No cache for %s, consistency check skipped", symbol)
            return False
        
        if source_data is None or source_data.empty:
            logger.warning("Failed to fetch data from source for consistency check")
            return False
        
        if not cached_data.empty:
            cached_latest = (
                cached_data.index.max()
                if isinstance(cached_data.index, pd.DatetimeIndex)
                else None
            )
            source_latest = (
                source_data.index.max()
                if isinstance(source_data.index, pd.DatetimeIndex)
                else None
            )
            
            if cached_latest and source_latest:
                if cached_latest >= source_latest:
                    logger.info("Cache is consistent for %s", symbol)
                    return True
                else:
                    logger.warning(
                        "Cache is outdated for %s: cached=%s, source=%s", symbol, cached_latest, source_latest
                    )
                    return False
        
        return False
    
    def safe_cache_data(
        self, 
        key: str, 
        data: Any, 
        ttl: Optional[int] = None, 
        data_type: str = "general"
    ) -> bool:
        """
        安全缓存数据（失败不影响业务流程）
        
        Args:
            key: 缓存键
            data: 缓存数据
            ttl: 过期时间
            data_type: 数据类型
            
        Returns:
            bool: 是否成功
        """
        try:
            self.set(key, data, ttl=ttl, data_type=data_type)
            logger.debug("数据已缓存: %s (ttl: %s)", key, ttl or 'auto')
            return True
        except CACHE_RECOVERABLE_ERRORS as e:
            logger.warning("缓存数据失败（非关键错误）: %s", e)
            return False
