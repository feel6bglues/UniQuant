#!/usr/bin/env python3
"""B 组 — P0 实施状态检查 (B1-B8)。

对 2026-08-12 深入再研究定稿 P0 七项的现实现状态做确定性检查
(源码/配置/运行时三者结合)，逐项 PASS/FAIL。

B1 (P0-1): WyckoffOutput.direction 字段 + to_dict/from_dict 透传 wyckoff_direction
B2 (P0-1): _extract_from_report 从 trading_plan.direction 提取 (含 MTF 融合后)
B3 (P0-3): ResearchPackWriter 仅展平 wyckoff 键 (不引入无关 metadata 键)
B4 (P0-2): adapter direction gate — 做多/买入/轻仓试探→BUY, 其余→None;
           删除 phase/spring/utad 直映射
B5 (P0-4): config wyckoff.confidence_gate == 0.40
B6 (P0-5): config wyckoff.structural_adjust_enabled 默认 false
B7 (P0-6): normalizer._DIRECTION_MAP 相位/spring 全部置 0
B8 (P0-7): 恒不产 SELL-as-entry (adapter + scan_signal 运行时验证)

用法: python3 scripts/wyckoff_verify_20260812/check_impl_state.py
输出: results/wyckoff_verify_20260812/check_impl_state.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _common import write_out  # noqa: E402


def _source_contains(path: str, needle: str) -> bool:
    p = Path(__file__).resolve().parents[2] / path
    return needle in p.read_text(encoding="utf-8")


def main() -> int:
    checks: dict = {}
    notes: dict = {}

    # ── B1: WyckoffOutput.direction 透传 ──
    from uniquant.shared.interfaces import WyckoffOutput

    out = WyckoffOutput(phase="markup", direction="做多")
    d = out.to_dict()
    restored = WyckoffOutput.from_dict(d)
    b1 = (
        out.direction == "做多"
        and d.get("wyckoff_direction") == "做多"
        and restored.direction == "做多"
    )
    checks["B1_direction_passthrough"] = b1
    notes["B1"] = "WyckoffOutput.direction 字段 + to_dict/from_dict wyckoff_direction roundtrip"

    # ── B2: _extract_from_report 提取 direction ──
    from unittest.mock import MagicMock

    from uniquant.services.analysis.wyckoff_analysis_engine import (
        WyckoffAnalysisEngine,
    )

    engine = WyckoffAnalysisEngine(MagicMock())
    report = MagicMock()
    tp = MagicMock()
    tp.direction = "轻仓试探"
    report.trading_plan = tp
    report.structure = MagicMock()
    report.structure.phase = MagicMock()
    report.structure.phase.value = "markup"
    report.signal = MagicMock()
    report.signal.signal_type = "markup"
    report.signal.confidence = "B"
    report.risk_reward = None
    report.pnf_analysis = None
    report.regime_phase = None
    report.vshape_detected = False
    report.adjustment_status = "unknown"
    report.structural_score = 0.0
    report.relative_strength = None
    report.pnf_phase_divergence = None
    report.vdb_divergence = "none"
    report.lps_stage = "not_test"
    report.resonance_count = 0
    report.resonance_dir = ""
    report.resonance_strength = 0.0
    extracted = engine._extract_from_report(report, price=100.0)
    b2 = extracted.direction == "轻仓试探"
    checks["B2_extract_from_report_direction"] = b2
    notes["B2"] = "_extract_from_report 从 trading_plan.direction 提取 (覆盖 MTF 融合 final_report)"

    # ── B3: RDP 仅展平 wyckoff 键 (含 P1-3~12 标注面键, 禁无关 engine 键) ──
    from uniquant.services.analysis.pack_writer import RDPackWriter
    from uniquant.shared.interfaces import ResearchDataPack

    rdp = ResearchDataPack(symbol="T", metadata={"pre": 1})
    RDPackWriter.write_wyckoff(rdp, WyckoffOutput(direction="做多"))
    meta_keys = set(rdp.metadata.keys())
    wyckoff_keys = {
        "wyckoff_phase", "wyckoff_confidence", "wyckoff_spring",
        "wyckoff_utad", "rr_ratio", "bypassed", "wyckoff_direction", "pre",
        # P1-3: SOS 候选
        "sos_candidate_detected",
        # P1-4~12: 标注面
        "evr_state", "evr_level", "evr_position_context",
        "pattern_failure_detected", "pattern_failure_ratio",
        "no_supply_detected", "nsd_detected", "vdu_detected",
        "event_cooldown_active", "event_cooldown_days",
        "range_score", "avwap", "bias200",
    }
    unrelated_engine_keys = {
        "regime", "entropy", "turnover_z",
        "risk", "bubble_confidence",
        "ntf_side", "ntf_intensity", "ntf_action",
        "is_3rd_buy", "bi_count",
        "alpha_score",
    }
    extra = meta_keys - wyckoff_keys
    unrelated_leak = meta_keys & unrelated_engine_keys
    b3 = (len(extra) == 0 and len(unrelated_leak) == 0
          and rdp.metadata.get("wyckoff_direction") == "做多")
    checks["B3_rdp_only_wyckoff_keys"] = b3
    notes["B3"] = (f"RDP metadata 键={sorted(meta_keys)}, 意外键={sorted(extra)}, "
                   f"无关 engine 键泄漏={sorted(unrelated_leak)}")

    # ── B4: adapter direction gate ──
    from uniquant.signal.adapters import WyckoffAdapter

    adapter = WyckoffAdapter()
    buy_cases = {"做多": 0.5, "买入": 0.5, "轻仓试探": 0.5}
    gate_ok = all(
        (adapter.adapt({"wyckoff_direction": k, "wyckoff_confidence": v, "price": 10.0},
                       symbol="T") is not None
         and adapter.adapt({"wyckoff_direction": k, "wyckoff_confidence": v, "price": 10.0},
                           symbol="T").action == "BUY")
        for k, v in buy_cases.items()
    )
    non_buy = {"持有": 0.9, "观察等待": 0.9, "空仓观望": 0.9, "做空": 0.9, "卖出": 0.9}
    none_ok = all(
        adapter.adapt({"wyckoff_direction": k, "wyckoff_confidence": v, "price": 10.0},
                      symbol="T") is None
        for k, v in non_buy.items()
    )
    phase_alone = adapter.adapt({"wyckoff_phase": "accumulation", "wyckoff_spring": True,
                                 "wyckoff_utad": False, "wyckoff_confidence": 0.8,
                                 "price": 10.0}, symbol="T")
    b4 = gate_ok and none_ok and phase_alone is None
    checks["B4_adapter_direction_gate"] = b4
    notes["B4"] = (f"做多/买入/轻仓试探→BUY={gate_ok}; 其余→None={none_ok}; "
                   f"相位/spring/utad 无 direction 直映射={phase_alone is None}")

    # ── B5: confidence_gate 0.40 ──
    from uniquant.shared.config_loader import get_config

    cfg = get_config()
    conf_gate = cfg.get("wyckoff.confidence_gate")
    b5 = abs(float(conf_gate) - 0.40) < 1e-9
    checks["B5_confidence_gate_0_40"] = b5
    notes["B5"] = f"config wyckoff.confidence_gate={conf_gate!r}"

    # ── B6: structural_adjust_enabled 默认 false ──
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    sa_cfg = cfg.get("wyckoff.structural_adjust_enabled")
    engine_obj = WyckoffEngine()
    b6 = bool(sa_cfg) is False and engine_obj._structural_adjust_enabled is False
    checks["B6_structural_adjust_default_off"] = b6
    notes["B6"] = (f"config={sa_cfg!r}, engine._structural_adjust_enabled="
                   f"{engine_obj._structural_adjust_enabled!r}")

    # ── B7: normalizer._DIRECTION_MAP 置 0 ──
    from uniquant.signal.normalizer import WyckoffSignalNormalizer

    norm = WyckoffSignalNormalizer()
    n_zero = sum(1 for v in norm._DIRECTION_MAP.values() if v == 0)
    n_total = len(norm._DIRECTION_MAP)
    b7 = n_total > 0 and n_zero == n_total
    checks["B7_normalizer_direction_map_zero"] = b7
    notes["B7"] = f"_DIRECTION_MAP {n_zero}/{n_total} 项为 0"

    # ── B8: 恒不产 SELL-as-entry ──

    from uniquant.brain.wyckoff.engine import WyckoffEngine
    from scripts.wyckoff_fixtures import synthetic_accumulation, synthetic_trading_range

    scan_eng = WyckoffEngine()
    frames = [synthetic_accumulation(seed=42), synthetic_trading_range(seed=42)]
    actions = [scan_eng.scan_signal(df, symbol="T")["action"] for df in frames]
    no_sell_scan = all(a in ("BUY", "HOLD") for a in actions)

    norm_raw = WyckoffSignalNormalizer()
    sell_from_norm = any(
        norm_raw.normalize({"type": t, "confidence": 0.9, "symbol": "T"}).direction == -1
        for t in ("distribution", "markdown", "markup", "accumulation", "spring", "utad")
    )
    b8 = no_sell_scan and not sell_from_norm
    checks["B8_no_seLL_as_entry"] = b8
    notes["B8"] = (f"scan_signal actions={actions} (恒 BUY/HOLD)={no_sell_scan}; "
                   f"normalizer 无 -1 注入={not sell_from_norm}")

    # ── 汇总 ──
    results = {
        "pre_registered": True,
        "checks": checks,
        "notes": notes,
        "overall": "PASS" if all(checks.values()) else "FAIL",
    }
    path = write_out("check_impl_state", results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n→ {path}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
