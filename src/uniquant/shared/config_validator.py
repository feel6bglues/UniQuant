from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, List

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    pass


class ConfigValidator:
    _REQUIRED_SECTIONS = ["base", "cache", "data_sources"]

    def __init__(self, config: Any) -> None:
        self._config = config

    def validate_all(self) -> List[str]:
        errors: List[str] = []
        errors.extend(self._validate_required_sections())
        errors.extend(self._validate_paths())
        errors.extend(self._validate_data_source_classes())
        errors.extend(self._validate_refactoring_config())
        errors.extend(self._validate_factor_registry())
        return errors

    def assert_valid(self) -> None:
        errors = self.validate_all()
        if errors:
            raise ConfigValidationError(
                "Configuration validation failed:\n  - " + "\n  - ".join(errors)
            )

    def _validate_required_sections(self) -> List[str]:
        errors: List[str] = []
        for section in self._REQUIRED_SECTIONS:
            if self._config.get(section) is None:
                errors.append(f"Missing required config section: {section}")
        if self._config.get("brain") is None:
            errors.append("Missing config section: brain")
        if self._config.get("risk") is None:
            errors.append("Missing config section: risk")
        return errors

    def _validate_paths(self) -> List[str]:
        errors: List[str] = []
        root = getattr(self._config, "ROOT_DIR", Path.cwd())

        data_lake_path = self._config.get("base.data_lake.path", "data/lake")
        if not isinstance(data_lake_path, str):
            errors.append("base.data_lake.path must be a string")
        else:
            resolved = (root / data_lake_path).resolve()
            if not resolved.exists():
                logger.warning("Data lake path does not exist: %s", resolved)

        cache_path = self._config.get("cache.global.path", "data/cache")
        if not isinstance(cache_path, str):
            errors.append("cache.global.path must be a string")

        tdx_path = self._config.get("base.tdx.path")
        if tdx_path is not None:
            resolved_tdx = Path(tdx_path).expanduser().resolve()
            if not resolved_tdx.exists():
                logger.warning("TDX path does not exist: %s", resolved_tdx)

        return errors

    def _validate_data_source_classes(self) -> List[str]:
        errors: List[str] = []
        sources = self._config.get("data_sources.sources", [])
        if isinstance(sources, dict):
            # config.yaml 采用 源名 -> 配置体 的 dict 形态 (D1/Step3 收缩后同)
            entries = list(sources.values())
        elif isinstance(sources, list):
            entries = sources
        else:
            return ["data_sources.sources must be a list or dict"]

        for source in entries:
            class_path = source.get("class") if isinstance(source, dict) else None
            if class_path:
                errors.extend(self._check_source_class_path(class_path))
        return errors

    @staticmethod
    def _check_source_class_path(class_path: str) -> List[str]:
        """Import-check one source `class` entry.

        支持两种写法: `pkg.mod.Class` (类路径, D1/Step3 收缩后配置) 与
        `pkg.mod` / `pkg.mod.Class` 兼容的纯模块路径 (历史写法)。
        """
        module_name, sep, attr_name = class_path.rpartition(".")
        candidates = (
            [(module_name, attr_name)] if sep and module_name else []
        ) + [(class_path, None)]

        last_error: ImportError | None = None
        for candidate_module, candidate_attr in candidates:
            try:
                module = importlib.import_module(candidate_module)
            except ImportError as e:
                last_error = e
                continue
            if candidate_attr is None or hasattr(module, candidate_attr):
                return []
            last_error = ImportError(
                f"module {candidate_module} has no attribute {candidate_attr}"
            )
        return [
            f"Data source class cannot be imported: {class_path} ({last_error})"
        ]

    def _validate_refactoring_config(self) -> List[str]:
        errors: List[str] = []
        refactoring = self._config.get("refactoring", {})
        if not isinstance(refactoring, dict):
            return []

        features = refactoring.get("feature_flags", {})
        if not isinstance(features, dict):
            return []

        factor_gate = features.get("factor_gate", "off")
        if factor_gate not in ("off", "warn", "block"):
            errors.append(
                f"Invalid factor_gate value: {factor_gate} "
                "(expected off|warn|block)"
            )

        return errors

    def _validate_factor_registry(self) -> List[str]:
        """Validate that all config-enabled factors exist in FactorRegistry.

        WS7-002: Config enabled factors must be registered in FactorRegistry,
        otherwise research reports overstate factor coverage.
        """
        errors: List[str] = []
        try:
            from ..brain.factors.registry import FactorRegistry
            registry = FactorRegistry()

            factors_config = self._config.get("factors", {})
            if not isinstance(factors_config, dict):
                return errors

            enabled = factors_config.get("enabled", [])
            if not isinstance(enabled, list):
                return errors

            for factor_name in enabled:
                if not registry.has(factor_name):
                    errors.append(
                        f"Factor '{factor_name}' is enabled in config "
                        f"but not registered in FactorRegistry"
                    )
        except ImportError:
            logger.warning("FactorRegistry not available, skipping factor config validation")
        except Exception as e:
            logger.warning(f"Factor config validation failed: {e}")

        return errors
