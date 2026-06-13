"""
依赖注入容器 — 消除所有隐式循环依赖和 God Object

拓扑：
  StorageManager ──→ MarketDataReader ──→ DataService ──→ AnalysisService
       ↓                                              ↓
  TradeCalendarManager                    ┌──── AnalysisEngineFactory
       ↓                                   │
  CacheCoordinator                         ├── FsmAnalysisEngine
                                           ├── CzscAnalysisEngine
                                           ├── LpplAnalysisEngine
                                           ├── RegimeAnalysisEngine
                                           └── ReportGeneratorEngine

零循环依赖（DAG）。AnalysisService 不再 import DataService；
二者通过容器注入接口依赖。
"""

from typing import Any, Callable, Dict, Optional, Set
import threading

from ..data.lake.storage_manager import StorageManager
from ..data.managers.trade_calendar_manager import TradeCalendarManager
from ..shared.config_validator import ConfigValidator
from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


class ServiceContainer:
    _instance: Optional["ServiceContainer"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable[[Any], Any]] = {}
        self._registrations: Set[str] = set()
        self._initialized = False

    @classmethod
    def instance(cls) -> "ServiceContainer":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register(self, name: str, service: Any) -> None:
        self._services[name] = service
        self._registrations.add(name)

    def register_factory(self, name: str, factory: Callable[[Any], Any]) -> None:
        if name in self._services or name in self._factories:
            logger.warning("Service %s already registered, overwriting", name)
        self._factories[name] = factory
        self._registrations.add(name)

    def get(self, name: str) -> Any:
        if name in self._factories and name not in self._services:
            self._services[name] = self._factories[name](self)
        return self._services.get(name)

    def has(self, name: str) -> bool:
        return name in self._registrations

    def reset(self) -> None:
        self._services.clear()
        self._initialized = False

    def clear(self) -> None:
        self._services.clear()
        self._factories.clear()
        self._registrations.clear()

    def initialize(self) -> None:
        if self._initialized:
            return

        from ..shared.config_loader import get_config
        from ..shared.time_provider import RealTimeProvider

        from .data_service import DataService
        from .cache_coordinator import CacheCoordinator

        config = get_config()
        validator = ConfigValidator(config)
        validation_errors = validator.validate_all()
        if validation_errors:
            logger.warning(
                "Config validation found %d issue(s):\n  - %s",
                len(validation_errors),
                "\n  - ".join(validation_errors),
            )

        storage = StorageManager()
        calendar = TradeCalendarManager()
        cache = CacheCoordinator()

        data_svc = DataService(
            storage_manager=storage,
        )
        self.register("storage", storage)
        self.register("calendar", calendar)
        self.register("cache", cache)
        self.register("data_service", data_svc)

        # 注入 TimeProvider (生产环境使用 RealTimeProvider)
        time_provider = RealTimeProvider()
        self.register("time_provider", time_provider)

        from .analysis.engine_factory import AnalysisEngineFactory
        from .market_cache import MarketLevelCache

        engine_factory = AnalysisEngineFactory(orchestrator=data_svc)
        market_cache = MarketLevelCache()
        data_svc.attach_market_cache(market_cache)
        self.register("engine_factory", engine_factory)
        self.register("market_cache", market_cache)

        from .analysis_service_v2 import AnalysisService
        from .research_pipeline import UnifiedResearchPipeline
        from ..hands.backtest.unified_engine import UnifiedBacktestEngine
        from ..signal.adapters import TradingSignalCollector, create_default_registry

        analysis_svc = AnalysisService(
            data_service=data_svc,
            engine_factory=engine_factory,
            market_cache=market_cache,
        )
        self.register("analysis_service", analysis_svc)

        backtest_engine = UnifiedBacktestEngine()
        signal_collector = TradingSignalCollector(create_default_registry())
        self.register("backtest_engine", backtest_engine)
        self.register("signal_collector", signal_collector)

        # 信号仲裁器 (特性开关控制)
        arbitrator = None
        try:
            from ..shared.config_models import load_refactoring_config
            ref_config = load_refactoring_config()
            if ref_config.feature_flags.signal_arbitration:
                from ..signal.arbitrator import SignalArbitrator
                arbitrator = SignalArbitrator()
                logger.info("信号仲裁器已启用")
        except Exception as exc:
            logger.debug("SignalArbitrator configuration failed; leaving arbitrator disabled: %s", exc)
        self.register("arbitrator", arbitrator)

        # 因子准入 (特性开关控制)
        try:
            ref_config = load_refactoring_config()
            gate_mode = ref_config.feature_flags.factor_gate
            if gate_mode != "off":
                from ..brain.factors.registry import FactorAccessLevel, FactorRegistry
                level = FactorAccessLevel(gate_mode)
                FactorRegistry.set_mode(level)
                logger.info("因子准入模式已设为: %s", gate_mode)
        except Exception as exc:
            logger.debug("FactorRegistry gate configuration failed; leaving default mode: %s", exc)

        pipeline = UnifiedResearchPipeline(
            analysis_service=analysis_svc,
            backtest_engine=backtest_engine,
            signal_collector=signal_collector,
            arbitrator=arbitrator,
            time_provider=time_provider,
        )
        self.register("research_pipeline", pipeline)

        self._initialized = True
        logger.info("ServiceContainer initialized with DAG topology + ResearchPipeline")
