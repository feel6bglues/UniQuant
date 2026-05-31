"""
统一缓存管理模块
Unified Cache Management Module
"""

import functools
import hashlib
import json
from typing import Callable

import pandas as pd

from ..constants import CacheConstants
from ..logger_factory import get_logger
from .backends import DiskCacheBackend, MemoryCacheBackend
from .cache_factory import CacheFactory
from .cache_interface import CacheInterface

logger = get_logger(__name__)

def _hash_dataframe(df: pd.DataFrame) -> str:
    """为DataFrame生成高效哈希 (SHA256)"""
    if df.empty:
        return "empty"
    
    return pd.util.hash_pandas_object(df).values.tobytes().hex()[:32]

def generate_cache_key(func: Callable, args: tuple, kwargs: dict) -> str:
    """生成优化的缓存键 (SHA256 + 前缀用于调试)"""
    func_info = f"{func.__module__}.{func.__name__}"
    
    args_repr = []
    for arg in args:
        if isinstance(arg, pd.DataFrame):
            df_hash = _hash_dataframe(arg)
            args_repr.append(f"DataFrame:{df_hash}")
        elif isinstance(arg, (pd.Series, pd.Index)):
            series_hash = hashlib.sha256(
                pd.util.hash_pandas_object(arg).values.tobytes()
            ).hexdigest()[:32]
            args_repr.append(f"Series:{series_hash}")
        elif isinstance(arg, dict):
            sorted_items = sorted(arg.items())
            dict_hash = hashlib.sha256(str(sorted_items).encode()).hexdigest()[:32]
            args_repr.append(f"Dict:{dict_hash}")
        elif isinstance(arg, list):
            list_hash = hashlib.sha256(str(arg).encode()).hexdigest()[:32]
            args_repr.append(f"List:{list_hash}")
        else:
            args_repr.append(repr(arg))
    
    sorted_kwargs = sorted(kwargs.items())
    kwargs_repr = [f"{k}={repr(v)}" for k, v in sorted_kwargs]
    
    key_str = f"{func_info}:{','.join(args_repr)},{','.join(kwargs_repr)}"
    full_hash = hashlib.sha256(key_str.encode()).hexdigest()
    prefix = func.__name__[:16]
    return f"{prefix}_{full_hash[:32]}"

# 全局缓存管理器实例，通过CacheFactory创建，收拢重复逻辑
cache_manager = CacheFactory.create("memory", max_size=5000)

def smart_cache(ttl: int = CacheConstants.CACHE_TTL_REALTIME) -> Callable:
    """
    智能缓存装饰器
    
    Args:
        ttl: 缓存过期时间（秒）
        
    Returns:
        装饰后的函数
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = generate_cache_key(func, args, kwargs)
            
            cached_value = cache_manager.get(key)
            if cached_value is not None:
                logger.debug(f"SmartCache hit for {func.__name__}")
                return cached_value
            
            result = func(*args, **kwargs)
            
            # memory cache accepts ttl dynamically in set or via wrapped object? 
            # Looking at CacheInterface, set takes Optional[int] = None for ttl depending on backend
            cache_manager.set(key, result, ttl=ttl)
            
            return result
        return wrapper
    return decorator

__all__ = [
    "CacheInterface",
    "CacheFactory",
    "MemoryCacheBackend",
    "DiskCacheBackend",
    "cache_manager",
    "smart_cache",
]
