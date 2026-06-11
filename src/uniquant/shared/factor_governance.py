from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class FactorAccessLevel(Enum):
    """因子访问级别"""
    FREE = "free"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class FactorManifest:
    """因子清单 — 集中注册和管理所有可用因子

    每个因子注册后记录其名称、描述、数据源和访问级别。
    在 warn/block 模式下可拦截未注册因子的访问。
    """
    name: str
    description: str = ""
    category: str = "generic"
    data_source: str = ""
    access_level: FactorAccessLevel = FactorAccessLevel.FREE
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class FactorRegistry:
    """因子注册中心

    管理所有因子的注册、查找和访问控制。
    支持 warn 模式（仅记录日志）和 block 模式（抛出异常）。
    """

    def __init__(self, mode: FactorAccessLevel = FactorAccessLevel.WARN):
        self._mode = mode
        self._factors: Dict[str, FactorManifest] = {}

    @property
    def mode(self) -> FactorAccessLevel:
        return self._mode

    def set_mode(self, mode: FactorAccessLevel) -> None:
        self._mode = mode

    def register(self, manifest: FactorManifest) -> None:
        self._factors[manifest.name] = manifest

    def get(self, name: str) -> Optional[FactorManifest]:
        return self._factors.get(name)

    def has(self, name: str) -> bool:
        return name in self._factors

    def list_factors(self) -> List[str]:
        return list(self._factors.keys())

    def check_access(self, name: str) -> bool:
        if name in self._factors:
            return True
        if self._mode == FactorAccessLevel.WARN:
            import logging
            logging.getLogger(__name__).warning(
                "未注册因子访问: %s (mode=warn)", name,
            )
            return True
        if self._mode == FactorAccessLevel.BLOCK:
            raise ValueError(f"未注册因子被拦截: {name}")
        return True


# 全局因子注册中心
global_factor_registry = FactorRegistry()
