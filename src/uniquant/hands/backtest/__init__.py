"""回测引擎包

旧版 (已废弃):
  - BacktestEngine: 单资产回测引擎
  - PortfolioEngine: 多资产回测引擎

新版 (推荐):
  - UnifiedBacktestEngine: 统一回测引擎 (强类型输入, A 股防线)
"""

from .unified_engine import (
    BacktestResult,
    BacktestResult as UnifiedBacktestResult,
    TradeRecord,
    TradeRecord as UnifiedTradeRecord,
    UnifiedBacktestEngine,
)

# 新增机构对冲与执行中枢模块
from .cffex_engine import (
    CFFEXMatchingAndRiskEngine,
    FuturesContractType,
    CONTRACT_SPECS,
    ContractSpec,
    FuturesPosition,
    PBSubAccount,
    DailyMTMSettlementReport,
)
from .twap_execution_slicer import (
    TWAPExecutionSlicer,
    MicrostructureOrderBookSimulator,
    OrderBookSnapshot,
    TWAPSliceResult,
)
from .saga_compensator import (
    CrossAssetSagaCoordinator,
    SqliteWalTwapStateMachine,
    OrderState,
    SagaCompensationLevel,
    CompensationAction,
)
from .institutional_fee_ledger import (
    InstitutionalFeeLedger,
    FeeSnapshot,
)

__all__ = [
    # 新版推荐
    "UnifiedBacktestEngine",
    "UnifiedBacktestResult",
    "UnifiedTradeRecord",
    # 机构对冲与执行中枢
    "CFFEXMatchingAndRiskEngine",
    "FuturesContractType",
    "CONTRACT_SPECS",
    "ContractSpec",
    "FuturesPosition",
    "PBSubAccount",
    "DailyMTMSettlementReport",
    "TWAPExecutionSlicer",
    "MicrostructureOrderBookSimulator",
    "OrderBookSnapshot",
    "TWAPSliceResult",
    "CrossAssetSagaCoordinator",
    "SqliteWalTwapStateMachine",
    "OrderState",
    "SagaCompensationLevel",
    "CompensationAction",
    "InstitutionalFeeLedger",
    "FeeSnapshot",
    # 兼容类型
    "BacktestResult",
    "TradeRecord",
]

