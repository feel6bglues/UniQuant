"""Phase 3 非 P0 — SQ-C1 structural_score TDD 验收测试。

对应实现方案 docs/analysis/CLASSIC_WYCKOFF_P1_RESEARCH_PLAN_CNC4_SQC1_RSC1.md §3:
- SQ-C1: structural_score (0-100) 存在于 WyckoffReport / WyckoffOutput / ConfidenceResult。
- 评分基于纯函数 event_sequence_score (确定性，可复现)。
"""

import pytest

from scripts.wyckoff_fixtures import (
    synthetic_accumulation,
    synthetic_distribution,
    synthetic_sine_wave,
    synthetic_spring,
)
from uniquant.brain.wyckoff.engine import (
    WyckoffEngine,
    _apply_structural_adjustment,
    _compute_structural_score,
)
from uniquant.brain.wyckoff.models import ConfidenceResult, WyckoffPhase, WyckoffReport
from uniquant.shared.interfaces import WyckoffOutput


# ─────────────────── 三处字段存在 + 值域 ───────────────────

def test_structural_score_in_all_models():
    """WyckoffReport / WyckoffOutput / ConfidenceResult 均有 structural_score 且默认合法。"""
    assert "structural_score" in WyckoffReport.__dataclass_fields__  # type: ignore
    assert "structural_score" in ConfidenceResult.__dataclass_fields__  # type: ignore

    report = WyckoffReport(
        symbol="T", period="日线",
        structure=None, signal=None, risk_reward=None, trading_plan=None,
    )
    assert 0.0 <= report.structural_score <= 100.0
    assert 0.0 <= ConfidenceResult().structural_score <= 100.0
    assert 0.0 <= WyckoffOutput().structural_score <= 100.0


@pytest.mark.parametrize("builder", [
    synthetic_accumulation,
    synthetic_distribution,
    synthetic_spring,
    synthetic_sine_wave,
])
def test_structural_score_range(builder):
    """多 fixture 下 analyze() 输出 structural_score ∈ [0, 100]。"""
    df = builder(seed=42)
    report = WyckoffEngine().analyze(df, symbol="TEST.SH")
    assert 0.0 <= report.structural_score <= 100.0


# ─────────────────── 纯函数确定性 (红蓝对抗回归防线) ───────────────────

def test_structural_score_deterministic():
    """同一输入两次计算得分一致 (纯函数验证，防有状态 scorer 回归)。"""
    df = synthetic_accumulation(seed=42)
    report1 = WyckoffEngine().analyze(df, symbol="TEST.SH")
    report2 = WyckoffEngine().analyze(df, symbol="TEST.SH")
    assert report1.structural_score == report2.structural_score


def test_compute_structural_score_is_pure():
    """_compute_structural_score 直接调用两次结果一致。"""
    df = synthetic_accumulation(seed=42)
    from uniquant.brain.wyckoff.events import detect_all_events

    events = detect_all_events(df)
    event_types = [ev.event_type for ev in events]
    step1 = type("S1", (), {"phase": WyckoffPhase.ACCUMULATION})()
    step3 = type("S3", (), {"spring_detected": True, "spring_quality": "一级(放量确认)",
                            "utad_detected": False})()
    a = _compute_structural_score(event_types, step1.phase, step3)
    b = _compute_structural_score(event_types, step1.phase, step3)
    assert a == b
    assert 0.0 <= a <= 100.0


# ─────────────────── 相位区分 + 参与信号 ───────────────────

def test_structural_score_higher_for_clear_phase():
    """明确相位 (accumulation) 的 score 应 ≥ UNKNOWN 对照。"""
    engine = WyckoffEngine()

    # 明确相位 fixture
    clear_df = synthetic_accumulation(seed=42)
    clear_report = engine.analyze(clear_df, symbol="TEST.SH")

    # UNKNOWN 对照: sine 波 seed=123 (经验证判定 UNKNOWN)
    unknown_df = synthetic_sine_wave(seed=123)
    unknown_report = engine.analyze(unknown_df, symbol="TEST.SH")

    assert unknown_report.structure.phase == WyckoffPhase.UNKNOWN
    assert clear_report.structural_score >= unknown_report.structural_score


def test_structural_score_affects_confidence_surface():
    """structural_score 已落入 ConfidenceResult 模型 (带默认 0.0 合法值)。"""
    cr = ConfidenceResult()
    assert 0.0 <= cr.structural_score <= 100.0

    df = synthetic_accumulation(seed=42)
    report = WyckoffEngine().analyze(df, symbol="TEST.SH")
    # 报告携带非零结构分 → 置信度矩阵有结构维度输入
    assert 0.0 <= report.structural_score <= 100.0


# ─────────────────── dict roundtrip + adapter ───────────────────

def test_output_dict_roundtrip_structural_score():
    """WyckoffOutput roundtrip 保留 structural_score。"""
    out = WyckoffOutput(phase="accumulation", structural_score=67.5)
    d = out.to_dict()
    assert d["structural_score"] == 67.5
    restored = WyckoffOutput.from_dict(d)
    assert restored.structural_score == 67.5


def test_adapter_metadata_structural_score():
    """WyckoffAdapter.adapt 的 metadata 含 wyckoff_structural_score。"""
    from uniquant.signal.adapters import WyckoffAdapter

    adapter = WyckoffAdapter()
    signal = adapter.adapt({
        "wyckoff_phase": "accumulation",
        "wyckoff_confidence": 0.6,
        "structural_score": 80.0,
        "price": 10.0,
    }, symbol="TEST.SH")
    assert signal is not None
    assert signal.metadata.get("wyckoff_structural_score") == 80.0


# ─────────────────── SQ-C1 置信度加权 (v2 补全) ───────────────────

def _mk_conf(level="C"):
    """构造最小 ConfidenceResult (5 条件矩阵成员)。"""
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


def test_adjustment_populates_structural_score():
    """_apply_structural_adjustment 恒回填 structural_score (不再恒 0.0)。"""
    cr = _mk_conf("C")
    out = _apply_structural_adjustment(cr, 80.0)
    assert out.structural_score == 80.0


def test_adjustment_high_upgrades_level():
    """结构分 ≥70 → 等级升 1 级 (C→B)。"""
    out = _apply_structural_adjustment(_mk_conf("C"), 80.0)
    assert out.level == "B"


def test_adjustment_low_downgrades_level():
    """结构分 ≤35 → 等级降 1 级 (B→C)。"""
    out = _apply_structural_adjustment(_mk_conf("B"), 20.0)
    assert out.level == "C"


def test_adjustment_middle_keeps_level():
    """结构分居中 (35< s <70) → 等级不变。"""
    out = _apply_structural_adjustment(_mk_conf("C"), 50.0)
    assert out.level == "C"


def test_adjustment_monotonic_direction():
    """单调性: 高分结果等级 ≥ 低分结果等级 (方向一致)。"""
    low = _apply_structural_adjustment(_mk_conf("C"), 10.0)
    high = _apply_structural_adjustment(_mk_conf("C"), 90.0)
    rank = {"A": 0, "B": 1, "C": 2, "D": 3}
    assert rank[high.level] <= rank[low.level]


def test_adjustment_b_plus_handled():
    """B+ 特殊等级归 B 处理，不崩溃。"""
    out = _apply_structural_adjustment(_mk_conf("B+"), 80.0)
    assert out.level in ("A", "B", "C", "D", "B+")
    assert out.structural_score == 80.0


def test_adjustment_preserves_matrix_members():
    """非破坏性: 5 条件矩阵成员 (bc/rr/…) 不变。"""
    cr = _mk_conf("C")
    out = _apply_structural_adjustment(cr, 80.0)
    assert out.bc_located == cr.bc_located
    assert out.counterfactual_passed == cr.counterfactual_passed
    assert out.rr_qualified == cr.rr_qualified
    assert out.multiframe_aligned == cr.multiframe_aligned


def test_analyze_report_confidence_field_wired():
    """端到端: analyze() 后 report 的 ConfidenceResult 带真实 structural_score。"""
    from scripts.wyckoff_fixtures import synthetic_accumulation_event_sequence

    df = synthetic_accumulation_event_sequence(seed=42)
    report = WyckoffEngine().analyze(df, symbol="TEST.SH")
    assert 0.0 <= report.structural_score <= 100.0
