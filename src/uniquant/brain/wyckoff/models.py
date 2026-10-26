# -*- coding: utf-8 -*-
"""
Wyckoff Analysis Data Models
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from uniquant.brain.wyckoff.domain_models import (
    BCPoint,
    ChartManifest,
    ChartManifestItem,
    ChipAnalysis,
    ConfidenceLevel,
    ImageEvidenceBundle,
    LimitMove,
    LimitMoveType,
    RiskRewardProjection,
    SCPoint,
    StressTest,
    SupportResistance,
    TradingPlan,
    VisualEvidence,
    VolumeLevel,
    WyckoffPhase,
    WyckoffSignal,
    WyckoffStructure,
)


@dataclass
class PreprocessingResult:
    trend_direction: str
    volume_label: str
    volatility_layer: str
    local_highs: List[Dict[str, Any]] = field(default_factory=list)
    local_lows: List[Dict[str, Any]] = field(default_factory=list)
    gap_candidates: List[Dict[str, Any]] = field(default_factory=list)
    long_wick_candidates: List[Dict[str, Any]] = field(default_factory=list)
    limit_anomalies: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BCResult:
    found: bool
    candidate_index: int
    candidate_date: str
    candidate_price: float
    volume_label: str
    enhancement_signals: List[str] = field(default_factory=list)


@dataclass
class PhaseResult:
    phase: str
    boundary_upper_zone: str
    boundary_lower_zone: str
    boundary_sources: List[str] = field(default_factory=list)


@dataclass
class EffortResult:
    phenomena: List[str] = field(default_factory=list)
    accumulation_evidence: float = 0.0
    distribution_evidence: float = 0.0
    net_bias: str = "neutral"


@dataclass
class PhaseCTestResult:
    spring_detected: bool = False
    utad_detected: bool = False
    st_detected: bool = False
    false_breakout_detected: bool = False
    spring_date: Optional[str] = None
    utad_date: Optional[str] = None


@dataclass
class CounterfactualResult:
    is_utad_not_breakout: str = "unknown"
    is_distribution_not_accumulation: str = "unknown"
    is_chaos_not_phase_c: str = "unknown"
    liquidity_vacuum_risk: str = "unknown"
    total_pro_score: float = 0.0
    total_con_score: float = 0.0
    conclusion_overturned: bool = False


@dataclass
class RiskAssessment:
    t1_risk_level: str = "unknown"
    t1_structural_description: str = ""
    rr_ratio: float = 0.0
    rr_assessment: str = "fail"
    freeze_until: Optional[str] = None


# ===== v3.0 数据结构 (REFACTOR_PLAN_WYCKOFF_V3_ENGINE.md P1) =====


@dataclass
class Rule0Result:
    """Step 0: BC/TR 定位扫描输出"""

    bc_found: bool = False
    bc_position: Optional[BCPoint] = None
    sc_found: bool = False
    sc_position: Optional[SCPoint] = None
    bc_in_chart: bool = False
    tr_upper: Optional[float] = None
    tr_lower: Optional[float] = None
    tr_source: str = "none"  # "bc_ar" | "sc_spring" | "rolling_range" | "none"
    validity: str = "insufficient"  # "full" | "partial" | "tr_fallback" | "insufficient"
    confidence_base: str = "D"  # 起评等级: A/B/C/D


@dataclass
class Step1Result:
    """Step 1: 大局观与宏观定调"""

    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    sub_phase: str = ""  # Phase A/B/C/D/E 细分
    unknown_candidate: str = ""
    prior_trend_pct: float = 0.0
    is_in_tr: bool = False
    short_trend_pct: float = 0.0
    relative_position: float = 0.0
    ma5: float = 0.0
    ma20: float = 0.0
    boundary_upper: float = 0.0
    boundary_lower: float = 0.0
    boundary_source: List[str] = field(default_factory=list)
    # P1-A: PnF hint 与检测器链分歧标记（None 表示无分歧）
    pnf_phase_divergence: Optional[str] = None


@dataclass
class Step2Result:
    """Step 2: 努力与结果"""

    phenomena: List[str] = field(default_factory=list)
    accumulation_evidence: float = 0.0
    distribution_evidence: float = 0.0
    net_bias: str = "neutral"  # "accumulation" | "distribution" | "neutral"
    has_breakaway_gap: bool = False   # 向上突破缺口
    has_exhaustion_gap: bool = False   # 向上竭尽缺口
    has_escape_gap: bool = False       # 向下逃逸缺口
    vdb_divergence: str = "none"  # P1-B: 量价背离标记 ("none"/"bullish_divergence"/"bearish_divergence")


@dataclass
class Step3Result:
    """Step 3: Spring/UTAD + T+1 风险"""

    spring_detected: bool = False
    spring_quality: str = "无"  # "一级(放量确认)" | "二级(缩量待确认)" | "无"
    spring_date: Optional[str] = None
    spring_low_price: Optional[float] = None
    utad_detected: bool = False
    utad_quality: str = "无"
    utad_date: Optional[str] = None
    st_detected: bool = False
    # P1-3 (2026-08-12 深入再研究定稿): SOS 候选独立布尔标注字段。
    # st_detected 的语义化别名，不复用 signal_type="sos_candidate"。
    sos_candidate_detected: bool = False
    lps_confirmed: bool = False  # v3.0 规则6
    lps_stage: str = "not_test"  # P0-A: "not_test" | "test_held" | "lps_confirmed" | "invalidated"
    test_low: Optional[float] = None  # P0-A: 测试K线最低价
    spring_volume: str = ""
    t1_max_drawdown_pct: float = 0.0
    t1_verdict: str = "安全"  # "安全" | "偏薄" | "超限"
    t1_description: str = ""


@dataclass
class V3CounterfactualResult:
    """Step 3.5: 反事实压力测试 (v3.0增强版)"""

    utad_not_breakout: str = "unknown"
    distribution_not_accumulation: str = "unknown"
    chaos_not_phase_c: str = "unknown"
    liquidity_vacuum_risk: str = "unknown"
    total_pro_score: float = 0.0
    total_con_score: float = 0.0
    conclusion_overturned: bool = False
    counterfactual_scenario: str = ""
    forward_evidence: List[str] = field(default_factory=list)
    backward_evidence: List[str] = field(default_factory=list)


@dataclass
class StopLossResult:
    """规则10: 精确止损"""

    entry_price: float = 0.0
    stop_loss_price: float = 0.0
    stop_pct: float = 0.0
    precision_warning: bool = False
    liquidity_risk_warning: str = ""
    stop_logic: str = ""


@dataclass
class RiskRewardResult:
    """Step 4: 盈亏比投影"""

    entry_price: float = 0.0
    stop_loss: float = 0.0
    first_target: float = 0.0
    first_target_source: str = ""  # "tr_upper" | "bearish_candle" | "gap_lower"
    rr_ratio: float = 0.0
    rr_verdict: str = "fail"  # "excellent" | "pass" | "marginal" | "fail"
    gain_pct: float = 0.0


@dataclass
class ConfidenceResult:
    """规则8: 置信度矩阵"""

    level: str = "D"  # "A" | "B" | "C" | "D"
    bc_located: bool = False  # 条件①
    spring_lps_verified: bool = False  # 条件②
    counterfactual_passed: bool = False  # 条件③
    rr_qualified: bool = False  # 条件④
    multiframe_aligned: bool = False  # 条件⑤
    position_size: str = ""
    reason: str = ""
    bypassed: bool = False  # True if result from early-return path, not full R8 matrix
    # SQ-C1: 结构完整性评分 (0-100) — 置信度矩阵的结构维度输入
    structural_score: float = 0.0


@dataclass
class V3TradingPlan:
    """Step 5: 机构级实战交易计划"""

    current_assessment: str = ""
    multi_timeframe_statement: str = ""
    execution_preconditions: List[str] = field(default_factory=list)
    direction: str = "空仓观望"
    entry_trigger: str = ""
    observation_window: str = ""
    stop_loss: Optional[StopLossResult] = None
    target: Optional[RiskRewardResult] = None
    confidence: Optional[ConfidenceResult] = None
    false_breakout_detected: bool = False  # CF-C4: 突破后 3 列内跌回 → 假突破惩罚


@dataclass
class AnalysisResult:
    """分析结果 - 融合引擎输出"""

    symbol: str = ""
    asset_type: str = "stock"  # "stock" or "index"
    analysis_date: str = ""
    input_sources: List[str] = field(default_factory=list)  # ["data", "images"]
    timeframes_seen: List[str] = field(default_factory=list)  # ["daily", "weekly", "60m"]

    # 核心字段
    bc_found: bool = False
    phase: str = "unknown"  # accumulation/markup/distribution/markdown/no_trade_zone
    micro_action: str = ""

    # 边界与量能
    boundary_upper_zone: str = ""  # 上边界区域
    boundary_lower_zone: str = ""  # 下边界区域
    volume_profile_label: str = ""  # 量能标签

    # 特殊信号
    spring_detected: bool = False
    utad_detected: bool = False

    # 风险评估
    counterfactual_summary: str = ""  # 反事实总结
    t1_risk_assessment: str = ""  # T+1 风险评估
    rr_assessment: str = ""  # 盈亏比评估 (pass/fail)

    # 交易计划字段
    decision: str = "no_trade_zone"  # long_setup/watch_only/no_trade_zone/abandon
    trigger: str = ""
    invalidation: str = ""
    target_1: str = ""
    confidence: str = "D"  # A/B/C/D
    abandon_reason: str = ""  # 放弃原因
    conflicts: List[str] = field(default_factory=list)  # 冲突列表
    image_bundle: Optional[ImageEvidenceBundle] = None
    consistency_score: str = ""
    weekly_context: str = ""
    intraday_context: str = ""


@dataclass
class AnalysisState:
    """分析状态 - 状态持久化"""

    symbol: str = ""
    asset_type: str = "stock"
    analysis_date: str = ""

    # 上次分析结果
    last_phase: str = ""
    last_micro_action: str = ""
    last_confidence: str = "D"

    # 关键状态
    bc_found: bool = False
    spring_detected: bool = False
    freeze_until: Optional[str] = None  # Spring 冷冻期截止日期
    watch_status: str = "none"  # none/watching/cooling_down

    # 触发器状态
    trigger_armed: bool = False
    trigger_text: str = ""
    invalid_level: str = ""
    target_1: str = ""

    # 上下文
    weekly_context: str = ""
    intraday_context: str = ""
    conflict_summary: Any = field(default_factory=list)

    # 决策记录
    last_decision: str = ""
    abandon_reason: str = ""


@dataclass
class DailyRuleResult:
    symbol: str
    asset_type: str
    analysis_date: str
    input_source: str
    preprocessing: PreprocessingResult
    bc_result: BCResult
    phase_result: PhaseResult
    effort_result: Optional[EffortResult]
    phase_c_test: Optional[PhaseCTestResult]
    counterfactual: Optional[CounterfactualResult]
    risk: Optional[RiskAssessment]
    plan: Optional[TradingPlan]
    confidence: str = "D"
    decision: str = "abandon"
    abandon_reason: str = ""


@dataclass
class TimeframeSnapshot:
    """单一周期快照"""

    period: str
    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    unknown_candidate: str = ""
    current_price: Optional[float] = None
    current_date: Optional[str] = None
    trading_range_high: Optional[float] = None
    trading_range_low: Optional[float] = None
    bc_price: Optional[float] = None
    sc_price: Optional[float] = None
    signal_type: str = "no_signal"
    signal_description: str = ""


@dataclass
class MultiTimeframeContext:
    """多周期上下文"""

    enabled: bool = False
    monthly: Optional[TimeframeSnapshot] = None
    weekly: Optional[TimeframeSnapshot] = None
    daily: Optional[TimeframeSnapshot] = None
    alignment: str = "single_timeframe"
    summary: str = ""
    constraint_note: str = ""
    # P2-1: MultiTimeframeResonance 标注 — 只标注，不反向信号
    resonance_count: int = 0
    resonance_dir: str = ""  # bullish | bearish | conflicting | ""
    resonance_strength: float = 0.0


@dataclass
class WyckoffReport:
    """威科夫分析报告"""

    symbol: str
    period: str  # "daily", "weekly", etc.
    structure: WyckoffStructure
    signal: WyckoffSignal
    risk_reward: RiskRewardProjection
    trading_plan: TradingPlan
    limit_moves: List[LimitMove] = field(default_factory=list)
    stress_tests: List[StressTest] = field(default_factory=list)
    chip_analysis: Optional[ChipAnalysis] = None
    engine_version: str = "v3.0"
    ruleset_version: str = "v3.0"

    # 多模态扩展字段
    image_evidence: Optional[ImageEvidenceBundle] = None
    analysis_result: Optional[AnalysisResult] = None
    pnf_analysis: Optional[dict] = None
    regime_phase: Optional[str] = None
    analysis_state: Optional[AnalysisState] = None
    multi_timeframe: Optional[MultiTimeframeContext] = None
    # CN-C4: 预复权状态探测 (pre_adjusted | raw | unknown)
    adjustment_status: str = "unknown"
    # SQ-C1: 结构完整性评分 (0-100，事件序列加权 + 相位/事件修正)
    structural_score: float = 0.0
    # RS-C1: 相对强弱分类 (leader | follower | weak_independent | systemic_decline | unknown)
    relative_strength: Optional[str] = None
    relative_strength_detail: Optional[dict] = None
    # P1-A: PnF hint 与检测器链分歧标记
    pnf_phase_divergence: Optional[str] = None
    # P1-B: VDB 量价背离标记
    vdb_divergence: str = "none"
    # P0-A: LPS 阶段判定
    lps_stage: str = "not_test"
    # P1-3: SOS 候选独立布尔标注 (不复用 signal_type)
    sos_candidate_detected: bool = False
    # P1-4~12: 标注面字段 (纯标注, 不改方向结论)
    evr_state: str = "none"  # "bullish_divergence" | "bearish_divergence" | "none"
    evr_level: int = 0  # 0-5
    evr_position_context: str = ""
    pattern_failure_detected: bool = False
    pattern_failure_ratio: float = 0.0
    no_supply_detected: bool = False
    nsd_detected: bool = False
    vdu_detected: bool = False
    event_cooldown_active: bool = False
    event_cooldown_days: int = 0
    range_score: float = 0.0
    avwap: float = 0.0
    bias200: float = 0.0

    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        lines = [
            f"# 威科夫分析报告 - {self.symbol}",
            f"**分析周期**: {self.period}",
            f"**引擎版本**: {self.engine_version} | **规则版本**: {self.ruleset_version}",
            "",
        ]

        if self.multi_timeframe and self.multi_timeframe.enabled:
            lines.extend(
                [
                    "## Step -1: 多周期总览",
                    f"- **一致性**: {self.multi_timeframe.alignment}",
                    f"- **结论摘要**: {self.multi_timeframe.summary}",
                    f"- **约束说明**: {self.multi_timeframe.constraint_note}",
                ]
            )
            if self.multi_timeframe.monthly:
                lines.append(
                    f"- **月线**: {self.multi_timeframe.monthly.phase.value} @ {self.multi_timeframe.monthly.current_date}"
                )
            if self.multi_timeframe.weekly:
                lines.append(
                    f"- **周线**: {self.multi_timeframe.weekly.phase.value} @ {self.multi_timeframe.weekly.current_date}"
                )
            if self.multi_timeframe.daily:
                lines.append(
                    f"- **日线**: {self.multi_timeframe.daily.phase.value} @ {self.multi_timeframe.daily.current_date}"
                )
            lines.append("")

        lines.extend(
            [
                "## Step 0: BC 定位扫描",
                f"- **BC点**: {self.structure.bc_point.date if self.structure.bc_point else '未找到'} @ {self.structure.bc_point.price if self.structure.bc_point else 'N/A'}",
                f"- **SC点**: {self.structure.sc_point.date if self.structure.sc_point else '未找到'} @ {self.structure.sc_point.price if self.structure.sc_point else 'N/A'}",
                "",
                "## Step 1: 大局观与宏观定调",
                f"- **当前阶段**: {self.structure.phase.value}",
                f"- **Unknown子状态**: {self.structure.unknown_candidate or 'N/A'}",
                f"- **震荡区间**: {self.structure.trading_range_low} - {self.structure.trading_range_high}",
                f"- **当前价格**: {self.structure.current_price}",
                "",
            ]
        )

        limit_moves_str = ""
        if self.limit_moves:
            lm_lines = [
                f"- **{lm.move_type.value}** @ {lm.date} ${lm.price}" for lm in self.limit_moves[:3]
            ]
            limit_moves_str = "\n".join(["## Step 1.5: 涨跌停与炸板异动"] + lm_lines)
            lines.append(limit_moves_str)

        lines.extend(
            [
                "",
                "## Step 2: 极端流动性与筹码微观扫描",
                f"- **量能状态**: {self.signal.volume_confirmation.value if self.signal.volume_confirmation else 'N/A'}",
            ]
        )

        if self.chip_analysis:
            chip_lines = []
            if self.chip_analysis.absorption_signature:
                chip_lines.append("检测到吸筹痕迹")
            if self.chip_analysis.distribution_signature:
                chip_lines.append("检测到派发痕迹")
            if self.chip_analysis.volume_price_divergence:
                chip_lines.append("⚠️ 量价背离警告")
            if self.chip_analysis.warnings:
                chip_lines.extend([f"⚠️ {w}" for w in self.chip_analysis.warnings])
            if chip_lines:
                lines.append("- " + "; ".join(chip_lines))

        lines.extend(
            [
                "",
                "## Step 3: T+1 风险评估",
                f"- **T+1风险**: {self.signal.t1_risk评估}",
                "",
                "## Step 3.5: 反事实压力测试",
            ]
        )

        if self.stress_tests:
            for st in self.stress_tests:
                status = "✅" if st.passes else "❌"
                lines.append(f"- {status} **{st.scenario_name}**: {st.outcome}")
        else:
            lines.append("- 无压力测试结果")

        # Calculate stop-loss risk percentage for T+1 color coding
        entry = self.risk_reward.entry_price or 0
        stop = self.risk_reward.stop_loss or 0
        if entry and stop and entry > stop:
            risk_pct = (entry - stop) / entry * 100
        else:
            risk_pct = 0.0
        if risk_pct < 3.0:
            risk_color = "🟢 绿灯（安全垫充足）"
        elif risk_pct <= 5.0:
            risk_color = "🟡 黄灯（风险偏高，限50%半仓）"
        else:
            risk_color = "🔴 红灯（极度危险，强制禁止做多）"

        lines.extend(
            [
                "",
                "## Step 4: 盈亏比投影",
                f"- **入场价**: {self.risk_reward.entry_price}",
                f"- **止损位**: {self.risk_reward.stop_loss}",
                f"- **第一目标**: {self.risk_reward.first_target}",
                f"- **盈亏比**: {self.risk_reward.reward_risk_ratio:.2f}",
                "",
                "## Step 5: 交易计划",
                f"- **【当前定性】**: {self.trading_plan.current_qualification}",
                f"- **【执行前提】**: {self.trading_plan.preconditions}",
                f"- **【操作方向】**: {self.trading_plan.direction}",
                f"- **【T+1 隔夜回撤评级】**: {risk_color}",
                f"- **【精确入场 Trigger】**: {self.trading_plan.trigger_condition}",
                f"- **【铁律止损点】**: {self.trading_plan.invalidation_point}",
                f"- **【第一目标位】**: {self.trading_plan.first_target}",
                "",
            ]
        )

        if self.trading_plan.spring_cooldown_days > 0:
            lines.append(f"- **【Spring冷静期】**: {self.trading_plan.spring_cooldown_days}天")

        if self.trading_plan.t1_blocked:
            lines.append("- **【T+1零容错】**: ❌ 阻止入场")

        lines.append(f"**【置信度等级】**: {self.trading_plan.confidence.value}")

        return "\n".join(lines)


__all__ = [
    "AnalysisResult",
    "AnalysisState",
    "BCPoint",
    "BCResult",
    "ChartManifest",
    "ChartManifestItem",
    "ChipAnalysis",
    "ConfidenceLevel",
    "ConfidenceResult",
    "CounterfactualResult",
    "DailyRuleResult",
    "EffortResult",
    "ImageEvidenceBundle",
    "LimitMove",
    "LimitMoveType",
    "MultiTimeframeContext",
    "PhaseCTestResult",
    "PhaseResult",
    "PreprocessingResult",
    "RiskAssessment",
    "RiskRewardProjection",
    "RiskRewardResult",
    "Rule0Result",
    "SCPoint",
    "Step1Result",
    "Step2Result",
    "Step3Result",
    "StopLossResult",
    "StressTest",
    "SupportResistance",
    "TimeframeSnapshot",
    "TradingPlan",
    "V3CounterfactualResult",
    "V3TradingPlan",
    "VisualEvidence",
    "VolumeLevel",
    "WyckoffPhase",
    "WyckoffReport",
    "WyckoffSignal",
    "WyckoffStructure",
]

