from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


class ConfigValidationError(ValueError):
    """Configuration validation failed."""


@dataclass
class DataLakeConfig:
    path: str = "data/lake"
    compression: str = "snappy"
    engine: str = "duckdb"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DataLakeConfig":
        return cls(
            path=str(data.get("path", "data/lake")),
            compression=str(data.get("compression", "snappy")),
            engine=str(data.get("engine", "duckdb")),
        )


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    directory: str = "logs"
    max_bytes: int = 10485760
    backup_count: int = 5
    console: bool = True
    file: bool = True
    json_format: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoggingConfig":
        return cls(
            level=str(data.get("level", "INFO")).upper(),
            format=str(data.get("format", cls.format)),
            directory=str(data.get("directory", "logs")),
            max_bytes=int(data.get("max_bytes", 10485760)),
            backup_count=int(data.get("backup_count", 5)),
            console=bool(data.get("console", True)),
            file=bool(data.get("file", True)),
            json_format=bool(data.get("json_format", False)),
        )


@dataclass
class ExecutionConfig:
    trading_enabled: bool = True
    kill_switch_reason: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionConfig":
        return cls(
            trading_enabled=bool(data.get("trading_enabled", True)),
            kill_switch_reason=str(data.get("kill_switch_reason", "")),
        )


@dataclass
class CacheGlobalConfig:
    enabled: bool = True
    path: str = "data/cache"
    max_age: int = 7
    batch_size: int = 5

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheGlobalConfig":
        return cls(
            enabled=bool(data.get("enabled", True)),
            path=str(data.get("path", "data/cache")),
            max_age=int(data.get("max_age", 7)),
            batch_size=int(data.get("batch_size", 5)),
        )


@dataclass
class FeatureFlags:
    signal_arbitration: bool = True
    factor_gate: str = "block"
    event_bus: bool = True
    async_event_bus: bool = False
    observability: bool = False
    use_research_data_pack: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FeatureFlags":
        return cls(
            signal_arbitration=bool(data.get("signal_arbitration", True)),
            factor_gate=str(data.get("factor_gate", "block")),
            event_bus=bool(data.get("event_bus", True)),
            async_event_bus=bool(data.get("async_event_bus", False)),
            observability=bool(data.get("observability", False)),
            use_research_data_pack=bool(data.get("use_research_data_pack", True)),
        )


@dataclass
class RefactoringConfig:
    enabled: bool = False
    feature_flags: FeatureFlags = field(default_factory=FeatureFlags)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RefactoringConfig":
        ff_data = data.get("feature_flags", {})
        return cls(
            enabled=bool(data.get("enabled", False)),
            feature_flags=FeatureFlags.from_dict(ff_data),
        )


@dataclass
class BaseConfig:
    data_lake: DataLakeConfig = field(default_factory=DataLakeConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    tdx: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseConfig":
        lake = DataLakeConfig.from_dict(data.get("data_lake", {}))
        log_cfg = LoggingConfig.from_dict(data.get("logging", {}))
        return cls(
            data_lake=lake,
            logging=log_cfg,
            tdx=dict(data.get("tdx", {})),
        )


@dataclass
class RiskConfig:
    default_risk_pct: float = 0.1
    circuit_break_pct: float = 0.15

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskConfig":
        return cls(
            default_risk_pct=float(data.get("default_risk_pct", 0.1)),
            circuit_break_pct=float(data.get("circuit_break_pct", 0.15)),
        )


@dataclass
class AppConfig:
    base: BaseConfig = field(default_factory=BaseConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    cache: Dict[str, Any] = field(default_factory=dict)
    network: Dict[str, Any] = field(default_factory=dict)
    data_sources: Dict[str, Any] = field(default_factory=dict)
    risk: RiskConfig = field(default_factory=RiskConfig)
    refactoring: RefactoringConfig = field(default_factory=RefactoringConfig)
    batch: Dict[str, Any] = field(default_factory=dict)
    brain: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        return cls(
            base=BaseConfig.from_dict(data.get("base", {})),
            execution=ExecutionConfig.from_dict(data.get("execution", {})),
            cache=dict(data.get("cache", {})),
            network=dict(data.get("network", {})),
            data_sources=dict(data.get("data_sources", {})),
            risk=RiskConfig.from_dict(data.get("risk", {})),
            refactoring=RefactoringConfig.from_dict(data.get("refactoring", {})),
            batch=dict(data.get("batch", {})),
            brain=dict(data.get("brain", {})),
        )

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not (0 < self.risk.default_risk_pct <= 1):
            errors.append("risk.default_risk_pct must be in (0, 1]")
        level = self.base.logging.level
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in valid_levels:
            errors.append(f"base.logging.level must be one of {valid_levels}, got {level}")
        return errors
