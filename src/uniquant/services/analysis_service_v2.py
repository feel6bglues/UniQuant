"""
分析服务 (重构版) — 纯流程编排，无缓存/数据处理职责
=====================================================

重构前: 1642 行 God Object (缓存+数据优化+验证+精度+引擎调用+报告)
重构后: ~300 行纯编排器 (引擎调用+决策+报告)

抽离的职责:
  - 缓存管理 → MarketLevelCache + CacheCoordinator
  - 数据优化 → DataService
  - 验证逻辑 → ValidationService
  - 精度处理 → shared.precision 模块
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from ..shared.time_provider import get_time_provider
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from ..shared.constants import (
    AnalysisServiceConstants,
    MarketConstants,
    PrecisionConstants,
)
from ..shared.error_handling import handle_errors
from ..shared.event_bus import EventBus
from ..shared.event_types import EngineCompleted
from ..shared.exceptions import AnalysisError, DataFetchError, ServiceError
from ..shared.interfaces import (
    AlphaOutput, CZSCOutput, DecisionOutput, LPPLOutput,
    MarketSignalContext, NtfOutput, RegimeOutput, ResearchDataPack,
    TradingSignal, WyckoffOutput,
)
from ..shared.config_models import load_refactoring_config
from ..shared.logger_factory import get_logger
from ..shared.observability import perf_section
from .analysis.engine_factory import AnalysisEngineFactory
from .analysis.pack_writer import DictPackWriter, RDPackWriter
from .data_service import DataService
from .market_cache import MarketLevelCache

RECOVERABLE_ERRORS = (
    AttributeError, ImportError, KeyError, ModuleNotFoundError,
    OSError, RuntimeError, TypeError, ValueError,
)

logger = get_logger("AnalysisService")


# ══════════════════════════════════════════════════════════════
# 分析结果领域对象
# ══════════════════════════════════════════════════════════════

@dataclass
class TickerAnalysisResult:
    """单只股票的分析结果"""
    symbol: str
    data_pack: Union[Dict[str, Any], ResearchDataPack]
    decision: Dict[str, Any]
    signals: List[TradingSignal]
    success: bool = True
    error: Optional[str] = None
    trace_id: Optional[str] = None


# ══════════════════════════════════════════════════════════════
# 分析服务 (重构版)
# ══════════════════════════════════════════════════════════════

class AnalysisService:
    """分析服务 — 纯流程编排器

    职责:
      1. 持有 AnalysisEngineFactory (延迟初始化所有 Brain 引擎)
      2. 编排 analyze_ticker 的完整流程
      3. 委托 MarketLevelCache 管理市场级缓存
      4. 委托 DataService 获取数据

    不再负责:
      - 内存/磁盘缓存管理 (已移除)
      - DataFrame 优化/采样 (已移除)
      - 验证逻辑 (已移除)
      - 精度一致性处理 (已移除)
    """

    def __init__(
        self,
        data_service: DataService,
        engine_factory: Optional[AnalysisEngineFactory] = None,
        market_cache: Optional[MarketLevelCache] = None,
        event_bus: Optional[EventBus] = None,
    ):
        self.data_service = data_service
        self._market_cache = market_cache or MarketLevelCache()
        self._event_bus = event_bus
        self.evt_risk = None
        self.sizer = None

        if engine_factory is None:
            engine_factory = AnalysisEngineFactory(orchestrator=self)
        self._factory = engine_factory

    # ── 引擎属性 (延迟初始化) ──────────────────────────────

    @property
    def brain(self):
        return self._factory.brain

    @property
    def lppl_engine(self):
        return self._factory.lppl

    @property
    def czsc_engine(self):
        return self._factory.czsc

    @property
    def wyckoff_engine(self):
        return self._factory.wyckoff

    @property
    def regime_engine(self):
        return self._factory.regime

    @property
    def ntf_engine(self):
        return self._factory.ntf

    @property
    def macro_engine(self):
        return self._factory.macro

    # ── 公共接口 ───────────────────────────────────────────

    @handle_errors(
        AnalysisError, DataFetchError, ServiceError,
        ValueError, TypeError,
        default_return=False, log_level=logging.ERROR,
    )
    def analyze_ticker(self, ticker: str) -> bool:
        """全流程分析单只股票 (重构版)"""
        result = self.run_ticker_analysis(ticker)
        return result.success

    # ── Engine adapter compatibility contract ─────────────────

    def _generate_cache_key(self, prefix: str, **kwargs) -> str:
        """Generate deterministic cache keys for analysis engine adapters."""
        parts = [prefix]
        for key, value in sorted(kwargs.items()):
            if value is not None:
                parts.append(f"{key}={value}")
        return ":".join(parts)

    def _get_cached_result(self, cache_key: str, use_disk: bool = False) -> Any:
        """Read adapter cache via DataService's shared cache facade."""
        if hasattr(self.data_service, "_get_cached"):
            return self.data_service._get_cached(cache_key)
        return None

    def _set_cached_result(
        self,
        cache_key: str,
        result: Any,
        use_disk: bool = False,
        ttl: Optional[int] = None,
    ) -> bool:
        """Write adapter cache via DataService's shared cache facade."""
        if hasattr(self.data_service, "_set_cache"):
            self.data_service._set_cache(cache_key, result, ttl=ttl)
            return True
        return False

    def _sample_data(
        self, df: pd.DataFrame, max_rows: Optional[int] = None,
    ) -> pd.DataFrame:
        """Downsample oversized frames while preserving chronological coverage."""
        if max_rows is None:
            max_rows = AnalysisServiceConstants.SAMPLE_MAX_ROWS_DEFAULT
        if df is None or len(df) <= max_rows:
            return df
        if max_rows <= 0:
            raise ValueError("max_rows must be positive")
        step = max(len(df) // max_rows, 1)
        sampled = df.iloc[::step].tail(max_rows)
        return sampled.reset_index(drop=True) if "date" in sampled.columns else sampled

    def _optimize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply lightweight dtype optimization expected by legacy adapters."""
        optimized = df.copy()
        for col in optimized.columns:
            if pd.api.types.is_integer_dtype(optimized[col]):
                optimized[col] = pd.to_numeric(optimized[col], downcast="integer")
            elif pd.api.types.is_float_dtype(optimized[col]):
                optimized[col] = pd.to_numeric(optimized[col], downcast="float")
        if "date" in optimized.columns:
            optimized = optimized.sort_values("date").reset_index(drop=True)
        return optimized

    def round_to_precision(self, value: float, precision_type: str) -> float:
        """Round numeric outputs using the shared analysis precision policy."""
        if precision_type == "price":
            return round(value, PrecisionConstants.PRICE_DECIMALS)
        if precision_type in {"ratio", "var", "drawdown"}:
            return round(value, PrecisionConstants.PCT_DECIMALS)
        return value

    def ensure_precision_consistency(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize nested adapter result precision without changing schema."""
        result: Dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, float):
                if key in {"var_95", "var_99", "cvar_95", "cvar_99"}:
                    result[key] = self.round_to_precision(value, "var")
                elif key == "max_drawdown":
                    result[key] = self.round_to_precision(value, "drawdown")
                elif key in {"signal_strength", "confidence", "amplitude"}:
                    result[key] = self.round_to_precision(value, "ratio")
                elif key in {"stop_loss", "take_profit", "close", "open", "high", "low"}:
                    result[key] = self.round_to_precision(value, "price")
                else:
                    result[key] = value
            elif isinstance(value, dict):
                result[key] = self.ensure_precision_consistency(value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _get_writer(data_pack: Union[Dict[str, Any], ResearchDataPack]):
        return RDPackWriter if isinstance(data_pack, ResearchDataPack) else DictPackWriter

    @staticmethod
    def _mark_engine_status(
        data_pack: Union[Dict[str, Any], ResearchDataPack],
        engine_name: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        if isinstance(data_pack, ResearchDataPack):
            data_pack.metadata.setdefault("engine_status", {})[engine_name] = status
            if error:
                data_pack.metadata.setdefault("engine_errors", {})[engine_name] = error
        else:
            data_pack.setdefault("engine_status", {})[engine_name] = status
            if error:
                data_pack.setdefault("engine_errors", {})[engine_name] = error

    @staticmethod
    def _attach_trace_id(data_pack: Union[Dict[str, Any], ResearchDataPack], trace_id: str) -> None:
        if isinstance(data_pack, ResearchDataPack):
            data_pack.metadata["trace_id"] = trace_id
            data_pack.metadata.setdefault("engine_status_meta", {})["trace_id"] = trace_id
        else:
            data_pack["trace_id"] = trace_id
            data_pack.setdefault("engine_status_meta", {})["trace_id"] = trace_id

    def run_ticker_analysis(
        self,
        ticker: str,
        trace_id: Optional[str] = None,
    ) -> TickerAnalysisResult:
        """全流程分析 — 返回强类型结果对象

        流程:
          1. DataService 获取数据 → data_pack
          2. AnalysisEngineFactory 运行所有 Brain 引擎
          3. DecisionBrain 做出决策
        """
        trace_id = trace_id or uuid.uuid4().hex

        # Step 1: 获取数据
        data_pack = self._prepare_data(ticker)
        if data_pack is None:
            data_pack = {}
            self._attach_trace_id(data_pack, trace_id)
            return TickerAnalysisResult(
                symbol=ticker, data_pack=data_pack, decision={},
                signals=[], success=False, error="数据不足", trace_id=trace_id,
            )
        self._attach_trace_id(data_pack, trace_id)

        # Step 2: 运行引擎
        if not self._run_engines(ticker, data_pack):
            return TickerAnalysisResult(
                symbol=ticker, data_pack=data_pack, decision={},
                signals=[], success=False, error="引擎分析失败", trace_id=trace_id,
            )

        # Step 3: 决策
        decision = self._make_decision(ticker, data_pack)
        if decision is None:
            return TickerAnalysisResult(
                symbol=ticker, data_pack=data_pack, decision={},
                signals=[], success=False, error="决策失败", trace_id=trace_id,
            )

        return TickerAnalysisResult(
            symbol=ticker,
            data_pack=data_pack,
            decision=decision,
            signals=[],  # 由 Pipeline 层通过 TradingSignalCollector 填充
            success=True,
            trace_id=trace_id,
        )

    # ── 内部方法: 数据准备 ─────────────────────────────────

    def _prepare_data(self, ticker: str) -> Optional[Union[Dict[str, Any], ResearchDataPack]]:
        """准备分析数据 — 委托 DataService"""
        try:
            research_pack: Optional[ResearchDataPack] = None
            try:
                ref_config = load_refactoring_config()
                if ref_config.feature_flags.use_research_data_pack:
                    research_pack = self.data_service.fetch_research_pack(ticker)
            except Exception as exc:
                logger.debug("ResearchDataPack feature flag check failed; falling back to dict path: %s", exc)

            if research_pack is not None:
                data_pack: Union[Dict[str, Any], ResearchDataPack] = research_pack
            else:
                data_pack = self.data_service.fetch_for_brain(ticker)

            if isinstance(data_pack, ResearchDataPack):
                stock_df = data_pack.stock_df
            else:
                if not data_pack:
                    logger.error(f"{ticker} 数据不足")
                    return None
                stock_df = data_pack.get("stock")

            if stock_df is None:
                logger.error(f"{ticker} 数据不足")
                return None
            if stock_df.empty:
                logger.error(f"{ticker} 股票数据为空")
                return None
            return data_pack
        except RECOVERABLE_ERRORS as e:
            logger.error(f"获取 {ticker} 数据失败: {e}")
            return None

    # ── 内部方法: 引擎编排 ─────────────────────────────────

    def _run_engines(self, ticker: str, data_pack: Union[Dict[str, Any], ResearchDataPack]) -> bool:
        """运行所有 Brain 引擎"""
        try:
            bus = self._event_bus
            with perf_section("engine.regime"):
                self._run_regime(ticker, data_pack)
            if bus is not None:
                bus.publish(EngineCompleted("regime", ticker, "OK"))

            with perf_section("engine.lppl"):
                self._run_lppl(data_pack)
            if bus is not None:
                bus.publish(EngineCompleted("lppl", ticker, "OK"))

            with perf_section("engine.ntf"):
                self._run_ntf(ticker, data_pack)
            if bus is not None:
                bus.publish(EngineCompleted("ntf", ticker, "OK"))

            with perf_section("engine.czsc"):
                self._run_czsc(ticker, data_pack)
            if bus is not None:
                bus.publish(EngineCompleted("czsc", ticker, "OK"))

            with perf_section("engine.wyckoff"):
                self._run_wyckoff(ticker, data_pack)
            if bus is not None:
                bus.publish(EngineCompleted("wyckoff", ticker, "OK"))

            with perf_section("engine.alpha"):
                self._run_alpha(data_pack)
            if bus is not None:
                bus.publish(EngineCompleted("alpha", ticker, "OK"))

            with perf_section("engine.derived"):
                self._calculate_derived(data_pack)
            if bus is not None:
                bus.publish(EngineCompleted("derived", ticker, "OK"))

            if isinstance(data_pack, ResearchDataPack):
                data_pack.symbol = ticker
                data_pack.metadata["market"] = "CN"
            else:
                data_pack["symbol"] = ticker
                data_pack["market"] = "CN"
            return True
        except RECOVERABLE_ERRORS as e:
            logger.error(f"引擎分析失败: {e}")
            return False

    def _run_regime(self, ticker: str, data_pack: Union[Dict[str, Any], ResearchDataPack]) -> None:
        """Regime 检测 (市场级缓存)"""
        writer = self._get_writer(data_pack)
        try:
            cached = self._market_cache.get_regime()
            if cached is not None:
                details = self._market_cache.get_regime_details() or {}
                output = RegimeOutput(
                    regime=str(cached),
                    entropy=float(details.get("entropy", 0.0)),
                    turnover_z=float(details.get("turnover_z", 0.0)),
                )
                writer.write_regime(data_pack, output)
                writer.mark_engine_status(data_pack, "regime", "OK")
                return

            from ..brain.regime.regime_detector import RegimeDetector
            detector = RegimeDetector()
            df = self.data_service.lake.read_data(
                MarketConstants.INDEX_HS300, data_type="index", market="cn",
            )
            if df is not None and not df.empty:
                result = detector.get_typed_summary(df)
            else:
                output = RegimeOutput(regime="UNKNOWN")
                writer.write_regime(data_pack, output)
                writer.mark_engine_status(
                    data_pack, "regime", "DATA_UNAVAILABLE",
                    "HS300 index data unavailable",
                )
                return

            self._market_cache.set_regime(result.regime, result.to_dict())
            writer.write_regime(data_pack, result)
            writer.mark_engine_status(data_pack, "regime", "OK")
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"Regime 检测失败: {e}")
            output = RegimeOutput(regime="UNKNOWN")
            writer.write_regime(data_pack, output)
            writer.mark_engine_status(data_pack, "regime", "ENGINE_FAILED", str(e))

    def _run_lppl(self, data_pack: Union[Dict[str, Any], ResearchDataPack]) -> None:
        """LPPL 泡沫检测"""
        writer = self._get_writer(data_pack)
        try:
            symbol = writer.get_symbol(data_pack)
            stock_df = writer.get_stock_df(data_pack)
            output = self.lppl_engine.run_lppl_analysis(
                symbol=symbol, df=stock_df,
            )
            writer.write_lppl(data_pack, output)

            if output.risk_level == "ENGINE_FAILED":
                writer.mark_engine_status(data_pack, "lppl", "ENGINE_FAILED", "LPPL analysis failed")
            else:
                writer.mark_engine_status(data_pack, "lppl", "OK")
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"LPPL 检测失败: {e}")
            output = LPPLOutput(risk_level="ENGINE_FAILED", confidence=1.0)
            writer.write_lppl(data_pack, output)
            writer.mark_engine_status(data_pack, "lppl", "ENGINE_FAILED", str(e))

    def _run_ntf(self, ticker: str, data_pack: Union[Dict[str, Any], ResearchDataPack]) -> None:
        """NTF 国家队检测 (市场级缓存)"""
        writer = self._get_writer(data_pack)
        try:
            cached = self._market_cache.get_ntf()
            if cached is not None:
                output = NtfOutput(
                    side=str(cached.get("side", "NONE")),
                    intensity=float(cached.get("intensity", 0.0)),
                )
                writer.write_ntf(data_pack, output, action=cached.get("action", ""))
                return

            from ..brain.ntf.ntf_engine import NTFEngine

            fetcher = self.data_service.fetcher
            end_date = pd.Timestamp(get_time_provider().now()).strftime("%Y-%m-%d")
            start_date = (
                pd.Timestamp(get_time_provider().now()) - pd.DateOffset(months=3)
            ).strftime("%Y-%m-%d")

            ntf = NTFEngine()
            result = ntf.detect_intervention_from_data(
                fetcher, "510300.SH", start_date, end_date,
            )

            output = NtfOutput(
                side=str(result.get("side", "NONE")),
                intensity=float(result.get("intensity", 0.0)),
            )
            self._market_cache.set_ntf(result)
            writer.write_ntf(data_pack, output, action=result.get("action", ""))
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"NTF 检测失败: {e}")
            output = NtfOutput(side="NONE")
            writer.write_ntf(data_pack, output)

    def _run_czsc(self, ticker: str, data_pack: Union[Dict[str, Any], ResearchDataPack]) -> None:
        """CZSC 缠论分析"""
        writer = self._get_writer(data_pack)
        try:
            stock_df = writer.get_stock_df(data_pack)
            result = self.czsc_engine.run_czsc_analysis(
                symbol=ticker, df=stock_df,
            )
            output = CZSCOutput(
                is_3rd_buy=bool(result.get("is_3rd_buy", False)),
                bi_count=int(result.get("bi_count", 0)),
                price=float(result.get("price", 0.0)),
                bottom=result.get("czsc_bottom"),
            )
            writer.write_czsc(data_pack, output)
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"CZSC 分析失败: {e}")
            writer.write_czsc(data_pack, CZSCOutput())

    def _run_wyckoff(self, ticker: str, data_pack: Union[Dict[str, Any], ResearchDataPack]) -> None:
        """Wyckoff 分析"""
        writer = self._get_writer(data_pack)
        try:
            stock_df = writer.get_stock_df(data_pack)
            result = self.wyckoff_engine.run_wyckoff_analysis(
                symbol=ticker, df=stock_df,
            )
            output = WyckoffOutput(
                phase=str(result.get("phase", "unknown")),
                confidence=float(result.get("confidence", 0.0)),
                spring=bool(result.get("spring_detected", False)),
                utad=bool(result.get("utad_detected", False)),
                price=float(result.get("price", 0.0)),
            )
            writer.write_wyckoff(data_pack, output)
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"Wyckoff 分析失败: {e}")
            writer.write_wyckoff(data_pack, WyckoffOutput())

    def _run_alpha(self, data_pack: Union[Dict[str, Any], ResearchDataPack]) -> None:
        """Alpha 分离度分析"""
        writer = self._get_writer(data_pack)
        try:
            from ..brain.alpha_decoupler.alpha_decoupler import AlphaDecoupler
            stock_df = writer.get_stock_df(data_pack)
            if stock_df is None or stock_df.empty:
                writer.write_alpha(data_pack, AlphaOutput(score=0.0))
                return

            storage = self.data_service.lake
            bench = storage.read_data("000300.SH", "index")
            sector = storage.read_data("000905.SH", "index")

            if bench is None or bench.empty:
                writer.write_alpha(data_pack, AlphaOutput(score=0.0))
                return

            score = float(AlphaDecoupler.get_alpha_score(
                stock_df, bench, sector,
            ))
            writer.write_alpha(data_pack, AlphaOutput(score=score))
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"Alpha 分析失败: {e}")
            writer.write_alpha(data_pack, AlphaOutput(score=0.0))

    def _calculate_derived(self, data_pack: Union[Dict[str, Any], ResearchDataPack]) -> None:
        """计算衍生指标 (MA状态, 价格, ATR止损)"""
        stock_df = data_pack.stock_df if isinstance(data_pack, ResearchDataPack) else data_pack.get("stock")
        if stock_df is None or stock_df.empty:
            return

        try:
            from ..brain.indicators.indicators import Indicators
            indicators = Indicators()

            is_typed = isinstance(data_pack, ResearchDataPack)
            meta = data_pack.metadata if is_typed else None

            # MA 状态
            ma_short = indicators.calc_ma(stock_df, window=20)
            ma_long = indicators.calc_ma(stock_df, window=60)
            if not ma_short.empty and not ma_long.empty:
                if ma_short.iloc[-1] > ma_long.iloc[-1]:
                    ma_status = "MA20 > MA60"
                else:
                    ma_status = "MA20 <= MA60"
            else:
                ma_status = "DATA_INSUFFICIENT"

            if is_typed:
                meta["ma_status"] = ma_status
            else:
                data_pack["ma_status"] = ma_status

            # 价格和止损
            price = float(stock_df.iloc[-1]["close"])
            if is_typed:
                meta["price"] = price
            else:
                data_pack["price"] = price

            atr = indicators.calc_atr(stock_df)
            if not atr.empty:
                atr_stop = price - float(atr.iloc[-1]) * 2
            else:
                atr_stop = price * 0.95

            if is_typed:
                meta["atr_stop"] = atr_stop
                meta["returns"] = stock_df["close"].pct_change().dropna()
            else:
                data_pack["atr_stop"] = atr_stop
                data_pack["returns"] = stock_df["close"].pct_change().dropna()
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"衍生指标计算失败: {e}")

    # ── 内部方法: 决策 ─────────────────────────────────────

    def _make_decision(
        self, ticker: str, data_pack: Union[Dict[str, Any], ResearchDataPack],
    ) -> Optional[Dict[str, Any]]:
        """调用 DecisionBrain 做出决策 (传入 MarketSignalContext)"""
        try:
            with perf_section("engine.decision"):
                if isinstance(data_pack, ResearchDataPack):
                    dict_pack = data_pack.to_dict()
                    dict_pack.update(data_pack.metadata)
                    ctx = MarketSignalContext.from_dict(dict_pack)
                else:
                    ctx = MarketSignalContext.from_dict(data_pack)
                raw = self.brain.make_decision(ctx)
                if raw:
                    decision_output = DecisionOutput.from_dict(raw)
                    raw["decision_output"] = decision_output
            return raw
        except RECOVERABLE_ERRORS as e:
            logger.error(f"{ticker} 决策失败: {e}")
            return None

    # ── 兼容旧接口 ─────────────────────────────────────────

    def clear_market_cache(self) -> None:
        self._market_cache.clear()

    def get_cache_status(self) -> Dict[str, Any]:
        return self._market_cache.status()

    def analyze_macro_health(self, mock: bool = False):
        return self.macro_engine.analyze_macro_health(mock=mock)
