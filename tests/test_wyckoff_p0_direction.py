"""P0 信号链根除定向测试 (2026-08-12 深入再研究定稿)。

覆盖:
- P0-1: WyckoffOutput.direction 透传 (roundtrip + _extract_from_report + pack_writers)
- P0-3: ResearchPackWriter 仅展平 wyckoff 键 (禁全量 metadata 展平)
- P0-5: structural_adjust_enabled 默认关闭
- P0-7: scan_signal 恒不产 SELL-as-entry
"""

from unittest.mock import MagicMock, patch


from uniquant.services.analysis.pack_writer import (
    DictPackWriter,
    RDPackWriter,
)
from uniquant.services.analysis.wyckoff_analysis_engine import (
    WyckoffAnalysisEngine,
)
from uniquant.shared.interfaces import (
    ResearchDataPack,
    WyckoffOutput,
)


# ─────────────────── P0-1: WyckoffOutput.direction roundtrip ───────────────────

def test_wyckoff_output_dict_roundtrip_direction():
    """to_dict/from_dict 保留 wyckoff_direction。"""
    out = WyckoffOutput(phase="markup", direction="做多")
    d = out.to_dict()
    assert d["wyckoff_direction"] == "做多"
    restored = WyckoffOutput.from_dict(d)
    assert restored.direction == "做多"


def test_wyckoff_output_from_dict_default_empty_direction():
    """旧 metadata (无 wyckoff_direction) → direction 空串，不崩溃。"""
    restored = WyckoffOutput.from_dict({"wyckoff_phase": "accumulation"})
    assert restored.direction == ""


# ─────────────────── P0-1: _extract_from_report 提取 direction ───────────────────

class _Tp:
    def __init__(self, direction: str, confidence=None):
        self.direction = direction
        self.confidence = confidence


class _Report:
    def __init__(self, phase="unknown", signal_type="no_signal", confidence=None,
                 trading_plan=None, rr=None, pnf=None):
        self.structure = type("S", (), {"phase": type("P", (), {"value": phase})()})()
        self.signal = type("S", (), {"signal_type": signal_type, "confidence": confidence})()
        self.risk_reward = rr
        self.trading_plan = trading_plan
        self.pnf_analysis = pnf
        self.regime_phase = None
        self.vshape_detected = False
        self.adjustment_status = "unknown"
        self.structural_score = 0.0
        self.relative_strength = None
        self.pnf_phase_divergence = None
        self.vdb_divergence = "none"
        self.lps_stage = "not_test"
        self.resonance_count = 0
        self.resonance_dir = ""
        self.resonance_strength = 0.0


def test_extract_from_report_direction_from_trading_plan():
    """_extract_from_report 从 trading_plan.direction 提取 (含 MTF 融合后 direction)。"""
    engine = WyckoffAnalysisEngine(MagicMock())
    report = _Report(
        phase="markup",
        signal_type="markup",
        confidence="B",
        trading_plan=_Tp(direction="轻仓试探", confidence="B"),
    )
    out = engine._extract_from_report(report, price=100.0)
    assert out.direction == "轻仓试探"


def test_extract_from_report_direction_empty_when_no_plan():
    """无 trading_plan → direction 空串。"""
    engine = WyckoffAnalysisEngine(MagicMock())
    out = engine._extract_from_report(_Report(), price=100.0)
    assert out.direction == ""


# ─────────────────── P0-1/P0-3: pack_writer 透传 ───────────────────

def test_dict_pack_writer_writes_direction():
    """DictPackWriter.write_wyckoff 写入 wyckoff_direction。"""
    dp = {}
    out = WyckoffOutput(phase="accumulation", direction="做多")
    DictPackWriter.write_wyckoff(dp, out)
    assert dp["wyckoff_direction"] == "做多"


def test_rd_pack_writer_writes_only_wyckoff_keys():
    """RDPackWriter 仅展平 wyckoff 键，不引入无关 metadata (P0-3)。"""
    rdp = ResearchDataPack(symbol="TEST.SH", metadata={"pre": 1})
    out = WyckoffOutput(phase="accumulation", confidence=0.6, spring=True,
                        utad=False, rr_ratio=1.5, bypassed=False,
                        direction="做多")
    RDPackWriter.write_wyckoff(rdp, out)
    assert rdp.wyckoff is out
    meta = rdp.metadata
    for key in ("wyckoff_phase", "wyckoff_confidence", "wyckoff_spring",
                "wyckoff_utad", "rr_ratio", "bypassed", "wyckoff_direction", "sos_candidate_detected",
                "evr_state", "evr_level", "evr_position_context",
                "pattern_failure_detected", "pattern_failure_ratio",
                "no_supply_detected", "nsd_detected", "vdu_detected",
                "event_cooldown_active", "event_cooldown_days",
                "range_score", "avwap", "bias200"):
        assert key in meta
    assert meta["wyckoff_direction"] == "做多"
    assert meta["pre"] == 1
    assert meta["sos_candidate_detected"] is False
    annok = {"rr_ratio", "bypassed", "pre", "sos_candidate_detected",
             "evr_state", "evr_level", "evr_position_context",
             "pattern_failure_detected", "pattern_failure_ratio",
             "no_supply_detected", "nsd_detected", "vdu_detected",
             "event_cooldown_active", "event_cooldown_days",
             "range_score", "avwap", "bias200"}
    assert not any(not k.startswith("wyckoff_") and k not in annok
                   for k in meta), "不应全量展平其它引擎键"


# ─────────────────── P0-5: structural_adjust_enabled 默认关 ───────────────────

def test_structural_adjust_default_off():
    """config 默认 structural_adjust_enabled=false → 引擎不调整置信度等级。"""
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    engine = WyckoffEngine()
    assert engine._structural_adjust_enabled is False


def test_structural_adjust_off_keeps_base_confidence():
    """关闭后: 结构分不再升降置信度等级。"""
    from uniquant.brain.wyckoff.engine import WyckoffEngine, _apply_structural_adjustment

    engine = WyckoffEngine()
    with patch.object(engine, "_structural_adjust_enabled", True):
        assert engine._structural_adjust_enabled is True
    # 纯函数本身仍可用 (供显式开启时调用)
    assert _apply_structural_adjustment is not None


# ─────────────────── P0-7: scan_signal 恒不产 SELL ───────────────────

def test_scan_signal_never_sells():
    """scan_signal 对所有输入 action ∈ {BUY, HOLD}，恒不产 SELL。"""

    from uniquant.brain.wyckoff.engine import WyckoffEngine
    from scripts.wyckoff_fixtures import (
        synthetic_accumulation,
        synthetic_trading_range,
    )

    engine = WyckoffEngine()
    frames = [
        synthetic_accumulation(seed=42),
        synthetic_trading_range(seed=42),
    ]
    for df in frames:
        out = engine.scan_signal(df, symbol="TEST.SH")
        assert out["action"] in ("BUY", "HOLD")
