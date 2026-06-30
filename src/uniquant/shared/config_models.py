from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class FeatureFlags:
    """特性开关 — 控制重构阶段的渐进式启用"""
    signal_arbitration: bool = False
    typed_contracts: bool = False
    factor_gate: str = "off"  # "off" | "warn" | "block"
    engine_migration: Dict[str, bool] = field(default_factory=dict)
    event_bus: bool = False
    observability: bool = False
    async_event_bus: bool = False
    use_research_data_pack: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FeatureFlags:
        flags = data.get("feature_flags", {}) if data else {}
        engine_migration = flags.get("engine_migration", {})
        return cls(
            signal_arbitration=bool(flags.get("signal_arbitration", False)),
            typed_contracts=bool(flags.get("typed_contracts", False)),
            factor_gate=str(flags.get("factor_gate", "off")),
            engine_migration={k: bool(v) for k, v in engine_migration.items()},
            event_bus=bool(flags.get("event_bus", False)),
            observability=bool(flags.get("observability", False)),
            async_event_bus=bool(flags.get("async_event_bus", False)),
            use_research_data_pack=bool(flags.get("use_research_data_pack", True)),
        )


@dataclass
class TimeConfig:
    provider: str = "real"  # "real" | "frozen"
    fixed_date: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TimeConfig:
        tc = data.get("time", {}) if data else {}
        return cls(
            provider=str(tc.get("provider", "real")),
            fixed_date=tc.get("fixed_date"),
        )


@dataclass
class RefactoringConfig:
    """重构配置 — 控制渐进式系统改造"""
    enabled: bool = False
    feature_flags: FeatureFlags = field(default_factory=FeatureFlags)
    time: TimeConfig = field(default_factory=TimeConfig)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> RefactoringConfig:
        if not data:
            return cls()
        ref = data.get("refactoring", {})
        return cls(
            enabled=bool(ref.get("enabled", False)),
            feature_flags=FeatureFlags.from_dict(ref),
            time=TimeConfig.from_dict(ref),
        )


# 兼容旧接口: 从 config_loader 获取
def load_refactoring_config() -> RefactoringConfig:
    from .config_loader import get_config
    return RefactoringConfig.from_dict(get_config())
