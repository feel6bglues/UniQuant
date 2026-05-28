"""
缓存后端实现
Cache Backend Implementations
"""

import os
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import joblib

from ..logger_factory import get_logger
from .cache_interface import CacheInterface

logger = get_logger(__name__)

try:
    from filelock import FileLock
    FILELOCK_AVAILABLE = True
except ImportError:
    FILELOCK_AVAILABLE = False
    logger.warning("filelock not installed, disk cache concurrent access protection disabled")


class MemoryCacheBackend(CacheInterface):
    """
    内存缓存后端
    使用字典存储，速度快但不持久化
    """

    def __init__(self, max_size: int = 100):
        """
        初始化内存缓存

        Args:
            max_size: 最大缓存项数量
        """
        self.max_size = max_size
        self.cache: Dict[str, Dict] = {}
        self.access_times: Dict[str, float] = {}
        self.hits = 0
        self.misses = 0
        logger.info(f"MemoryCacheBackend initialized with max_size: {max_size}")

    def get(self, key: str) -> Optional[Any]:
        """获取缓存数据"""
        if key in self.cache:
            cache_item = self.cache[key]

            # 检查是否过期
            if (time.time() - cache_item["created_at"]) > cache_item["ttl"]:
                self.delete(key)
                self.misses += 1
                logger.debug(f"Cache expired for key: {key}")
                return None

            # 更新访问时间
            self.access_times[key] = time.time()
            self.hits += 1
            logger.debug(f"Cache hit for key: {key}")
            return cache_item["data"]
        else:
            self.misses += 1
            logger.debug(f"Cache miss for key: {key}")
            return None

    def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """设置缓存数据"""
        if value is None:
            return False

        # 检查是否为空数据
        if hasattr(value, "empty") and value.empty:
            logger.debug(f"Skipping cache for empty data: {key}")
            return False

        # 检查缓存大小
        if len(self.cache) >= self.max_size:
            self._evict_oldest()

        # 设置缓存
        self.cache[key] = {"data": value, "ttl": ttl, "created_at": time.time()}
        self.access_times[key] = time.time()
        logger.debug(f"Cache set for key: {key}")
        return True

    def delete(self, key: str) -> bool:
        """删除指定缓存"""
        if key in self.cache:
            del self.cache[key]
            if key in self.access_times:
                del self.access_times[key]
            logger.debug(f"Cache deleted for key: {key}")
            return True
        return False

    def clear(self, pattern: Optional[str] = None) -> int:
        """清空缓存"""
        if pattern:
            keys_to_delete = [key for key in self.cache if pattern in key]
            for key in keys_to_delete:
                self.delete(key)
            logger.info(
                f"Cleared {len(keys_to_delete)} cache entries matching pattern: {pattern}"
            )
            return len(keys_to_delete)
        else:
            count = len(self.cache)
            self.cache.clear()
            self.access_times.clear()
            logger.info(f"Cleared all {count} cache entries")
            return count

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0.0

        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": len(self.cache),
            "max_size": self.max_size,
            "hit_rate": hit_rate,
        }

    def reset_stats(self) -> None:
        """重置统计信息"""
        self.hits = 0
        self.misses = 0
        logger.info("Cache stats reset")

    def cleanup(self) -> int:
        """清理过期缓存"""
        current_time = time.time()
        expired_keys = []

        for key, cache_item in self.cache.items():
            if (current_time - cache_item["created_at"]) > cache_item["ttl"]:
                expired_keys.append(key)

        for key in expired_keys:
            self.delete(key)

        logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
        return len(expired_keys)

    def _evict_oldest(self) -> None:
        """淘汰最旧的缓存项（LRU）"""
        if not self.access_times:
            return

        oldest_key = min(self.access_times, key=lambda k: self.access_times[k])
        self.delete(oldest_key)
        logger.debug(f"Evicted oldest cache entry: {oldest_key}")


class DiskCacheBackend(CacheInterface):
    """
    磁盘缓存后端
    使用 joblib 持久化存储，可跨进程共享
    """

    def __init__(
        self,
        cache_dir: str = "data/cache",
        max_cache_age: int = 7,
        max_cache_size: int = 500 * 1024 * 1024,  # 500MB
    ):
        """
        初始化磁盘缓存

        Args:
            cache_dir: 缓存目录路径
            max_cache_age: 缓存最大天数
            max_cache_size: 最大缓存大小（字节）
        """
        self.cache_dir = Path(cache_dir)
        self.max_cache_age = max_cache_age
        self.max_cache_size = max_cache_size
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        self._file_locks: Dict[str, "FileLock"] = {}

        # 创建缓存目录
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"DiskCacheBackend initialized at: {self.cache_dir}")

    def _get_file_lock(self, cache_path: Path) -> Optional["FileLock"]:
        """获取文件锁 (如果 filelock 可用)"""
        if not FILELOCK_AVAILABLE:
            return None
        
        lock_path = cache_path.with_suffix(".lock")
        return FileLock(lock_path)
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存数据"""
        cache_path = self._get_cache_path(key)

        if not cache_path.exists():
            self.misses += 1
            return None

        file_lock = self._get_file_lock(cache_path)
        
        try:
            if file_lock:
                file_lock.acquire(timeout=5)
            
            cache_content = joblib.load(cache_path)

            # 检查是否过期
            cache_time = datetime.fromtimestamp(cache_content["timestamp"])
            if (datetime.now() - cache_time).days > self.max_cache_age:
                os.remove(cache_path)
                self.misses += 1
                logger.debug(f"Cache expired for key: {key}")
                return None

            self.hits += 1
            logger.debug(f"Cache hit for key: {key}")
            return cache_content["data"]
        except Exception as e:
            logger.warning(f"Failed to load cache for {key}: {e}")
            # 删除损坏的缓存文件
            try:
                os.remove(cache_path)
            except OSError as e:
                logger.debug(
                    f"Failed to remove corrupted cache file {cache_path.name}: {e}"
                )
            self.misses += 1
            return None
        finally:
            if file_lock:
                try:
                    file_lock.release()
                except Exception:
                    pass

    def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """设置缓存数据"""
        if value is None:
            return False

        # 检查是否为空数据
        if hasattr(value, "empty") and value.empty:
            logger.debug(f"Skipping cache for empty data: {key}")
            return False

        cache_path = self._get_cache_path(key)
        file_lock = self._get_file_lock(cache_path)

        try:
            if file_lock:
                file_lock.acquire(timeout=5)
            
            cache_content = {
                "data": value,
                "timestamp": datetime.now().timestamp(),
                "key": key,
                "ttl": ttl,
            }

            # 使用 joblib 压缩保存
            joblib.dump(cache_content, cache_path, compress=3)
            logger.debug(f"Cache set for key: {key}")

            # 检查缓存大小
            if self._get_total_size() > self.max_cache_size:
                self.cleanup()

            return True
        except Exception as e:
            logger.error(f"Failed to cache data for {key}: {e}")
            return False
        finally:
            if file_lock:
                try:
                    file_lock.release()
                except Exception:
                    pass

    def delete(self, key: str) -> bool:
        """删除指定缓存"""
        cache_path = self._get_cache_path(key)

        if cache_path.exists():
            try:
                os.remove(cache_path)
                logger.debug(f"Cache deleted for key: {key}")
                return True
            except OSError as e:
                logger.error(f"Failed to delete cache for {key}: {e}")
                return False
        return False

    def clear(self, pattern: Optional[str] = None) -> int:
        """清空缓存"""
        count = 0

        for cache_file in self.cache_dir.glob("*.joblib"):
            if pattern and pattern not in cache_file.stem:
                continue

            try:
                os.remove(cache_file)
                count += 1
            except OSError as e:
                logger.warning(f"Failed to delete {cache_file}: {e}")

        logger.info(f"Cleared {count} cache entries")
        return count

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_size = self._get_total_size()
        file_count = len(list(self.cache_dir.glob("*.joblib")))
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0.0

        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": total_size,
            "size_mb": total_size / 1024 / 1024,
            "files": file_count,
            "max_size": self.max_cache_size,
            "max_size_mb": self.max_cache_size / 1024 / 1024,
            "hit_rate": hit_rate,
        }

    def reset_stats(self) -> None:
        """重置统计信息"""
        self.hits = 0
        self.misses = 0
        logger.info("Cache stats reset")

    def cleanup(self) -> int:
        """清理过期缓存和超大缓存"""
        current_time = datetime.now()
        cache_files = list(self.cache_dir.glob("*.joblib"))
        cleaned_count = 0

        # 第一阶段：清理过期文件
        for cache_file in cache_files:
            try:
                cache_content = joblib.load(cache_file)
                cache_time = datetime.fromtimestamp(cache_content["timestamp"])

                if (current_time - cache_time).days > self.max_cache_age:
                    os.remove(cache_file)
                    cleaned_count += 1
                    logger.debug(f"Cleaned expired cache: {cache_file.name}")
            except (EOFError, OSError, KeyError, TypeError, AttributeError):
                # 删除损坏的文件
                try:
                    os.remove(cache_file)
                    cleaned_count += 1
                except OSError as e:
                    logger.debug(
                        f"Failed to remove corrupted cache file {cache_file.name}: {e}"
                    )

        # 第二阶段：如果超过大小限制，删除最旧的文件
        total_size = self._get_total_size()
        if total_size > self.max_cache_size:
            cache_files = list(self.cache_dir.glob("*.joblib"))
            cache_files.sort(key=lambda x: x.stat().st_mtime)

            for cache_file in cache_files:
                if total_size <= self.max_cache_size * 0.8:  # 留 20% 缓冲
                    break

                try:
                    file_size = cache_file.stat().st_size
                    os.remove(cache_file)
                    total_size -= file_size
                    cleaned_count += 1
                    logger.debug(f"Cleaned oldest cache: {cache_file.name}")
                except Exception as e:
                    logger.debug(f"Failed to clean oldest cache {cache_file.name}: {e}")

        logger.info(f"Cleanup completed, cleaned {cleaned_count} entries")
        return cleaned_count

    def _sanitize_cache_key(self, key: str) -> str:
        """清理缓存键，移除 Windows 文件系统不允许的字符"""
        import re

        # 移除 Windows 文件系统不允许的字符: < > : " / \ | ? *
        sanitized = re.sub(r'[<>:"/\\|?*]', "_", key)
        # 移除多余的下划线
        sanitized = re.sub(r"_+", "_", sanitized)
        # 移除首尾下划线
        sanitized = sanitized.strip("_")
        # 限制长度，避免路径过长
        max_length = 200
        if len(sanitized) > max_length:
            import hashlib

            hash_part = hashlib.md5(
                sanitized.encode(), usedforsecurity=False
            ).hexdigest()
            sanitized = sanitized[: max_length - len(hash_part) - 1] + "_" + hash_part
        return sanitized

    def _get_cache_path(self, key: str) -> Path:
        """获取缓存文件路径"""
        sanitized_key = self._sanitize_cache_key(key)
        return self.cache_dir / f"{sanitized_key}.joblib"

    def _get_total_size(self) -> int:
        """获取缓存总大小"""
        total_size = 0
        for cache_file in self.cache_dir.glob("*.joblib"):
            try:
                total_size += cache_file.stat().st_size
            except OSError:
                pass
        return total_size
