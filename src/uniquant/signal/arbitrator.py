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
from typing import Dict, List, Optional

from ..shared.interfaces import TradingSignal
from ..shared.logger_factory import get_logger

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


class SignalArbitrator:
    """信号仲裁器

    用法:
        arbitrator = SignalArbitrator()
        final_signals = arbitrator.arbitrate(all_signals)
    """

    def __init__(
        self,
        engine_priority: Optional[Dict[str, int]] = None,
        sell_priority: bool = True,
    ):
        self._priority = engine_priority or ENGINE_PRIORITY.copy()
        self._sell_priority = sell_priority
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

        by_date: Dict[str, List[TradingSignal]] = {}
        for sig in signals:
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
        log = ArbitrationLog(
            symbol=symbol,
            date=date_key,
            total_signals=len(day_signals),
        )

        if len(day_signals) == 1:
            winner = day_signals[0]
            log.selected_action = winner.action
            log.selected_reason = winner.reason
            log.selected_confidence = winner.confidence
            self._logs.append(log)
            return winner

        # 规则 1: SELL 优先于 BUY
        if self._sell_priority:
            sells = [s for s in day_signals if s.action == "SELL"]
            if sells:
                winner = self._highest_confidence(sells)
                log.selected_action = "SELL"
                log.selected_reason = f"arbitrated: {winner.reason}"
                log.selected_confidence = winner.confidence
                log.conflicts_resolved = len(day_signals) - 1
                log.rejection_reasons.append(
                    f"sell_priority: rejected {len(day_signals) - len(sells)} buy signal(s)"
                )
                self._logs.append(log)
                return winner

        # 规则 2: 同方向取最高 confidence
        action_groups: Dict[str, List[TradingSignal]] = {}
        for sig in day_signals:
            action_groups.setdefault(sig.action, []).append(sig)

        for action in ("BUY", "SELL"):
            if action in action_groups:
                winner = self._highest_confidence(action_groups[action])
                log.selected_action = winner.action
                log.selected_reason = f"arbitrated: {winner.reason}"
                log.selected_confidence = winner.confidence
                log.conflicts_resolved = len(day_signals) - 1
                self._logs.append(log)
                return winner

        # 规则 3: 按引擎优先级
        winner = self._by_engine_priority(day_signals)
        if winner:
            log.selected_action = winner.action
            log.selected_reason = f"arbitrated(engine_priority): {winner.reason}"
            log.selected_confidence = winner.confidence
            log.conflicts_resolved = len(day_signals) - 1
        self._logs.append(log)
        return winner

    @staticmethod
    def _highest_confidence(signals: List[TradingSignal]) -> TradingSignal:
        return max(signals, key=lambda s: s.confidence)

    def _by_engine_priority(self, signals: List[TradingSignal]) -> Optional[TradingSignal]:
        candidates: List[TradingSignal] = []
        for sig in signals:
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

    def clear_logs(self) -> None:
        self._logs.clear()
