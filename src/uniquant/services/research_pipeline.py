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

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from ..hands.backtest.unified_engine import BacktestResult, UnifiedBacktestEngine
from ..shared.event_bus import EventBus
from ..shared.event_types import (
    BacktestCompleted as BacktestCompletedEvent,
    DataLoaded,
    DecisionProduced,
    RunCompleted,
    RunStarted,
    SignalsCollected,
)
from ..shared.interfaces import TradingSignal
from ..shared.logger_factory import get_logger
from ..shared.observability import InMemoryMetricsRecorder, perf_section
from ..signal.adapters import TradingSignalCollector, create_default_registry
from ..signal.arbitrator import SignalArbitrator
from ..shared.time_provider import RealTimeProvider, TimeProvider
from .analysis_service_v2 import AnalysisService

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
    trace_id: Optional[str] = None
    metrics: Optional[InMemoryMetricsRecorder] = None

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
        arbitrator: Optional[SignalArbitrator] = None,
        time_provider: Optional[TimeProvider] = None,
        event_bus: Optional[EventBus] = None,
        metrics: Optional[InMemoryMetricsRecorder] = None,
    ):
        self._analysis = analysis_service
        self._engine = backtest_engine or UnifiedBacktestEngine()
        self._collector = signal_collector or TradingSignalCollector(
            create_default_registry(),
        )
        self._arbitrator = arbitrator
        self._time_provider = time_provider or RealTimeProvider()
        self._event_bus = event_bus
        self._metrics = metrics or InMemoryMetricsRecorder()

    def run(
        self,
        symbol: str,
        name: Optional[str] = None,
        default_shares: int = 100,
        trace_id: Optional[str] = None,
    ) -> PipelineResult:
        """运行完整研报流水线

        Args:
            symbol: 股票代码 (如 "000001.SZ")
            name: 股票名称 (用于 ST 识别)
            default_shares: 默认交易股数

        Returns:
            PipelineResult 包含全链路输出
        """
        trace_id = trace_id or uuid.uuid4().hex

        bus = self._event_bus
        metrics = self._metrics

        with perf_section("pipeline.total", recorder=metrics):
            if bus is not None:
                bus.publish(RunStarted(symbol=symbol, trace_id=trace_id))

            # Step 1-2: 运行 Brain 引擎分析
            with perf_section("pipeline.analysis", recorder=metrics):
                analysis = self._analysis.run_ticker_analysis(
                    symbol, trace_id=trace_id,
                )

            if bus is not None:
                data_ok = bool(
                    analysis.success and analysis.data_pack.get("stock") is not None
                )
                rows = len(analysis.data_pack.get("stock")) if data_ok else 0
                bus.publish(DataLoaded(symbol=symbol, success=data_ok, rows=rows))

            if not analysis.success:
                bus_result = PipelineResult(
                    symbol=symbol,
                    data_pack=analysis.data_pack,
                    decision=analysis.decision,
                    signals=[],
                    backtest=BacktestResult(),
                    success=False,
                    error=analysis.error,
                    trace_id=trace_id,
                    metrics=metrics,
                )
                if bus is not None:
                    bus.publish(RunCompleted(symbol=symbol, success=False))
                return bus_result

            # Step 3: 收集信号
            data_pack = analysis.data_pack
            with perf_section("pipeline.collect", recorder=metrics):
                collector_pack = self._merge_decision_for_collection(
                    data_pack, analysis.decision,
                )
                timestamp = self._time_provider.now()
                stock_df = data_pack.get("stock") if isinstance(data_pack, dict) else None
                bar_date = None
                if stock_df is not None and not stock_df.empty:
                    last_date = pd.to_datetime(stock_df["date"].iloc[-1])
                    bar_date = last_date.to_pydatetime()
                signals = self._collector.collect(
                    collector_pack,
                    timestamp=timestamp,
                    bar_date=bar_date,
                    default_shares=default_shares,
                )

            if bus is not None:
                bus.publish(DecisionProduced(
                    symbol=symbol,
                    action=analysis.decision.get("action", "HOLD"),
                    confidence=float(analysis.decision.get("confidence", 0.0)),
                ))

            # Step 3b: 信号仲裁 (特性开关控制)
            with perf_section("pipeline.arbitrate", recorder=metrics):
                if self._arbitrator is not None:
                    signals = self._arbitrator.arbitrate(signals, symbol=symbol)
                    if signals:
                        logger.debug(
                            "仲裁完成: %s -> %s (%s)",
                            symbol, signals[0].action, signals[0].reason,
                        )

            if bus is not None:
                bus.publish(SignalsCollected(symbol=symbol, count=len(signals)))

            # Step 4: 回测撮合
            stock_df = data_pack.get("stock")
            if stock_df is None or stock_df.empty:
                bus_result = PipelineResult(
                    symbol=symbol,
                    data_pack=data_pack,
                    decision=analysis.decision,
                    signals=signals,
                    backtest=BacktestResult(),
                    success=False,
                    error="K线数据为空",
                    trace_id=trace_id,
                    metrics=metrics,
                )
                if bus is not None:
                    bus.publish(RunCompleted(symbol=symbol, success=False))
                return bus_result

            with perf_section("pipeline.backtest", recorder=metrics):
                backtest_result = self._engine.run(
                    df=stock_df,
                    signals=signals,
                    symbol=symbol,
                    name=name,
                )

            if bus is not None:
                bus.publish(BacktestCompletedEvent(
                    symbol=symbol,
                    trades=backtest_result.total_trades,
                    total_return=backtest_result.total_return,
                ))

            logger.info(
                f"Pipeline 完成: trace_id={trace_id} | {symbol} | "
                f"信号={len(signals)} | 成交={backtest_result.total_trades} | "
                f"收益={backtest_result.total_return:.2%}"
            )

            result = PipelineResult(
                symbol=symbol,
                data_pack=data_pack,
                decision=analysis.decision,
                signals=signals,
                backtest=backtest_result,
                success=True,
                trace_id=trace_id,
                metrics=metrics,
            )

        if bus is not None:
            bus.publish(RunCompleted(
                symbol=symbol,
                success=True,
                total_return=backtest_result.total_return,
                total_trades=backtest_result.total_trades,
            ))

        return result

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

    @staticmethod
    def _merge_decision_for_collection(
        data_pack: Dict[str, Any],
        decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Expose DecisionBrain output to TradingSignalCollector safely."""
        if not decision:
            return data_pack

        collector_pack = dict(data_pack)
        if "final_decision" in decision:
            collector_pack["final_decision"] = decision["final_decision"]
        elif "action" in decision:
            collector_pack["action"] = decision["action"]

        for key in ("action", "shares", "confidence", "reason", "price"):
            if key in decision:
                collector_pack[key] = decision[key]
        if "final_score" in decision and "confidence" not in collector_pack:
            collector_pack["confidence"] = max(
                0.0, min(float(decision["final_score"]) / 100.0, 1.0)
            )
        if "score" in decision and "confidence" not in collector_pack:
            collector_pack["confidence"] = max(
                0.0, min(float(decision["score"]) / 100.0, 1.0)
            )

        return collector_pack
