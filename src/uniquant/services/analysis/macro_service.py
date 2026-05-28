"""
MacroAnalysisService: 宏观分析服务

职责：
- LPPL 泡沫检测
- 市场状态检测 (Regime)
- 国家队干预检测 (NTF)
- 宏观健康分析
"""

import datetime
import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ...shared.constants import (
    AnalysisServiceConstants,
    MarketConstants,
    TimeConstants,
    RiskCalculationConstants,
    IndicatorThresholds,
)
from ...shared.error_handling import handle_errors
from ...shared.exceptions import AnalysisError, DataFetchError, DataValidationError
from ...shared.logger_factory import get_logger

logger = get_logger("MacroAnalysisService")

MACRO_RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    ModuleNotFoundError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


class MacroAnalysisService:
    """
    宏观分析服务
    
    负责市场级别的分析：
    - LPPL 泡沫检测
    - Regime 市场状态
    - NTF 国家队干预
    - 宏观健康指标
    """

    def __init__(
        self,
        data_service=None,
        evt_risk=None,
        memory_cache=None,
        disk_cache=None,
    ):
        """
        初始化宏观分析服务
        
        Args:
            data_service: 数据服务实例
            evt_risk: EVT风险计算器
            memory_cache: 内存缓存
            disk_cache: 磁盘缓存
        """
        self.data_service = data_service
        self.evt_risk = evt_risk
        self.memory_cache = memory_cache
        self.disk_cache = disk_cache
        
        self._market_cache_date: Optional[str] = None
        self._market_regime: Optional[str] = None
        self._market_regime_details: Optional[Dict[str, Any]] = None
        self._ntf_signals: Optional[Dict[str, Any]] = None
        self._benchmark_data: Optional[pd.DataFrame] = None

    def _generate_cache_key(self, prefix: str, **kwargs) -> str:
        sorted_params = sorted(kwargs.items())
        param_str = "_".join([f"{k}={v}" for k, v in sorted_params])
        return f"{prefix}:{param_str}"

    def _get_cached_result(self, cache_key: str, use_disk: bool = False) -> Any:
        if self.memory_cache:
            result = self.memory_cache.get(cache_key)
            if result is not None:
                return result
        if use_disk and self.disk_cache:
            result = self.disk_cache.get(cache_key)
            if result is not None:
                if self.memory_cache:
                    self.memory_cache.set(cache_key, result)
                return result
        return None

    def _set_cached_result(
        self, cache_key: str, result: Any, use_disk: bool = False, ttl: Optional[int] = None
    ) -> bool:
        if self.memory_cache:
            self.memory_cache.set(cache_key, result, ttl)
        if use_disk and self.disk_cache:
            self.disk_cache.set(cache_key, result, ttl)
        return True

    def clear_market_cache(self) -> None:
        self._market_cache_date = None
        self._market_regime = None
        self._market_regime_details = None
        self._ntf_signals = None
        self._benchmark_data = None
        logger.info("Market-level cache cleared")

    @handle_errors(
        AnalysisError,
        ValueError,
        TypeError,
        default_return={
            "var_95": AnalysisServiceConstants.DEFAULT_VAR_95,
            "var_99": AnalysisServiceConstants.DEFAULT_VAR_99,
            "cvar_95": AnalysisServiceConstants.DEFAULT_CVAR_95,
            "cvar_99": AnalysisServiceConstants.DEFAULT_CVAR_99,
            "max_drawdown": AnalysisServiceConstants.DEFAULT_MAX_DRAWDOWN,
            "regime": "NORMAL",
            "ntf_signal": "中性",
            "summary": "宏观环境分析完成",
        },
        log_level=logging.ERROR,
    )
    def analyze_macro_health(self, mock: bool = False) -> Dict[str, Any]:
        """Calculate EVT metrics for macro health."""
        cache_key = self._generate_cache_key("macro_health", mock=mock)
        cached_result = self._get_cached_result(cache_key, use_disk=True)
        if cached_result is not None:
            return cached_result

        returns = self.get_macro_returns()
        if returns.empty:
            returns = pd.Series(
                np.random.normal(
                    0,
                    AnalysisServiceConstants.RANDOM_DATA_STD,
                    AnalysisServiceConstants.RANDOM_DATA_LENGTH,
                )
            )

        if self.evt_risk is None:
            from ...risk.evt_risk import EVTRisk
            self.evt_risk = EVTRisk()

        metrics = self.evt_risk.calculate_metrics(returns)

        default_result = {
            "var_95": AnalysisServiceConstants.DEFAULT_VAR_95,
            "var_99": AnalysisServiceConstants.DEFAULT_VAR_99,
            "cvar_95": AnalysisServiceConstants.DEFAULT_CVAR_95,
            "cvar_99": AnalysisServiceConstants.DEFAULT_CVAR_99,
            "max_drawdown": AnalysisServiceConstants.DEFAULT_MAX_DRAWDOWN,
            "regime": "NORMAL",
            "ntf_signal": "中性",
            "summary": "宏观环境分析完成",
        }

        var_95 = metrics.get("var_95")
        var_99 = metrics.get("var_99")
        if var_95 is not None and (var_95 < 0 or var_95 > 1):
            logger.warning(f"Invalid VaR 95% value: {var_95}")
            self._set_cached_result(cache_key, default_result, use_disk=True, ttl=AnalysisServiceConstants.CACHE_TTL_1HOUR)
            return default_result
        if var_99 is not None and var_95 is not None and var_99 < var_95:
            logger.warning(f"VaR 99% ({var_99}) should be greater than VaR 95% ({var_95})")
            self._set_cached_result(cache_key, default_result, use_disk=True, ttl=AnalysisServiceConstants.CACHE_TTL_1HOUR)
            return default_result

        self._set_cached_result(cache_key, metrics, use_disk=True, ttl=AnalysisServiceConstants.CACHE_TTL_1HOUR)
        return metrics

    @handle_errors(
        AnalysisError,
        DataFetchError,
        DataValidationError,
        ValueError,
        TypeError,
        default_return=pd.Series(),
        log_level=logging.ERROR,
        error_type="macro_returns_calculation",
    )
    def get_macro_returns(self, window: int = 200) -> pd.Series:
        """Fetch real returns for Macro Cockpit (HS300)."""
        end_date = datetime.datetime.now().strftime("%Y%m%d")
        start_date = (
            datetime.datetime.now() - datetime.timedelta(days=window * 2)
        ).strftime("%Y%m%d")

        if self.data_service is None:
            logger.warning("DataService not available for macro returns")
            return pd.Series()

        df = self.data_service.fetcher.fetch_index_daily(
            "sh000300", start_date, end_date
        )
        if df is None or df.empty:
            logger.warning("No data returned for HS300 index")
            return pd.Series()

        df["pct_change"] = df["close"].pct_change()
        returns = df["pct_change"].dropna()

        if returns.empty:
            logger.warning("Calculated returns series is empty")
            return pd.Series()

        return returns.tail(window)

    def run_lppl_analysis(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """Run LPPL (Log Periodic Power Law) analysis for bubble detection."""
        try:
            cache_key = self._generate_cache_key("lppl_analysis", symbol=symbol)

            if df is None:
                cached_result = self._get_cached_result(cache_key, use_disk=True)
                if cached_result is not None:
                    return cached_result

            if df is None:
                if self.data_service is None:
                    return {"error": "DataService not available", "status": "failed"}
                df = self.data_service.lake.read_data(symbol, data_type="stock", market="cn")
                if df is None or df.empty:
                    return {"error": "数据不足", "status": "failed"}

            try:
                from ...brain.lppl.engine import LPPLEngine
                lppl_engine = LPPLEngine()
                result = lppl_engine.detect_bubble(df)

                result = {
                    "symbol": symbol,
                    "status": "success",
                    "bubble_detected": result.get("is_bubble", False),
                    "confidence": result.get("confidence", 0.0),
                    "critical_time": result.get("days_to_tc", None),
                    "amplitude": result.get("amplitude", 0.0),
                    "risk_level": result.get("risk_level", "Safe"),
                    "summary": f"LPPL分析完成，风险等级: {result.get('risk_level', 'Safe')}",
                }

                self._set_cached_result(cache_key, result, use_disk=True, ttl=AnalysisServiceConstants.CACHE_TTL_2HOURS)
                return result
            except (ImportError, ModuleNotFoundError) as e:
                logger.warning(f"Failed to import LPPLEngine: {e}")
                return self._fallback_lppl_analysis(symbol, df)
            except MACRO_RECOVERABLE_ERRORS as e:
                logger.error(f"LPPL engine failed: {e}")
                return self._fallback_lppl_analysis(symbol, df)
        except MACRO_RECOVERABLE_ERRORS as e:
            logger.error(f"LPPL analysis failed for {symbol}: {e}")
            return {"error": str(e), "status": "failed"}

    def _fallback_lppl_analysis(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """Fallback LPPL analysis using basic statistics."""
        try:
            if "close" not in df.columns:
                return {
                    "symbol": symbol,
                    "status": "success",
                    "bubble_detected": False,
                    "confidence": 0.5,
                    "critical_time": None,
                    "amplitude": 0.0,
                    "summary": "数据不足，无法进行LPPL分析",
                }

            prices = df["close"]
            returns = prices.pct_change().dropna()
            volatility = returns.std() * np.sqrt(252)

            if len(prices) > IndicatorThresholds.MA_MEDIUM:
                short_ma = prices.rolling(window=IndicatorThresholds.MA_SHORT).mean().iloc[-1]
                long_ma = prices.rolling(window=IndicatorThresholds.MA_MEDIUM).mean().iloc[-1]
                trend_strength = (short_ma - long_ma) / long_ma
            else:
                trend_strength = 0.0

            bubble_detected = (
                volatility > RiskCalculationConstants.VOLATILITY_HIGH
                and abs(trend_strength) > 0.1
            )
            confidence = (
                min(abs(trend_strength) * 5, 1.0)
                if volatility > RiskCalculationConstants.VOLATILITY_MEDIUM
                else 0.5
            )

            return {
                "symbol": symbol,
                "status": "success",
                "bubble_detected": bubble_detected,
                "confidence": confidence,
                "critical_time": None,
                "amplitude": volatility,
                "summary": "使用基本统计方法进行泡沫风险分析",
            }
        except MACRO_RECOVERABLE_ERRORS as e:
            logger.error(f"Fallback LPPL analysis failed: {e}")
            return {
                "symbol": symbol,
                "status": "success",
                "bubble_detected": False,
                "confidence": 0.0,
                "critical_time": None,
                "amplitude": 0.0,
                "summary": "LPPL分析失败，使用默认结果",
            }

    def run_regime_detection(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """Run regime detection for market state analysis."""
        try:
            from ...brain.regime.regime_detector import RegimeDetector
            regime_detector = RegimeDetector()
            regime_result = regime_detector.detect(symbol)
            return {
                "symbol": symbol,
                "status": "success",
                "regime": regime_result.get("regime", "NORMAL"),
            }
        except MACRO_RECOVERABLE_ERRORS as e:
            logger.warning(f"RegimeDetector 分析失败: {e}")
            return {
                "symbol": symbol,
                "status": "failed",
                "regime": "NORMAL",
                "error": str(e),
            }

    def detect_market_regime(self, data_pack: Dict[str, Any]) -> None:
        """Detect market regime with caching."""
        try:
            today = pd.Timestamp.now().strftime("%Y-%m-%d")
            
            if self._market_cache_date == today and self._market_regime is not None:
                data_pack["regime"] = self._market_regime
                if self._market_regime_details:
                    data_pack["entropy"] = self._market_regime_details.get("entropy", 0.0)
                    data_pack["turnover_z"] = self._market_regime_details.get("turnover_z", 0.0)
                return
            
            from ...brain.regime.regime_detector import RegimeDetector

            regime_detector = RegimeDetector()
            from ...services.data_service import DataService
            data_svc = DataService()
            df = data_svc.lake.read_data(
                MarketConstants.INDEX_HS300, data_type="index", market="cn"
            )
            if df is not None and not df.empty:
                regime_result = regime_detector.get_summary(df)
            else:
                regime_result = {"regime": "NORMAL", "entropy": 0.0, "turnover_z": 0.0}
            
            self._market_regime = regime_result.get("regime", "NORMAL")
            self._market_regime_details = regime_result
            self._market_cache_date = today
            
            data_pack["regime"] = self._market_regime
            data_pack["entropy"] = regime_result.get("entropy", 0.0)
            data_pack["turnover_z"] = regime_result.get("turnover_z", 0.0)
        except MACRO_RECOVERABLE_ERRORS as e:
            logger.warning(f"RegimeDetector 分析失败: {e}")
            data_pack["regime"] = "NORMAL"

    def run_ntf_detection(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """Run NTF (National Team Fund) detection for policy intervention analysis."""
        try:
            from ...brain.ntf.ntf_engine import NTFEngine
            ntf_engine = NTFEngine()
            ntf_result = ntf_engine.detect_intervention(symbol)
            return {
                "symbol": symbol,
                "status": "success",
                "ntf_side": ntf_result.get("side", "NONE"),
                "ntf_intensity": ntf_result.get("intensity", 0.0),
            }
        except MACRO_RECOVERABLE_ERRORS as e:
            logger.warning(f"NTFEngine 分析失败: {e}")
            return {
                "symbol": symbol,
                "status": "failed",
                "ntf_side": "NONE",
                "ntf_intensity": 0.0,
                "error": str(e),
            }

    def detect_ntf_signals(self, data_pack: Dict[str, Any]) -> None:
        """Detect NTF signals with caching."""
        try:
            today = pd.Timestamp.now().strftime("%Y-%m-%d")
            
            if self._market_cache_date == today and self._ntf_signals is not None:
                data_pack["ntf_side"] = self._ntf_signals.get("side", "NONE")
                data_pack["ntf_intensity"] = self._ntf_signals.get("intensity", 0.0)
                data_pack["ntf_action"] = self._ntf_signals.get("action", "")
                return
            
            from ...brain.ntf.ntf_engine import NTFEngine
            from ...data.data_fetcher import DataFetcher
            
            fetcher = DataFetcher()
            end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
            start_date = (pd.Timestamp.now() - pd.DateOffset(days=TimeConstants.DAYS_MONTH * 3)).strftime("%Y-%m-%d")
            
            ntf_engine = NTFEngine()
            primary_etf = "510300.SH"
            ntf_result = ntf_engine.detect_intervention_from_data(
                fetcher, primary_etf, start_date, end_date
            )
            
            self._ntf_signals = ntf_result
            if self._market_cache_date != today:
                self._market_cache_date = today
            
            data_pack["ntf_side"] = ntf_result.get("side", "NONE")
            data_pack["ntf_intensity"] = ntf_result.get("intensity", 0.0)
            data_pack["ntf_action"] = ntf_result.get("action", "")
        except MACRO_RECOVERABLE_ERRORS as e:
            logger.warning(f"NTFEngine 分析失败: {e}")
            data_pack["ntf_side"] = "NONE"
            data_pack["ntf_intensity"] = 0.0
