"""
TechnicalAnalysisService: 技术分析服务

职责：
- CZSC 缠论分析
- MA 均线状态
- ATR 止损计算
- 价格和止损计算
"""

from typing import Any, Dict, Optional

import pandas as pd

from ...shared.constants import (
    AnalysisServiceConstants,
    IndicatorThresholds,
)
from ...shared.logger_factory import get_logger

logger = get_logger("TechnicalAnalysisService")

TECHNICAL_RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    ModuleNotFoundError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


class TechnicalAnalysisService:
    """
    技术分析服务
    
    负责：
    - CZSC 缠论分析
    - MA 均线状态
    - ATR 止损计算
    """

    def __init__(
        self,
        data_service=None,
        memory_cache=None,
        disk_cache=None,
    ):
        """
        初始化技术分析服务
        
        Args:
            data_service: 数据服务实例
            memory_cache: 内存缓存
            disk_cache: 磁盘缓存
        """
        self.data_service = data_service
        self.memory_cache = memory_cache
        self.disk_cache = disk_cache

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

    def run_czsc_analysis(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Run CZSC (缠论) analysis for technical analysis

        Args:
            symbol: Stock symbol
            df: Optional DataFrame with stock data

        Returns:
            CZSC analysis results
        """
        try:
            cache_key = self._generate_cache_key("czsc_analysis", symbol=symbol)

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
                from ...brain.czsc.czsc_engine import CZSCEngine
                czsc_engine = CZSCEngine()
                result = czsc_engine.get_czsc_signals(df)

                result = {
                    "symbol": symbol,
                    "status": "success",
                    "current_state": result.get("czsc_signal", "UNKNOWN"),
                    "trend": "上升" if result.get("is_3rd_buy") else "震荡",
                    "support_level": df["low"].min() if "low" in df.columns else 0,
                    "resistance_level": df["high"].max() if "high" in df.columns else 0,
                    "bi_count": result.get("bi_count", 0),
                    "is_3rd_buy": result.get("is_3rd_buy", False),
                    "summary": f"CZSC分析完成，笔数: {result.get('bi_count', 0)}",
                }

                self._set_cached_result(cache_key, result, use_disk=True, ttl=AnalysisServiceConstants.CACHE_TTL_2HOURS)
                return result
            except (ImportError, ModuleNotFoundError) as e:
                logger.warning(f"Failed to import CZSCEngine: {e}")
                return self._fallback_czsc_analysis(symbol, df)
            except TECHNICAL_RECOVERABLE_ERRORS as e:
                logger.error(f"CZSC engine failed: {e}")
                return self._fallback_czsc_analysis(symbol, df)
        except TECHNICAL_RECOVERABLE_ERRORS as e:
            logger.error(f"CZSC analysis failed for {symbol}: {e}")
            return {"error": str(e), "status": "failed"}

    def _fallback_czsc_analysis(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Fallback CZSC analysis using basic technical analysis
        """
        try:
            required_cols = ["open", "high", "low", "close"]
            for col in required_cols:
                if col not in df.columns:
                    return {
                        "symbol": symbol,
                        "status": "success",
                        "current_state": "UNKNOWN",
                        "trend": "未知",
                        "support_level": 0.0,
                        "resistance_level": 0.0,
                        "summary": "数据不足，无法进行CZSC分析",
                    }

            latest_data = df.iloc[-1]
            latest_close = latest_data["close"]
            latest_open = latest_data["open"]

            recent_highs = df["high"].tail(AnalysisServiceConstants.RECENT_HIGH_LOW_WINDOW).max()
            recent_lows = df["low"].tail(AnalysisServiceConstants.RECENT_HIGH_LOW_WINDOW).min()

            if len(df) > AnalysisServiceConstants.MA_WINDOW_MEDIUM:
                short_ma = df["close"].rolling(window=AnalysisServiceConstants.MA_WINDOW_SHORT).mean().iloc[-1]
                medium_ma = df["close"].rolling(window=AnalysisServiceConstants.MA_WINDOW_MEDIUM).mean().iloc[-1]
                if short_ma > medium_ma:
                    trend = "上升"
                elif short_ma < medium_ma:
                    trend = "下降"
                else:
                    trend = "震荡"
            else:
                trend = "未知"

            if latest_close > latest_open * AnalysisServiceConstants.TREND_STRONG_UP_THRESHOLD:
                current_state = "STRONG_BUY"
            elif latest_close > latest_open:
                current_state = "BUY"
            elif latest_close < latest_open * AnalysisServiceConstants.TREND_STRONG_DOWN_THRESHOLD:
                current_state = "STRONG_SELL"
            elif latest_close < latest_open:
                current_state = "SELL"
            else:
                current_state = "NEUTRAL"

            return {
                "symbol": symbol,
                "status": "success",
                "current_state": current_state,
                "trend": trend,
                "support_level": recent_lows,
                "resistance_level": recent_highs,
                "summary": "使用基本技术分析方法进行判断",
            }
        except TECHNICAL_RECOVERABLE_ERRORS as e:
            logger.error(f"Fallback CZSC analysis failed: {e}")
            return {
                "symbol": symbol,
                "status": "success",
                "current_state": "UNKNOWN",
                "trend": "未知",
                "support_level": 0.0,
                "resistance_level": 0.0,
                "summary": "CZSC分析失败，使用默认结果",
            }

    def detect_czsc_signals(self, ticker: str, data_pack: Dict[str, Any]) -> None:
        """Detect CZSC signals for data pack."""
        try:
            from ...brain.czsc.czsc_engine import CZSCEngine
            czsc_engine = CZSCEngine()
            czsc_result = czsc_engine.update_and_get_signals(ticker)
            data_pack["is_3rd_buy"] = czsc_result.get("is_3rd_buy", False)
            data_pack["bi_count"] = czsc_result.get("bi_count", 0)
        except TECHNICAL_RECOVERABLE_ERRORS as e:
            logger.warning(f"CZSCEngine 分析失败: {e}")
            data_pack["is_3rd_buy"] = False
            data_pack["bi_count"] = 0

    def calculate_ma_status(self, data_pack: Dict[str, Any]) -> None:
        """Calculate MA status for data pack."""
        try:
            from ...brain.indicators.indicators import Indicators
            indicators = Indicators()
            ma_short = indicators.calc_ma(data_pack["stock"], window=IndicatorThresholds.MA_SHORT)
            ma_long = indicators.calc_ma(data_pack["stock"], window=IndicatorThresholds.MA_MEDIUM)
            if not ma_short.empty and not ma_long.empty:
                if ma_short.iloc[-1] > ma_long.iloc[-1]:
                    data_pack["ma_status"] = "MA20 > MA60"
                else:
                    data_pack["ma_status"] = "MA20 <= MA60"
            else:
                data_pack["ma_status"] = "DATA_INSUFFICIENT"
        except TECHNICAL_RECOVERABLE_ERRORS as e:
            logger.warning(f"MA 状态计算失败: {e}")
            data_pack["ma_status"] = "DATA_INSUFFICIENT"

    def calculate_price_and_stop(self, data_pack: Dict[str, Any]) -> None:
        """Calculate price and stop loss for data pack."""
        try:
            data_pack["price"] = data_pack["stock"].iloc[-1]["close"]
            from ...brain.indicators.indicators import Indicators
            indicators = Indicators()
            atr = indicators.calc_atr(data_pack["stock"])
            if not atr.empty:
                data_pack["atr_stop"] = data_pack["price"] - atr.iloc[-1] * 2
            else:
                data_pack["atr_stop"] = data_pack["price"] * 0.95
        except TECHNICAL_RECOVERABLE_ERRORS as e:
            logger.warning(f"价格和止损计算失败: {e}")
            data_pack["price"] = 0
            data_pack["atr_stop"] = 0
