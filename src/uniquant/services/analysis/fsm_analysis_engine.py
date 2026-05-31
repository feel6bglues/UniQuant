from typing import Dict, Any
import pandas as pd
from ...shared.logger_factory import get_logger
from ...shared.constants import AnalysisServiceConstants

logger = get_logger(__name__)

FSM_RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    ModuleNotFoundError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

class FsmAnalysisEngine:
    """有限状态机(FSM)分析引擎"""
    
    def __init__(self, orchestrator):
        """
        Args:
            orchestrator: AnalysisService instance that provides shared context
        """
        self.orchestrator = orchestrator

    def run_fsm_analysis(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Run FSM (Finite State Machine) analysis for trading logic

        Args:
            symbol: Stock symbol
            df: Optional DataFrame with stock data

        Returns:
            FSM analysis results
        """
        try:
            # 生成缓存键
            cache_key = self.orchestrator._generate_cache_key("fsm_analysis", symbol=symbol)

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
                df, max_rows=AnalysisServiceConstants.SAMPLE_MAX_ROWS_FSM
            )

            # 导入并使用真实的FSM引擎
            try:
                # 使用现有的brain实例或延迟导入创建
                if hasattr(self.orchestrator, "brain") and self.orchestrator.brain is not None:
                    fsm_engine = self.orchestrator.brain
                else:
                    from ...brain.fsm import DecisionBrain

                    # 确保evt_risk和sizer已初始化
                    if self.orchestrator.evt_risk is None:
                        from ...risk.evt_risk import EVTRisk
                        self.orchestrator.evt_risk = EVTRisk()
                    if self.orchestrator.sizer is None:
                        from ...risk.sizer import PositionSizer
                        self.orchestrator.sizer = PositionSizer()

                    fsm_engine = DecisionBrain(evt_risk=self.orchestrator.evt_risk, sizer=self.orchestrator.sizer)

                # 准备数据包
                data_pack = {
                    "stock": df,
                    "bench": None,  # 暂时使用None，实际应用中应提供基准数据
                    "sector": None,  # 暂时使用None，实际应用中应提供行业数据
                    "etf": None,  # 暂时使用None，实际应用中应提供ETF数据
                }

                # 运行FSM分析
                result = fsm_engine.make_decision(data_pack)

                # 计算止损和止盈价格
                latest_close = df.iloc[-1]["close"]
                stop_loss = (
                    latest_close * AnalysisServiceConstants.STOP_LOSS_RATIO
                )  # 默认止损
                take_profit = (
                    latest_close * AnalysisServiceConstants.TAKE_PROFIT_RATIO
                )  # 默认止盈

                # 格式化结果
                result = {
                    "symbol": symbol,
                    "status": "success",
                    "current_state": result.get("decision", "UNKNOWN"),
                    "signal_strength": result.get("score", 0.0)
                    / AnalysisServiceConstants.SIGNAL_STRENGTH_SCALE,
                    "recommendation": self._map_decision_to_recommendation(
                        result.get("decision", "UNKNOWN")
                    ),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "summary": result.get("summary", "FSM分析完成"),
                }

                # 确保精度一致性
                result = self.orchestrator.ensure_precision_consistency(result)

                # 缓存结果
                if df is None:
                    cache_key = self.orchestrator._generate_cache_key("fsm_analysis", symbol=symbol)
                    self.orchestrator._set_cached_result(
                        cache_key,
                        result,
                        use_disk=True,
                        ttl=AnalysisServiceConstants.CACHE_TTL_2HOURS,
                    )  # 2小时缓存

                return result
            except (ImportError, ModuleNotFoundError) as e:
                logger.warning(f"Failed to import FSM engine: {e}")
                # 降级处理：使用基本交易逻辑
                return self._fallback_fsm_analysis(symbol, df)
            except FSM_RECOVERABLE_ERRORS as e:
                logger.error(f"FSM engine failed: {e}")
                # 降级处理：使用基本交易逻辑
                return self._fallback_fsm_analysis(symbol, df)
        except FSM_RECOVERABLE_ERRORS as e:
            logger.error(f"FSM analysis failed for {symbol}: {e}")
            return {"error": str(e), "status": "failed"}

    def _map_decision_to_recommendation(self, decision: str) -> str:
        """
        将FSM决策映射为推荐操作
        """
        return AnalysisServiceConstants.RECOMMENDATION_MAP.get(decision, "未知")

    def _fallback_fsm_analysis(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """
        降级处理：当FSM引擎不可用时使用基本交易逻辑
        """
        try:
            if "close" not in df.columns:
                return {
                    "symbol": symbol,
                    "status": "success",
                    "current_state": "UNKNOWN",
                    "signal_strength": 0.0,
                    "recommendation": "未知",
                    "stop_loss": 0.0,
                    "take_profit": 0.0,
                    "summary": "数据不足，无法进行FSM分析",
                }

            # 计算基本指标
            latest_close = df.iloc[-1]["close"]

            # 计算移动平均线
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
                long_ma = (
                    df["close"]
                    .rolling(window=AnalysisServiceConstants.MA_WINDOW_LONG)
                    .mean()
                    .iloc[-1]
                )

                # 基于均线关系判断状态
                if short_ma > medium_ma > long_ma:
                    current_state = AnalysisServiceConstants.SIGNAL_BUY
                    recommendation = AnalysisServiceConstants.RECOMMENDATION_MAP.get(
                        AnalysisServiceConstants.SIGNAL_BUY
                    )
                    signal_strength = 0.8
                elif short_ma < medium_ma < long_ma:
                    current_state = AnalysisServiceConstants.SIGNAL_SELL
                    recommendation = AnalysisServiceConstants.RECOMMENDATION_MAP.get(
                        AnalysisServiceConstants.SIGNAL_SELL
                    )
                    signal_strength = 0.8
                elif medium_ma > long_ma:
                    current_state = "hold"
                    recommendation = "持有"
                    signal_strength = 0.5
                else:
                    current_state = "wait"
                    recommendation = "等待"
                    signal_strength = 0.3
            else:
                current_state = "UNKNOWN"
                recommendation = "未知"
                signal_strength = 0.0

            # 计算止损和止盈价格
            stop_loss = (
                latest_close * AnalysisServiceConstants.STOP_LOSS_RATIO
            )  # 默认止损
            take_profit = (
                latest_close * AnalysisServiceConstants.TAKE_PROFIT_RATIO
            )  # 默认止盈

            return {
                "symbol": symbol,
                "status": "success",
                "current_state": current_state,
                "signal_strength": signal_strength,
                "recommendation": recommendation,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "summary": "使用基本交易逻辑进行判断",
            }
        except FSM_RECOVERABLE_ERRORS as e:
            logger.error(f"Fallback FSM analysis failed: {e}")
            return {
                "symbol": symbol,
                "status": "success",
                "current_state": "UNKNOWN",
                "signal_strength": 0.0,
                "recommendation": "未知",
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "summary": "FSM分析失败，使用默认结果",
            }
