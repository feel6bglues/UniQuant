from __future__ import annotations

import logging
import threading
import time
from typing import Callable, List, Optional

from .state_store import DiskStateStore, StateStore

logger = logging.getLogger("uniquant.shared.kill_switch")


class KillSwitchError(RuntimeError):
    """Trading has been stopped by kill switch."""


class SharedKillSwitch:
    _instance: Optional["SharedKillSwitch"] = None
    _lock = threading.Lock()

    def __new__(
        cls,
        state_store: Optional[StateStore] = None,
    ) -> "SharedKillSwitch":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        state_store: Optional[StateStore] = None,
    ) -> None:
        with self._lock:
            if hasattr(self, "_initialized"):
                if state_store is not None:
                    self._state_store = state_store
                return
            self._state_store = state_store if state_store is not None else DiskStateStore()
            self._hooks: List[Callable[[], None]] = []
            self._killed = False
            self._reason = ""

            # 从持久化状态恢复 (T9a 崩溃恢复守卫: 停机状态重启不丢失)
            try:
                saved = self._state_store.get("kill_switch")
                if saved and saved.get("killed", False):
                    self._killed = True
                    self._reason = saved.get("reason", "recovered_from_state_store")
                    logger.warning(
                        "SharedKillSwitch 恢复持久化停机状态: reason=%s (T9a Fail-Closed 保护)",
                        self._reason,
                    )
            except Exception as e:
                logger.error("SharedKillSwitch 恢复持久化状态失败: %s", e)

            self._initialized = True

    @property
    def is_killed(self) -> bool:
        return self._killed

    @property
    def reason(self) -> str:
        return self._reason

    def kill(self, reason: str = "manual_override") -> None:
        with self._lock:
            self._killed = True
            self._reason = reason
            try:
                self._state_store.put(
                    "kill_switch",
                    {
                        "killed": True,
                        "reason": reason,
                        "timestamp": time.time(),
                    },
                )
            except Exception as e:
                logger.error("SharedKillSwitch 持久化停机状态失败: %s", e)

        for hook in self._hooks:
            try:
                hook()
            except Exception as e:
                logger.error(f"Kill switch hook {hook} failed: {e}", exc_info=True)

    def reset(self) -> None:
        with self._lock:
            self._killed = False
            self._reason = ""
            try:
                self._state_store.delete("kill_switch")
            except Exception as e:
                logger.error("SharedKillSwitch 清理持久化状态失败: %s", e)

    def register_hook(self, hook: Callable[[], None]) -> None:
        with self._lock:
            self._hooks.append(hook)

    def check(self) -> None:
        if self._killed:
            raise KillSwitchError(f"Trading stopped: {self._reason}")


def get_kill_switch(state_store: Optional[StateStore] = None) -> SharedKillSwitch:
    return SharedKillSwitch(state_store=state_store)
