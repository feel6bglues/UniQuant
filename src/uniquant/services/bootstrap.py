"""UniQuant 轻量服务组装器 (Bootstrap).

为日常定时任务、批处理脚本与单元测试提供轻量、快速、按需依赖装配：
- 规避 ServiceContainer 全局单例状态与 UI 级无关服务初始化开销;
- 显式入参注入，严格遵循 DAG 无环依赖结构;
- 启动耗时 < 50ms, 便于隔离测试与安全恢复.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..data.lake.storage_manager import StorageManager
from ..hands.backtest.unified_engine import UnifiedBacktestEngine
from ..shared.interfaces import PositionSizerProtocol
from ..shared.logger_factory import get_logger
from ..shared.time_provider import RealTimeProvider, TimeProvider
from ..signal.adapters import (
    TradingSignalCollector,
    create_default_registry as create_default_adapter_registry,
)
from ..signal.arbitrator import SignalArbitrator
from .analysis.engine_factory import AnalysisEngineFactory
from .analysis_service_v2 import AnalysisService
from .data_service import DataService
from .market_cache import MarketLevelCache
from .research_pipeline import UnifiedResearchPipeline

logger = get_logger(__name__)


def create_storage_manager(data_dir: Optional[str | Path] = None) -> StorageManager:
    """按需构造存储管理器。"""
    return StorageManager(data_dir=data_dir)


def create_data_service(
    storage_manager: Optional[StorageManager] = None,
    data_dir: Optional[str | Path] = None,
) -> DataService:
    """按需构造数据服务 (DataService)。"""
    storage = storage_manager or create_storage_manager(data_dir=data_dir)
    return DataService(
        storage_manager=storage,
    )


def create_engine_factory(
    data_service: Optional[DataService] = None,
) -> AnalysisEngineFactory:
    """按需构造分析引擎工厂。"""
    ds = data_service or create_data_service()
    return AnalysisEngineFactory(orchestrator=ds)


def create_analysis_service(
    data_service: Optional[DataService] = None,
    engine_factory: Optional[AnalysisEngineFactory] = None,
    market_cache: Optional[MarketLevelCache] = None,
) -> AnalysisService:
    """按需构造单标的分析编排服务 (AnalysisService)。"""
    ds = data_service or create_data_service()
    ef = engine_factory or create_engine_factory(data_service=ds)
    mc = market_cache or MarketLevelCache()

    if hasattr(ds, "attach_market_cache"):
        ds.attach_market_cache(mc)

    analysis_svc = AnalysisService(
        data_service=ds,
        engine_factory=ef,
        market_cache=mc,
    )
    if hasattr(ef, "bind_orchestrator"):
        ef.bind_orchestrator(analysis_svc)

    return analysis_svc


def create_signal_arbitrator(
    sell_priority: bool = True,
    engine_priority: Optional[dict[str, int]] = None,
    quality_threshold: float = 0.3,
    max_signal_age_seconds: float = 0.0,
) -> SignalArbitrator:
    """按需构造信号仲裁器。"""
    return SignalArbitrator(
        engine_priority=engine_priority,
        sell_priority=sell_priority,
        quality_threshold=quality_threshold,
        max_signal_age_seconds=max_signal_age_seconds,
    )


def create_trading_signal_collector(
    registry: Optional[Any] = None,
) -> TradingSignalCollector:
    """按需构造信号收集器。"""
    reg = registry or create_default_adapter_registry()
    return TradingSignalCollector(reg)


def create_research_pipeline(
    analysis_service: Optional[AnalysisService] = None,
    backtest_engine: Optional[UnifiedBacktestEngine] = None,
    signal_collector: Optional[TradingSignalCollector] = None,
    arbitrator: Optional[SignalArbitrator] = None,
    sizer: Optional[PositionSizerProtocol] = None,
    time_provider: Optional[TimeProvider] = None,
    max_workers: Optional[int] = None,
) -> UnifiedResearchPipeline:
    """按需构造端到端量化研究流水线。"""
    asvc = analysis_service or create_analysis_service()
    bt = backtest_engine or UnifiedBacktestEngine()
    sc = signal_collector or create_trading_signal_collector()
    tp = time_provider or RealTimeProvider()

    return UnifiedResearchPipeline(
        analysis_service=asvc,
        backtest_engine=bt,
        signal_collector=sc,
        arbitrator=arbitrator,
        sizer=sizer,
        time_provider=tp,
        max_workers=max_workers,
    )
