from enum import Enum
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

import pandas as pd

from filelock import FileLock

from ...shared.config_loader import get_config
from ...shared.constants import IndicatorThresholds
from ...shared.error_handling import handle_errors
from ...shared.exceptions import AnalysisError
from ...shared.time_provider import get_time_provider
from ...shared.interfaces import MarketSignalContext, PositionSizerProtocol, RiskAssessmentProtocol
from ...shared.limit_checker import check_limit_status
from ...shared.logger_factory import get_logger
try:
    from ..indicators.indicators import Indicators
except ImportError:
    Indicators = None  # TODO: Phase 1A 迁移 brain/indicators.py 后移除

logger = get_logger(__name__)


class FSMState(Enum):
    IDLE = "IDLE"
    SIGNAL = "SIGNAL"
    PROBE = "PROBE"
    MONITOR = "MONITOR"
    PYRAMID = "PYRAMID"
    EXIT = "EXIT"
    CIRCUIT_BREAK = "CIRCUIT_BREAK"


class InvalidInputError(ValueError):
    pass


class StateTransitionError(AnalysisError):
    """状态转换错误"""


class FSM:
    """
    FSM: 状态机模块
    用于判断当前市场状态，支持盘中和盘后模式
    """

    _REQUIRED_COLUMNS = frozenset({"close", "high", "low", "open"})

    def __init__(
        self,
        ma_short: int = IndicatorThresholds.FSM_MA_SHORT,
        ma_long: int = IndicatorThresholds.FSM_MA_LONG,
        is_intraday: bool = False,
    ):
        """
        Initialize FSM with MA parameters.

        Args:
            ma_short: Short MA period
            ma_long: Long MA period
            is_intraday: Whether running in intraday mode (default False)
                         In intraday mode, uses previous close for MA calculation
                         to avoid look-ahead bias
        """
        if ma_short <= 0 or ma_long <= 0:
            raise ValueError("MA windows must be positive integers")
        if ma_short >= ma_long:
            raise ValueError("ma_short must be less than ma_long")
        self.ma_short = ma_short
        self.ma_long = ma_long
        self.is_intraday = is_intraday
        self.state_descriptions = {
            FSMState.IDLE: "市场处于横盘或下行趋势，尚未出现明确的买入信号",
            FSMState.SIGNAL: f"股价突破MA{ma_long}，发出买入信号",
            FSMState.PROBE: f"股价突破MA{ma_long}后，缩量回踩MA{ma_short}且未跌破，处于试盘/回踩阶段",
            FSMState.MONITOR: f"股价处于明确的上升趋势，MA{ma_short} > MA{ma_long}，适合持有和监控",
            FSMState.PYRAMID: "股价持续上涨，可以考虑加仓",
            FSMState.EXIT: "股价跌破关键均线，应考虑平仓",
            FSMState.CIRCUIT_BREAK: "市场出现极端波动，触发熔断机制",
        }

    def _validate_input(self, df: pd.DataFrame) -> None:
        if df is None:
            raise InvalidInputError("Input DataFrame is None")
        if df.empty:
            raise InvalidInputError("Input DataFrame is empty")
        missing_cols = self._REQUIRED_COLUMNS - set(df.columns)
        if missing_cols:
            raise InvalidInputError(f"Missing required columns: {missing_cols}")

    def infer_state(self, df: pd.DataFrame) -> Dict[str, Any]:
        self._validate_input(df)

        # Look-ahead Bias 修复: 盘中模式使用前一日数据
        if self.is_intraday:
            # 盘中模式：排除当前未确定的K线，使用历史数据计算MA
            analysis_df = df.iloc[:-1].copy() if len(df) > 1 else df.copy()
            current_price = df["close"].iloc[-1]  # 当前实时价格
        else:
            # 盘后模式：使用全部数据
            analysis_df = df.copy()
            current_price = df["close"].iloc[-1]

        if len(analysis_df) < self.ma_long:
            return self._build_state_result(FSMState.IDLE, "数据不足，无法进行完整分析")

        # Calculate indicators using analysis data
        if Indicators is None:
            raise ImportError("Indicators module not available")
        shifted_df = analysis_df.shift(1) if len(analysis_df) > 1 else analysis_df
        ma20 = Indicators.calc_ma(shifted_df, self.ma_short)
        ma60 = Indicators.calc_ma(shifted_df, self.ma_long)

        prev_price = analysis_df["close"].iloc[-1]

        curr_ma20 = ma20.iloc[-1]
        curr_ma60 = ma60.iloc[-1]
        prev_ma60 = ma60.iloc[-2] if len(ma60) > 1 else curr_ma60

        # Check if we have a clear trend (MA20 > MA60)
        has_upward_trend = curr_ma20 > curr_ma60
        ma_status = "MA20 > MA60" if has_upward_trend else "MA20 <= MA60"

        # Logic for state transition (Enhanced for V8.0)
        transition_reason = ""

        # Check for SIGNAL state
        if current_price > curr_ma60 and prev_price <= prev_ma60:
            transition_reason = f"股价突破MA60，当前价格: {round(current_price, 2)}，MA60: {round(curr_ma60, 2)}"
            return self._build_state_result(
                FSMState.SIGNAL, transition_reason, ma_status
            )

        # Check for PROBE state
        if current_price > curr_ma60 and has_upward_trend:
            # Pullback to MA20
            pullback_to_ma20 = (
                current_price <= curr_ma20 * IndicatorThresholds.FSM_PULLBACK_UPPER
                and current_price >= curr_ma20 * IndicatorThresholds.FSM_PULLBACK_LOWER
            )
            if pullback_to_ma20:
                transition_reason = f"股价突破MA60后缩量回踩MA20，当前价格: {round(current_price, 2)}，MA20: {round(curr_ma20, 2)}"
                return self._build_state_result(
                    FSMState.PROBE, transition_reason, ma_status
                )

            # Check for MONITOR state
            transition_reason = (
                f"股价处于明确上升趋势，MA20 > MA60，当前价格: {round(current_price, 2)}"
            )
            return self._build_state_result(
                FSMState.MONITOR, transition_reason, ma_status
            )

        # Default to IDLE
        transition_reason = f"股价未突破MA60或趋势不明确，当前价格: {round(current_price, 2)}，MA60: {round(curr_ma60, 2)}"
        return self._build_state_result(FSMState.IDLE, transition_reason, ma_status)

    def _build_state_result(
        self, state: FSMState, reason: str, ma_status: str = "N/A"
    ) -> Dict[str, Any]:
        """
        Build the state result dictionary.
        """
        return {
            "state": state,
            "state_name": state.value,
            "state_desc": self.state_descriptions[state],
            "transition_reason": reason,
            "ma_status": ma_status,
            "fsm_state": state.value,
        }


class DecisionBrain:
    """
    DecisionBrain: 总控执行模块
    采用"Veto-Scoring"（否决-加权）架构
    整合各个引擎的信号，做出最终的买卖决策
    
    支持状态持久化机制，可在程序重启后恢复状态。
    """

    _STATE_FILE_NAME = "fsm_state.json"

    def __init__(
        self,
        evt_risk: Optional[RiskAssessmentProtocol] = None,
        sizer: Optional[PositionSizerProtocol] = None,
        persist_state: bool = True,
        state_file: Optional[str] = None,
        data_service: Any = None,
    ):
        """
        Initialize DecisionBrain.

        Args:
            evt_risk: Risk assessment instance (optional, auto-created if None)
            sizer: Position sizer instance (optional, auto-created if None)
            persist_state: Whether to persist state to disk (default True)
            state_file: Custom path for state file (optional)
        """
        self.state = FSMState.IDLE
        self._previous_state = FSMState.IDLE
        self._persist_state = persist_state
        self._state_file = state_file

        if evt_risk is None:
            from ...risk.evt_risk import HistoricalSimulationRisk
            evt_risk = HistoricalSimulationRisk()
            logger.debug("DecisionBrain: Using default HistoricalSimulationRisk instance")
        
        if sizer is None:
            from ...risk.sizer import PositionSizer
            sizer = PositionSizer()
            logger.debug("DecisionBrain: Using default PositionSizer instance")

        self.evt_risk = evt_risk
        self.sizer = sizer

        self._state_history: list = []
        
        if self._persist_state:
            self._load_state()

    def _build_response(
        self,
        action: str,
        reason: str,
        ctx: MarketSignalContext,
        score: int = 0,
        **kwargs,
    ) -> Dict[str, Any]:
        """构建标准响应字典"""
        response = {
            "action": action,
            "reason": reason,
            "regime": ctx.regime.value,
            "risk": ctx.risk,
            "bubble_confidence": ctx.bubble_confidence,
            "ntf_side": ctx.ntf_side.value,
            "ntf_intensity": ctx.ntf_intensity,
            "is_3rd_buy": ctx.is_3rd_buy,
            "bi_count": ctx.bi_count,
            "alpha_score": ctx.alpha_score,
            "final_decision": action,
            "final_score": score,
            "engine_status": ctx.engine_status,
            "engine_errors": ctx.engine_errors,
        }
        response.update(kwargs)
        return response

    @staticmethod
    def _risk_engine_blockers(ctx: MarketSignalContext) -> list[str]:
        """Return blockers for unavailable critical risk engines."""
        blockers: list[str] = []
        failed_statuses = {"ENGINE_FAILED", "DATA_UNAVAILABLE", "UNKNOWN", "FAILED"}
        critical_engines = {"regime", "lppl", "macro"}

        if ctx.regime.value == "UNKNOWN":
            blockers.append("REGIME_UNKNOWN")

        if str(ctx.risk).upper() in failed_statuses:
            blockers.append("RISK_ENGINE_FAILED")

        for engine, status in ctx.engine_status.items():
            if engine in critical_engines and str(status).upper() in failed_statuses:
                if engine == "regime" and "REGIME_UNKNOWN" not in blockers:
                    blockers.append("REGIME_UNKNOWN")
                elif engine in {"lppl", "macro"} and "RISK_ENGINE_FAILED" not in blockers:
                    blockers.append("RISK_ENGINE_FAILED")

        return blockers

    @staticmethod
    def _stop_loss_blockers(ctx: MarketSignalContext) -> list[str]:
        """Return passive risk blockers for missing or non-survivable stops."""
        if ctx.price <= 0:
            return ["PRICE_MISSING"]
        if ctx.atr_stop <= 0:
            return ["STOP_LOSS_MISSING"]
        if ctx.atr_stop >= ctx.price:
            return ["STOP_LOSS_INVALID"]

        max_stop_loss_pct = get_config().get("brain.fsm.max_stop_loss_pct", 0.15)
        loss_pct = (ctx.price - ctx.atr_stop) / ctx.price
        if loss_pct > max_stop_loss_pct:
            return ["STOP_LOSS_TOO_WIDE"]
        return []

    def _check_veto_conditions(self, ctx: MarketSignalContext) -> Optional[Dict[str, Any]]:
        """检查否决条件，返回则表示被否决"""
        if ctx.regime.value == "FROZEN":
            return self._build_response(
                "FORCE_WAIT", "市场处于冻结状态", ctx, final_decision="FORCE_WAIT"
            )
        risk_blockers = self._risk_engine_blockers(ctx)
        if risk_blockers:
            return self._build_response(
                "FORCE_WAIT",
                f"关键风险引擎不可用: {', '.join(risk_blockers)}",
                ctx,
                final_decision="FORCE_WAIT",
                buy_blockers=risk_blockers,
            )
        if ctx.risk == "Danger" and ctx.ntf_side.value != "SUPPORT":
            return self._build_response(
                "FORCE_EXIT", "宏观风险较高且政策面不支持", ctx, final_decision="FORCE_EXIT"
            )
        return None

    def _calculate_score(self, ctx: MarketSignalContext) -> int:
        """计算综合得分"""
        score = 0
        if ctx.is_3rd_buy:
            score += IndicatorThresholds.FSM_SCORE_CZSC
        if ctx.ma_status == f"MA{IndicatorThresholds.FSM_MA_SHORT} > MA{IndicatorThresholds.FSM_MA_LONG}":
            score += IndicatorThresholds.FSM_SCORE_TREND
        if ctx.alpha_score > IndicatorThresholds.FSM_ALPHA_THRESHOLD:
            score += IndicatorThresholds.FSM_SCORE_ALPHA
        if ctx.ntf_side.value == "SUPPORT":
            score += IndicatorThresholds.FSM_SCORE_NTF
        return score

    def _check_sell_conditions(
        self, ctx: MarketSignalContext, score: int
    ) -> Optional[Dict[str, Any]]:
        """检查卖出条件"""
        sell_conditions = []
        
        if ctx.risk == "Danger":
            sell_conditions.append("LPPL_DANGER")
        if ctx.ma_status == f"MA{IndicatorThresholds.FSM_MA_SHORT} <= MA{IndicatorThresholds.FSM_MA_LONG}":
            sell_conditions.append("MA_REVERSAL")
        sell_threshold = get_config().get("brain.fsm.sell_threshold", -0.5)
        if ctx.alpha_score < sell_threshold:
            sell_conditions.append("ALPHA_WEAK")
        if ctx.regime.value in ["FROZEN", "STRESSED"]:
            sell_conditions.append("REGIME_RISK")
        
        sell_limit_blocked = False
        if ctx.price > 0 and ctx.pre_close > 0:
            limit_status = check_limit_status(ctx.price, ctx.pre_close, ctx.symbol, ctx.name)
            if limit_status.is_limit_down:
                sell_conditions.append("LIMIT_DOWN")
                sell_limit_blocked = True
        
        if sell_conditions:
            self.state = FSMState.EXIT
            action = "HOLD" if sell_limit_blocked else "SELL"
            reason_suffix = " (跌停无法卖出)" if sell_limit_blocked else ""
            return self._build_response(
                action,
                f"触发卖出条件: {', '.join(sell_conditions)}, 综合得分: {score}{reason_suffix}",
                ctx,
                score,
                state=FSMState.EXIT.value,
                sell_triggers=sell_conditions,
                sell_limit_blocked=sell_limit_blocked,
            )
        return None

    def _determine_target_state(self, score: int, is_3rd_buy: bool) -> FSMState:
        """根据得分确定目标状态"""
        if self.state == FSMState.IDLE:
            if score >= IndicatorThresholds.FSM_SCORE_THRESHOLD_IDLE_TO_SIGNAL:
                return FSMState.PROBE if is_3rd_buy else FSMState.SIGNAL
        elif self.state in [FSMState.SIGNAL, FSMState.PROBE]:
            if score >= IndicatorThresholds.FSM_SCORE_THRESHOLD_SIGNAL_TO_MONITOR:
                return FSMState.MONITOR
            if score < IndicatorThresholds.FSM_SCORE_THRESHOLD_TO_EXIT:
                return FSMState.IDLE
        elif self.state == FSMState.MONITOR:
            if score >= IndicatorThresholds.FSM_SCORE_THRESHOLD_TO_PYRAMID:
                return FSMState.PYRAMID
            if score < IndicatorThresholds.FSM_SCORE_THRESHOLD_EXIT:
                return FSMState.EXIT
        return self.state

    def _check_buy_blockers(
        self, ctx: MarketSignalContext, score: int
    ) -> Optional[Dict[str, Any]]:
        """检查买入阻断条件"""
        buy_blockers = []
        
        if ctx.risk == "Danger":
            buy_blockers.append("LPPL_DANGER")
        if ctx.regime.value == "FROZEN":
            buy_blockers.append("MARKET_FROZEN")
        buy_blockers.extend(self._risk_engine_blockers(ctx))
        buy_blockers.extend(self._stop_loss_blockers(ctx))
        buy_block_threshold = get_config().get("brain.fsm.buy_block_threshold", -0.3)
        if ctx.alpha_score < buy_block_threshold:
            buy_blockers.append("ALPHA_TOO_WEAK")
        
        if ctx.price > 0 and ctx.pre_close > 0:
            limit_status = check_limit_status(ctx.price, ctx.pre_close, ctx.symbol, ctx.name)
            if limit_status.is_limit_up:
                buy_blockers.append("LIMIT_UP")
            if limit_status.is_limit_down:
                buy_blockers.append("LIMIT_DOWN_SELL_BLOCKED")
        
        if buy_blockers:
            return self._build_response(
                "HOLD",
                f"买入被阻断: {', '.join(buy_blockers)}",
                ctx,
                score,
                state=self.state.value,
                buy_blockers=buy_blockers,
            )
        return None

    def _execute_buy(
        self, ctx: MarketSignalContext, score: int
    ) -> Dict[str, Any]:
        """执行买入逻辑"""
        if ctx.returns is not None and not ctx.returns.empty:
            evt_metrics = self.evt_risk.calculate_metrics(ctx.returns)
            risk_level_map = {"CRISIS": "CRITICAL", "HIGH_VOL": "HIGH", "BEAR": "WARNING", "BULL": "LOW", "NORMAL": "LOW"}
            raw_risk = evt_metrics.get("regime", "NORMAL")
            risk_level = risk_level_map.get(raw_risk, "LOW")
            risk_scaler = (
                IndicatorThresholds.FSM_RISK_SCALER_CRITICAL
                if risk_level == "CRITICAL"
                else 1.0
            )
            position_plan = self.sizer.calculate_shares(
                price=ctx.price,
                stop_loss=ctx.atr_stop,
                czsc_bottom=ctx.czsc_bottom,
                market=ctx.market,
                symbol=ctx.symbol,
            )
            final_shares = int(position_plan["建议仓位"] * risk_scaler)
            action = "BUY" if self.state != FSMState.PYRAMID else "ADD"
            return self._build_response(
                action,
                f"状态: {self.state.value}, 综合得分: {score}, 风险等级: {risk_level}",
                ctx,
                score,
                shares=final_shares,
                state=self.state.value,
                position_details=position_plan,
            )
        return self._build_response(
            "BUY",
            f"状态: {self.state.value}, 综合得分: {score}, 但缺少计算仓位所需数据",
            ctx,
            score,
            state=self.state.value,
        )

    @handle_errors(
        ValueError, TypeError, Exception, default_return=False, log_level=logging.ERROR
    )
    def _validate_state_transition(
        self, from_state: FSMState, to_state: FSMState
    ) -> bool:
        """
        验证状态转换是否合法

        Args:
            from_state: 当前状态
            to_state: 目标状态

        Returns:
            bool: 转换是否合法
        """
        # 定义合法的状态转换
        _CB = FSMState.CIRCUIT_BREAK
        valid_transitions = {
            FSMState.IDLE: [FSMState.SIGNAL, FSMState.PROBE, _CB],
            FSMState.SIGNAL: [FSMState.PROBE, FSMState.IDLE, _CB],
            FSMState.PROBE: [
                FSMState.MONITOR, FSMState.IDLE, FSMState.EXIT, _CB,
            ],
            FSMState.MONITOR: [
                FSMState.PYRAMID, FSMState.EXIT, FSMState.IDLE, _CB,
            ],
            FSMState.PYRAMID: [FSMState.MONITOR, FSMState.EXIT, _CB],
            FSMState.EXIT: [FSMState.IDLE, _CB],
            FSMState.CIRCUIT_BREAK: [FSMState.IDLE],
        }

        allowed = valid_transitions.get(from_state, [])
        return to_state in allowed or from_state == to_state

    def _record_state_change(
        self, from_state: FSMState, to_state: FSMState, reason: str
    ):
        """
        记录状态变更历史

        Args:
            from_state: 原状态
            to_state: 新状态
            reason: 变更原因
        """
        import time

        from_state_value = (
            from_state.value if isinstance(from_state, FSMState) else str(from_state)
        )
        to_state_value = (
            to_state.value if isinstance(to_state, FSMState) else str(to_state)
        )

        self._state_history.append(
            {
                "timestamp": time.time(),
                "from": from_state_value,
                "to": to_state_value,
                "reason": reason,
            }
        )
        logger.info(f"状态变更: {from_state_value} -> {to_state_value}, 原因: {reason}")
        
        self._save_state()

    def _rollback_state(self):
        """回滚到上一个状态"""
        if self._previous_state:
            from_val = (
                self.state.value
                if isinstance(self.state, FSMState)
                else str(self.state)
            )
            to_val = (
                self._previous_state.value
                if isinstance(self._previous_state, FSMState)
                else str(self._previous_state)
            )
            logger.warning(f"状态回滚: {from_val} -> {to_val}")
            self.state = self._previous_state

    @handle_errors(
        AnalysisError,
        Exception,
        default_return={"action": "ERROR", "reason": "决策执行失败"},
        log_level=logging.ERROR,
    )
    def make_decision(
        self, data_packet: Union[dict, MarketSignalContext]
    ) -> Dict[str, Any]:
        """
        做出决策

        参数:
        data_packet: 包含各个引擎信号的数据包 (支持 dict 或 MarketSignalContext 类型)

        返回:
        Dict[str, Any]: 决策结果，包含动作、仓位等详细信息
        """
        if isinstance(data_packet, MarketSignalContext):
            ctx = data_packet
        else:
            ctx = MarketSignalContext.from_dict(data_packet)

        # 跨股票状态重置：检测 symbol 变化时重置 FSM 状态
        if hasattr(self, '_last_symbol') and self._last_symbol != ctx.symbol:
            logger.info(f"检测到股票切换 {self._last_symbol} -> {ctx.symbol}，重置 FSM 状态")
            self.state = FSMState.IDLE
        self._last_symbol = ctx.symbol

        self._previous_state = self.state

        try:
            veto_result = self._check_veto_conditions(ctx)
            if veto_result:
                return veto_result

            # B-007: 熔断检查 — 当日跌幅超过阈值时触发 CIRCUIT_BREAK
            if ctx.price > 0 and ctx.pre_close > 0:
                daily_return = (
                    (ctx.price - ctx.pre_close) / ctx.pre_close
                )
                cb_thresh = get_config().get(
                    "brain.fsm.circuit_break_threshold", -0.05
                )
                if daily_return < cb_thresh:
                    if self.state != FSMState.CIRCUIT_BREAK:
                        self.state = FSMState.CIRCUIT_BREAK
                        self._record_state_change(
                            self._previous_state,
                            FSMState.CIRCUIT_BREAK,
                            f"当日跌幅 {daily_return:.2%} "
                            f"超过熔断阈值 {cb_thresh:.2%}",
                        )
                    return self._build_response(
                        "CIRCUIT_BREAK",
                        f"触发熔断: 当日跌幅 {daily_return:.2%} "
                        f"超过阈值 {cb_thresh:.2%}",
                        ctx,
                        final_decision="CIRCUIT_BREAK",
                        state=FSMState.CIRCUIT_BREAK.value,
                        daily_return=daily_return,
                    )
                elif self.state == FSMState.CIRCUIT_BREAK:
                    # 冷却恢复: 跌幅回到阈值内，恢复到 IDLE
                    self.state = FSMState.IDLE
                    self._record_state_change(
                        FSMState.CIRCUIT_BREAK,
                        FSMState.IDLE,
                        f"熔断恢复: 当日跌幅 {daily_return:.2%} "
                        f"已回到阈值内",
                    )

            score = self._calculate_score(ctx)

            sell_result = self._check_sell_conditions(ctx, score)
            if sell_result:
                return sell_result

            target_state = self._determine_target_state(score, ctx.is_3rd_buy)

            if target_state != self.state:
                if not self._validate_state_transition(self.state, target_state):
                    raise StateTransitionError(
                        f"非法状态转换: {self.state.value} -> {target_state.value}"
                    )
                self.state = target_state
                self._record_state_change(
                    self._previous_state, target_state, f"综合得分 {score}"
                )

            if self.state in [FSMState.PROBE, FSMState.SIGNAL, FSMState.PYRAMID]:
                blocker_result = self._check_buy_blockers(ctx, score)
                if blocker_result:
                    return blocker_result
                return self._execute_buy(ctx, score)

            if self.state == FSMState.EXIT:
                self.state = FSMState.IDLE
                return self._build_response(
                    "SELL",
                    f"综合得分: {score}, 趋势转弱或形态走坏",
                    ctx,
                    score,
                    state=FSMState.EXIT.value,
                )

            return self._build_response(
                "STAY_CURRENT_STATE",
                f"综合得分: {score}, 维持当前状态",
                ctx,
                score,
                state=self.state.value,
            )

        except Exception as e:
            self._rollback_state()
            logger.error(f"决策执行失败，状态已回滚: {e}")
            raise

    def reset_state(self):
        """
        重置状态并清除持久化文件
        """
        self._previous_state = self.state
        self.state = FSMState.IDLE
        self._state_history = []
        self._clear_state()
        logger.info("FSM状态已重置为 IDLE")

    def get_state(self):
        """
        获取当前状态

        返回:
        str: 当前状态
        """
        return self.state

    def get_state_history(self) -> list:
        """
        获取状态变更历史

        返回:
            list: 状态变更历史记录
        """
        return self._state_history.copy()

    def _get_state_file_path(self) -> Path:
        """获取状态文件路径"""
        if self._state_file:
            return Path(self._state_file)
        
        state_dir = get_config().ROOT_DIR / "data" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / self._STATE_FILE_NAME

    def _save_state(self) -> None:
        """保存状态到磁盘"""
        if not self._persist_state:
            return
        
        try:
            state_data = {
                "state": self.state.value if isinstance(self.state, FSMState) else str(self.state),
                "previous_state": self._previous_state.value if isinstance(self._previous_state, FSMState) else str(self._previous_state),
                "state_history": self._state_history[-100:],  # 只保存最近100条记录
                "timestamp": pd.Timestamp(get_time_provider().now()).isoformat(),
            }
            
            state_file = self._get_state_file_path()
            lock_file = state_file.with_suffix(state_file.suffix + ".lock")
            with FileLock(str(lock_file)):
                with open(state_file, 'w', encoding='utf-8') as f:
                    json.dump(state_data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"FSM状态已保存到: {state_file}")
        except Exception as e:
            logger.warning(f"保存FSM状态失败: {e}")

    def _load_state(self) -> None:
        """从磁盘加载状态"""
        if not self._persist_state:
            return
        
        try:
            state_file = self._get_state_file_path()
            if not state_file.exists():
                logger.debug("FSM状态文件不存在，使用默认状态")
                return
            
            lock_file = state_file.with_suffix(state_file.suffix + ".lock")
            with FileLock(str(lock_file)):
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
            
            loaded_state = state_data.get("state", "IDLE")
            self.state = FSMState(loaded_state) if loaded_state in [s.value for s in FSMState] else FSMState.IDLE
            
            prev_state = state_data.get("previous_state", "IDLE")
            self._previous_state = FSMState(prev_state) if prev_state in [s.value for s in FSMState] else FSMState.IDLE
            
            self._state_history = state_data.get("state_history", [])
            
            logger.info(f"FSM状态已从磁盘恢复: {self.state.value}")
        except Exception as e:
            logger.warning(f"加载FSM状态失败，使用默认状态: {e}")
            self.state = FSMState.IDLE
            self._previous_state = FSMState.IDLE
            self._state_history = []

    def _clear_state(self) -> None:
        """清除持久化的状态"""
        if not self._persist_state:
            return
        
        try:
            state_file = self._get_state_file_path()
            lock_file = state_file.with_suffix(state_file.suffix + ".lock")
            with FileLock(str(lock_file)):
                if state_file.exists():
                    os.remove(state_file)
                    logger.info(f"FSM状态文件已删除: {state_file}")
        except Exception as e:
            logger.warning(f"删除FSM状态文件失败: {e}")
