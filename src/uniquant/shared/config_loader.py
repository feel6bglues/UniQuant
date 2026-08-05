import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger("ConfigLoader")

_ENV_PREFIX = "UNIQUANT_"
_ENV_ALIASES: Dict[str, str] = {
    "TDX_PATH": "base.tdx.path",
    "DATA_LAKE_PATH": "base.data_lake.path",
    "LOG_LEVEL": "base.logging.level",
    "CACHE_PATH": "cache.global.path",
    "CACHE_ENABLED": "cache.global.enabled",
    "DEFAULT_RISK_PCT": "risk.default_risk_pct",
    "EVENT_BUS": "refactoring.feature_flags.event_bus",
    "OBSERVABILITY": "refactoring.feature_flags.observability",
    "STRICT_TIMESTAMPS": "refactoring.feature_flags.strict_timestamps",
    "FACTOR_GATE": "refactoring.feature_flags.factor_gate",
}


def _parse_env_key(env_name: str) -> Optional[str]:
    """Parse a UNIQUANT_ env var name into a config key path.

    Priority:
    1. Alias match in _ENV_ALIASES
    2. Double-underscore separator: UNIQUANT_BASE__TDX__PATH -> base.tdx.path
    """
    if not env_name.startswith(_ENV_PREFIX):
        return None
    suffix = env_name[len(_ENV_PREFIX):]
    if suffix in _ENV_ALIASES:
        return _ENV_ALIASES[suffix]
    parts = suffix.lower().split("__")
    return ".".join(parts)


def _cast_env_value(value: str) -> Any:
    """Cast environment variable string to appropriate Python type."""
    lower = value.lower().strip()
    if lower in ("true", "yes", "1"):
        return True
    if lower in ("false", "no", "0"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply UNIQUANT_ environment variable overrides to config dict."""
    overridden: List[str] = []
    for env_name, env_value in os.environ.items():
        key_path = _parse_env_key(env_name)
        if key_path is None:
            continue
        keys = key_path.split(".")
        target = config
        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            target = target[k]
        target[keys[-1]] = _cast_env_value(env_value)
        overridden.append(f"{key_path}={env_value}")
    if overridden:
        logger.info("Env overrides applied: %s", ", ".join(overridden))
    return config


class GlobalConfig:
    """
    Singleton Configuration Loader for Alpha-Tactician Pro V8.0.
    Loads settings from config/*.yaml and provides a unified interface.
    """

    _instance = None
    _lock = threading.Lock()
    _config: Dict[str, Any] = {}
    _root_dir: Path = Path(__file__).parent.parent.parent.parent.resolve()

    _REQUIRED_SECTIONS = ["base", "cache", "network", "data_sources"]

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(GlobalConfig, cls).__new__(cls)
                    cls._instance._load_config()
        return cls._instance

    @property
    def ROOT_DIR(self) -> Path:
        return self._root_dir

    @property
    def DATA_DIR(self) -> Path:
        return self._root_dir / self.get("base.data_lake.path", "data")

    @property
    def LAKE_DIR(self) -> Path:
        return self._root_dir / self.get("base.data_lake.path", "data/lake")

    @property
    def LOG_DIR(self) -> Path:
        log_path = self._root_dir / self.get("cache.global.path", "logs")
        log_path.mkdir(parents=True, exist_ok=True)
        return log_path

    @property
    def CACHE_DIR(self) -> Path:
        cache_path = self._root_dir / self.get("cache.global.path", "data/cache")
        cache_path.mkdir(parents=True, exist_ok=True)
        return cache_path

    def _load_config(self):
        """Load all yaml files from config/ directory."""
        config_dir = self._root_dir / "config"

        if not config_dir.exists():
            logger.warning(
                f"Config directory not found at {config_dir}. Using defaults."
            )
            self._config = self._get_defaults()
            return

        unified_config_path = config_dir / "config.yaml"
        if unified_config_path.exists():
            logger.info("Loading unified configuration from config.yaml")
            self._load_yaml(unified_config_path, "")
        else:
            logger.info("Loading individual configuration files")
            config_files = [
                ("settings.yaml", "settings"),
                ("markets.yaml", "markets"),
                ("brain.yaml", "brain"),
                ("data_sources.yaml", "data_sources"),
                ("cache.yaml", "cache"),
                ("czsc.yaml", "czsc"),
                ("indicators.yaml", "indicators"),
                ("indices.yaml", "indices"),
                ("lppl.yaml", "lppl"),
                ("network.yaml", "network"),
            ]
            for filename, namespace in config_files:
                self._load_yaml(config_dir / filename, namespace)

        # Always load factors.yaml separately (individual or standalone)
        self._load_factors_config(config_dir)

        _apply_env_overrides(self._config)

        logger.info("Global Configuration Loaded.")
        self.validate_config()

    def _load_yaml(self, path: Path, namespace: str):
        if not path.exists():
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    if namespace:
                        self._config[namespace] = data
                    else:
                        self._config.update(data)
        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error in {path}: {e}")
        except (IOError, OSError) as e:
            logger.error(f"File I/O error in {path}: {e}")
        except Exception as e:
            logger.critical(f"Unexpected error loading {path}: {e}", exc_info=True)

    def _load_factors_config(self, config_dir: Path) -> None:
        """Load factors.yaml into config (YAML already has 'factors:' root key)."""
        factors_path = config_dir / "factors.yaml"
        if factors_path.exists():
            logger.info("Loading factors configuration from factors.yaml")
            self._load_yaml(factors_path, "")

    def _get_defaults(self) -> Dict[str, Any]:
        return {
            "base": {
                "data_lake": {"path": "data/lake", "engine": "duckdb"},
                "logging": {"level": "INFO"},
            },
            "cache": {
                "global": {"enabled": True, "path": "data/cache"},
                "ttl": {"stock_data": 3600, "realtime_data": 60},
            },
            "risk": {"default_risk_pct": 0.1},
        }

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Retrieve a config value using dot notation.
        e.g. get('settings.data_lake.path')
        """
        keys = key_path.split(".")
        value = self._config
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def set(self, key_path: str, value: Any) -> None:
        """
        Set a config value using dot notation.
        e.g. set('brain.fsm.ma_short', 10)
        """
        keys = key_path.split(".")
        cfg = self._config
        for k in keys[:-1]:
            if k not in cfg or not isinstance(cfg[k], dict):
                cfg[k] = {}
            cfg = cfg[k]
        cfg[keys[-1]] = value

    def reload(self) -> None:
        """Re-read all config files and clear cached values."""
        with self._lock:
            self._config = {}
            self._load_config()

    def validate_config(self) -> bool:
        """
        Validate the configuration parameters

        Returns:
            bool: True if validation passes, False otherwise
        """
        # The module-level logger is already available and should be used.
        # from .logger_factory import get_logger
        # logger = get_logger("ConfigLoader")

        validation_passed = True

        validation_passed &= self._validate_required_sections(logger)
        validation_passed &= self._validate_base_config(logger)
        validation_passed &= self._validate_cache_config(logger)
        validation_passed &= self._validate_network_config(logger)
        validation_passed &= self._validate_data_sources_config(logger)
        self._validate_brain_config(logger)
        validation_passed &= self._validate_risk_config(logger)
        self._validate_lppl_config(logger)

        if validation_passed:
            logger.info("Configuration validation passed")
        else:
            logger.warning("Configuration validation failed")

        return validation_passed

    def _validate_required_sections(self, logger) -> bool:
        """Validate required configuration sections exist."""
        passed = True
        for section in self._REQUIRED_SECTIONS:
            if section not in self._config:
                logger.warning(f"Missing required configuration section: {section}")
                passed = False
        return passed

    def _validate_base_config(self, logger) -> bool:
        """Validate base configuration section."""
        if "base" not in self._config:
            return False

        passed = True
        base = self._config["base"]

        if "data_lake" not in base:
            logger.warning("Missing data_lake in base configuration")
            return False

        data_lake = base["data_lake"]
        if "path" not in data_lake:
            logger.warning("Missing data_lake.path in base configuration")
            passed = False
        if "engine" not in data_lake:
            logger.warning("Missing data_lake.engine in base configuration")
            passed = False

        return passed

    def _validate_cache_config(self, logger) -> bool:
        """Validate cache configuration section."""
        if "cache" not in self._config:
            return False

        passed = True
        cache = self._config["cache"]

        if "global" in cache:
            global_cache = cache["global"]
            if "enabled" not in global_cache:
                logger.warning("Missing global.enabled in cache configuration")
                passed = False
            if "path" not in global_cache:
                logger.warning("Missing global.path in cache configuration")
                passed = False
        else:
            logger.warning("Missing global in cache configuration")
            passed = False

        if "ttl" in cache:
            ttl = cache["ttl"]
            if "stock_data" not in ttl:
                logger.warning("Missing ttl.stock_data in cache configuration")
                passed = False
            if "realtime_data" not in ttl:
                logger.warning("Missing ttl.realtime_data in cache configuration")
                passed = False
        else:
            logger.warning("Missing ttl in cache configuration")
            passed = False

        return passed

    def _validate_network_config(self, logger) -> bool:
        """Validate network configuration section."""
        if "network" not in self._config:
            return False

        network = self._config["network"]
        if "timeout" in network:
            timeout = network["timeout"]
            if "default" not in timeout:
                logger.warning("Missing timeout.default in network configuration")
                return False
        else:
            logger.warning("Missing timeout in network configuration")
            return False

        return True

    def _validate_data_sources_config(self, logger) -> bool:
        """Validate data_sources configuration section."""
        if "data_sources" not in self._config:
            return False

        data_sources = self._config["data_sources"]
        if "sources" not in data_sources:
            logger.warning("Missing sources in data_sources configuration")
            return False

        return True

    def _validate_brain_config(self, logger) -> None:
        """Validate brain configuration section (warnings only, not required)."""
        if "brain" not in self._config:
            return

        brain = self._config["brain"]
        brain_keys = ["alpha_decoupler", "ntf", "regime", "fsm"]
        for key in brain_keys:
            if key not in brain:
                logger.warning(f"Missing {key} in brain configuration")

    def _validate_risk_config(self, logger) -> bool:
        """Validate risk configuration section."""
        if "risk" not in self._config:
            return False

        risk = self._config["risk"]
        if "default_risk_pct" not in risk:
            logger.warning("Missing default_risk_pct in risk configuration")
            return False

        if not (0 < risk["default_risk_pct"] <= 1):
            logger.warning("default_risk_pct must be between 0 and 1")
            return False

        return True

    def _validate_lppl_config(self, logger) -> None:
        """Validate LPPL configuration section (warnings only, not required)."""
        if "lppl" not in self._config:
            return

        lppl = self._config["lppl"]
        if "optimizer" in lppl:
            optimizer = lppl["optimizer"]
            if "max_iter" not in optimizer:
                logger.warning("Missing optimizer.max_iter in lppl configuration")
            if "popsize" not in optimizer:
                logger.warning("Missing optimizer.popsize in lppl configuration")

        if "data" in lppl:
            data = lppl["data"]
            if "min_data_points" not in data:
                logger.warning("Missing data.min_data_points in lppl configuration")


config = None


def get_config() -> GlobalConfig:
    """
    获取全局配置实例（延迟初始化）

    Returns:
        GlobalConfig: 全局配置实例
    """
    global config
    if config is None:
        config = GlobalConfig()
    return config
