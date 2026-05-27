"""信号数据模型

定义信号系统的全部数据结构：信号类型枚举、信号来源、强度等级、
核心 Signal 数据类、批量信号容器 SignalBatch、共识结果 SignalConsensus、
聚合信号 AggregatedSignal。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional


# ───────────────────────── 信号类型枚举 (27 种, 9 大类) ─────────────────────────

class SignalType(Enum):
    """信号类型枚举，覆盖 9 大类 27 种信号"""

    # 趋势
    TREND_BULLISH = "trend_bullish"
    TREND_BEARISH = "trend_bearish"
    TREND_NEUTRAL = "trend_neutral"

    # 动量
    MOMENTUM_OVERBOUGHT = "momentum_overbought"
    MOMENTUM_OVERSOLD = "momentum_oversold"
    MOMENTUM_DIVERGENCE = "momentum_divergence"

    # 波动
    VOLATILITY_BREAKOUT = "volatility_breakout"
    VOLATILITY_CONTRACTION = "volatility_contraction"

    # 量能
    VOLUME_SURGE = "volume_surge"
    VOLUME_CLIMAX = "volume_climax"

    # 形态
    PATTERN_BREAKOUT = "pattern_breakout"
    PATTERN_REVERSAL = "pattern_reversal"
    PATTERN_CONTINUATION = "pattern_continuation"

    # LPPL
    LPPL_BUBBLE = "lppl_bubble"
    LPPL_CRASH = "lppl_crash"
    LPPL_NEGATIVE_BUBBLE = "lppl_negative_bubble"

    # Wyckoff
    WYCKOFF_ACCUMULATION = "wyckoff_accumulation"
    WYCKOFF_DISTRIBUTION = "wyckoff_distribution"
    WYCKOFF_SPRING = "wyckoff_spring"
    WYCKOFF_UTAD = "wyckoff_utad"
    WYCKOFF_LPS = "wyckoff_lps"
    WYCKOFF_SOW = "wyckoff_sow"

    # 缠论
    CZSC_BI_END = "czsc_bi_end"
    CZSC_ZHONGSHU_3RD = "czsc_zhongshu_3rd"
    CZSC_TREND_EXHAUST = "czsc_trend_exhaust"

    # 复合
    COMPOSITE_CONSENSUS = "composite_consensus"
    COMPOSITE_DIVERGENCE = "composite_divergence"


# ───────────────────────── 信号来源枚举 (10 种) ─────────────────────────

class SignalSource(Enum):
    """信号来源枚举"""
    LPPL = "lppl"
    WYCKOFF = "wyckoff"
    CZSC = "czsc"
    NTF = "ntf"
    FSM = "fsm"
    REGIME = "regime"
    INDICATOR = "indicator"
    SCREENER = "screener"
    FACTOR = "factor"
    ENSEMBLE = "ensemble"


# ───────────────────────── 信号强度枚举 (4 级) ─────────────────────────

class SignalStrength(IntEnum):
    """信号强度枚举，支持 >= 比较运算符"""
    WEAK = 1
    MODERATE = 2
    STRONG = 3
    VERY_STRONG = 4


# ───────────────────────── 核心 Signal 数据类 ─────────────────────────

@dataclass
class Signal:
    """信号核心数据结构

    Attributes:
        id: 唯一标识 (UUID4)
        symbol: 证券代码
        signal_type: 信号类型
        source: 信号来源
        direction: 方向 1=看多, -1=看空, 0=中性
        strength: 信号强度
        confidence: 置信度 [0, 1]
        timestamp: 生成时间
        expiration: 过期时间
        price: 触发价格
        value: 信号值
        metadata: 附加元数据
        parent_id: 父信号 ID
    """
    signal_type: SignalType = SignalType.TREND_NEUTRAL
    source: SignalSource = SignalSource.INDICATOR
    symbol: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    direction: int = 0
    strength: SignalStrength = SignalStrength.MODERATE
    confidence: float = 0.5
    timestamp: datetime = field(default_factory=datetime.now)
    expiration: Optional[datetime] = None
    price: float = 0.0
    value: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_id: Optional[str] = None

    def is_expired(self) -> bool:
        """信号是否已过期"""
        if self.expiration is None:
            return False
        return datetime.now() > self.expiration

    def is_bullish(self) -> bool:
        """是否看多信号"""
        return self.direction > 0

    def is_bearish(self) -> bool:
        """是否看空信号"""
        return self.direction < 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "signal_type": self.signal_type.value,
            "source": self.source.value,
            "direction": self.direction,
            "strength": self.strength.value,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "expiration": self.expiration.isoformat() if self.expiration else None,
            "price": self.price,
            "value": self.value,
            "metadata": self.metadata,
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Signal:
        """从字典创建实例"""
        return cls(
            id=data.get("id", uuid.uuid4().hex),
            symbol=data.get("symbol", ""),
            signal_type=SignalType(data["signal_type"]) if "signal_type" in data else SignalType.TREND_NEUTRAL,
            source=SignalSource(data["source"]) if "source" in data else SignalSource.INDICATOR,
            direction=data.get("direction", 0),
            strength=SignalStrength(data["strength"]) if "strength" in data else SignalStrength.MODERATE,
            confidence=data.get("confidence", 0.5),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            expiration=datetime.fromisoformat(data["expiration"]) if data.get("expiration") else None,
            price=data.get("price", 0.0),
            value=data.get("value", 0.0),
            metadata=data.get("metadata", {}),
            parent_id=data.get("parent_id"),
        )


# ───────────────────────── 批量信号容器 ─────────────────────────

@dataclass
class SignalBatch:
    """批量信号容器，提供过滤方法"""
    signals: List[Signal] = field(default_factory=list)

    def add(self, signal: Signal) -> None:
        """添加信号"""
        self.signals.append(signal)

    def by_type(self, signal_type: SignalType) -> List[Signal]:
        """按信号类型过滤"""
        return [s for s in self.signals if s.signal_type == signal_type]

    def by_source(self, source: SignalSource) -> List[Signal]:
        """按信号来源过滤"""
        return [s for s in self.signals if s.source == source]

    def by_strength(self, min_strength: SignalStrength) -> List[Signal]:
        """按最小强度过滤"""
        return [s for s in self.signals if s.strength >= min_strength]

    def by_direction(self, direction: int) -> List[Signal]:
        """按方向过滤"""
        return [s for s in self.signals if s.direction == direction]

    def bullish(self) -> List[Signal]:
        """看多信号"""
        return self.by_direction(1)

    def bearish(self) -> List[Signal]:
        """看空信号"""
        return self.by_direction(-1)

    def neutral(self) -> List[Signal]:
        """中性信号"""
        return self.by_direction(0)

    def average_confidence(self) -> float:
        """批次平均置信度"""
        if not self.signals:
            return 0.0
        return sum(s.confidence for s in self.signals) / len(self.signals)

    def __len__(self) -> int:
        return len(self.signals)

    def __getitem__(self, index: int) -> Signal:
        return self.signals[index]


# ───────────────────────── 共识结果 ─────────────────────────

@dataclass
class SignalConsensus:
    """共识结果数据结构

    Attributes:
        consensus_direction: 共识方向
        consensus_confidence: 共识置信度
        agreement_ratio: 一致性比例
        total_sources: 总来源数
        agreeing_sources: 一致来源数
    """
    consensus_direction: int = 0
    consensus_confidence: float = 0.0
    agreement_ratio: float = 0.0
    total_sources: int = 0
    agreeing_sources: int = 0

    def is_strong_consensus(self, threshold: float = 0.75) -> bool:
        """判断是否为强共识

        Args:
            threshold: 一致性比例阈值
        """
        return self.agreement_ratio >= threshold


# ───────────────────────── 聚合信号 ─────────────────────────

@dataclass
class AggregatedSignal:
    """聚合后的信号

    Attributes:
        signal: 聚合后的标准信号
        contributing_signals: 贡献信号列表
        sources: 来源集合
        agreement_ratio: 一致性比例
        weighted_score: 加权得分
    """
    signal: Signal = field(default_factory=Signal)
    contributing_signals: List[Signal] = field(default_factory=list)
    sources: set = field(default_factory=set)
    agreement_ratio: float = 0.0
    weighted_score: float = 0.0
