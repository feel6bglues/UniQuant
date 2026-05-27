"""信号质量评估

提供信号质量的事后评估能力，包括精确率、召回率、F1 分数、
命中率、盈利因子等指标的计算，以及持续质量跟踪。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import Signal, SignalSource, SignalType


# ───────────────────────── 质量指标数据类 ─────────────────────────

@dataclass
class SignalQualityMetrics:
    """信号质量指标

    Attributes:
        precision: 精确率
        recall: 召回率
        f1_score: F1 分数
        accuracy: 准确率
        average_lead_time: 平均提前时间（小时）
        hit_rate: 命中率
        false_positive_rate: 假阳性率
        sample_size: 样本量
        average_confidence: 平均置信度
        profit_factor: 盈利因子
        sharpe_ratio: 夏普比率
    """
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    accuracy: float = 0.0
    average_lead_time: float = 0.0
    hit_rate: float = 0.0
    false_positive_rate: float = 0.0
    sample_size: int = 0
    average_confidence: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0


# ───────────────────────── 信号质量评估器 ─────────────────────────

class SignalQualityAssessor:
    """信号质量评估器（静态方法集）"""

    @staticmethod
    def assess(
        signal: Signal,
        subsequent_prices: List[float],
        lookahead: int = 20,
    ) -> Optional[bool]:
        """评估单个信号质量

        对看多信号计算未来 lookahead 天内最高价收益，对看空信号计算最低价收益。
        命中标准：看多 +1%，看空 -1%。

        Args:
            signal: 待评估信号
            subsequent_prices: 信号后的价格序列
            lookahead: 向前看的天数

        Returns:
            True=命中, False=未命中, None=数据不足
        """
        if not subsequent_prices or len(subsequent_prices) < 1:
            return None

        prices = subsequent_prices[:lookahead]
        trigger_price = signal.price if signal.price > 0 else prices[0]
        if trigger_price <= 0:
            return None

        if signal.is_bullish():
            max_return = (max(prices) - trigger_price) / trigger_price
            return max_return >= 0.01
        if signal.is_bearish():
            min_return = (min(prices) - trigger_price) / trigger_price
            return min_return <= -0.01
        return None

    @staticmethod
    def calculate_hit_rate(
        signals: List[Signal],
        price_data: Dict[str, List[float]],
        lookahead: int = 20,
    ) -> float:
        """批量计算命中率

        Args:
            signals: 信号列表
            price_data: 信号 ID 到后续价格序列的映射
            lookahead: 向前看的天数

        Returns:
            命中率 [0, 1]
        """
        hits = 0
        total = 0
        for signal in signals:
            prices = price_data.get(signal.id)
            if prices is None:
                continue
            result = SignalQualityAssessor.assess(signal, prices, lookahead)
            if result is not None:
                total += 1
                if result:
                    hits += 1
        return hits / total if total > 0 else 0.0

    @staticmethod
    def calculate_accuracy(
        signals: List[Signal],
        actual_directions: Dict[str, int],
    ) -> float:
        """计算方向准确率

        Args:
            signals: 信号列表
            actual_directions: 信号 ID 到实际方向的映射 (1/-1/0)

        Returns:
            准确率 [0, 1]
        """
        correct = 0
        total = 0
        for signal in signals:
            actual = actual_directions.get(signal.id)
            if actual is None:
                continue
            total += 1
            if signal.direction == actual:
                correct += 1
        return correct / total if total > 0 else 0.0

    @staticmethod
    def calculate_precision_recall(
        signals: List[Signal],
        actual_outcomes: Dict[str, bool],
    ) -> SignalQualityMetrics:
        """计算精确率/召回率/F1

        Args:
            signals: 信号列表
            actual_outcomes: 信号 ID 到实际结果的映射 (True=有效信号)

        Returns:
            质量指标
        """
        tp = fp = fn = tn = 0
        for signal in signals:
            actual = actual_outcomes.get(signal.id)
            if actual is None:
                continue
            predicted_positive = signal.direction != 0
            if predicted_positive and actual:
                tp += 1
            elif predicted_positive and not actual:
                fp += 1
            elif not predicted_positive and actual:
                fn += 1
            else:
                tn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        accuracy = (tp + tn) / (tp + fp + fn + tn) if (tp + fp + fn + tn) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

        return SignalQualityMetrics(
            precision=precision,
            recall=recall,
            f1_score=f1,
            accuracy=accuracy,
            hit_rate=accuracy,
            false_positive_rate=fpr,
            sample_size=tp + fp + fn + tn,
            average_confidence=sum(s.confidence for s in signals) / len(signals) if signals else 0.0,
        )


# ───────────────────────── 信号质量跟踪器 ─────────────────────────

@dataclass
class _OutcomeRecord:
    """内部结果记录"""
    signal_id: str
    outcome: bool
    source: SignalSource
    signal_type: SignalType
    timestamp: datetime = field(default_factory=datetime.now)


class SignalQualityTracker:
    """持续追踪信号质量的跟踪器"""

    def __init__(self) -> None:
        self._records: List[_OutcomeRecord] = []

    def record_outcome(
        self,
        signal_id: str,
        outcome: bool,
        source: SignalSource,
        signal_type: SignalType,
    ) -> None:
        """记录信号结果

        Args:
            signal_id: 信号 ID
            outcome: True=命中, False=未命中
            source: 信号来源
            signal_type: 信号类型
        """
        self._records.append(_OutcomeRecord(
            signal_id=signal_id,
            outcome=outcome,
            source=source,
            signal_type=signal_type,
        ))

    def _metrics_from_records(self, records: List[_OutcomeRecord]) -> SignalQualityMetrics:
        """从记录列表计算质量指标"""
        if not records:
            return SignalQualityMetrics()
        hits = sum(1 for r in records if r.outcome)
        total = len(records)
        return SignalQualityMetrics(
            hit_rate=hits / total if total > 0 else 0.0,
            sample_size=total,
        )

    def get_source_quality(self, source: SignalSource) -> SignalQualityMetrics:
        """按来源查询质量

        Args:
            source: 信号来源

        Returns:
            该来源的质量指标
        """
        records = [r for r in self._records if r.source == source]
        return self._metrics_from_records(records)

    def get_type_quality(self, signal_type: SignalType) -> SignalQualityMetrics:
        """按信号类型查询质量

        Args:
            signal_type: 信号类型

        Returns:
            该类型的质量指标
        """
        records = [r for r in self._records if r.signal_type == signal_type]
        return self._metrics_from_records(records)

    def get_overall_quality(self) -> SignalQualityMetrics:
        """全局质量"""
        return self._metrics_from_records(self._records)

    def summary(self) -> Dict[str, Any]:
        """生成完整质量报告

        Returns:
            包含 overall + 每个 source + 每个 type 的质量报告
        """
        report: Dict[str, Any] = {
            "overall": self.get_overall_quality(),
            "by_source": {},
            "by_type": {},
        }

        sources = {r.source for r in self._records}
        for source in sources:
            report["by_source"][source.value] = self.get_source_quality(source)

        types = {r.signal_type for r in self._records}
        for st in types:
            report["by_type"][st.value] = self.get_type_quality(st)

        return report
