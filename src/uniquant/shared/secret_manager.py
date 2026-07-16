from __future__ import annotations

import os
import threading
from typing import Any, Dict, Optional


class SecretManager:
    _instance: Optional["SecretManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "SecretManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        with self._lock:
            if hasattr(self, "_initialized"):
                return
            self._secrets: Dict[str, str] = {}
            self._initialized = True

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if key in self._secrets:
            return self._secrets[key]
        return os.environ.get(key, default)

    def set(self, key: str, value: str) -> None:
        self._secrets[key] = value

    def get_required(self, key: str) -> str:
        value = self.get(key)
        if value is None:
            raise ValueError(f"Required secret not found: {key}")
        return value

    def get_llm_api_key(self) -> Optional[str]:
        return self.get("WYCKOFF_LLM_API_KEY") or self.get("OPENAI_API_KEY")

    def mask(self, value: str, visible_chars: int = 4) -> str:
        if len(value) <= visible_chars + 4:
            return "***"
        return value[:visible_chars] + "..." + value[-4:]

    def snapshot_metadata(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key in self._secrets:
            result[key] = self.mask(self._secrets[key])
        for env_key in ("WYCKOFF_LLM_API_KEY", "OPENAI_API_KEY", "TDX_PATH"):
            val = os.environ.get(env_key)
            if val:
                result[env_key] = self.mask(val)
        return result


def get_secret_manager() -> SecretManager:
    return SecretManager()
