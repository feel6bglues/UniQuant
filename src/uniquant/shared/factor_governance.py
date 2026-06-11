from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..brain.factors.registry import FactorAccessLevel, FactorRegistry

__all__ = ["FactorAccessLevel", "FactorManifest", "FactorRegistry", "global_factor_registry"]

warnings.warn(
    "uniquant.shared.factor_governance is deprecated. "
    "Use uniquant.brain.factors.registry.FactorRegistry directly instead.",
    DeprecationWarning,
    stacklevel=2,
)


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


# 全局因子注册中心 — 引用 brain 的统一单例
global_factor_registry = FactorRegistry()
