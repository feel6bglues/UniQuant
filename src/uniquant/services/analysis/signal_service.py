"""
信号分析服务

整合 FSM/CZSC/LPPL 等引擎信号，提供统一的信号分析接口。
"""

from typing import Dict, Any
import pandas as pd
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)

SIGNAL_RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    ModuleNotFoundError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


class SignalAnalysisService:
    """信号分析服务"""

    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator

    def _get_fsm_engine(self):
        """获取 FSM 引擎"""
        from ...brain.fsm.fsm import FSM
        return FSM()

    def run_fsm_analysis(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        运行 FSM 分析

        Args:
            symbol: 股票代码
            df: OHLCV DataFrame

        Returns:
            FSM 分析结果
        """
        try:
            if df is not None and not df.empty:
                engine = self._get_fsm_engine()
                result = engine.infer_state(df)
                state = result.get("state", "UNKNOWN")
                recommendation = self._state_to_recommendation(state)
                return {
                    "symbol": symbol,
                    "status": "success",
                    "state": state,
                    "summary": result.get("state_desc", ""),
                    "recommendation": recommendation,
                }
            return self._fallback_fsm_result(symbol)
        except SIGNAL_RECOVERABLE_ERRORS as e:
            logger.warning(f"FSM 分析失败: {e}")
            return self._fallback_fsm_result(symbol)

    def _fallback_fsm_result(self, symbol: str) -> Dict[str, Any]:
        """FSM 分析失败时的降级结果"""
        return {
            "symbol": symbol,
            "status": "success",
            "state": "UNKNOWN",
            "summary": "使用基本交易逻辑进行判断",
            "recommendation": "未知",
        }

    def _state_to_recommendation(self, state) -> str:
        """将 FSM 状态转换为中文推荐"""
        mapping = {
            "IDLE": "等待",
            "SIGNAL": "买入",
            "PROBE": "买入",
            "MONITOR": "持有",
            "PYRAMID": "买入",
            "EXIT": "卖出",
            "CIRCUIT_BREAK": "卖出",
        }
        state_name = state.value if hasattr(state, "value") else str(state)
        return mapping.get(state_name, "未知")

    def run_signal_analysis(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        运行综合信号分析

        Args:
            symbol: 股票代码
            df: OHLCV DataFrame

        Returns:
            信号分析结果
        """
        try:
            signals = {}

            # FSM 信号
            try:
                fsm_result = self.run_fsm_analysis(symbol, df)
                signals["fsm"] = fsm_result
            except SIGNAL_RECOVERABLE_ERRORS as e:
                logger.debug(f"FSM 信号获取失败: {e}")
                signals["fsm"] = {"state": "UNKNOWN"}

            return {
                "symbol": symbol,
                "status": "success",
                "signals": signals,
            }
        except SIGNAL_RECOVERABLE_ERRORS as e:
            logger.warning(f"SignalAnalysisService 分析失败: {e}")
            return {
                "symbol": symbol,
                "status": "failed",
                "signals": {},
                "error": str(e),
            }

    def analyze_alpha(self, data_pack: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析 Alpha 收益

        Args:
            data_pack: 包含 stock, benchmark, sector 数据的字典
                      会在原地设置 alpha_score 字段

        Returns:
            Alpha 分析结果
        """
        try:
            from ...brain.alpha_decoupler.alpha_decoupler import AlphaDecoupler
            stock_df = data_pack.get("stock")
            bench_df = data_pack.get("benchmark")
            sector_df = data_pack.get("sector")

            if stock_df is not None:
                decoupler = AlphaDecoupler()
                score = decoupler.get_alpha_score(stock_df, bench_df, sector_df)
                data_pack["alpha_score"] = score
                return {
                    "status": "success",
                    "alpha_score": score,
                }
            data_pack["alpha_score"] = 0.0
            return {
                "status": "success",
                "alpha_score": 0.0,
            }
        except SIGNAL_RECOVERABLE_ERRORS as e:
            logger.warning(f"Alpha 分析失败: {e}")
            data_pack["alpha_score"] = 0.0
            return {
                "status": "success",
                "alpha_score": 0.0,
            }
