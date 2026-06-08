"""
统一量化投研流水线 (UnifiedResearchPipeline)
=============================================

数据流:
  DataFetcher → AnalysisEngine (Brain) → data_pack (Dict)
  → TradingSignalCollector → List[TradingSignal]
  → UnifiedBacktestEngine → BacktestResult

设计原则:
  - 强类型输入输出 (TradingSignal, BacktestResult)
  - 单一职责: 每个步骤只做一件事
  - 依赖注入: 通过 ServiceContainer 或构造函数注入
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from ..hands.backtest.unified_engine import BacktestResult, UnifiedBacktestEngine
from ..shared.interfaces import TradingSignal
from ..shared.logger_factory import get_logger
from ..signal.adapters import TradingSignalCollector, create_default_registry
from .analysis_service_v2 import AnalysisService, TickerAnalysisResult

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
# 流水线结果领域对象
# ══════════════════════════════════════════════════════════════

@dataclass
class PipelineResult:
    """统一研报流水线结果

    包含从 Brain 引擎到回测撮合的全链路输出。
    """
    symbol: str
    data_pack: Dict[str, Any]
    decision: Dict[str, Any]
    signals: List[TradingSignal]
    backtest: BacktestResult
    success: bool = True
    error: Optional[str] = None

    @property
    def total_signals(self) -> int:
        return len(self.signals)

    @property
    def total_trades(self) -> int:
        return self.backtest.total_trades

    @property
    def total_return(self) -> float:
        return self.backtest.total_return


# ══════════════════════════════════════════════════════════════
# 统一研报流水线
# ══════════════════════════════════════════════════════════════

class UnifiedResearchPipeline:
    """统一量化投研流水线

    编排完整的研究流程:
      1. 数据获取 (DataService)
      2. Brain 引擎分析 (AnalysisEngineFactory)
      3. 信号收集 (TradingSignalCollector)
      4. 回测撮合 (UnifiedBacktestEngine)

    使用方式:
        pipeline = UnifiedResearchPipeline(analysis_service, backtest_engine)
        result = pipeline.run("000001.SZ")
    """

    def __init__(
        self,
        analysis_service: AnalysisService,
        backtest_engine: Optional[UnifiedBacktestEngine] = None,
        signal_collector: Optional[TradingSignalCollector] = None,
    ):
        self._analysis = analysis_service
        self._engine = backtest_engine or UnifiedBacktestEngine()
        self._collector = signal_collector or TradingSignalCollector(
            create_default_registry(),
        )

    def run(
        self,
        symbol: str,
        name: Optional[str] = None,
        default_shares: int = 100,
    ) -> PipelineResult:
        """运行完整研报流水线

        Args:
            symbol: 股票代码 (如 "000001.SZ")
            name: 股票名称 (用于 ST 识别)
            default_shares: 默认交易股数

        Returns:
            PipelineResult 包含全链路输出
        """
        # Step 1-2: 运行 Brain 引擎分析
        analysis = self._analysis.run_ticker_analysis(symbol)
        if not analysis.success:
            return PipelineResult(
                symbol=symbol,
                data_pack=analysis.data_pack,
                decision=analysis.decision,
                signals=[],
                backtest=BacktestResult(),
                success=False,
                error=analysis.error,
            )

        # Step 3: 收集信号
        data_pack = analysis.data_pack
        timestamp = pd.Timestamp.now()
        signals = self._collector.collect(
            data_pack, timestamp=timestamp, default_shares=default_shares,
        )

        # Step 4: 回测撮合
        stock_df = data_pack.get("stock")
        if stock_df is None or stock_df.empty:
            return PipelineResult(
                symbol=symbol,
                data_pack=data_pack,
                decision=analysis.decision,
                signals=signals,
                backtest=BacktestResult(),
                success=False,
                error="K线数据为空",
            )

        backtest_result = self._engine.run(
            df=stock_df,
            signals=signals,
            symbol=symbol,
            name=name,
        )

        logger.info(
            f"Pipeline 完成: {symbol} | "
            f"信号={len(signals)} | 成交={backtest_result.total_trades} | "
            f"收益={backtest_result.total_return:.2%}"
        )

        return PipelineResult(
            symbol=symbol,
            data_pack=data_pack,
            decision=analysis.decision,
            signals=signals,
            backtest=backtest_result,
            success=True,
        )

    def run_batch(
        self,
        symbols: List[str],
        names: Optional[Dict[str, str]] = None,
        default_shares: int = 100,
    ) -> List[PipelineResult]:
        """批量运行研报流水线

        Args:
            symbols: 股票代码列表
            names: 股票名称字典 {symbol: name}
            default_shares: 默认交易股数

        Returns:
            PipelineResult 列表
        """
        results = []
        for symbol in symbols:
            name = names.get(symbol) if names else None
            try:
                result = self.run(symbol, name=name, default_shares=default_shares)
                results.append(result)
            except Exception as e:
                logger.error(f"Pipeline 失败: {symbol}: {e}")
                results.append(PipelineResult(
                    symbol=symbol,
                    data_pack={},
                    decision={},
                    signals=[],
                    backtest=BacktestResult(),
                    success=False,
                    error=str(e),
                ))
        return results
