"""Tests for uniquant.signal module — models, normalizer, aggregator, quality."""

import pytest
from datetime import datetime, timedelta

from uniquant.signal.models import (
    Signal,
    SignalBatch,
    SignalConsensus,
    SignalSource,
    SignalStrength,
    SignalType,
)
from uniquant.signal.normalizer import (
    CZSCSignalNormalizer,
    IndicatorSignalNormalizer,
    LPPLSignalNormalizer,
    SignalNormalizerRegistry,
    WyckoffSignalNormalizer,
    create_default_registry,
)
from uniquant.signal.aggregator import (
    SignalAggregationMethod,
    SignalAggregator,
    SourceWeightManager,
    TimeWindowAggregator,
)
from uniquant.signal.quality import (
    SignalQualityAssessor,
    SignalQualityTracker,
)


# ───────────────────────── models ─────────────────────────


class TestSignal:
    def test_create_default_signal(self):
        s = Signal()
        assert s.signal_type == SignalType.TREND_NEUTRAL
        assert s.direction == 0
        assert 0.0 <= s.confidence <= 1.0
        assert s.id  # UUID generated

    def test_bullish_bearish(self):
        bull = Signal(direction=1)
        bear = Signal(direction=-1)
        neutral = Signal(direction=0)
        assert bull.is_bullish() and not bull.is_bearish()
        assert bear.is_bearish() and not bear.is_bullish()
        assert not neutral.is_bullish() and not neutral.is_bearish()

    def test_to_dict_roundtrip(self):
        s = Signal(
            signal_type=SignalType.LPPL_BUBBLE,
            source=SignalSource.LPPL,
            symbol="000001",
            direction=1,
            confidence=0.85,
            price=10.5,
        )
        d = s.to_dict()
        s2 = Signal.from_dict(d)
        assert s2.signal_type == SignalType.LPPL_BUBBLE
        assert s2.symbol == "000001"
        assert s2.direction == 1
        assert abs(s2.confidence - 0.85) < 1e-6
        assert abs(s2.price - 10.5) < 1e-6

    def test_expiration(self):
        s = Signal(expiration=datetime.now() - timedelta(seconds=1))
        assert s.is_expired()
        s2 = Signal(expiration=datetime.now() + timedelta(hours=1))
        assert not s2.is_expired()
        s3 = Signal()
        assert not s3.is_expired()


class TestSignalBatch:
    def test_add_and_filter(self):
        batch = SignalBatch()
        batch.add(Signal(direction=1, signal_type=SignalType.TREND_BULLISH))
        batch.add(Signal(direction=-1, signal_type=SignalType.TREND_BEARISH))
        batch.add(Signal(direction=0, signal_type=SignalType.TREND_NEUTRAL))
        assert len(batch) == 3
        assert len(batch.bullish()) == 1
        assert len(batch.bearish()) == 1
        assert len(batch.neutral()) == 1

    def test_by_type(self):
        batch = SignalBatch()
        batch.add(Signal(signal_type=SignalType.LPPL_BUBBLE))
        batch.add(Signal(signal_type=SignalType.LPPL_CRASH))
        batch.add(Signal(signal_type=SignalType.LPPL_BUBBLE))
        assert len(batch.by_type(SignalType.LPPL_BUBBLE)) == 2

    def test_average_confidence(self):
        batch = SignalBatch()
        batch.add(Signal(confidence=0.8))
        batch.add(Signal(confidence=0.6))
        assert abs(batch.average_confidence() - 0.7) < 1e-6


class TestSignalConsensus:
    def test_strong_consensus(self):
        c = SignalConsensus(agreement_ratio=0.8)
        assert c.is_strong_consensus(threshold=0.75)
        assert not c.is_strong_consensus(threshold=0.9)


# ───────────────────────── normalizer ─────────────────────────


class TestLPPLSignalNormalizer:
    def test_bubble_signal(self):
        norm = LPPLSignalNormalizer()
        raw = {"type": "bubble", "symbol": "000001", "confidence": 0.9, "price": 15.0}
        s = norm.normalize(raw)
        assert s.signal_type == SignalType.LPPL_BUBBLE
        assert s.direction == 1
        assert s.source == SignalSource.LPPL
        assert s.strength == SignalStrength.VERY_STRONG

    def test_crash_signal(self):
        norm = LPPLSignalNormalizer()
        raw = {"type": "crash", "confidence": 0.5}
        s = norm.normalize(raw)
        assert s.signal_type == SignalType.LPPL_CRASH
        assert s.direction == -1

    def test_unknown_type_defaults_to_neutral(self):
        norm = LPPLSignalNormalizer()
        raw = {"type": "unknown_type", "confidence": 0.3}
        s = norm.normalize(raw)
        assert s.signal_type == SignalType.TREND_NEUTRAL


class TestWyckoffSignalNormalizer:
    def test_accumulation(self):
        norm = WyckoffSignalNormalizer()
        raw = {"type": "accumulation", "symbol": "600000", "confidence": 0.7}
        s = norm.normalize(raw)
        assert s.signal_type == SignalType.WYCKOFF_ACCUMULATION
        assert s.direction == 1

    def test_distribution(self):
        norm = WyckoffSignalNormalizer()
        raw = {"type": "distribution", "confidence": 0.6}
        s = norm.normalize(raw)
        assert s.signal_type == SignalType.WYCKOFF_DISTRIBUTION
        assert s.direction == -1


class TestIndicatorSignalNormalizer:
    def test_overbought(self):
        norm = IndicatorSignalNormalizer()
        raw = {"type": "overbought", "confidence": 0.8}
        s = norm.normalize(raw)
        assert s.signal_type == SignalType.MOMENTUM_OVERBOUGHT
        assert s.direction == -1

    def test_oversold(self):
        norm = IndicatorSignalNormalizer()
        raw = {"type": "oversold", "confidence": 0.7}
        s = norm.normalize(raw)
        assert s.signal_type == SignalType.MOMENTUM_OVERSOLD
        assert s.direction == 1

    def test_bullish(self):
        norm = IndicatorSignalNormalizer()
        raw = {"type": "bullish", "confidence": 0.6}
        s = norm.normalize(raw)
        assert s.signal_type == SignalType.TREND_BULLISH
        assert s.direction == 1


class TestCZSCSignalNormalizer:
    def test_bi_end(self):
        norm = CZSCSignalNormalizer()
        raw = {"type": "bi_end", "confidence": 0.5, "direction": 1}
        s = norm.normalize(raw)
        assert s.signal_type == SignalType.CZSC_BI_END
        assert s.source == SignalSource.CZSC


class TestSignalNormalizerRegistry:
    def test_register_and_normalize(self):
        registry = SignalNormalizerRegistry()
        registry.register(SignalSource.LPPL, LPPLSignalNormalizer())
        assert registry.has(SignalSource.LPPL)
        raw = {"type": "bubble", "confidence": 0.8}
        s = registry.normalize(SignalSource.LPPL, raw)
        assert s.signal_type == SignalType.LPPL_BUBBLE

    def test_unregistered_source_returns_default(self):
        registry = SignalNormalizerRegistry()
        raw = {"confidence": 0.5, "symbol": "TEST"}
        s = registry.normalize(SignalSource.NTF, raw)
        assert s.signal_type == SignalType.TREND_NEUTRAL
        assert s.source == SignalSource.NTF

    def test_create_default_registry(self):
        registry = create_default_registry()
        assert registry.has(SignalSource.LPPL)
        assert registry.has(SignalSource.WYCKOFF)
        assert registry.has(SignalSource.INDICATOR)
        assert registry.has(SignalSource.CZSC)


# ───────────────────────── aggregator ─────────────────────────


class TestSourceWeightManager:
    def test_default_weight(self):
        wm = SourceWeightManager()
        assert wm.get_weight(SignalSource.LPPL) == 1.0

    def test_set_weight(self):
        wm = SourceWeightManager()
        wm.set_weight(SignalSource.LPPL, 2.0)
        assert wm.get_weight(SignalSource.LPPL) == 2.0

    def test_negative_weight_clamped(self):
        wm = SourceWeightManager()
        wm.set_weight(SignalSource.LPPL, -1.0)
        assert wm.get_weight(SignalSource.LPPL) == 0.0

    def test_update_weights_from_performance(self):
        wm = SourceWeightManager()
        wm.update_weights({SignalSource.LPPL: 3.0, SignalSource.WYCKOFF: 1.0})
        assert wm.get_weight(SignalSource.LPPL) > wm.get_weight(SignalSource.WYCKOFF)


class TestSignalAggregator:
    def _make_signals(self, directions, confidences=None):
        if confidences is None:
            confidences = [0.5] * len(directions)
        return [
            Signal(
                signal_type=SignalType.TREND_BULLISH,
                source=SignalSource.LPPL,
                direction=d,
                confidence=c,
            )
            for d, c in zip(directions, confidences)
        ]

    def test_empty_aggregation(self):
        agg = SignalAggregator()
        result = agg.aggregate([])
        assert result.signal.direction == 0

    def test_weighted_average_all_bullish(self):
        agg = SignalAggregator(method=SignalAggregationMethod.WEIGHTED_AVERAGE)
        signals = self._make_signals([1, 1, 1])
        result = agg.aggregate(signals)
        assert result.signal.direction == 1

    def test_weighted_average_all_bearish(self):
        agg = SignalAggregator(method=SignalAggregationMethod.WEIGHTED_AVERAGE)
        signals = self._make_signals([-1, -1, -1])
        result = agg.aggregate(signals)
        assert result.signal.direction == -1

    def test_majority_vote(self):
        agg = SignalAggregator(method=SignalAggregationMethod.MAJORITY_VOTE)
        signals = self._make_signals([1, 1, -1])
        result = agg.aggregate(signals)
        assert result.signal.direction == 1

    def test_max_confidence(self):
        agg = SignalAggregator(method=SignalAggregationMethod.MAX_CONFIDENCE)
        signals = self._make_signals([-1, 1, 1], confidences=[0.9, 0.3, 0.4])
        result = agg.aggregate(signals)
        assert result.signal.direction == -1  # highest confidence is -1

    def test_consensus_threshold(self):
        agg = SignalAggregator(method=SignalAggregationMethod.CONSENSUS_THRESHOLD)
        signals = self._make_signals([1, 1, 1, -1, -1])
        result = agg.aggregate(signals)
        # 3/5 = 0.6 >= threshold 0.6, direction = 1
        assert result.signal.direction == 1

    def test_consensus_calculation(self):
        agg = SignalAggregator()
        signals = self._make_signals([1, 1, -1])
        consensus = agg.calculate_consensus(signals, threshold=0.5)
        assert consensus.consensus_direction == 1
        assert consensus.agreement_ratio == pytest.approx(2 / 3)

    def test_aggregate_by_type(self):
        agg = SignalAggregator()
        signals = [
            Signal(signal_type=SignalType.LPPL_BUBBLE, direction=1, confidence=0.8),
            Signal(signal_type=SignalType.LPPL_CRASH, direction=-1, confidence=0.7),
        ]
        result = agg.aggregate_by_type(signals)
        assert SignalType.LPPL_BUBBLE in result
        assert SignalType.LPPL_CRASH in result


class TestTimeWindowAggregator:
    def test_add_and_flush(self):
        twa = TimeWindowAggregator(window=timedelta(minutes=5))
        twa.add(Signal(signal_type=SignalType.TREND_BULLISH, direction=1, confidence=0.8))
        assert twa.buffer_size == 1
        results = twa.flush()
        assert len(results) >= 1


# ───────────────────────── quality ─────────────────────────


class TestSignalQualityAssessor:
    def test_bullish_hit(self):
        s = Signal(direction=1, price=10.0)
        prices = [10.0, 10.5, 11.0]  # +10% max return
        assert SignalQualityAssessor.assess(s, prices, lookahead=10) is True

    def test_bullish_miss(self):
        s = Signal(direction=1, price=10.0)
        prices = [10.0, 9.95, 9.9]  # max return < 1%
        assert SignalQualityAssessor.assess(s, prices, lookahead=10) is False

    def test_bearish_hit(self):
        s = Signal(direction=-1, price=10.0)
        prices = [10.0, 9.5, 9.0]  # -10% min return
        assert SignalQualityAssessor.assess(s, prices, lookahead=10) is True

    def test_neutral_returns_none(self):
        s = Signal(direction=0, price=10.0)
        prices = [10.0, 11.0]
        assert SignalQualityAssessor.assess(s, prices) is None

    def test_empty_prices_returns_none(self):
        s = Signal(direction=1, price=10.0)
        assert SignalQualityAssessor.assess(s, []) is None

    def test_calculate_hit_rate(self):
        s1 = Signal(direction=1, price=10.0)
        s2 = Signal(direction=-1, price=10.0)
        price_data = {
            s1.id: [10.0, 11.0],
            s2.id: [10.0, 9.0],
        }
        rate = SignalQualityAssessor.calculate_hit_rate([s1, s2], price_data, lookahead=5)
        assert rate == 1.0

    def test_calculate_accuracy(self):
        s1 = Signal(direction=1)
        s2 = Signal(direction=-1)
        actual = {s1.id: 1, s2.id: -1}
        acc = SignalQualityAssessor.calculate_accuracy([s1, s2], actual)
        assert acc == 1.0

    def test_precision_recall(self):
        # Both direction=1 and direction=-1 are "predicted positive" (direction != 0)
        s1 = Signal(direction=1)   # predicted positive, actual=True → TP
        s2 = Signal(direction=-1)  # predicted positive, actual=False → FP
        outcomes = {s1.id: True, s2.id: False}
        metrics = SignalQualityAssessor.calculate_precision_recall([s1, s2], outcomes)
        assert metrics.precision == 0.5  # TP/(TP+FP) = 1/2
        assert metrics.recall == 1.0     # TP/(TP+FN) = 1/1
        assert abs(metrics.f1_score - 2/3) < 1e-6


class TestSignalQualityTracker:
    def test_record_and_get_quality(self):
        tracker = SignalQualityTracker()
        tracker.record_outcome("s1", True, SignalSource.LPPL, SignalType.LPPL_BUBBLE)
        tracker.record_outcome("s2", False, SignalSource.LPPL, SignalType.LPPL_BUBBLE)
        tracker.record_outcome("s3", True, SignalSource.WYCKOFF, SignalType.WYCKOFF_SPRING)

        overall = tracker.get_overall_quality()
        assert overall.sample_size == 3
        assert abs(overall.hit_rate - 2 / 3) < 1e-6

        lppl_q = tracker.get_source_quality(SignalSource.LPPL)
        assert lppl_q.sample_size == 2
        assert abs(lppl_q.hit_rate - 0.5) < 1e-6

        spring_q = tracker.get_type_quality(SignalType.WYCKOFF_SPRING)
        assert spring_q.sample_size == 1
        assert spring_q.hit_rate == 1.0

    def test_summary(self):
        tracker = SignalQualityTracker()
        tracker.record_outcome("s1", True, SignalSource.LPPL, SignalType.LPPL_BUBBLE)
        report = tracker.summary()
        assert "overall" in report
        assert "by_source" in report
        assert "by_type" in report
