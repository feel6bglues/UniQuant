from __future__ import annotations

import threading
from typing import Callable, List, Optional


class KillSwitchError(RuntimeError):
    """Trading has been stopped by kill switch."""


class SharedKillSwitch:
    _instance: Optional["SharedKillSwitch"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "SharedKillSwitch":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        with self._lock:
            if hasattr(self, "_initialized"):
                return
            self._killed = False
            self._reason = ""
            self._hooks: List[Callable[[], None]] = []
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
        for hook in self._hooks:
            try:
                hook()
            except Exception:
                pass

    def reset(self) -> None:
        with self._lock:
            self._killed = False
            self._reason = ""

    def register_hook(self, hook: Callable[[], None]) -> None:
        with self._lock:
            self._hooks.append(hook)

    def check(self) -> None:
        if self._killed:
            raise KillSwitchError(f"Trading stopped: {self._reason}")


def get_kill_switch() -> SharedKillSwitch:
    return SharedKillSwitch()
