"""
股票池与基准宇宙包 (Universe Package)
=============================================================================
包含:
1. DynamicPointInTimeUniverse: 动态点在时股票池构建器 (消除幸存者偏差)
2. TotalReturnBenchmarkAdapter: 全收益基准对齐引擎 (消除股息剪刀差)
3. DelistedStockIngestor: 历史退市股票日频补录引擎
=============================================================================
"""

from .dynamic_pit_universe import DynamicPointInTimeUniverse
from .total_return_benchmark import TotalReturnBenchmarkAdapter
from .delisted_ingestor import DelistedStockIngestor
from .dynamic_pit_loader import CrossSectionalPITDataLoader

__all__ = [
    "DynamicPointInTimeUniverse",
    "TotalReturnBenchmarkAdapter",
    "DelistedStockIngestor",
    "CrossSectionalPITDataLoader",
]
