"""
LPPL 分析引擎适配器

将 brain.lppl.LPPLEngine 包装为 services 层可用的分析引擎。
"""

import pandas as pd

from ...shared.interfaces import LPPLOutput
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)

LPPL_RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    ModuleNotFoundError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


def create_lppl_engine():
    """Factory: create a brain-layer LPPLEngine via the services layer."""
    from ...brain.lppl.engine import LPPLEngine

    return LPPLEngine()


def create_lppl_data_service():
    """Factory: create a data-layer LPPLDataService via the services layer."""
    from ...data.services.lppl_data_service import LPPLDataService

    return LPPLDataService()


class LpplAnalysisEngine:
    """LPPL 泡沫检测分析引擎"""

    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator

    def run_lppl_analysis(self, symbol: str, df: pd.DataFrame = None) -> LPPLOutput:
        """
        运行 LPPL 泡沫检测分析

        Args:
            symbol: 股票代码
            df: 可选的 OHLCV DataFrame

        Returns:
            LPPL 分析结果
        """
        try:
            if df is None or df.empty:
                df = self.orchestrator.data_service.lake.read_data(symbol)
                if df is None or df.empty:
                    return self._fallback_lppl_analysis(symbol, df)

            try:
                from ...brain.lppl.engine import LPPLEngine

                engine = LPPLEngine()
                result = engine.detect_bubble(df)
                price = float(df["close"].iloc[-1]) if "close" in df.columns else 0.0
                return LPPLOutput(
                    risk_level=str(result.get("risk_level", "Safe")),
                    confidence=float(result.get("confidence", 0.0)),
                    days_to_tc=result.get("days_to_tc"),
                    price=price,
                    r_squared=float(result.get("r_squared", 0.0)),
                    out_of_sample_r_squared=float(result.get("out_of_sample_r_squared", 0.0)),
                )
            except LPPL_RECOVERABLE_ERRORS as e:
                logger.warning(f"LPPLEngine 分析失败: {e}")
                return self._fallback_lppl_analysis(symbol, df)
        except LPPL_RECOVERABLE_ERRORS as e:
            logger.error(f"LPPL analysis failed for {symbol}: {e}")
            return LPPLOutput(risk_level="ENGINE_FAILED", confidence=0.0)

    def _fallback_lppl_analysis(self, symbol: str, df: pd.DataFrame) -> LPPLOutput:
        """
        降级处理：当 LPPL 引擎不可用时使用基本统计方法进行泡沫风险分析
        """
        try:
            if "close" not in df.columns:
                return LPPLOutput(risk_level="Safe", confidence=0.0)

            close = df["close"]

            if len(close) > 1:
                amplitude = (close.max() - close.min()) / close.min()
            else:
                amplitude = 0.0

            pct_changes = close.pct_change().dropna()

            if len(pct_changes) > 0:
                max_pct_change = pct_changes.max()
                bubble_detected = max_pct_change > 0.20

                recent_window = min(20, len(pct_changes))
                recent_volatility = pct_changes.tail(recent_window).std()
                confidence = (
                    min(recent_volatility * 10, 1.0)
                    if not pd.isna(recent_volatility)
                    else 0.0
                )
            else:
                bubble_detected = False
                confidence = 0.0

            risk_level = "Warning" if bubble_detected else "Safe"
            return LPPLOutput(
                risk_level=risk_level,
                confidence=round(float(confidence), 4),
                price=round(float(amplitude), 4),
            )
        except Exception as e:
            logger.error(f"Fallback LPPL analysis failed: {e}")
            return LPPLOutput(risk_level="ENGINE_FAILED", confidence=0.0)
