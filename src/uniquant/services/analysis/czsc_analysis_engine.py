from typing import Dict, Any
import pandas as pd
from ...shared.logger_factory import get_logger
from ...shared.constants import AnalysisServiceConstants

logger = get_logger(__name__)

CZSC_RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    ModuleNotFoundError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

class CzscAnalysisEngine:
    """缠论(CZSC)分析引擎"""
    
    def __init__(self, orchestrator):
        """
        Args:
            orchestrator: AnalysisService instance that provides shared context
        """
        self.orchestrator = orchestrator

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
            # 生成缓存键
            cache_key = self.orchestrator._generate_cache_key("czsc_analysis", symbol=symbol)

            # 尝试从缓存获取结果
            if df is None:
                cached_result = self.orchestrator._get_cached_result(cache_key, use_disk=True)
                if cached_result is not None:
                    return cached_result

            if df is None:
                # 使用数据湖中的数据，避免网络请求
                df = self.orchestrator.data_service.lake.read_data(
                    symbol, data_type="stock", market="cn"
                )
                if df is None or df.empty:
                    return {"error": "数据不足", "status": "failed"}

            # 优化DataFrame以提高处理效率
            df = self.orchestrator._optimize_dataframe(df)

            # 对大数据集进行采样
            df = self.orchestrator._sample_data(
                df, max_rows=AnalysisServiceConstants.SAMPLE_MAX_ROWS_CZSC
            )

            # 导入并使用真实的CZSC引擎
            try:
                from ...brain.czsc.czsc_engine import CZSCEngine
                czsc_engine = CZSCEngine()

                # 运行CZSC分析 - 使用 get_czsc_signals 方法
                result = czsc_engine.get_czsc_signals(df)

                # 格式化结果
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

                # 确保精度一致性
                result = self.orchestrator.ensure_precision_consistency(result)

                # 缓存结果
                if df is None:
                    cache_key = self.orchestrator._generate_cache_key("czsc_analysis", symbol=symbol)
                    self.orchestrator._set_cached_result(
                        cache_key,
                        result,
                        use_disk=True,
                        ttl=AnalysisServiceConstants.CACHE_TTL_2HOURS,
                    )  # 2小时缓存

                return result
            except (ImportError, ModuleNotFoundError) as e:
                logger.warning(f"Failed to import CZSCEngine: {e}")
                # 降级处理：使用基本技术分析
                return self._fallback_czsc_analysis(symbol, df)
            except CZSC_RECOVERABLE_ERRORS as e:
                logger.error(f"CZSC engine failed: {e}")
                # 降级处理：使用基本技术分析
                return self._fallback_czsc_analysis(symbol, df)
        except CZSC_RECOVERABLE_ERRORS as e:
            logger.error(f"CZSC analysis failed for {symbol}: {e}")
            return {"error": str(e), "status": "failed"}

    def _fallback_czsc_analysis(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """
        降级处理：当CZSC引擎不可用时使用基本技术分析
        """
        try:
            # 检查必要列
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

            # 计算基本技术指标
            latest_data = df.iloc[-1]
            latest_close = latest_data["close"]
            latest_open = latest_data["open"]

            # 计算近期高低点
            recent_highs = (
                df["high"].tail(AnalysisServiceConstants.RECENT_HIGH_LOW_WINDOW).max()
            )
            recent_lows = (
                df["low"].tail(AnalysisServiceConstants.RECENT_HIGH_LOW_WINDOW).min()
            )

            # 简单趋势判断
            if len(df) > AnalysisServiceConstants.MA_WINDOW_MEDIUM:
                short_ma = (
                    df["close"]
                    .rolling(window=AnalysisServiceConstants.MA_WINDOW_SHORT)
                    .mean()
                    .iloc[-1]
                )
                medium_ma = (
                    df["close"]
                    .rolling(window=AnalysisServiceConstants.MA_WINDOW_MEDIUM)
                    .mean()
                    .iloc[-1]
                )
                if short_ma > medium_ma:
                    trend = "上升"
                elif short_ma < medium_ma:
                    trend = "下降"
                else:
                    trend = "震荡"
            else:
                trend = "未知"

            # 简单状态判断
            if (
                latest_close
                > latest_open * AnalysisServiceConstants.TREND_STRONG_UP_THRESHOLD
            ):
                current_state = "STRONG_BUY"
            elif latest_close > latest_open:
                current_state = "BUY"
            elif (
                latest_close
                < latest_open * AnalysisServiceConstants.TREND_STRONG_DOWN_THRESHOLD
            ):
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
        except CZSC_RECOVERABLE_ERRORS as e:
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
