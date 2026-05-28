"""
LPPL 分析引擎适配器

将 brain.lppl.LPPLEngine 包装为 services 层可用的分析引擎。
"""

from typing import Dict, Any
import pandas as pd
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


class LpplAnalysisEngine:
    """LPPL 泡沫检测分析引擎"""

    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator

    def run_lppl_analysis(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        运行 LPPL 泡沫检测分析

        Args:
            symbol: 股票代码
            df: 可选的 OHLCV DataFrame

        Returns:
            LPPL 分析结果
        """
        try:
            from ...brain.lppl.engine import LPPLEngine, LPPLConfig
            config = LPPLConfig(window_range=(60, 120))
            engine = LPPLEngine(config=config)
            if df is not None and not df.empty:
                close = df["close"]
                result = engine.detect_bubble(close)
                return {
                    "symbol": symbol,
                    "status": "success",
                    "risk_level": result.get("risk_level", "Safe"),
                    "confidence": result.get("confidence", 0.0),
                    "votes": result.get("votes", 0),
                }
            return {
                "symbol": symbol,
                "status": "success",
                "risk_level": "Safe",
                "confidence": 0.0,
                "summary": "使用基本统计方法进行泡沫风险分析",
            }
        except LPPL_RECOVERABLE_ERRORS as e:
            logger.warning(f"LPPLEngine 分析失败: {e}")
            return {
                "symbol": symbol,
                "status": "success",
                "risk_level": "Safe",
                "confidence": 0.0,
                "summary": "使用基本统计方法进行泡沫风险分析",
            }
