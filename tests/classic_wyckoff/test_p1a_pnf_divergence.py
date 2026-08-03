"""P1-A: PnF hint degraded 标记 + 去 PnF 主导第 1 步。

测试 PnF hint 与检测器链的分歧标记逻辑。
第 1 步不改变相位结果，只输出分歧标记。
"""

from dataclasses import asdict

from scripts.wyckoff_fixtures import synthetic_accumulation
from uniquant.brain.wyckoff.engine import WyckoffEngine
from uniquant.brain.wyckoff.models import (
    RiskRewardProjection,
    TradingPlan,
    WyckoffPhase,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
)
from uniquant.brain.wyckoff.pnf import PointAndFigure
from uniquant.shared.interfaces import WyckoffOutput


# ───────────────────────── T1: 无分歧 ─────────────────────────

def test_no_divergence_when_pnf_matches_chain(monkeypatch):
    """PnF hint=accumulation 且检测器链也返回 ACCUMULATION → divergence=None。"""
    df = synthetic_accumulation(seed=42)
    engine = WyckoffEngine()

    monkeypatch.setattr(PointAndFigure, "wyckoff_phase_hint", lambda self: "accumulation")
    report = engine.analyze(df, symbol="TEST.SH")
    assert report.structure.phase == WyckoffPhase.ACCUMULATION
    divergence = getattr(report, "pnf_phase_divergence", None)
    assert divergence is None, f"预期无分歧，得到: {divergence}"


# ───────────────────────── T2: 有分歧 ─────────────────────────

def test_divergence_when_pnf_mismatches_chain(monkeypatch):
    """PnF hint=accumulation 但检测器链返回 UNKNOWN → divergence 含分歧字符串。"""
    df = synthetic_accumulation(seed=42)
    engine = WyckoffEngine()
    monkeypatch.setattr(PointAndFigure, "wyckoff_phase_hint", lambda self: "accumulation")
    # 让所有检测器返回 None，模拟检测器链找不到任何东西
    for detector_name in [
        "_detect_markup", "_detect_distribution", "_detect_markdown",
        "_detect_accumulation", "_detect_spring", "_detect_utad", "_detect_sos",
    ]:
        monkeypatch.setattr(engine, detector_name, lambda *a, **kw: None)
    report = engine.analyze(df, symbol="TEST.SH")
    divergence = getattr(report, "pnf_phase_divergence", None)
    assert divergence is not None, "预期有分歧，但得到 None"
    assert "PnF" in divergence and "DetectorChain" in divergence, \
        f"分歧字符串应含 PnF 和 DetectorChain，得到: {divergence}"
    assert report.structure.phase == WyckoffPhase.ACCUMULATION, \
        f"相位仍应为 ACCUMULATION，得到: {report.structure.phase}"


# ───────────────────────── T3: PnF hint=None ─────────────────────────

def test_no_divergence_when_pnf_hint_none(monkeypatch):
    """PnF hint=None → 走原逻辑，divergence=None。"""
    df = synthetic_accumulation(seed=42)
    engine = WyckoffEngine()
    monkeypatch.setattr(PointAndFigure, "wyckoff_phase_hint", lambda self: None)
    report = engine.analyze(df, symbol="TEST.SH")
    divergence = getattr(report, "pnf_phase_divergence", None)
    assert divergence is None, f"PnF hint=None 时 divergence 应为 None，得到: {divergence}"


# ───────────────────────── T4: 序列化/反序列化 ─────────────────────────

def test_wyckoff_report_serialization():
    """WyckoffReport 的 pnf_phase_divergence 字段可序列化/反序列化。"""
    report = WyckoffReport(
        symbol="TEST.SH",
        period="daily",
        structure=WyckoffStructure(phase=WyckoffPhase.ACCUMULATION),
        signal=WyckoffSignal(signal_type="accumulation", trigger_price=100.0),
        risk_reward=RiskRewardProjection(),
        trading_plan=TradingPlan(),
        pnf_phase_divergence="PnF=accumulation, DetectorChain=unknown",
    )
    as_dict = asdict(report)
    assert as_dict.get("pnf_phase_divergence") == "PnF=accumulation, DetectorChain=unknown"
    report2 = WyckoffReport(
        symbol=as_dict["symbol"],
        period=as_dict["period"],
        structure=WyckoffStructure(phase=WyckoffPhase.ACCUMULATION),
        signal=WyckoffSignal(signal_type="accumulation", trigger_price=100.0),
        risk_reward=RiskRewardProjection(),
        trading_plan=TradingPlan(),
        pnf_phase_divergence=as_dict.get("pnf_phase_divergence"),
    )
    assert report2.pnf_phase_divergence == "PnF=accumulation, DetectorChain=unknown"


# ───────────────────────── T5: WyckoffOutput 序列化 ─────────────────────────

def test_wyckoff_output_serialization():
    """WyckoffOutput.to_dict/from_dict 不丢 pnf_phase_divergence 字段。"""
    out = WyckoffOutput(
        phase="accumulation",
        confidence=0.7,
        pnf_phase_divergence="PnF=accumulation, DetectorChain=unknown",
    )
    d = out.to_dict()
    assert d.get("pnf_phase_divergence") == "PnF=accumulation, DetectorChain=unknown"
    out2 = WyckoffOutput.from_dict(d)
    assert out2.pnf_phase_divergence == "PnF=accumulation, DetectorChain=unknown"


# ───────────────────────── T6: 无分歧时序列化 ─────────────────────────

def test_wyckoff_output_no_divergence_serialization():
    """pnf_phase_divergence=None 时序列化/反序列化应保持 None。"""
    out = WyckoffOutput(phase="unknown")
    d = out.to_dict()
    assert d.get("pnf_phase_divergence") is None
    out2 = WyckoffOutput.from_dict(d)
    assert out2.pnf_phase_divergence is None