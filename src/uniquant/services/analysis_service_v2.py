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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from ..shared.config_loader import get_config
from ..shared.constants import MarketConstants, ResultsConstants
from ..shared.error_handling import handle_errors
from ..shared.exceptions import AnalysisError, DataFetchError, ServiceError
from ..shared.interfaces import TradingSignal
from ..shared.logger_factory import get_logger
from .analysis.engine_factory import AnalysisEngineFactory
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
    data_pack: Dict[str, Any]
    decision: Dict[str, Any]
    signals: List[TradingSignal]
    success: bool = True
    error: Optional[str] = None


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
    ):
        self.data_service = data_service
        self._market_cache = market_cache or MarketLevelCache()

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

    def run_ticker_analysis(self, ticker: str) -> TickerAnalysisResult:
        """全流程分析 — 返回强类型结果对象

        流程:
          1. DataService 获取数据 → data_pack
          2. AnalysisEngineFactory 运行所有 Brain 引擎
          3. DecisionBrain 做出决策
        """
        # Step 1: 获取数据
        data_pack = self._prepare_data(ticker)
        if data_pack is None:
            return TickerAnalysisResult(
                symbol=ticker, data_pack={}, decision={},
                signals=[], success=False, error="数据不足",
            )

        # Step 2: 运行引擎
        if not self._run_engines(ticker, data_pack):
            return TickerAnalysisResult(
                symbol=ticker, data_pack=data_pack, decision={},
                signals=[], success=False, error="引擎分析失败",
            )

        # Step 3: 决策
        decision = self._make_decision(ticker, data_pack)
        if decision is None:
            return TickerAnalysisResult(
                symbol=ticker, data_pack=data_pack, decision={},
                signals=[], success=False, error="决策失败",
            )

        return TickerAnalysisResult(
            symbol=ticker,
            data_pack=data_pack,
            decision=decision,
            signals=[],  # 由 Pipeline 层通过 TradingSignalCollector 填充
            success=True,
        )

    # ── 内部方法: 数据准备 ─────────────────────────────────

    def _prepare_data(self, ticker: str) -> Optional[Dict[str, Any]]:
        """准备分析数据 — 委托 DataService"""
        try:
            data_pack = self.data_service.fetch_for_brain(ticker)
            if not data_pack or data_pack.get("stock") is None:
                logger.error(f"{ticker} 数据不足")
                return None
            if data_pack["stock"].empty:
                logger.error(f"{ticker} 股票数据为空")
                return None
            return data_pack
        except RECOVERABLE_ERRORS as e:
            logger.error(f"获取 {ticker} 数据失败: {e}")
            return None

    # ── 内部方法: 引擎编排 ─────────────────────────────────

    def _run_engines(self, ticker: str, data_pack: Dict[str, Any]) -> bool:
        """运行所有 Brain 引擎"""
        try:
            self._run_regime(ticker, data_pack)
            self._run_lppl(data_pack)
            self._run_ntf(ticker, data_pack)
            self._run_czsc(ticker, data_pack)
            self._run_wyckoff(ticker, data_pack)
            self._run_alpha(data_pack)
            self._calculate_derived(data_pack)

            data_pack["symbol"] = ticker
            data_pack["market"] = "CN"
            return True
        except RECOVERABLE_ERRORS as e:
            logger.error(f"引擎分析失败: {e}")
            return False

    def _run_regime(self, ticker: str, data_pack: Dict[str, Any]) -> None:
        """Regime 检测 (市场级缓存)"""
        try:
            cached = self._market_cache.get_regime()
            if cached is not None:
                data_pack["regime"] = cached
                details = self._market_cache.get_regime_details()
                if details:
                    data_pack["entropy"] = details.get("entropy", 0.0)
                    data_pack["turnover_z"] = details.get("turnover_z", 0.0)
                return

            from ..brain.regime.regime_detector import RegimeDetector
            detector = RegimeDetector()
            df = self.data_service.lake.read_data(
                MarketConstants.INDEX_HS300, data_type="index", market="cn",
            )
            if df is not None and not df.empty:
                result = detector.get_summary(df)
            else:
                result = {"regime": "NORMAL", "entropy": 0.0, "turnover_z": 0.0}

            self._market_cache.set_regime(result.get("regime", "NORMAL"), result)
            data_pack["regime"] = result.get("regime", "NORMAL")
            data_pack["entropy"] = result.get("entropy", 0.0)
            data_pack["turnover_z"] = result.get("turnover_z", 0.0)
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"Regime 检测失败: {e}")
            data_pack["regime"] = "NORMAL"

    def _run_lppl(self, data_pack: Dict[str, Any]) -> None:
        """LPPL 泡沫检测"""
        try:
            symbol = data_pack.get("symbol", "unknown")
            result = self.lppl_engine.run_lppl_analysis(
                symbol=symbol, df=data_pack.get("stock"),
            )
            data_pack["risk"] = result.get("risk_level", "Safe")
            data_pack["bubble_confidence"] = result.get("confidence", 0.0)
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"LPPL 检测失败: {e}")
            data_pack["risk"] = "Safe"
            data_pack["bubble_confidence"] = 0.0

    def _run_ntf(self, ticker: str, data_pack: Dict[str, Any]) -> None:
        """NTF 国家队检测 (市场级缓存)"""
        try:
            cached = self._market_cache.get_ntf()
            if cached is not None:
                data_pack["ntf_side"] = cached.get("side", "NONE")
                data_pack["ntf_intensity"] = cached.get("intensity", 0.0)
                data_pack["ntf_action"] = cached.get("action", "")
                return

            from ..brain.ntf.ntf_engine import NTFEngine
            from ..data.data_fetcher import DataFetcher

            fetcher = DataFetcher()
            end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
            start_date = (
                pd.Timestamp.now() - pd.DateOffset(months=3)
            ).strftime("%Y-%m-%d")

            ntf = NTFEngine()
            result = ntf.detect_intervention_from_data(
                fetcher, "510300.SH", start_date, end_date,
            )

            self._market_cache.set_ntf(result)
            data_pack["ntf_side"] = result.get("side", "NONE")
            data_pack["ntf_intensity"] = result.get("intensity", 0.0)
            data_pack["ntf_action"] = result.get("action", "")
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"NTF 检测失败: {e}")
            data_pack["ntf_side"] = "NONE"
            data_pack["ntf_intensity"] = 0.0

    def _run_czsc(self, ticker: str, data_pack: Dict[str, Any]) -> None:
        """CZSC 缠论分析"""
        try:
            result = self.czsc_engine.run_czsc_analysis(
                symbol=ticker, df=data_pack.get("stock"),
            )
            data_pack["is_3rd_buy"] = result.get("is_3rd_buy", False)
            data_pack["bi_count"] = result.get("bi_count", 0)
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"CZSC 分析失败: {e}")
            data_pack["is_3rd_buy"] = False
            data_pack["bi_count"] = 0

    def _run_wyckoff(self, ticker: str, data_pack: Dict[str, Any]) -> None:
        """Wyckoff 分析"""
        try:
            result = self.wyckoff_engine.run_wyckoff_analysis(
                symbol=ticker, df=data_pack.get("stock"),
            )
            data_pack["wyckoff_phase"] = result.get("phase", "unknown")
            data_pack["wyckoff_confidence"] = result.get("confidence", 0.0)
            data_pack["wyckoff_spring"] = result.get("spring_detected", False)
            data_pack["wyckoff_utad"] = result.get("utad_detected", False)
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"Wyckoff 分析失败: {e}")
            data_pack["wyckoff_phase"] = "unknown"
            data_pack["wyckoff_confidence"] = 0.0

    def _run_alpha(self, data_pack: Dict[str, Any]) -> None:
        """Alpha 分离度分析"""
        try:
            from ..brain.alpha_decoupler.alpha_decoupler import AlphaDecoupler
            stock_df = data_pack.get("stock")
            if stock_df is None or stock_df.empty:
                data_pack["alpha_score"] = 0.0
                return

            from ..data.lake.storage_manager import StorageManager
            storage = StorageManager()
            bench = storage.read_data("000300.SH", "index")
            sector = storage.read_data("000905.SH", "index")

            if bench is None or bench.empty:
                data_pack["alpha_score"] = 0.0
                return

            data_pack["alpha_score"] = AlphaDecoupler.get_alpha_score(
                stock_df, bench, sector,
            )
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"Alpha 分析失败: {e}")
            data_pack["alpha_score"] = 0.0

    def _calculate_derived(self, data_pack: Dict[str, Any]) -> None:
        """计算衍生指标 (MA状态, 价格, ATR止损)"""
        stock_df = data_pack.get("stock")
        if stock_df is None or stock_df.empty:
            return

        try:
            from ..brain.indicators.indicators import Indicators
            indicators = Indicators()

            # MA 状态
            ma_short = indicators.calc_ma(stock_df, window=20)
            ma_long = indicators.calc_ma(stock_df, window=60)
            if not ma_short.empty and not ma_long.empty:
                if ma_short.iloc[-1] > ma_long.iloc[-1]:
                    data_pack["ma_status"] = "MA20 > MA60"
                else:
                    data_pack["ma_status"] = "MA20 <= MA60"
            else:
                data_pack["ma_status"] = "DATA_INSUFFICIENT"

            # 价格和止损
            data_pack["price"] = float(stock_df.iloc[-1]["close"])
            atr = indicators.calc_atr(stock_df)
            if not atr.empty:
                data_pack["atr_stop"] = data_pack["price"] - float(atr.iloc[-1]) * 2
            else:
                data_pack["atr_stop"] = data_pack["price"] * 0.95

            # 收益率
            data_pack["returns"] = stock_df["close"].pct_change().dropna()
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"衍生指标计算失败: {e}")

    # ── 内部方法: 决策 ─────────────────────────────────────

    def _make_decision(
        self, ticker: str, data_pack: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """调用 DecisionBrain 做出决策"""
        try:
            return self.brain.make_decision(data_pack)
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
