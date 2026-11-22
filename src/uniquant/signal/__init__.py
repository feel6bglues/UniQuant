"""uniquant.signal — 信号系统

生产信号适配与仲裁管线。
brain 层各类信号适配为 TradingSignal → arbitrator 仲裁聚合。
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from .adapters import (
        AdapterRegistry,
        AlphaScoreAdapter,
        CZSCAdapter,
        EngineAdapter,
        FSMAdapter,
        LPPLAdapter,
        MAStatusAdapter,
        NTFAdapter,
        RegimeAdapter,
        TradingSignalCollector,
        WyckoffAdapter,
        create_default_registry as create_default_adapter_registry,
    )
except ImportError:
    _logger.warning("signal.adapters 导入失败")

try:
    from .arbitrator import SignalArbitrator
except ImportError:
    SignalArbitrator = None

__all__ = [
    # adapters
    "AdapterRegistry",
    "AlphaScoreAdapter",
    "CZSCAdapter",
    "EngineAdapter",
    "FSMAdapter",
    "LPPLAdapter",
    "MAStatusAdapter",
    "NTFAdapter",
    "RegimeAdapter",
    "TradingSignalCollector",
    "WyckoffAdapter",
    "create_default_adapter_registry",
    # arbitrator
    "SignalArbitrator",
]
