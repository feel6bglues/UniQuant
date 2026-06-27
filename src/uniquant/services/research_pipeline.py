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

import concurrent.futures
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
from ..shared.interfaces import (
    CandidateSignal,
    DecisionOutput,
    MarketSignalContext,
    PositionSizerProtocol,
    ResearchDataPack,
    TradingSignal,
)
from ..shared.logger_factory import get_logger
from ..shared.observability import InMemoryMetricsRecorder, perf_section
from ..signal.adapters import TradingSignalCollector, create_default_registry
from ..signal.arbitrator import SignalArbitrator
from ..shared.time_provider import RealTimeProvider, TimeProvider
from .analysis_service_v2 import AnalysisService

logger = get_logger(__name__)


def _checkpoint_json_default(obj: Any) -> str:
    """JSON encoder default for datetime objects in checkpoints."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ══════════════════════════════════════════════════════════════
# 流水线结果领域对象
# ══════════════════════════════════════════════════════════════

@dataclass
class PipelineResult:
    """统一研报流水线结果

    包含从 Brain 引擎到回测撮合的全链路输出。
    """
    symbol: str
    data_pack: Union[Dict[str, Any], ResearchDataPack]
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
        sizer: Optional[PositionSizerProtocol] = None,
        time_provider: Optional[TimeProvider] = None,
        event_bus: Optional[EventBus] = None,
        metrics: Optional[InMemoryMetricsRecorder] = None,
        max_workers: Optional[int] = None,
    ):
        self._analysis = analysis_service
        self._engine = backtest_engine or UnifiedBacktestEngine()
        self._collector = signal_collector or TradingSignalCollector(
            create_default_registry(),
        )
        self._arbitrator = arbitrator
        self._sizer = sizer
        self._time_provider = time_provider or RealTimeProvider()
        self._event_bus = event_bus
        self._metrics = metrics or InMemoryMetricsRecorder()
        self._max_workers = max_workers

    # ──────────────────────────────────────────────────────────
    # Batch checkpoint helpers
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _result_to_checkpoint_dict(result: PipelineResult) -> Dict[str, Any]:
        return {
            "symbol": result.symbol,
            "success": result.success,
            "error": result.error,
            "trace_id": result.trace_id,
            "decision": result.decision,
            "signals": [
                {
                    "action": s.action,
                    "reason": s.reason,
                    "confidence": s.confidence,
                    "shares": s.shares,
                    "symbol": s.symbol,
                    "price": s.price,
                    "timestamp": s.timestamp.isoformat() if s.timestamp else None,
                }
                for s in result.signals
            ],
            "backtest": {
                "trades": [
                    {
                        "timestamp": t.timestamp.isoformat(),
                        "action": t.action,
                        "symbol": t.symbol,
                        "price": t.price,
                        "shares": t.shares,
                        "commission": t.commission,
                        "stamp_duty": t.stamp_duty,
                        "transfer_fee": t.transfer_fee,
                        "slippage": t.slippage,
                        "pnl": t.pnl,
                        "reason": t.reason,
                    }
                    for t in result.backtest.trades
                ],
                "equity_curve": result.backtest.equity_curve,
                "daily_returns": result.backtest.daily_returns,
                "initial_capital": result.backtest.initial_capital,
                "final_cash": result.backtest.final_cash,
                "metadata": result.backtest.metadata,
            },
        }

    @staticmethod
    def _result_from_checkpoint_dict(data: Dict[str, Any]) -> PipelineResult:
        signals = [
            TradingSignal.from_dict(s) for s in data.get("signals", [])
        ]
        bt = data.get("backtest", {})
        trades_raw = bt.get("trades", [])
        backtest = BacktestResult(
            trades=trades_raw,
            equity_curve=bt.get("equity_curve", []),
            daily_returns=bt.get("daily_returns", []),
            initial_capital=bt.get("initial_capital", 0.0),
            final_cash=bt.get("final_cash", 0.0),
            metadata=bt.get("metadata", {}),
        )
        return PipelineResult(
            symbol=data["symbol"],
            data_pack={},
            decision=data.get("decision", {}),
            signals=signals,
            backtest=backtest,
            success=data.get("success", True),
            error=data.get("error"),
            trace_id=data.get("trace_id"),
        )

    def _save_batch_checkpoint(
        self, result: PipelineResult, checkpoint_dir: Path,
    ) -> None:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        data = self._result_to_checkpoint_dict(result)
        path = checkpoint_dir / f"{result.symbol}.json"
        tmp = tempfile.NamedTemporaryFile(
            mode='w', dir=str(checkpoint_dir), suffix='.tmp', delete=False,
            encoding='utf-8',
        )
        try:
            tmp.write(json.dumps(data, default=_checkpoint_json_default, ensure_ascii=False))
            tmp.close()
            os.replace(tmp.name, str(path))
        except:
            os.unlink(tmp.name)
            raise

    @staticmethod
    def _signals_to_candidates(signals: List[TradingSignal]) -> List[CandidateSignal]:
        direction_map = {"BUY": 1, "SELL": -1}
        return [
            CandidateSignal(
                action=s.action,
                confidence=s.confidence,
                direction=direction_map.get(s.action, 0),
                strength=s.confidence,
                source=s.reason.split(":")[0].split(" ")[0].lower() if s.reason else "unknown",
                price_target=s.price if s.price > 0 else None,
            )
            for s in signals
            if s.action in ("BUY", "SELL")
        ]

    @staticmethod
    def _load_completed_symbols(checkpoint_dir: Path) -> set:
        if not checkpoint_dir.exists():
            return set()
        return {
            f.stem for f in checkpoint_dir.iterdir()
            if f.suffix == ".json"
        }

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
                dp = analysis.data_pack
                stock_df = dp.stock_df if isinstance(dp, ResearchDataPack) else dp.get("stock")
                data_ok = bool(analysis.success and stock_df is not None)
                rows = len(stock_df) if data_ok else 0
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
                stock_df = data_pack.stock_df if isinstance(data_pack, ResearchDataPack) else data_pack.get("stock")
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
                    candidates = self._signals_to_candidates(signals)
                    decision_output = DecisionOutput.from_dict(analysis.decision)
                    context_dict = data_pack.to_dict() if isinstance(data_pack, ResearchDataPack) else data_pack
                    context = MarketSignalContext.from_dict(context_dict)
                    signals, report = self._arbitrator.arbitrate_candidates(
                        candidates=candidates,
                        decision_output=decision_output,
                        context=context,
                        sizer=self._sizer,
                        symbol=symbol,
                    )
                    if signals:
                        logger.debug(
                            "仲裁完成: %s -> %s (%s) | veto=%s",
                            symbol, signals[0].action, signals[0].reason,
                            report.veto_chain,
                        )

            if bus is not None:
                bus.publish(SignalsCollected(symbol=symbol, count=len(signals)))

            # Step 4: 回测撮合
            stock_df = data_pack.stock_df if isinstance(data_pack, ResearchDataPack) else data_pack.get("stock")
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
        checkpoint_dir: Optional[Path] = None,
        max_workers: Optional[int] = None,
    ) -> List[PipelineResult]:
        """批量运行研报流水线

        Args:
            symbols: 股票代码列表
            names: 股票名称字典 {symbol: name}
            default_shares: 默认交易股数
            checkpoint_dir: checkpoint 目录（启用断点续跑功能）
            max_workers: 并行工作线程数，None=self._max_workers（实例默认），再退化为 cpu_count//2

        Returns:
            PipelineResult 列表（按输入 symbols 顺序返回）

        Note:
            Checkpoint 恢复后 data_pack 为空字典（仅保存 decision/signals/backtest），
            不保存原始 K 线 data_pack。
        """
        results: List[PipelineResult] = []

        completed: set = set()
        if checkpoint_dir is not None:
            completed = self._load_completed_symbols(checkpoint_dir)
            if completed:
                logger.info(
                    "Checkpoint found: %d symbols already completed, resuming",
                    len(completed),
                )
                for symbol in symbols:
                    if symbol in completed:
                        result = self._load_checkpoint_result(checkpoint_dir, symbol)
                        if result is not None:
                            results.append(result)

        to_process = [s for s in symbols if s not in completed]
        if not to_process:
            return results

        if max_workers is None:
            max_workers = self._max_workers
        if max_workers is None:
            max_workers = max(1, (os.cpu_count() or 4) // 2)

        def _run_single(symbol: str) -> PipelineResult:
            name = names.get(symbol) if names else None
            try:
                return self.run(symbol, name=name, default_shares=default_shares)
            except Exception as e:
                logger.error(f"Pipeline 失败: {symbol}: {e}")
                return PipelineResult(
                    symbol=symbol,
                    data_pack={},
                    decision={},
                    signals=[],
                    backtest=BacktestResult(),
                    success=False,
                    error=str(e),
                )

        result_map: Dict[str, PipelineResult] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_run_single, symbol): symbol
                for symbol in to_process
            }
            for future in concurrent.futures.as_completed(futures):
                symbol = futures[future]
                result = future.result()
                result_map[symbol] = result
                if checkpoint_dir is not None:
                    self._save_batch_checkpoint(result, checkpoint_dir)

        results.extend(result_map[s] for s in symbols if s not in completed)
        return results

    @staticmethod
    def _load_checkpoint_result(
        checkpoint_dir: Path, symbol: str,
    ) -> Optional[PipelineResult]:
        path = checkpoint_dir / f"{symbol}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return UnifiedResearchPipeline._result_from_checkpoint_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load checkpoint for {symbol}: {e}")
            return None

    @staticmethod
    def _merge_decision_for_collection(
        data_pack: Union[Dict[str, Any], ResearchDataPack],
        decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Expose DecisionBrain output to TradingSignalCollector safely."""
        if isinstance(data_pack, ResearchDataPack):
            data_pack = data_pack.to_dict()
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
