# -*- coding: utf-8 -*-
"""
Wyckoff Base Domain Data Models and Types.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class WyckoffPhase(Enum):
    """威科夫周期阶段"""

    ACCUMULATION = "accumulation"  # 积累阶段
    MARKUP = "markup"  # 上涨阶段
    DISTRIBUTION = "distribution"  # 派发阶段
    MARKDOWN = "markdown"  # 下跌阶段
    UNKNOWN = "unknown"  # 未知/不可交易


class ConfidenceLevel(Enum):
    """置信度等级"""

    A = "A"  # 高置信度 - 信号清晰
    B = "B"  # 中置信度 - 信号较明确
    C = "C"  # 低置信度 - 信号模糊
    D = "D"  # 放弃 - 信号杂乱/无法辨认


class VolumeLevel(Enum):
    """量能等级（相对描述）"""

    EXTREME_HIGH = "天量/爆量"  # 显著高于平均
    HIGH = "高于平均"  # 明显高于平均
    AVERAGE = "平均"  # 接近平均
    LOW = "萎缩"  # 低于平均
    EXTREME_LOW = "地量"  # 极度萎缩


@dataclass
class BCPoint:
    """买入高潮点 (Buying Climax)"""

    date: str
    price: float
    volume_level: VolumeLevel
    is_extremum: bool = True
    confidence_score: int = 0  # BC 置信度评分（0-10）


@dataclass
class SCPoint:
    """卖出高潮点 (Selling Climax)"""

    date: str
    price: float
    volume_level: VolumeLevel
    is_extremum: bool = True
    confidence_score: int = 0  # SC 置信度评分（0-10）


@dataclass
class SupportResistance:
    """支撑/阻力位"""

    level: float
    type: str  # "support" or "resistance"
    source: str  # "BC", "SC", "AR", "自然回撤"
    strength: float = 1.0  # 0-1, 强度


@dataclass
class WyckoffStructure:
    """威科夫结构"""

    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    unknown_candidate: str = ""
    bc_point: Optional[BCPoint] = None
    sc_point: Optional[SCPoint] = None
    support_levels: List[SupportResistance] = field(default_factory=list)
    resistance_levels: List[SupportResistance] = field(default_factory=list)
    trading_range_high: Optional[float] = None
    trading_range_low: Optional[float] = None
    current_price: Optional[float] = None
    current_date: Optional[str] = None


@dataclass
class WyckoffSignal:
    """威科夫交易信号"""

    signal_type: str = "no_signal"  # "spring", "utad", "sos", "lps", "bc", "sc", "no_signal"
    trigger_price: Optional[float] = None
    volume_confirmation: Optional[VolumeLevel] = None
    confidence: ConfidenceLevel = ConfidenceLevel.D
    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    description: str = ""
    t1_risk评估: str = ""  # T+1 风险评估
    spring_date: Optional[str] = None  # Spring 信号日期 (T+3 冷冻期用)


@dataclass
class RiskRewardProjection:
    """盈亏比投影"""

    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    first_target: Optional[float] = None
    reward_risk_ratio: float = 0.0
    risk_amount: float = 0.0
    reward_amount: float = 0.0
    structure_based: str = ""  # 结构描述


@dataclass
class TradingPlan:
    """交易计划"""

    direction: str = "空仓观望"  # "long" or "empty" (空仓观望)
    trigger_condition: str = ""  # 入场触发条件
    invalidation_point: str = ""  # 失效点/止损点
    first_target: str = ""  # 第一目标位
    confidence: ConfidenceLevel = ConfidenceLevel.D
    preconditions: str = ""  # 执行前提
    current_qualification: str = ""  # 当前定性
    spring_cooldown_days: int = 0  # Spring 冷静期
    t1_blocked: bool = False  # T+1 零容错阻止
    current_assessment: str = ""  # 新规则引擎字段
    execution_preconditions: List[str] = field(default_factory=list)  # 新规则引擎字段
    entry_trigger: str = ""  # 新规则引擎字段
    invalidation: str = ""  # 新规则引擎字段
    target_1: str = ""  # 新规则引擎字段

    def __post_init__(self) -> None:
        if self.entry_trigger and not self.trigger_condition:
            self.trigger_condition = self.entry_trigger
        elif self.trigger_condition and not self.entry_trigger:
            self.entry_trigger = self.trigger_condition

        if self.invalidation and not self.invalidation_point:
            self.invalidation_point = self.invalidation
        elif self.invalidation_point and not self.invalidation:
            self.invalidation = self.invalidation_point

        if self.target_1 and not self.first_target:
            self.first_target = self.target_1
        elif self.first_target and not self.target_1:
            self.target_1 = self.first_target

        if self.current_assessment and not self.current_qualification:
            self.current_qualification = self.current_assessment
        elif self.current_qualification and not self.current_assessment:
            self.current_assessment = self.current_qualification

        if self.execution_preconditions and not self.preconditions:
            self.preconditions = "; ".join(self.execution_preconditions)
        elif self.preconditions and not self.execution_preconditions:
            self.execution_preconditions = [self.preconditions]


@dataclass
class ChartManifestItem:
    """图片清单中的单个文件"""

    file_path: str
    file_name: str
    relative_dir: str
    modified_time: str
    symbol: str
    inferred_timeframe: str
    image_quality: str


@dataclass
class ChartManifest:
    """图片清单摘要"""

    files: List[ChartManifestItem] = field(default_factory=list)
    total_count: int = 0
    usable_count: int = 0
    scan_time: str = ""


@dataclass
class VisualEvidence:
    """单张或一组图表的视觉结论"""

    visual_trend: str = "unclear"
    visual_phase_hint: str = "unclear"
    visual_boundaries: Dict[str, Any] = field(default_factory=dict)
    visual_anomalies: List[str] = field(default_factory=list)
    visual_volume_label: str = "unclear"


class LimitMoveType(Enum):
    """涨跌停类型"""

    LIMIT_UP = "涨停"
    LIMIT_DOWN = "跌停"
    BREAK_LIMIT_UP = "炸板"  # 涨停被砸
    BREAK_LIMIT_DOWN = "撬板"  # 跌停被撬
    NONE = "无"


@dataclass
class LimitMove:
    """涨跌停事件"""

    date: str
    move_type: LimitMoveType
    price: float
    volume_level: VolumeLevel
    is_broken: bool = False


@dataclass
class StressTest:
    """反事实压力测试"""

    scenario_name: str = ""
    scenario_description: str = ""
    outcome: str = ""
    passes: bool = False
    risk_level: str = ""  # "低", "中", "高"


@dataclass
class ChipAnalysis:
    """筹码微观分析（v2: 加入成交额维度的量价背离检测）"""

    absorption_signature: bool = False  # 吸筹痕迹
    distribution_signature: bool = False  # 派发痕迹
    volume_price_divergence: bool = False  # 量价背离（基于volume）
    amount_price_divergence: bool = False  # 金额背离（基于amount）
    institutional_footprint: bool = False  # 机构痕迹
    divergence_score: float = 0.0  # 连续量价背离评分 [-1, 1]
    amount_divergence_score: float = 0.0  # 连续金额背离评分 [-1, 1]
    avg_price_deviation: float = 0.0  # 收盘价偏离均价的程度
    money_flow_trend: float = 0.0  # 资金流向趋势 [-1, 1]
    warnings: List[str] = field(default_factory=list)


@dataclass
class ImageEvidenceBundle:
    """图像证据包 - 图像引擎输出"""

    files: List[str] = field(default_factory=list)  # 图片文件列表
    detected_timeframe: str = (
        "unknown_tf"  # 检测到的时间周期 (weekly/daily/60m/30m/15m/5m/unknown_tf)
    )
    image_quality: str = "medium"  # 图像质量 (high/medium/low/unusable)
    visual_trend: str = "unclear"  # 视觉趋势 (uptrend/downtrend/range/unclear)
    visual_phase_hint: str = "unclear"  # 视觉阶段提示 (possible_accumulation/possible_markup/possible_distribution/possible_markdown/unclear)
    visual_boundaries: List[dict] = field(
        default_factory=list
    )  # 视觉边界 [{'type': 'upper/lower', 'level': float}]
    visual_anomalies: List[str] = field(
        default_factory=list
    )  # 视觉异常 (长上影/长下影/跳空/假突破/快速收回/放量滞涨)
    visual_volume_labels: str = (
        "unclear"  # 视觉量能标签 (extreme_high/above_average/contracted/extreme_contracted/unclear)
    )
    trust_level: str = "medium"  # 信任级别 (high/medium/low)
    manifest: Optional[ChartManifest] = None  # 新图像引擎字段
    detected_timeframes: List[str] = field(default_factory=list)  # 新图像引擎字段
    overall_image_quality: str = ""  # 新图像引擎字段
    visual_evidence_list: List[VisualEvidence] = field(default_factory=list)  # 新图像引擎字段

    def __post_init__(self) -> None:
        if self.manifest is None:
            manifest_items = [
                ChartManifestItem(
                    file_path=file_path,
                    file_name=file_path.split("/")[-1],
                    relative_dir="",
                    modified_time="",
                    symbol="unassigned",
                    inferred_timeframe=self.detected_timeframe,
                    image_quality=self.image_quality,
                )
                for file_path in self.files
            ]
            self.manifest = ChartManifest(
                files=manifest_items,
                total_count=len(manifest_items),
                usable_count=len(manifest_items),
                scan_time="",
            )

        if self.detected_timeframes:
            if not self.detected_timeframe or self.detected_timeframe == "unknown_tf":
                self.detected_timeframe = self.detected_timeframes[0]
        elif self.detected_timeframe and self.detected_timeframe != "unknown_tf":
            self.detected_timeframes = [self.detected_timeframe]

        if self.overall_image_quality:
            if not self.image_quality:
                self.image_quality = self.overall_image_quality
        else:
            self.overall_image_quality = self.image_quality

        if not self.visual_evidence_list and (
            self.visual_trend != "unclear"
            or self.visual_phase_hint != "unclear"
            or self.visual_boundaries
            or self.visual_anomalies
            or self.visual_volume_labels != "unclear"
        ):
            boundaries: Dict[str, Any]
            if isinstance(self.visual_boundaries, dict):
                boundaries = self.visual_boundaries
            else:
                boundaries = {"levels": self.visual_boundaries}
            self.visual_evidence_list = [
                VisualEvidence(
                    visual_trend=self.visual_trend,
                    visual_phase_hint=self.visual_phase_hint,
                    visual_boundaries=boundaries,
                    visual_anomalies=self.visual_anomalies,
                    visual_volume_label=self.visual_volume_labels,
                )
            ]


__all__ = [
    "BCPoint",
    "ChartManifest",
    "ChartManifestItem",
    "ChipAnalysis",
    "ConfidenceLevel",
    "ImageEvidenceBundle",
    "LimitMove",
    "LimitMoveType",
    "RiskRewardProjection",
    "SCPoint",
    "StressTest",
    "SupportResistance",
    "TradingPlan",
    "VisualEvidence",
    "VolumeLevel",
    "WyckoffPhase",
    "WyckoffSignal",
    "WyckoffStructure",
]
