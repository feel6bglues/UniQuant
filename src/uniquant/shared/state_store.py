"""持久化状态存储 (StateStore)
=============================================================================
核心职责:
1. 定义持久化状态存储契约 (StateStore Protocol);
2. 提供基于本地磁盘的 DiskStateStore 实现 (T9a 崩溃恢复与停机状态跨进程保持);
3. 遵循严格的原子写入契约 (tmp + os.replace + FileLock 互斥), 杜绝半写与损坏。
=============================================================================
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Union, runtime_checkable

from filelock import FileLock

from .constants.path import PROJECT_ROOT

logger = logging.getLogger("uniquant.shared.state_store")

_SAFE_KEY_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


@runtime_checkable
class StateStore(Protocol):
    """持久化状态存储契约"""

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """获取指定 key 的持久化状态字典。若不存在或解析失败返回 None。"""
        ...

    def put(self, key: str, data: Dict[str, Any]) -> None:
        """原子写入状态字典到持久化介质。"""
        ...

    def delete(self, key: str) -> bool:
        """删除指定 key 的持久化状态。若存在并删除返回 True，否则返回 False。"""
        ...

    def exists(self, key: str) -> bool:
        """检查指定 key 是否存在。"""
        ...


class DiskStateStore:
    """基于本地文件系统的持久化状态存储实现。

    采用 FileLock 进程间互斥锁与临时文件原子替换保证故障一致性。
    根目录默认: PROJECT_ROOT / "data" / "state"
    """

    def __init__(
        self,
        root_dir: Optional[Union[str, Path]] = None,
        lock_timeout: float = 10.0,
    ) -> None:
        if root_dir is None:
            self.root_dir = PROJECT_ROOT / "data" / "state"
        else:
            p = Path(root_dir)
            if not p.is_absolute():
                p = (PROJECT_ROOT / p).resolve()
            self.root_dir = p
        self.lock_timeout = lock_timeout
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _validate_key(self, key: str) -> None:
        if not isinstance(key, str) or not _SAFE_KEY_RE.match(key):
            raise ValueError(
                f"Invalid state store key '{key}': must match {_SAFE_KEY_RE.pattern}"
            )

    def _key_path(self, key: str) -> Path:
        self._validate_key(key)
        return self.root_dir / f"{key}.json"

    def _lock_path(self, key: str) -> Path:
        self._validate_key(key)
        return self.root_dir / f".{key}.lock"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        file_path = self._key_path(key)
        lock = FileLock(self._lock_path(key), timeout=self.lock_timeout)
        with lock:
            if not file_path.exists():
                return None
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
                    logger.warning("State for key %s is not a dict: %s", key, type(data))
                    return None
            except Exception as exc:
                logger.error("Failed to read state for key %s: %s", key, exc)
                return None

    def put(self, key: str, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise TypeError(f"State data must be a dict, got {type(data).__name__}")
        file_path = self._key_path(key)
        lock = FileLock(self._lock_path(key), timeout=self.lock_timeout)
        with lock:
            self.root_dir.mkdir(parents=True, exist_ok=True)
            tmp_file = self.root_dir / f".{key}.tmp.{os.getpid()}"
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_file, file_path)
            except Exception:
                if tmp_file.exists():
                    try:
                        tmp_file.unlink()
                    except OSError:
                        pass
                raise

    def delete(self, key: str) -> bool:
        file_path = self._key_path(key)
        lock = FileLock(self._lock_path(key), timeout=self.lock_timeout)
        with lock:
            if file_path.exists():
                try:
                    file_path.unlink()
                    return True
                except OSError as exc:
                    logger.warning("Failed to delete state for key %s: %s", key, exc)
                    return False
            return False

    def exists(self, key: str) -> bool:
        file_path = self._key_path(key)
        return file_path.exists()
