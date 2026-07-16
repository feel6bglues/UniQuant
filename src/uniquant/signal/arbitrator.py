"""信号仲裁器 — 解决多引擎信号冲突

在多引擎并行输出场景下, 仲裁器按优先级规则选择最终信号:
  1. SELL 始终优先于 BUY (LPPL 不可覆盖)
  2. 同方向信号取最高 confidence
  3. 引擎优先级: LPPL > FSM > CZSC > Wyckoff > Regime > NTF > Alpha

设计原则:
  - 不修改原始信号列表 (不可变)
  - 仲裁结果可通过特性开关控制
  - 所有决策记录到仲裁日志
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..shared.interfaces import CandidateSignal, DecisionOutput, MarketSignalContext, PositionSizerProtocol
from ..shared.interfaces import TradingSignal
from ..shared.kill_switch import get_kill_switch
from ..shared.logger_factory import get_logger
from ..shared.time_provider import get_time_provider

logger = get_logger(__name__)

# 引擎优先级 (数值越小优先级越高)
ENGINE_PRIORITY: Dict[str, int] = {
    "lppl": 0,
    "fsm": 1,
    "czsc": 2,
    "wyckoff": 3,
    "regime": 4,
    "ntf": 5,
    "alpha_score": 6,
    "ma_status": 7,
}

# 信号过期时间 (秒) — 0 表示不启用过期检查
DEFAULT_MAX_SIGNAL_AGE_SECONDS: float = 0.0  # 0=禁用; 回测模式下应保持禁用，信号时间戳 vs 壁钟时间不匹配  # 默认禁用


@dataclass
class ArbitrationLog:
    """单次仲裁记录"""
    symbol: str
    date: str
    total_signals: int
    selected_action: str = "HOLD"
    selected_reason: str = ""
    selected_confidence: float = 0.0
    conflicts_resolved: int = 0
    rejection_reasons: List[str] = field(default_factory=list)


@dataclass
class ArbitrationReport:
    """仲裁报告 — 记录仲裁决策过程和拒绝链"""
    symbol: str
    date: str
    candidates_count: int
    final_action: str = "HOLD"
    final_reason: str = ""
    final_confidence: float = 0.0
    veto_chain: List[str] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)


class SignalArbitrator:
    """信号仲裁器

    用法:
        arbitrator = SignalArbitrator()
        final_signals = arbitrator.arbitrate(all_signals)
        final_signals, report = arbitrator.arbitrate_candidates(candidates, ...)
    """

    def __init__(
        self,
        engine_priority: Optional[Dict[str, int]] = None,
        sell_priority: bool = True,
        quality_threshold: float = 0.3,
        max_signal_age_seconds: float = DEFAULT_MAX_SIGNAL_AGE_SECONDS,
    ):
        self._priority = engine_priority or ENGINE_PRIORITY.copy()
        self._sell_priority = sell_priority
        self._quality_threshold = quality_threshold
        self._max_signal_age_seconds = max_signal_age_seconds
        self._logs: List[ArbitrationLog] = []

    @property
    def logs(self) -> List[ArbitrationLog]:
        return list(self._logs)

    def arbitrate(
        self,
        signals: List[TradingSignal],
        symbol: str = "",
    ) -> List[TradingSignal]:
        """仲裁信号列表, 返回最终要执行的信号

        Args:
            signals: 来自所有引擎的原始信号列表
            symbol: 证券代码

        Returns:
            仲裁后的最终信号列表 (每日至多一个)
        """
        if not signals:
            return []

        if get_kill_switch().is_killed:
            logger.info("All signals dropped: kill switch active (%s)", get_kill_switch().reason)
            return []

        now = get_time_provider().now()
        by_date: Dict[str, List[TradingSignal]] = {}
        for sig in signals:
            # 信号超时检查
            if sig.timestamp is not None and self._max_signal_age_seconds > 0:
                age = (now - sig.timestamp).total_seconds()
                if age > self._max_signal_age_seconds:
                    logger.info(
                        "Signal dropped (expired): age=%.1fs max=%.1fs for %s",
                        age, self._max_signal_age_seconds, sig.reason,
                    )
                    continue
            key = (
                str(sig.timestamp.date())
                if sig.timestamp
                else "unknown"
            )
            by_date.setdefault(key, []).append(sig)

        result: List[TradingSignal] = []
        for date_key in sorted(by_date.keys()):
            day_signals = by_date[date_key]
            winner = self._pick_winner(day_signals, symbol, date_key)
            if winner is not None:
                result.append(winner)

        return result

    def _pick_winner(
        self,
        day_signals: List[TradingSignal],
        symbol: str,
        date_key: str,
    ) -> Optional[TradingSignal]:
        # 只考虑可执行信号 (BUY/SELL), 过滤 HOLD/未知动作
        actionable = [s for s in day_signals if s.action in ("BUY", "SELL")]

        log = ArbitrationLog(
            symbol=symbol,
            date=date_key,
            total_signals=len(day_signals),
        )

        if not actionable:
            log.selected_action = "HOLD"
            log.selected_reason = "no actionable signals"
            self._logs.append(log)
            return None

        # 规则 0: 质量阈值过滤 (P6.5) — 在任何仲裁之前进行
        if self._quality_threshold > 0.0:
            filtered = []
            for sig in actionable:
                oos_r2 = sig.metadata.get("out_of_sample_r_squared", 1.0)
                if oos_r2 < self._quality_threshold and sig.action == "SELL":
                    log.rejection_reasons.append(
                        f"quality_gate: rejected SELL from {sig.reason} "
                        f"(OOS R²={oos_r2:.2f} < {self._quality_threshold})"
                    )
                    logger.info(
                        "Quality gate rejected SELL %s OOS R²=%.2f for %s on %s",
                        sig.reason, oos_r2, symbol, date_key,
                    )
                else:
                    filtered.append(sig)
            actionable = filtered

        if not actionable:
            log.selected_action = "HOLD"
            log.selected_reason = "no actionable signals after quality filter"
            self._logs.append(log)
            return None

        if len(actionable) == 1:
            winner = actionable[0]
            log.selected_action = winner.action
            log.selected_reason = winner.reason
            log.selected_confidence = winner.confidence
            self._logs.append(log)
            return winner

        # 规则 1: SELL 优先于 BUY
        if self._sell_priority:
            sells = [s for s in actionable if s.action == "SELL"]
            if sells:
                winner = self._highest_confidence(sells)
                if winner is None:
                    return None
                log.selected_action = "SELL"
                log.selected_reason = f"arbitrated: {winner.reason}"
                log.selected_confidence = winner.confidence
                log.conflicts_resolved = len(actionable) - 1
                log.rejection_reasons.append(
                    f"sell_priority: rejected {len(actionable) - len(sells)} buy signal(s)"
                )
                self._logs.append(log)
                return winner

        # 规则 2: 同方向取最高 confidence
        action_groups: Dict[str, List[TradingSignal]] = {}
        for sig in actionable:
            action_groups.setdefault(sig.action, []).append(sig)

        for action in ("BUY", "SELL"):
            if action in action_groups:
                winner = self._highest_confidence(action_groups[action])
                if winner is None:
                    continue
                log.selected_action = winner.action
                log.selected_reason = f"arbitrated: {winner.reason}"
                log.selected_confidence = winner.confidence
                log.conflicts_resolved = len(actionable) - 1
                self._logs.append(log)
                return winner

        # 规则 3: 按引擎优先级
        winner = self._by_engine_priority(actionable)
        if winner:
            log.selected_action = winner.action
            log.selected_reason = f"arbitrated(engine_priority): {winner.reason}"
            log.selected_confidence = winner.confidence
            log.conflicts_resolved = len(actionable) - 1
        self._logs.append(log)
        return winner

    @staticmethod
    def _highest_confidence(signals: List[TradingSignal]) -> Optional[TradingSignal]:
        valid = [s for s in signals if s.confidence is not None and s.confidence >= 0.0]
        if not valid:
            return signals[0] if signals else None
        return max(valid, key=lambda s: s.confidence)

    def _by_engine_priority(self, signals: List[TradingSignal]) -> Optional[TradingSignal]:
        candidates: List[Tuple[int, TradingSignal]] = []
        for sig in signals:
            if sig.action not in ("BUY", "SELL"):
                continue
            priority = self._get_engine_priority(sig.reason)
            candidates.append((priority, sig))
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1] if candidates else None

    @staticmethod
    def _get_engine_priority(reason: str) -> int:
        reason_lower = reason.lower()
        for engine, priority in ENGINE_PRIORITY.items():
            if engine in reason_lower:
                return priority
        return 99

    def arbitrate_candidates(
        self,
        candidates: List[CandidateSignal],
        decision_output: Optional[DecisionOutput] = None,
        context: Optional[MarketSignalContext] = None,
        sizer: Optional[PositionSizerProtocol] = None,
        symbol: str = "",
    ) -> Tuple[List[TradingSignal], ArbitrationReport]:
        """仲裁候选信号列表, 返回最终要执行的信号 + 仲裁报告

        Args:
            candidates: 来自所有引擎的候选信号列表
            decision_output: DecisionBrain 的类型化输出
            context: 市场信号上下文
            sizer: 仓位计算器 (非 FSM BUY 需要)
            symbol: 证券代码

        Returns:
            (最终信号列表, 仲裁报告)
        """
        if not candidates:
            return [], ArbitrationReport(
                symbol=symbol, date="", candidates_count=0,
                final_action="HOLD", final_reason="no candidates",
            )

        if get_kill_switch().is_killed:
            return [], ArbitrationReport(
                symbol=symbol, date="", candidates_count=len(candidates),
                final_action="HOLD",
                final_reason=f"kill_switch: {get_kill_switch().reason}",
                veto_chain=[f"kill_switch={get_kill_switch().reason}"],
            )

        report = ArbitrationReport(
            symbol=symbol,
            date="",
            candidates_count=len(candidates),
        )

        # Priority 1: DecisionOutput hard constraints
        if decision_output is not None:
            if decision_output.action in ("FORCE_WAIT", "CIRCUIT_BREAK"):
                report.final_action = "HOLD"
                report.final_reason = "risk_veto"
                report.veto_chain.append(f"decision_output={decision_output.action}")
                return [], report

            if decision_output.action == "FORCE_EXIT":
                report.final_action = "SELL"
                report.final_reason = "force_exit"
                report.veto_chain.append("decision_output=FORCE_EXIT")
                return [
                    TradingSignal(action="SELL", reason="FORCE_EXIT", confidence=1.0, symbol=symbol)
                ], report

            if decision_output.action == "BUY" and decision_output.shares > 0:
                report.final_action = "BUY"
                report.final_reason = "decision_brain"
                report.final_confidence = decision_output.confidence
                report.veto_chain.append(f"decision_output=BUY shares={decision_output.shares}")
                return [
                    TradingSignal(
                        action="BUY",
                        reason="decision_brain",
                        confidence=decision_output.confidence,
                        shares=decision_output.shares,
                        symbol=symbol,
                    )
                ], report

        # Priority 2: SELL over BUY (from existing arbitrate logic)
        sell_candidates = [c for c in candidates if c.action == "SELL"]
        if sell_candidates:
            best_sell = max(sell_candidates, key=lambda c: c.confidence)
            report.final_action = "SELL"
            report.final_reason = f"arbitrated: {best_sell.source} SELL"
            report.final_confidence = best_sell.confidence
            report.veto_chain.append(f"sell_priority: {best_sell.source}")
            for c in candidates:
                if c.action != "SELL":
                    report.rejected.append(f"{c.source} {c.action} (overridden by SELL priority)")
            return [
                TradingSignal(
                    action="SELL",
                    reason=f"arbitrated: {best_sell.source} confidence={best_sell.confidence:.2f}",
                    confidence=best_sell.confidence,
                    symbol=symbol,
                )
            ], report

        # Priority 3: Non-FSM BUY candidates need PositionSizer
        buy_candidates = [c for c in candidates if c.action == "BUY"]
        non_fsm_buys = [c for c in buy_candidates if c.source != "fsm"]
        fsm_buys = [c for c in buy_candidates if c.source == "fsm"]

        # FSM buys pass through
        if fsm_buys:
            best_fsm = max(fsm_buys, key=lambda c: c.confidence)
            report.final_action = "BUY"
            report.final_reason = f"fsm: {best_fsm.source}"
            report.final_confidence = best_fsm.confidence
            report.veto_chain.append("fsm_buy")
            return [
                TradingSignal(
                    action="BUY",
                    reason=f"fsm: {best_fsm.source}",
                    confidence=best_fsm.confidence,
                    symbol=symbol,
                )
            ], report

        # Non-FSM buys need sizer
        if non_fsm_buys:
            if sizer is None:
                for c in non_fsm_buys:
                    report.rejected.append(f"{c.source} BUY (no sizer available)")
                report.final_action = "HOLD"
                report.final_reason = f"non-fsm buys require sizer: {[c.source for c in non_fsm_buys]}"
                report.veto_chain.append("non_fsm_needs_sizer")
                return [], report
            else:
                best_non_fsm = max(non_fsm_buys, key=lambda c: c.confidence)
                try:
                    sized = sizer.calculate_shares(
                        price=best_non_fsm.price_target or 0.0,
                        stop_loss=best_non_fsm.stop_loss or 0.0,
                        czsc_bottom=None,
                        market="CN",
                        symbol=symbol,
                    )
                    sized_shares = int(sized.get("suggested_shares", 100))
                except Exception as e:
                    logger.warning("Sizer sizing failed for %s: %s", symbol, e)
                    sized_shares = 100
                report.final_action = "BUY"
                report.final_reason = f"sizer approved: {best_non_fsm.source}"
                report.final_confidence = best_non_fsm.confidence
                report.veto_chain.append(f"non_fsm_sizer_approved:{best_non_fsm.source}")
                return [
                    TradingSignal(
                        action="BUY",
                        reason=f"sizer approved: {best_non_fsm.source}",
                        confidence=best_non_fsm.confidence,
                        shares=sized_shares,
                        symbol=symbol,
                    )
                ], report

        # Priority 4: HOLD by default
        report.final_action = "HOLD"
        report.final_reason = "default_no_trade"
        return [], report

    def clear_logs(self) -> None:
        self._logs.clear()
