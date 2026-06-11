"""信号聚合器

实现多信号融合，支持加权平均、多数表决、最大置信度、共识阈值四种聚合方法。
包含时间窗口聚合器和来源权重管理器。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

from ..shared.time_provider import get_time_provider
from .models import (
    AggregatedSignal,
    Signal,
    SignalConsensus,
    SignalSource,
    SignalStrength,
    SignalType,
)


# ───────────────────────── 聚合方法枚举 ─────────────────────────

class SignalAggregationMethod(Enum):
    """信号聚合方法枚举"""
    WEIGHTED_AVERAGE = "weighted_average"
    MAJORITY_VOTE = "majority_vote"
    MAX_CONFIDENCE = "max_confidence"
    CONSENSUS_THRESHOLD = "consensus_threshold"


# ───────────────────────── 来源权重管理器 ─────────────────────────

class SourceWeightManager:
    """来源权重管理器，支持基于绩效的自适应权重更新"""

    def __init__(self) -> None:
        self._weights: Dict[SignalSource, float] = {}

    def set_weight(self, source: SignalSource, weight: float) -> None:
        """手动设置权重

        Args:
            source: 信号来源
            weight: 权重值 (>= 0)
        """
        self._weights[source] = max(0.0, weight)

    def get_weight(self, source: SignalSource) -> float:
        """获取权重，默认 1.0

        Args:
            source: 信号来源

        Returns:
            权重值
        """
        return self._weights.get(source, 1.0)

    def update_weights(self, performance: Dict[SignalSource, float]) -> None:
        """根据绩效归一化更新权重（最低 0.1）

        Args:
            performance: 来源到绩效值的映射
        """
        if not performance:
            return
        total = sum(performance.values())
        if total <= 0:
            return
        for source, perf in performance.items():
            normalized = perf / total
            self._weights[source] = max(0.1, normalized)


# ───────────────────────── 核心聚合器 ─────────────────────────

class SignalAggregator:
    """核心信号聚合器

    支持四种聚合方法，管理来源权重。
    """

    def __init__(
        self,
        method: SignalAggregationMethod = SignalAggregationMethod.WEIGHTED_AVERAGE,
        weight_manager: Optional[SourceWeightManager] = None,
    ) -> None:
        self.method = method
        self._weight_manager = weight_manager or SourceWeightManager()

    def set_weight(self, source: SignalSource, weight: float) -> None:
        """设置来源权重"""
        self._weight_manager.set_weight(source, weight)

    def get_weight(self, source: SignalSource) -> float:
        """获取来源权重"""
        return self._weight_manager.get_weight(source)

    def aggregate(self, signals: List[Signal]) -> AggregatedSignal:
        """聚合信号列表

        Args:
            signals: 待聚合的信号列表

        Returns:
            聚合后的信号
        """
        if not signals:
            return AggregatedSignal()

        if self.method == SignalAggregationMethod.WEIGHTED_AVERAGE:
            return self._aggregate_weighted_average(signals)
        if self.method == SignalAggregationMethod.MAJORITY_VOTE:
            return self._aggregate_majority_vote(signals)
        if self.method == SignalAggregationMethod.MAX_CONFIDENCE:
            return self._aggregate_max_confidence(signals)
        if self.method == SignalAggregationMethod.CONSENSUS_THRESHOLD:
            return self._aggregate_consensus_threshold(signals)
        return self._aggregate_weighted_average(signals)

    def aggregate_by_type(self, signals: List[Signal]) -> Dict[SignalType, AggregatedSignal]:
        """按信号类型分组聚合

        Args:
            signals: 信号列表

        Returns:
            信号类型到聚合结果的映射
        """
        groups: Dict[SignalType, List[Signal]] = defaultdict(list)
        for s in signals:
            groups[s.signal_type].append(s)
        return {st: self.aggregate(sigs) for st, sigs in groups.items()}

    def calculate_consensus(
        self, signals: List[Signal], threshold: float = 0.6
    ) -> SignalConsensus:
        """计算信号共识

        Args:
            signals: 信号列表
            threshold: 一致性阈值

        Returns:
            共识结果
        """
        if not signals:
            return SignalConsensus()

        bullish = sum(1 for s in signals if s.direction > 0)
        bearish = sum(1 for s in signals if s.direction < 0)
        total = len(signals)

        if bullish >= bearish:
            consensus_dir = 1
            agreeing = bullish
        else:
            consensus_dir = -1
            agreeing = bearish

        agreement_ratio = agreeing / total if total > 0 else 0.0
        avg_confidence = sum(s.confidence for s in signals) / total if total > 0 else 0.0

        return SignalConsensus(
            consensus_direction=consensus_dir,
            consensus_confidence=avg_confidence,
            agreement_ratio=agreement_ratio,
            total_sources=total,
            agreeing_sources=agreeing,
        )

    def _aggregate_weighted_average(self, signals: List[Signal]) -> AggregatedSignal:
        """加权平均聚合"""
        total_weight = 0.0
        weighted_direction = 0.0
        weighted_confidence = 0.0

        for s in signals:
            w = self._weight_manager.get_weight(s.source) * s.confidence
            weighted_direction += s.direction * w
            weighted_confidence += s.confidence * w
            total_weight += w

        if total_weight > 0:
            norm_dir = weighted_direction / total_weight
            norm_conf = weighted_confidence / total_weight
        else:
            norm_dir = 0.0
            norm_conf = 0.0

        direction = 1 if norm_dir > 0.1 else (-1 if norm_dir < -0.1 else 0)
        confidence = min(1.0, max(0.0, abs(norm_conf)))
        strength = SignalNormalizer._compute_strength(confidence) if confidence > 0 else SignalStrength.WEAK

        # 计算一致性
        consensus = self.calculate_consensus(signals)

        result_signal = Signal(
            signal_type=signals[0].signal_type,
            source=SignalSource.ENSEMBLE,
            symbol=signals[0].symbol,
            direction=direction,
            strength=strength,
            confidence=confidence,
            price=sum(s.price * s.confidence for s in signals) / sum(s.confidence for s in signals) if sum(s.confidence for s in signals) > 0 else 0.0,
        )

        return AggregatedSignal(
            signal=result_signal,
            contributing_signals=list(signals),
            sources={s.source for s in signals},
            agreement_ratio=consensus.agreement_ratio,
            weighted_score=norm_dir,
        )

    def _aggregate_majority_vote(self, signals: List[Signal]) -> AggregatedSignal:
        """多数表决聚合"""
        bullish = sum(1 for s in signals if s.direction > 0)
        bearish = sum(1 for s in signals if s.direction < 0)
        total = len(signals)

        if bullish > bearish:
            direction = 1
            agreeing = bullish
        elif bearish > bullish:
            direction = -1
            agreeing = bearish
        else:
            direction = 0
            agreeing = max(bullish, bearish)

        agreement_ratio = agreeing / total if total > 0 else 0.0
        avg_confidence = sum(s.confidence for s in signals) / total if total > 0 else 0.0
        strength = SignalNormalizer._compute_strength(avg_confidence)

        result_signal = Signal(
            signal_type=signals[0].signal_type,
            source=SignalSource.ENSEMBLE,
            symbol=signals[0].symbol,
            direction=direction,
            strength=strength,
            confidence=avg_confidence,
        )

        return AggregatedSignal(
            signal=result_signal,
            contributing_signals=list(signals),
            sources={s.source for s in signals},
            agreement_ratio=agreement_ratio,
            weighted_score=float(direction),
        )

    def _aggregate_max_confidence(self, signals: List[Signal]) -> AggregatedSignal:
        """最大置信度聚合"""
        best = max(signals, key=lambda s: s.confidence)
        consensus = self.calculate_consensus(signals)

        result_signal = Signal(
            signal_type=best.signal_type,
            source=SignalSource.ENSEMBLE,
            symbol=best.symbol,
            direction=best.direction,
            strength=best.strength,
            confidence=best.confidence,
            price=best.price,
        )

        return AggregatedSignal(
            signal=result_signal,
            contributing_signals=list(signals),
            sources={s.source for s in signals},
            agreement_ratio=consensus.agreement_ratio,
            weighted_score=float(best.direction) * best.confidence,
        )

    def _aggregate_consensus_threshold(self, signals: List[Signal]) -> AggregatedSignal:
        """共识阈值聚合，一致性比例 >= 0.6 时取共识方向"""
        consensus = self.calculate_consensus(signals)
        threshold = 0.6

        if consensus.agreement_ratio >= threshold:
            direction = consensus.consensus_direction
            confidence = consensus.consensus_confidence
        else:
            direction = 0
            confidence = 0.0

        strength = SignalNormalizer._compute_strength(confidence) if confidence > 0 else SignalStrength.WEAK

        result_signal = Signal(
            signal_type=signals[0].signal_type,
            source=SignalSource.ENSEMBLE,
            symbol=signals[0].symbol,
            direction=direction,
            strength=strength,
            confidence=confidence,
        )

        return AggregatedSignal(
            signal=result_signal,
            contributing_signals=list(signals),
            sources={s.source for s in signals},
            agreement_ratio=consensus.agreement_ratio,
            weighted_score=float(direction) * confidence,
        )


# 避免循环导入，内联引用
from .normalizer import SignalNormalizer  # noqa: E402


# ───────────────────────── 时间窗口聚合器 ─────────────────────────

class TimeWindowAggregator:
    """时间窗口聚合器

    将信号按时间窗口分组，对窗口内的信号按类型聚合。

    Args:
        window: 时间窗口长度，默认 5 分钟
        method: 聚合方法
    """

    def __init__(
        self,
        window: timedelta = timedelta(minutes=5),
        method: SignalAggregationMethod = SignalAggregationMethod.WEIGHTED_AVERAGE,
    ) -> None:
        self.window = window
        self._buffer: List[Signal] = []
        self._aggregator = SignalAggregator(method=method)

    def add(self, signal: Signal) -> None:
        """将信号加入缓冲区

        Args:
            signal: 待缓冲的信号
        """
        self._buffer.append(signal)

    def flush(self) -> List[AggregatedSignal]:
        """清除过期信号，对当前窗口内的信号按类型聚合

        Returns:
            聚合结果列表（每种信号类型一个）
        """
        now = get_time_provider().now()
        cutoff = now - self.window

        # 清除过期信号
        self._buffer = [s for s in self._buffer if s.timestamp >= cutoff]

        if not self._buffer:
            return []

        # 按类型分组聚合
        result = self._aggregator.aggregate_by_type(self._buffer)
        return list(result.values())

    @property
    def buffer_size(self) -> int:
        """当前缓冲区大小"""
        return len(self._buffer)
