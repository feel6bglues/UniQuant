"""SQ-C1 结构分可达性验收测试 (P1-C 再校准).

验证 _compute_structural_score 的真实输出能否触发 _apply_structural_adjustment
的升级/降级路径。先 RED (当前 FAIL) → 改权重/阈值 → GREEN。
"""

from scripts.wyckoff_fixtures import (
    synthetic_accumulation,
    synthetic_accumulation_event_sequence,
    synthetic_sine_wave,
)
from uniquant.brain.wyckoff.engine import (
    _apply_structural_adjustment,
    _compute_structural_score,
)
from uniquant.brain.wyckoff.events import detect_all_events
from uniquant.brain.wyckoff.models import ConfidenceResult, WyckoffPhase


def _mk_conf(level="C"):
    return ConfidenceResult(
        level=level,
        bc_located=True,
        spring_lps_verified=False,
        counterfactual_passed=True,
        rr_qualified=False,
        multiframe_aligned=False,
        position_size="试仓",
        reason="test",
    )


def _compute_score_from_fixture(fixture_fn, seed=42):
    """通过真实 fixture 路径计算结构分，走 _compute_structural_score 全链路。"""
    df = fixture_fn(seed=seed)
    events = detect_all_events(df)
    event_types = [ev.event_type for ev in events]
    engine = __import__("uniquant.brain.wyckoff.engine", fromlist=[""]).WyckoffEngine()
    report = engine.analyze(df, symbol="TEST.SH")
    phase = report.structure.phase if report.structure else WyckoffPhase.UNKNOWN
    step3 = getattr(report, "step3", None) or type(
        "S3",
        (),
        {
            "spring_detected": False,
            "spring_quality": "无",
            "utad_detected": False,
        },
    )()
    return _compute_structural_score(event_types, phase, step3)


def test_upgrade_reachable_via_real_path():
    """T1: 真实权重路径产生的结构分 ≥ 升级阈值 (55)。

    当前 _compute_structural_score 数学上限 65.67 < 旧阈值 70，
    此测试应 FAIL 直到权重/阈值修正。
    """
    score = _compute_score_from_fixture(synthetic_accumulation_event_sequence)
    assert score >= 55.0, (
        f"升级路径不可达: 最高分 {score} < 55.0。"
        f"需调整 _compute_structural_score 权重或 _apply_structural_adjustment 阈值。"
    )


def test_upgrade_actually_raises_confidence():
    """T2: 升级后置信度确实提升 (C→B)。"""
    score = _compute_score_from_fixture(synthetic_accumulation_event_sequence)
    cr = _mk_conf("C")
    result = _apply_structural_adjustment(cr, score)
    rank = {"A": 0, "B": 1, "C": 2, "D": 3}
    assert rank[result.level] < rank[cr.level], (
        f"升级路径未生效: score={score}, level={cr.level}→{result.level}"
    )


def test_downgrade_path_triggerable():
    """T3: 降级路径仍可触发 (低分场景 ≤ 降级阈值 45)。"""
    score = _compute_score_from_fixture(synthetic_sine_wave, seed=123)
    cr = _mk_conf("B")
    result = _apply_structural_adjustment(cr, score)
    rank = {"A": 0, "B": 1, "C": 2, "D": 3}
    assert rank[result.level] > rank[cr.level], (
        f"降级路径未生效: score={score}, level={cr.level}→{result.level}"
    )


def test_five_condition_matrix_unchanged():
    """T4: 5 条件矩阵成员 (bc/rr/…) 在调整后不变。"""
    score = _compute_score_from_fixture(synthetic_accumulation_event_sequence)
    cr = _mk_conf("C")
    out = _apply_structural_adjustment(cr, score)
    assert out.bc_located == cr.bc_located
    assert out.counterfactual_passed == cr.counterfactual_passed
    assert out.rr_qualified == cr.rr_qualified
    assert out.multiframe_aligned == cr.multiframe_aligned
    assert out.position_size == cr.position_size
    assert out.reason == cr.reason


def test_score_distribution_spread():
    """T5: 分布拉开——明确相位与 UNKNOWN 的得分差距应 > 5 分。"""
    acc_score = _compute_score_from_fixture(synthetic_accumulation_event_sequence)
    unknown_score = _compute_score_from_fixture(synthetic_sine_wave, seed=123)
    assert acc_score - unknown_score > 5.0, (
        f"分布未拉开: accumulation={acc_score}, unknown={unknown_score}, "
        f"差={acc_score - unknown_score:.2f} < 5.0"
    )


def test_wso_base_amplification_spreads_scores():
    """P1-2: BASE_AMPLIFICATION 放大统计验证的事件 base，恢复判别力。

    验证两个同相位 fixture 仅因事件质量不同即可拉开得分差距
    (改造前 WSO base ±0.1 被相位启发式淹没，得分几乎无法区分)。
    """
    acc_full = _compute_score_from_fixture(synthetic_accumulation_event_sequence)
    accum_simple = _compute_score_from_fixture(synthetic_accumulation)
    assert acc_full - accum_simple > 3.0, (
        f"P1-2: 完整积累事件序列应明显高于单事件积累, "
        f"acc_full={acc_full}, accum_simple={accum_simple}"
    )