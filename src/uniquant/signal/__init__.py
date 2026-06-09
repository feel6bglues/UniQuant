"""uniquant.signal — 信号系统

统一的信号建模、归一化、聚合、质量评估和持久化流水线。
brain 层产出原始信号 → signal 归一化为标准 Signal → 聚合为共识 → 评估质量 → 持久化存储。
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from .aggregator import (
        SignalAggregationMethod,
        SignalAggregator,
        SourceWeightManager,
        TimeWindowAggregator,
    )
except ImportError:
    _logger.warning("signal.aggregator 导入失败")

try:
    from .models import (
        AggregatedSignal,
        Signal,
        SignalBatch,
        SignalConsensus,
        SignalSource,
        SignalStrength,
        SignalType,
    )
except ImportError:
    _logger.warning("signal.models 导入失败")

try:
    from .normalizer import (
        CZSCSignalNormalizer,
        IndicatorSignalNormalizer,
        LPPLSignalNormalizer,
        SignalNormalizer,
        SignalNormalizerRegistry,
        WyckoffSignalNormalizer,
        create_default_registry,
    )
except ImportError:
    _logger.warning("signal.normalizer 导入失败")

try:
    from .quality import (
        SignalQualityAssessor,
        SignalQualityMetrics,
        SignalQualityTracker,
    )
except ImportError:
    _logger.warning("signal.quality 导入失败")

try:
    from .adapters import (
        AdapterRegistry,
        CZSCAdapter,
        EngineAdapter,
        FSMAdapter,
        LPPLAdapter,
        RegimeAdapter,
        TradingSignalCollector,
        WyckoffAdapter,
        create_default_registry as create_default_adapter_registry,
    )
except ImportError:
    _logger.warning("signal.adapters 导入失败")

__all__ = [
    # models
    "SignalType",
    "SignalSource",
    "SignalStrength",
    "Signal",
    "SignalBatch",
    "SignalConsensus",
    "AggregatedSignal",
    # normalizer
    "SignalNormalizer",
    "LPPLSignalNormalizer",
    "WyckoffSignalNormalizer",
    "IndicatorSignalNormalizer",
    "CZSCSignalNormalizer",
    "SignalNormalizerRegistry",
    "create_default_registry",
    # aggregator
    "SignalAggregationMethod",
    "SignalAggregator",
    "TimeWindowAggregator",
    "SourceWeightManager",
    # quality
    "SignalQualityMetrics",
    "SignalQualityAssessor",
    "SignalQualityTracker",
    # adapters
    "EngineAdapter",
    "LPPLAdapter",
    "CZSCAdapter",
    "WyckoffAdapter",
    "FSMAdapter",
    "RegimeAdapter",
    "AdapterRegistry",
    "TradingSignalCollector",
    "create_default_adapter_registry",
]

# db 延迟导入，避免 SQLAlchemy 硬依赖
def get_db_class():
    """获取 SignalDatabase 类（延迟导入）"""
    from .db import SignalDatabase
    return SignalDatabase
