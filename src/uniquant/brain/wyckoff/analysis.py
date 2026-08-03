# -*- coding: utf-8 -*-
"""
Wyckoff analysis functions - extracted from engine.py
"""

import copy
from typing import Optional

import numpy as np
import pandas as pd

from uniquant.brain.wyckoff.models import (
    ChipAnalysis,
    ConfidenceLevel,
    ImageEvidenceBundle,
    MultiTimeframeContext,
    RiskRewardProjection,
    TimeframeSnapshot,
    TradingPlan,
    WyckoffPhase,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
)
from uniquant.brain.wyckoff.rules import V3Rules
from uniquant.brain.wyckoff.constants import (
    ANALYSIS_LOOKBACK,
    DIVERGENCE_WINDOW,
    MONEY_FLOW_LOOKBACK,
    PRICE_DEVIATION_LOOKBACK,
)
from uniquant.brain.wyckoff.phase_analysis import MultiTimeframeResonance
from uniquant.shared.config_loader import get_config


def analyze_chips(df: pd.DataFrame, structure: WyckoffStructure) -> ChipAnalysis:
    """
    筹码微观分析（v2: 加入成交额维度的量价背离检测）

    核心改进:
    1. 同时使用volume和amount检测背离
    2. 计算连续背离评分而非仅bool
    3. 检测收盘价偏离均价的幅度
    4. 计算资金流向趋势
    """
    analysis = ChipAnalysis()
    recent = df.tail(ANALYSIS_LOOKBACK)

    if len(recent) < 10:
        return analysis

    # ---- 1. 价格与成交量变化 ----
    price_change = (recent["close"].iloc[-1] - recent["close"].iloc[0]) / recent["close"].iloc[
        0
    ]
    volume_change = (recent["volume"].iloc[-1] - recent["volume"].iloc[0]) / recent[
        "volume"
    ].iloc[0]

    # 量价背离 (volume-based)
    if price_change > 0.05 and volume_change < -0.3:
        analysis.volume_price_divergence = True
        analysis.warnings.append("量价背离：价格上涨但量能萎缩")

    if price_change < -0.05 and volume_change > 0.3:
        analysis.distribution_signature = True

    if price_change > 0.05 and volume_change > 0.2:
        analysis.absorption_signature = True
        analysis.institutional_footprint = True

    # ---- 2. 成交额维度分析 (amount-based) ----
    if "amount" in recent.columns and recent["amount"].notna().all():
        amount_change = (recent["amount"].iloc[-1] - recent["amount"].iloc[0]) / max(
            recent["amount"].iloc[0], 1
        )

        # 金额背离: 价格与成交额方向不一致
        if price_change > 0.05 and amount_change < -0.3:
            analysis.amount_price_divergence = True
            analysis.warnings.append("金额背离：价格上涨但成交额萎缩（买方力量衰竭）")

        # 机构吸筹痕迹: 价格微跌但成交额放大
        if -0.05 < price_change < 0 and amount_change > 0.2:
            analysis.absorption_signature = True
            analysis.institutional_footprint = True
            analysis.warnings.append("机构吸筹迹象：价格微跌但成交额放大")

        # 派发痕迹: 价格微涨但成交额异常放大
        if 0 < price_change < 0.05 and amount_change > 0.3:
            analysis.distribution_signature = True
            analysis.warnings.append("派发迹象：价格微涨但成交额异常放大")

        # 计算平均成交价偏离度
        analysis.avg_price_deviation = compute_avg_price_deviation(recent)

        # 计算资金流向趋势
        analysis.money_flow_trend = compute_money_flow_trend(recent)

    # ---- 3. 连续背离评分（滑动窗口） ----
    divergence_scores = []
    amount_div_scores = []
    window = DIVERGENCE_WINDOW
    for i in range(window, len(recent)):
        p = (recent["close"].iloc[i] - recent["close"].iloc[i - window]) / recent["close"].iloc[
            i - window
        ]
        v = (recent["volume"].iloc[i] - recent["volume"].iloc[i - window]) / recent[
            "volume"
        ].iloc[i - window]
        # 背离评分: 正值=正价格负量能(熊背离), 负值=负价格正量能(牛背离)
        ds = p * (1 - v) if abs(v) > 0.1 else 0
        divergence_scores.append(ds)

        if "amount" in recent.columns:
            a = (recent["amount"].iloc[i] - recent["amount"].iloc[i - window]) / max(
                recent["amount"].iloc[i - window], 1
            )
            ad = p * (1 - a) if abs(a) > 0.1 else 0
            amount_div_scores.append(ad)

    analysis.divergence_score = (
        round(np.mean(divergence_scores), 4) if divergence_scores else 0.0
    )
    analysis.amount_divergence_score = (
        round(np.mean(amount_div_scores), 4) if amount_div_scores else 0.0
    )

    return analysis


def compute_avg_price_deviation(df: pd.DataFrame) -> float:
    """计算收盘价偏离成交均价的程度"""
    if "amount" not in df.columns:
        return 0.0
    recent = df.tail(PRICE_DEVIATION_LOOKBACK)
    avg_prices = recent["amount"] / recent["volume"].replace(0, 1)
    current_avg = avg_prices.iloc[-1]
    if current_avg == 0:
        return 0.0
    deviation = (recent["close"].iloc[-1] - current_avg) / current_avg
    return round(float(deviation), 4)


def compute_money_flow_trend(df: pd.DataFrame) -> float:
    """计算资金流向趋势 [-1, 1]"""
    if "amount" not in df.columns:
        return 0.0
    recent = df.tail(MONEY_FLOW_LOOKBACK)
    if len(recent) < 5:
        return 0.0
    # 资金流向: (close - avg_price) * volume，正值表示资金流入
    avg_prices = recent["amount"] / recent["volume"].replace(0, 1)
    money_flows = (recent["close"] - avg_prices) * recent["volume"]
    total_flow = money_flows.sum()
    total_volume = recent["volume"].sum()
    if total_volume == 0:
        return 0.0
    # 归一化到 [-1, 1]
    trend = total_flow / (total_volume * recent["close"].mean())
    return round(float(np.clip(trend, -1, 1)), 4)


def analyze_multiframe(
    df: pd.DataFrame,
    symbol: str,
    image_evidence: Optional[ImageEvidenceBundle],
    normalize_input_frame,
    resample_ohlcv,
    analyze_single,
    multi_timeframe_lookback_days: int,
    rules: V3Rules,
    index_df: Optional[pd.DataFrame] = None,
) -> WyckoffReport:
    """多周期分析"""
    frame = normalize_input_frame(df)
    if frame is None or len(frame) < 100:
        reason = f"数据不足，需要至少 100 根 K 线，当前只有 {len(frame) if frame is not None else 0} 根"
        return create_no_signal_report(symbol, "日线+周线+月线", reason)

    long_frame = frame.tail(multi_timeframe_lookback_days).reset_index(drop=True)
    weekly_df = resample_ohlcv(long_frame, "W-FRI")
    monthly_df = resample_ohlcv(long_frame, "ME")

    daily_report = analyze_single(frame, symbol, "日线", image_evidence, index_df)
    weekly_report = analyze_single(weekly_df, symbol, "周线")
    monthly_report = analyze_single(monthly_df, symbol, "月线")

    return merge_multitimeframe_reports(
        symbol=symbol,
        daily_report=daily_report,
        weekly_report=weekly_report,
        monthly_report=monthly_report,
        rules=rules,
    )


def _resonance_to_rule9_alignment(
    resonance_result: dict,
    monthly_phase: WyckoffPhase,
    weekly_phase: WyckoffPhase,
    daily_phase: WyckoffPhase,
) -> tuple[str, str]:
    """Map MultiTimeframeResonance output to rule9-compatible alignment_type/alignment_desc."""
    monthly_val = monthly_phase.value if hasattr(monthly_phase, 'value') else monthly_phase
    weekly_val = weekly_phase.value if hasattr(weekly_phase, 'value') else weekly_phase
    daily_val = daily_phase.value if hasattr(daily_phase, 'value') else daily_phase

    if monthly_val == 'markdown':
        return "markdown_override", "月线Markdown，强制空仓"
    if weekly_val == 'markdown':
        return "markdown_override", "周线Markdown，强制空仓"
    if monthly_val == 'distribution':
        return "distribution_override", "月线Distribution，降级"
    if weekly_val == 'distribution':
        return "distribution_override", "周线Distribution，降级"

    if resonance_result['resonance_count'] == 3 and resonance_result['resonance_dir'] != 'conflicting':
        direction = "多头" if resonance_result['resonance_dir'] == 'bullish' else "空头"
        return "fully_aligned", f"三周期{direction}共振"

    if weekly_val == 'markup' and monthly_val == 'markup':
        return "aligned", "月线+周线Markup支持日线"

    if weekly_val == 'unknown' and daily_val == 'markup':
        return "degraded", "周线Unknown，日线Markup降级"

    return "mixed", "多周期信号混合"


def merge_multitimeframe_reports(
    symbol: str,
    daily_report: WyckoffReport,
    weekly_report: WyckoffReport,
    monthly_report: WyckoffReport,
    rules: V3Rules,
) -> WyckoffReport:
    """多周期融合"""
    final_report = copy.deepcopy(daily_report)
    monthly_phase = monthly_report.structure.phase
    weekly_phase = weekly_report.structure.phase
    daily_phase = daily_report.structure.phase

    alignment = "mixed"
    if monthly_phase == weekly_phase == daily_phase:
        alignment = "fully_aligned"
    elif weekly_phase == daily_phase:
        alignment = "weekly_daily_aligned"
    elif monthly_phase == weekly_phase:
        alignment = "higher_timeframe_aligned"

    summary = (
        f"月线={monthly_phase.value} / 周线={weekly_phase.value} / 日线={daily_phase.value}"
    )
    constraint_note = "维持日线结论"

    # 使用规则9或MultiTimeframeResonance进行多周期一致性判断
    cfg = get_config()
    use_mtf_resonance = cfg.get("wyckoff.mtf_resonance", True)
    if use_mtf_resonance:
        resonance_result = MultiTimeframeResonance.resonance(
            monthly_phase.value, weekly_phase.value, daily_phase.value
        )
        alignment_type, alignment_desc = _resonance_to_rule9_alignment(
            resonance_result, monthly_phase, weekly_phase, daily_phase
        )
    else:
        alignment_type, alignment_desc = rules.rule9_multiframe_alignment(
            daily_phase, weekly_phase, monthly_phase
        )

    if alignment_type == "markdown_override":
        if (daily_report.trading_plan.direction == "做多" and (
            daily_report.signal.signal_type in ("spring", "sos_candidate", "markup")
        )):
            constraint_note = f"右侧强力突破信号，免于{alignment_desc}限制"
            final_report.trading_plan.direction = "做多"
            if "SOS" not in final_report.signal.description:
                final_report.signal.description = "检测到SOS候选信号 " + final_report.signal.description
                final_report.signal.signal_type = "sos_candidate"
        else:
            final_report.signal.signal_type = "no_signal"
            final_report.signal.confidence = ConfidenceLevel.D
            final_report.signal.description = f"{final_report.signal.description} {alignment_desc}"
            final_report.trading_plan.direction = "空仓观望"
            final_report.trading_plan.current_qualification = f"{final_report.trading_plan.current_qualification} {alignment_desc}"
            final_report.trading_plan.confidence = ConfidenceLevel.D
            constraint_note = alignment_desc
    elif alignment_type == "distribution_override":
        final_report.signal.signal_type = "no_signal"
        final_report.signal.confidence = ConfidenceLevel.D
        final_report.signal.description = f"{final_report.signal.description} {alignment_desc}"
        final_report.trading_plan.direction = "空仓观望"
        final_report.trading_plan.confidence = ConfidenceLevel.D
        constraint_note = alignment_desc
    elif alignment_type == "degraded":
        final_report.signal.confidence = ConfidenceLevel.C
        final_report.trading_plan.confidence = ConfidenceLevel.C
        constraint_note = alignment_desc
    elif alignment_type == "aligned":
        final_report.trading_plan.confidence = final_report.signal.confidence
        constraint_note = alignment_desc

    final_report.period = "日线+周线+月线"
    final_report.multi_timeframe = MultiTimeframeContext(
        enabled=True,
        monthly=build_timeframe_snapshot(monthly_report),
        weekly=build_timeframe_snapshot(weekly_report),
        daily=build_timeframe_snapshot(daily_report),
        alignment=alignment,
        summary=summary,
        constraint_note=constraint_note,
    )

    return final_report


def build_timeframe_snapshot(report: WyckoffReport) -> TimeframeSnapshot:
    """构建周期快照"""
    return TimeframeSnapshot(
        period=report.period,
        phase=report.structure.phase,
        unknown_candidate=report.structure.unknown_candidate,
        current_price=report.structure.current_price,
        current_date=report.structure.current_date,
        trading_range_high=report.structure.trading_range_high,
        trading_range_low=report.structure.trading_range_low,
        bc_price=report.structure.bc_point.price if report.structure.bc_point else None,
        sc_price=report.structure.sc_point.price if report.structure.sc_point else None,
        signal_type=report.signal.signal_type,
        signal_description=report.signal.description,
    )


def create_no_signal_report(symbol: str, period: str, reason: str) -> WyckoffReport:
    """创建无信号报告"""
    structure = WyckoffStructure(
        phase=WyckoffPhase.UNKNOWN,
        unknown_candidate="",
        bc_point=None,
        sc_point=None,
        current_price=0.0,
        current_date="",
    )

    signal = WyckoffSignal(
        signal_type="no_signal",
        confidence=ConfidenceLevel.D,
        description=reason,
    )

    risk_reward = RiskRewardProjection()
    trading_plan = TradingPlan(
        direction="空仓观望",
        current_qualification=reason,
        confidence=ConfidenceLevel.D,
    )

    return WyckoffReport(
        symbol=symbol,
        period=period,
        structure=structure,
        signal=signal,
        risk_reward=risk_reward,
        trading_plan=trading_plan,
        engine_version="v3.0",
        ruleset_version="v3.0",
    )
