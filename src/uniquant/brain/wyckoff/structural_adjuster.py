# -*- coding: utf-8 -*-
"""
Wyckoff Structural Scoring and Adjustments Module.
"""

from typing import List, Optional

import pandas as pd

from uniquant.brain.wyckoff.models import (
    ConfidenceResult,
    WyckoffPhase,
)
from uniquant.brain.wyckoff.sequence import WyckoffScorer, event_sequence_score

# P1-2 (2026-08-07): WSO 事件序列 base 放大系数。
# 实证 WSO base 在真实数据上仅 ±0.1 量级，线性 min-max 导致结构分严重拥挤，
# 无法排序信号。放大统计验证过的 base，恢复事件质量的判别力。
BASE_AMPLIFICATION = 5.0


def _downgrade_confidence(level: str) -> str:
    """CF-C4: 假突破惩罚 → 置信度降 1 级 (A→B, B→C, C→D, D→D)."""
    order = ["A", "B", "C", "D"]
    if level in order:
        idx = order.index(level)
        return order[min(idx + 1, len(order) - 1)]
    return "D"


def _downgrade_direction(direction: str) -> str:
    """红蓝对抗 (2026-08-07) : ACCUMULATION 蓄势超额为负, 多头方向降 1 档。

    做多/买入 → 轻仓试探; 轻仓试探 → 观察等待; 其他保持。
    纯函数, 不改变空仓方向语义。
    """
    if direction in ("做多", "买入"):
        return "轻仓试探"
    if direction == "轻仓试探":
        return "观察等待"
    return direction


def _apply_structural_adjustment(
    confidence: ConfidenceResult, structural_score: float
) -> ConfidenceResult:
    """SQ-C1: 结构完整性评分作为置信度加权输入 (非破坏性，纯函数)。

    - 恒回填 structural_score 到 ConfidenceResult (不再恒为 0.0)。
    - 等级单调微调: 高结构分 (≥55) 升 1 级；低结构分 (≤45) 降 1 级；居中不变。
    - 阈值经 P1-C 可达性验证: 真实 _compute_structural_score 最高约 70.2，
      最低约 44.1，确保升级/降级路径均可达。
    - 5 条件矩阵成员 (bc/rr/…) 与 bypassed/reason 保持原样。
    - B+ 特殊等级归 B 处理，A/D 为边界 (不越界)。
    """
    result = ConfidenceResult(
        level=confidence.level,
        bc_located=confidence.bc_located,
        spring_lps_verified=confidence.spring_lps_verified,
        counterfactual_passed=confidence.counterfactual_passed,
        rr_qualified=confidence.rr_qualified,
        multiframe_aligned=confidence.multiframe_aligned,
        position_size=confidence.position_size,
        reason=confidence.reason,
        bypassed=confidence.bypassed,
        structural_score=float(structural_score),
    )

    order = ["A", "B", "C", "D"]
    base_level = "B" if confidence.level == "B+" else confidence.level
    if base_level not in order:
        return result

    idx = order.index(base_level)
    if structural_score >= 55.0:
        idx = max(idx - 1, 0)
    elif structural_score <= 45.0:
        idx = min(idx + 1, len(order) - 1)
    result.level = order[idx]
    return result


def _detect_adjustment_status(close) -> str:
    """CN-C4: 探测数据是否为前复权 (pre_adjusted) 或未复权 (raw)。

    启发式: A 股单日涨跌停上限 20%。前复权数据相邻收盘价 pct_change
    不应持续超过 20%；未复权数据在除权除息日会出现 >20% 收盘跳空。
    排除连续涨停结构 (前一日本身已涨停 >15%，次日跳空属正常)。
    """
    pct = pd.Series(close).astype(float).pct_change()
    over = (pct.abs() > 0.20) & (pct.shift(1).fillna(0.0).abs() <= 0.15)
    if int(over.sum()) >= 1:
        return "raw"
    return "pre_adjusted"


def _compute_structural_score(
    event_types: List[str],
    phase,
    step3,
    scorer: Optional[WyckoffScorer] = None,
) -> float:
    """SQ-C1: 结构完整性评分 (0-100)，纯函数可复现。

    - event_sequence_score 对事件序列加权 → base ∈ [-1, 1]；
    - 若 scorer 提供且 WSS 已加载 → 使用 scorer.score_sequence 取 blended 评分；
    - 明确相位 (非 unknown) +0.20，unknown 相位 -0.10 (拉开分布)；
    - spring/utad 已确认按质量加成 (0.07/0.03)；
    - clamp 到 [-1, 1] → min-max 映射到 [0, 100]。
    - P1-C 再校准: 权重放大使升级路径可达 (max ≈ 70.2)，降级路径可达 (min ≈ 44.1)。
    - P1-2 修正 (2026-08-07): 实证 WSO base 在真实数据上仅有 ±0.1 量级
      (p90=0.068, max=0.094)，线性 min-max 浪费 3/4 输出范围导致结构分
      高度拥挤 (真实 p25=60.3 → p75=62.7, span 2.4)，无法排序信号。
      将统计验证过的 WSO 事件序列 base 放大 BASE_AMPLIFICATION 倍，
      使相位启发式不再淹没事件质量 → span 提升至 12+，且升级/降级
      路径 (reachability) 均保持可达。
    """
    if scorer is not None and scorer.wss.is_loaded:
        seq_key = ">".join(event_types)
        # 2026-08-18 修复: 复用 WSS lookup 但冷启动 WSO。
        # WSOScorer.score_events 的 EMA 平滑 (self._last_score/_is_warm) 是
        # 研究管线时间序列推进专用语义; 共享 scorer 跨股票/跨 MTF 调用会使
        # structural_score 被前一次平滑历史污染 (同一输入不同结果)。
        # 横截面评分须冷启动 → 每次以 lookup 引用新建无状态 scorer。
        fresh = WyckoffScorer(wss_lookup=scorer.wss.lookup)
        base, _ = fresh.score_sequence(event_types, seq_key)
    else:
        base, _ = event_sequence_score(event_types)
    base *= BASE_AMPLIFICATION
    phase_bonus = 0.20 if phase != WyckoffPhase.UNKNOWN else -0.10
    event_bonus = 0.0
    if step3.spring_detected:
        quality_str = str(getattr(step3, "spring_quality", "无"))
        quality_boost = 0.07 if "一级" in quality_str else 0.03
        event_bonus += quality_boost
    if step3.utad_detected:
        event_bonus += 0.07
    raw = max(-1.0, min(1.0, base + phase_bonus + event_bonus))
    return round((raw + 1.0) / 2.0 * 100.0, 2)


__all__ = [
    "BASE_AMPLIFICATION",
    "_apply_structural_adjustment",
    "_compute_structural_score",
    "_detect_adjustment_status",
    "_downgrade_confidence",
    "_downgrade_direction",
]
