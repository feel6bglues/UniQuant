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

from typing import Any, Dict, Optional

from ..data.lake.storage_manager import StorageManager
from ..data.managers.trade_calendar_manager import TradeCalendarManager
from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


class ServiceContainer:
    _instance: Optional["ServiceContainer"] = None

    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._initialized = False

    @classmethod
    def instance(cls) -> "ServiceContainer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, name: str, service: Any) -> None:
        self._services[name] = service

    def get(self, name: str) -> Any:
        return self._services.get(name)

    def reset(self) -> None:
        self._services.clear()
        self._initialized = False

    def clear(self) -> None:
        self._services.clear()

    def initialize(self) -> None:
        if self._initialized:
            return

        from .data_service import DataService
        from .cache_coordinator import CacheCoordinator

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

        from .analysis.engine_factory import AnalysisEngineFactory

        engine_factory = AnalysisEngineFactory(orchestrator=data_svc)
        self.register("engine_factory", engine_factory)

        self._initialized = True
        logger.info("ServiceContainer initialized with DAG topology")
