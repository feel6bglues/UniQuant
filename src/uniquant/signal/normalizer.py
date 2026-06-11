"""信号归一化器

将各引擎的原始输出转换为标准 Signal 对象。
支持 LPPL、Wyckoff、指标、CZSC 四种归一化器，以及注册表模式。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List

from .models import Signal, SignalSource, SignalStrength, SignalType
from ..shared.time_provider import get_time_provider


# ───────────────────────── 归一化基类 ─────────────────────────

class SignalNormalizer(ABC):
    """信号归一化器抽象基类"""

    @abstractmethod
    def normalize(self, raw_signal: Dict[str, Any]) -> Signal:
        """单条归一化

        Args:
            raw_signal: 原始信号字典

        Returns:
            标准 Signal 对象
        """
        ...

    def normalize_batch(self, raw_signals: List[Dict[str, Any]]) -> List[Signal]:
        """批量归一化

        Args:
            raw_signals: 原始信号字典列表

        Returns:
            标准 Signal 对象列表
        """
        return [self.normalize(raw) for raw in raw_signals]

    @staticmethod
    def _compute_strength(confidence: float) -> SignalStrength:
        """根据置信度计算信号强度

        Args:
            confidence: 置信度 [0, 1]

        Returns:
            信号强度等级
        """
        if confidence >= 0.8:
            return SignalStrength.VERY_STRONG
        if confidence >= 0.6:
            return SignalStrength.STRONG
        if confidence >= 0.4:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK


# ───────────────────────── LPPL 归一化器 ─────────────────────────

class LPPLSignalNormalizer(SignalNormalizer):
    """LPPL 引擎信号归一化器"""

    _TYPE_MAP: Dict[str, SignalType] = {
        "bubble": SignalType.LPPL_BUBBLE,
        "crash": SignalType.LPPL_CRASH,
        "negative_bubble": SignalType.LPPL_NEGATIVE_BUBBLE,
        "anti_bubble": SignalType.LPPL_NEGATIVE_BUBBLE,
    }

    def normalize(self, raw_signal: Dict[str, Any]) -> Signal:
        raw_type = raw_signal.get("type", raw_signal.get("signal_type", ""))
        signal_type = self._TYPE_MAP.get(raw_type, SignalType.TREND_NEUTRAL)
        confidence = float(raw_signal.get("confidence", raw_signal.get("bubble_confidence", 0.5)))
        strength = self._compute_strength(confidence)

        direction = 0
        if signal_type == SignalType.LPPL_BUBBLE:
            direction = 1
        elif signal_type == SignalType.LPPL_CRASH:
            direction = -1

        return Signal(
            signal_type=signal_type,
            source=SignalSource.LPPL,
            symbol=raw_signal.get("symbol", ""),
            direction=direction,
            strength=strength,
            confidence=confidence,
            timestamp=raw_signal.get("timestamp", get_time_provider().now()),
            price=raw_signal.get("price", 0.0),
            value=raw_signal.get("value", 0.0),
            metadata={k: v for k, v in raw_signal.items() if k not in ("type", "signal_type", "confidence", "symbol", "timestamp", "price", "value")},
        )


# ───────────────────────── Wyckoff 归一化器 ─────────────────────────

class WyckoffSignalNormalizer(SignalNormalizer):
    """Wyckoff 引擎信号归一化器"""

    _TYPE_MAP: Dict[str, SignalType] = {
        "accumulation": SignalType.WYCKOFF_ACCUMULATION,
        "distribution": SignalType.WYCKOFF_DISTRIBUTION,
        "spring": SignalType.WYCKOFF_SPRING,
        "utad": SignalType.WYCKOFF_UTAD,
        "lps": SignalType.WYCKOFF_LPS,
        "sow": SignalType.WYCKOFF_SOW,
    }

    _DIRECTION_MAP: Dict[SignalType, int] = {
        SignalType.WYCKOFF_ACCUMULATION: 1,
        SignalType.WYCKOFF_SPRING: 1,
        SignalType.WYCKOFF_LPS: 1,
        SignalType.WYCKOFF_DISTRIBUTION: -1,
        SignalType.WYCKOFF_UTAD: -1,
        SignalType.WYCKOFF_SOW: -1,
    }

    def normalize(self, raw_signal: Dict[str, Any]) -> Signal:
        raw_type = raw_signal.get("type", raw_signal.get("signal_type", ""))
        signal_type = self._TYPE_MAP.get(raw_type, SignalType.TREND_NEUTRAL)
        confidence = float(raw_signal.get("confidence", 0.5))
        strength = self._compute_strength(confidence)
        direction = self._DIRECTION_MAP.get(signal_type, 0)

        return Signal(
            signal_type=signal_type,
            source=SignalSource.WYCKOFF,
            symbol=raw_signal.get("symbol", ""),
            direction=direction,
            strength=strength,
            confidence=confidence,
            timestamp=raw_signal.get("timestamp", get_time_provider().now()),
            price=raw_signal.get("price", 0.0),
            value=raw_signal.get("value", 0.0),
            metadata={k: v for k, v in raw_signal.items() if k not in ("type", "signal_type", "confidence", "symbol", "timestamp", "price", "value")},
        )


# ───────────────────────── 指标归一化器 ─────────────────────────

class IndicatorSignalNormalizer(SignalNormalizer):
    """技术指标信号归一化器，基于关键词匹配"""

    def normalize(self, raw_signal: Dict[str, Any]) -> Signal:
        raw_type = raw_signal.get("type", raw_signal.get("signal_type", "")).lower()
        confidence = float(raw_signal.get("confidence", 0.5))
        strength = self._compute_strength(confidence)

        signal_type = SignalType.TREND_NEUTRAL
        direction = 0

        if "overbought" in raw_type:
            signal_type = SignalType.MOMENTUM_OVERBOUGHT
            direction = -1
        elif "oversold" in raw_type:
            signal_type = SignalType.MOMENTUM_OVERSOLD
            direction = 1
        elif "divergence" in raw_type:
            signal_type = SignalType.MOMENTUM_DIVERGENCE
            direction = raw_signal.get("direction", 0)
        elif "breakout" in raw_type:
            signal_type = SignalType.PATTERN_BREAKOUT
            direction = raw_signal.get("direction", 1)
        elif "surge" in raw_type:
            signal_type = SignalType.VOLUME_SURGE
            direction = raw_signal.get("direction", 1)
        elif "climax" in raw_type:
            signal_type = SignalType.VOLUME_CLIMAX
            direction = raw_signal.get("direction", -1)
        elif "bullish" in raw_type:
            signal_type = SignalType.TREND_BULLISH
            direction = 1
        elif "bearish" in raw_type:
            signal_type = SignalType.TREND_BEARISH
            direction = -1
        else:
            direction = raw_signal.get("direction", 0)

        return Signal(
            signal_type=signal_type,
            source=SignalSource.INDICATOR,
            symbol=raw_signal.get("symbol", ""),
            direction=direction,
            strength=strength,
            confidence=confidence,
            timestamp=raw_signal.get("timestamp", get_time_provider().now()),
            price=raw_signal.get("price", 0.0),
            value=raw_signal.get("value", 0.0),
            metadata={k: v for k, v in raw_signal.items() if k not in ("type", "signal_type", "confidence", "symbol", "timestamp", "price", "value", "direction")},
        )


# ───────────────────────── CZSC 归一化器 ─────────────────────────

class CZSCSignalNormalizer(SignalNormalizer):
    """缠论 (CZSC) 信号归一化器"""

    _TYPE_MAP: Dict[str, SignalType] = {
        "bi_end": SignalType.CZSC_BI_END,
        "zhongshu_3rd": SignalType.CZSC_ZHONGSHU_3RD,
        "trend_exhaust": SignalType.CZSC_TREND_EXHAUST,
    }

    def normalize(self, raw_signal: Dict[str, Any]) -> Signal:
        raw_type = raw_signal.get("type", raw_signal.get("signal_type", ""))
        signal_type = self._TYPE_MAP.get(raw_type, SignalType.TREND_NEUTRAL)
        confidence = float(raw_signal.get("confidence", 0.5))
        strength = self._compute_strength(confidence)
        direction = raw_signal.get("direction", 0)

        return Signal(
            signal_type=signal_type,
            source=SignalSource.CZSC,
            symbol=raw_signal.get("symbol", ""),
            direction=direction,
            strength=strength,
            confidence=confidence,
            timestamp=raw_signal.get("timestamp", get_time_provider().now()),
            price=raw_signal.get("price", 0.0),
            value=raw_signal.get("value", 0.0),
            metadata={k: v for k, v in raw_signal.items() if k not in ("type", "signal_type", "confidence", "symbol", "timestamp", "price", "value", "direction")},
        )


# ───────────────────────── 归一化器注册表 ─────────────────────────

class SignalNormalizerRegistry:
    """归一化器注册表，管理来源到归一化器的映射"""

    def __init__(self) -> None:
        self._normalizers: Dict[SignalSource, SignalNormalizer] = {}

    def register(self, source: SignalSource, normalizer: SignalNormalizer) -> None:
        """注册归一化器

        Args:
            source: 信号来源
            normalizer: 对应的归一化器实例
        """
        self._normalizers[source] = normalizer

    def unregister(self, source: SignalSource) -> None:
        """注销归一化器"""
        self._normalizers.pop(source, None)

    def has(self, source: SignalSource) -> bool:
        """检查来源是否已注册归一化器"""
        return source in self._normalizers

    def normalize(self, source: SignalSource, raw_signal: Dict[str, Any]) -> Signal:
        """使用对应归一化器处理单条信号

        未注册来源的信号会创建默认 Signal 对象（保留 raw_signal 为 metadata）。

        Args:
            source: 信号来源
            raw_signal: 原始信号字典

        Returns:
            标准 Signal 对象
        """
        normalizer = self._normalizers.get(source)
        if normalizer is not None:
            return normalizer.normalize(raw_signal)

        # 未注册来源，创建默认 Signal
        confidence = float(raw_signal.get("confidence", 0.5))
        return Signal(
            signal_type=SignalType.TREND_NEUTRAL,
            source=source,
            symbol=raw_signal.get("symbol", ""),
            direction=raw_signal.get("direction", 0),
            strength=SignalNormalizer._compute_strength(confidence),
            confidence=confidence,
            timestamp=raw_signal.get("timestamp", get_time_provider().now()),
            price=raw_signal.get("price", 0.0),
            value=raw_signal.get("value", 0.0),
            metadata={"raw_signal": raw_signal},
        )

    def normalize_batch(self, source: SignalSource, raw_signals: List[Dict[str, Any]]) -> List[Signal]:
        """批量归一化

        Args:
            source: 信号来源
            raw_signals: 原始信号字典列表

        Returns:
            标准 Signal 对象列表
        """
        normalizer = self._normalizers.get(source)
        if normalizer is not None:
            return normalizer.normalize_batch(raw_signals)
        return [self.normalize(source, raw) for raw in raw_signals]


def create_default_registry() -> SignalNormalizerRegistry:
    """创建包含全部 4 个内置归一化器的注册表

    Returns:
        预配置的注册表实例
    """
    registry = SignalNormalizerRegistry()
    registry.register(SignalSource.LPPL, LPPLSignalNormalizer())
    registry.register(SignalSource.WYCKOFF, WyckoffSignalNormalizer())
    registry.register(SignalSource.INDICATOR, IndicatorSignalNormalizer())
    registry.register(SignalSource.CZSC, CZSCSignalNormalizer())
    return registry
