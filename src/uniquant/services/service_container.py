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

from ..shared.interfaces import PositionSizerProtocol
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

        # 1. 注册核心数据层服务工厂 (无 IO 懒加载)
        self.register_factory("storage", lambda c: StorageManager())
        self.register_factory("calendar", lambda c: TradeCalendarManager())
        self.register_factory("cache", lambda c: CacheCoordinator())
        self.register_factory(
            "data_service",
            lambda c: DataService(storage_manager=c.get("storage")),
        )
        self.register_factory("time_provider", lambda c: RealTimeProvider())

        # 2. 注册分析引擎工厂与缓存
        def _make_engine_factory(c):
            from .analysis.engine_factory import AnalysisEngineFactory

            return AnalysisEngineFactory(orchestrator=c.get("data_service"))

        def _make_market_cache(c):
            from .market_cache import MarketLevelCache

            mc = MarketLevelCache()
            ds = c.get("data_service")
            if ds is not None and hasattr(ds, "attach_market_cache"):
                ds.attach_market_cache(mc)
            return mc

        self.register_factory("engine_factory", _make_engine_factory)
        self.register_factory("market_cache", _make_market_cache)

        # 3. 注册分析服务 (AnalysisService)
        def _make_analysis_svc(c):
            from .analysis_service_v2 import AnalysisService

            ef = c.get("engine_factory")
            asvc = AnalysisService(
                data_service=c.get("data_service"),
                engine_factory=ef,
                market_cache=c.get("market_cache"),
            )
            if ef is not None and hasattr(ef, "bind_orchestrator"):
                ef.bind_orchestrator(asvc)
            return asvc

        self.register_factory("analysis_service", _make_analysis_svc)

        # 4. 注册回测引擎与信号收集器
        def _make_backtest_engine(c):
            from ..hands.backtest.unified_engine import UnifiedBacktestEngine

            return UnifiedBacktestEngine()

        def _make_signal_collector(c):
            from ..signal.adapters import TradingSignalCollector, create_default_registry

            return TradingSignalCollector(create_default_registry())

        self.register_factory("backtest_engine", _make_backtest_engine)
        self.register_factory("signal_collector", _make_signal_collector)

        # 5. 信号仲裁器 (特性开关控制)
        def _make_arbitrator(c):
            try:
                from ..shared.config_models import load_refactoring_config

                ref_config = load_refactoring_config()
                if ref_config.feature_flags.signal_arbitration:
                    from ..signal.arbitrator import SignalArbitrator

                    logger.info("信号仲裁器已启用")
                    return SignalArbitrator()
            except Exception as exc:
                logger.debug("SignalArbitrator configuration failed; leaving arbitrator disabled: %s", exc)
            return None

        self.register_factory("arbitrator", _make_arbitrator)

        # 6. 因子准入 (特性开关控制)
        try:
            from ..shared.config_models import load_refactoring_config

            ref_config = load_refactoring_config()
            gate_mode = ref_config.feature_flags.factor_gate
            if gate_mode != "off":
                from ..brain.factors.registry import FactorAccessLevel, FactorRegistry

                level = FactorAccessLevel(gate_mode)
                FactorRegistry.set_mode(level)
                logger.info("因子准入模式已设为: %s", gate_mode)
        except Exception as exc:
            logger.debug("FactorRegistry gate configuration failed; leaving default mode: %s", exc)

        # 7. 综合研究流水线 (UnifiedResearchPipeline)
        def _make_research_pipeline(c):
            from .research_pipeline import UnifiedResearchPipeline

            sizer: Optional[PositionSizerProtocol] = None
            try:
                from ..risk.sizer import PositionSizer

                sizer = PositionSizer()
            except Exception as exc:
                logger.debug("PositionSizer init failed; sizer disabled: %s", exc)

            cfg = get_config()
            batch_max_workers: Optional[int] = cfg.get("batch", {}).get("max_workers", None)

            return UnifiedResearchPipeline(
                analysis_service=c.get("analysis_service"),
                backtest_engine=c.get("backtest_engine"),
                signal_collector=c.get("signal_collector"),
                arbitrator=c.get("arbitrator"),
                sizer=sizer,
                time_provider=c.get("time_provider"),
                max_workers=batch_max_workers,
            )

        self.register_factory("research_pipeline", _make_research_pipeline)

        self._initialized = True
        logger.info("ServiceContainer initialized with lazy DAG factories")
