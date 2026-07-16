"""回测引擎包

旧版 (已废弃):
  - BacktestEngine: 单资产回测引擎
  - PortfolioEngine: 多资产回测引擎

新版 (推荐):
  - UnifiedBacktestEngine: 统一回测引擎 (强类型输入, A 股防线)
"""

from .unified_engine import BacktestResult as UnifiedBacktestResult
from .unified_engine import TradeRecord as UnifiedTradeRecord
from .unified_engine import UnifiedBacktestEngine

# 旧版导入 (带废弃警告)
from .engine import BacktestEngine  # Deprecated
# PortfolioEngine deprecated — removed from exports, use UnifiedBacktestEngine
from .result import BacktestResult, TradeRecord

__all__ = [
    # 新版推荐
    "UnifiedBacktestEngine",
    "UnifiedBacktestResult",
    "UnifiedTradeRecord",
    # 旧版 (已废弃)
    "BacktestEngine",
    "BacktestResult",
    "TradeRecord",
]
