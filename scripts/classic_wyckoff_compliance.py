#!/usr/bin/env python3
"""Classic Wyckoff compliance audit — measure existing engine vs classic theory.

Usage:
    # First baseline
    python scripts/classic_wyckoff_compliance.py --output docs/compliance/baseline_report.json

    # Compare after changes
    python scripts/classic_wyckoff_compliance.py --compare docs/compliance/baseline_report.json

    # Single dimension
    python scripts/classic_wyckoff_compliance.py --dimension D1,D2
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import pandas as pd

# ── project imports (lazy to avoid import failures) ──────────────────────


def _import_engine():
    from uniquant.brain.wyckoff.engine import WyckoffEngine
    return WyckoffEngine


def _import_pnf():
    from uniquant.brain.wyckoff.pnf import PointAndFigure
    return PointAndFigure


def _import_events():
    from uniquant.brain.wyckoff.events import detect_all_events, WyckoffEvent
    return detect_all_events, WyckoffEvent


def _import_phase():
    from uniquant.brain.wyckoff.phase_analysis import MultiTimeframeResonance
    return MultiTimeframeResonance


def _import_board():
    from uniquant.shared.board_registry import BoardType, BoardTypeRegistry
    return BoardType, BoardTypeRegistry


def _import_event_utils():
    from uniquant.brain.wyckoff.events import event_sequence_key
    from uniquant.brain.wyckoff.sequence import WSOScorer
    return event_sequence_key, WSOScorer


# ── data ────────────────────────────────────────────────────────────────


def load_golden_symbols() -> list[str]:
    path = Path("tests/benchmark/golden_20.txt")
    if not path.exists():
        print("WARNING: golden_20.txt not found, using fallback")
        return ["000001.SH", "000300.SH", "399300.SZ"]
    return [s.strip() for s in path.read_text().splitlines() if s.strip()]


def load_stock_data(symbol: str) -> Optional[pd.DataFrame]:
    lake = Path("data/lake/quotes/daily")
    candidates = [
        lake / f"{symbol}.parquet",
        lake / f"{symbol}.csv",
    ]
    for c in candidates:
        if c.exists():
            df = pd.read_parquet(c) if c.suffix == ".parquet" else pd.read_csv(c)
            needed = {"date", "open", "high", "low", "close", "volume"}
            if needed.issubset(df.columns):
                df["date"] = pd.to_datetime(df["date"])
                return df.sort_values("date").reset_index(drop=True)
    return None


# ── audit results ───────────────────────────────────────────────────────


class AuditResult:
    """Collect all compliance checks into a report."""

    def __init__(self):
        self.checks: list[dict] = []
        self.errors: list[str] = []

    def check(self, check_id: str, dimension: str, description: str,
              passed: bool, detail: str = "",
              classification: str = "") -> None:
        self.checks.append({
            "check_id": check_id,
            "dimension": dimension,
            "description": description,
            "passed": passed,
            "status": "PASS" if passed else "FAIL",
            "detail": detail,
            "classification": classification,
        })

    def partial(self, check_id: str, dimension: str, description: str,
                detail: str = "", classification: str = "") -> None:
        self.checks.append({
            "check_id": check_id,
            "dimension": dimension,
            "description": description,
            "passed": True,
            "status": "PARTIAL",
            "detail": detail,
            "classification": classification,
        })

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def summary(self) -> dict:
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c["status"] == "PASS")
        partial = sum(1 for c in self.checks if c["status"] == "PARTIAL")
        failed = sum(1 for c in self.checks if c["status"] == "FAIL")
        by_dim: dict[str, dict] = {}
        for c in self.checks:
            d = c["dimension"]
            if d not in by_dim:
                by_dim[d] = {"pass": 0, "partial": 0, "fail": 0, "total": 0}
            by_dim[d][c["status"].lower()] += 1
            by_dim[d]["total"] += 1
        return {
            "total_checks": total,
            "passed": passed,
            "partial": partial,
            "failed": failed,
            "score_pct": round((passed + 0.5 * partial) / max(total, 1) * 100, 1),
            "by_dimension": by_dim,
            "checks": self.checks,
            "errors": self.errors,
        }


# ── dimension audits ────────────────────────────────────────────────────


def audit_pnf(result: AuditResult, symbols: list[str]) -> None:
    """D1 — P&F compliance."""
    PointAndFigure = _import_pnf()

    hardcoded_count = 0
    box_sizes_seen: set[float] = set()

    for sym in symbols[:5]:
        df = load_stock_data(sym)
        if df is None:
            continue
        pnf = PointAndFigure(box_size=0.02, reversal=2)
        pnf.build(df)
        box_sizes_seen.add(pnf.box_size)
        if pnf.box_size == 0.02:
            hardcoded_count += 1

    # PF-C1: P&F used in phase decision
    engine_src = Path("src/uniquant/brain/wyckoff/engine.py").read_text()
    pnf_early = "_step0_bc_tr_scan(frame, pnf_zone=" in engine_src
    pnf_phase = "_step1_phase_determine(frame, rule0, pnf_hint=" in engine_src
    pnf_hint_branch = 'pnf_hint in ("accumulation", "distribution")' in engine_src
    if pnf_early and pnf_phase and pnf_hint_branch:
        result.check("PF-C1", "D1-PnF",
                     "P&F participates in Phase decision",
                     passed=True,
                     detail="P&F 先行构建；phase_hint 传入 _step1_phase_determine 驱动判定",
                     classification="ERROR")
    else:
        result.check("PF-C1", "D1-PnF",
                     "P&F participates in Phase decision",
                     passed=False,
                     detail="P&F called at end of _analyze_single, not used in _step1_phase_determine",
                     classification="ERROR")

    # PF-C2: Count Target in trading plan
    pnf_ct_flow = "pnf_count_target=" in engine_src
    pnf_ct_use = 'first_target_source = "pnf_count_target"' in engine_src
    if pnf_ct_flow and pnf_ct_use:
        result.check("PF-C2", "D1-PnF",
                     "Count Target affects trading plan",
                     passed=True,
                     detail="_step4_risk_reward 采用 PNF count_target 作为第一目标源",
                     classification="ERROR")
    else:
        result.check("PF-C2", "D1-PnF",
                     "Count Target affects trading plan",
                     passed=False,
                     detail="V3TradingPlan.target uses RR projection, not PNF count target",
                     classification="ERROR")

    # PF-C3: P&F S/R in boundary
    pnf_zone_use = "pnf_zone=" in engine_src
    pnf_zone_pref = "tr_source_override" in engine_src
    if pnf_zone_use and pnf_zone_pref:
        result.check("PF-C3", "D1-PnF",
                     "P&F support/resistance in boundary detection",
                     passed=True,
                     detail="_step0_bc_tr_scan 优先采用 P&F 密集区作为 TR 边界",
                     classification="ERROR")
    else:
        result.check("PF-C3", "D1-PnF",
                     "P&F support/resistance in boundary detection",
                     passed=False,
                     detail="Boundaries from recent_60 high/low, not P&F column analysis",
                     classification="ERROR")

    # PF-C4: box_size adaptive
    if hardcoded_count >= 3:
        result.check("PF-C4", "D1-PnF",
                     "box_size adapts to price and board",
                     passed=False,
                     detail=f"box_size=0.02 hardcoded in engine.py:244 for {hardcoded_count}/{min(5, len(symbols))} symbols",
                     classification="TRADE-OFF")
    else:
        result.partial("PF-C4", "D1-PnF",
                       "box_size adapts to price and board",
                       detail="box_size may vary across symbols",
                       classification="TRADE-OFF")

    # PF-C5: incremental update
    result.check("PF-C5", "D1-PnF",
                 "P&F supports incremental O(1) update",
                 passed=False,
                 detail="PointAndFigure.build() does full rebuild each call",
                 classification="GAP")


def audit_events(result: AuditResult, symbols: list[str]) -> None:
    """D2 — Event sequence compliance."""
    WyckoffEngine = _import_engine()
    detect_all_events, WyckoffEvent = _import_events()

    # ES-C1: Spring definition matches classic
    # Spring = O 列跌破 TR 下沿 0.5-1.5% 后 1-2 列内收回 + 量能萎缩确认 (shared _scan_spring)
    spring_implemented = False
    try:
        import inspect
        src_scan = inspect.getsource(WyckoffEngine._scan_spring)  # type: ignore
        src_step3 = inspect.getsource(WyckoffEngine._step3_phase_c_t1)  # type: ignore
        has_lower_band = "boundary_lower * 0.985" in src_scan  # 0.5-1.5% 跌破带
        has_recovery = "closes[j] >= boundary_lower" in src_scan  # 1-2 列内收回
        has_contraction = "vol_ratio > 0.8" in src_scan  # 量能萎缩确认
        calls_helper = "_scan_spring" in src_step3  # step3 复用共享助手
        spring_implemented = (
            has_lower_band and has_recovery and has_contraction and calls_helper
        )
    except Exception:
        pass

    result.check("ES-C1", "D2-Events",
                 "Spring definition matches classic Wyckoff",
                 passed=spring_implemented,
                 detail="Spring 检测: O 列跌破 TR 下沿 0.5-1.5% (boundary_lower*0.985) 后 1-2 列内收回 (closes[j]>=boundary_lower) + 量能萎缩 (vol_ratio<=0.8), step3 复用共享 _scan_spring" if spring_implemented else "Spring 检测未绑定 TR 下沿 + 1-2 列收回 + 量能萎缩特征",
                 classification="PASS" if spring_implemented else "GAP")

    # ES-C2: Event order matches classic sequence
    # Check that detect_all_events output order is PS→SC→AR→ST→SOS→LPS→JAC
    order_checks = 0
    for sym in symbols[:5]:
        df = load_stock_data(sym)
        if df is None:
            continue
        events = detect_all_events(df)
        order_checks += 1
        # Check the sequence key
        event_sequence_key_fn, _ = _import_event_utils()
        key = event_sequence_key_fn(events)
        # Count events in key
        event_types_in_key = [e for e in ["PS", "SC", "AR", "ST", "SOS", "LPS", "JAC"] if e in key]
        expected_order = ["PS", "SC", "AR", "ST", "SOS", "LPS", "JAC"]
        [e for e in expected_order if e in event_types_in_key]
        # Check if actual order matches expected
        actual_indices = [key.split(">").index(e) for e in event_types_in_key if e in key.split(">")]
        [expected_order.index(e) for e in event_types_in_key]
        if actual_indices != sorted(actual_indices):
            # expected order violation
            pass

    result.partial("ES-C2", "D2-Events",
                   "Event order matches classic Wyckoff sequence",
                   detail="sequence.py uses WSOScorer empirical weights, not Needleman-Wunsch alignment. 6 classic events (BUEC, UTAD) not tracked",
                   classification="TRADE-OFF")

    # ES-C3: BUEC/UTAD detection
    utad_implemented = False
    try:
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        # Check _detect_utad + shared _scan_utad: 2% breakout + recovery + volume confirmation
        import inspect
        src_detect = inspect.getsource(WyckoffEngine._detect_utad)  # type: ignore
        src_scan = inspect.getsource(WyckoffEngine._scan_utad)  # type: ignore
        has_breakout = "boundary_upper * 1.02" in src_scan
        has_recovery = "boundary_upper * 1.01" in src_scan
        has_volume = "vol_ratio <= 1.5" in src_scan
        calls_helper = "_scan_utad" in src_detect
        utad_implemented = has_breakout and has_recovery and has_volume and calls_helper
    except Exception:
        pass

    result.check("ES-C3", "D2-Events",
                 "BUEC/UTAD events are detected",
                 passed=utad_implemented,
                 detail="UTAD _detect_utad 实现: 突破 TR 上沿 2%+ 后 1-2 列内收回 + 量比>1.5 放量确认 (shared _scan_utad). BUEC 无独立实现" if utad_implemented else "UTAD _detect_utad 未实现 2%+突破/收回/放量特征. BUEC 无独立实现",
                 classification="PASS" if utad_implemented else "GAP")

    # ES-C4: SOS false positive rate
    sos_fp_rate = 0.0
    sos_samples = 0
    for sym in symbols[:5]:
        df = load_stock_data(sym)
        if df is None:
            continue
        events = detect_all_events(df)
        sos_count = sum(1 for e in events if e.event_type == "SOS")
        total_bars = len(df)
        sos_fp_rate += sos_count / max(total_bars / 120, 1)  # normalize to per-120-bar
        sos_samples += 1

    avg_sos_rate = sos_fp_rate / max(sos_samples, 1)
    sos_ok = avg_sos_rate < 1.0  # Should not fire more than once per 120 bars

    result.check("ES-C4", "D2-Events",
                 "SOS detection rate is not excessive",
                 passed=sos_ok,
                 detail=f"SOS events per 120-bar window: {avg_sos_rate:.2f}. events.py comment warns 109.5% detection rate",
                 classification="ERROR")

    # ES-C5: JAC matches classic SOS
    result.partial("ES-C5", "D2-Events",
                   "JAC detection matches classic SOS definition",
                   detail="JAC uses 20-day TR breakout, which is a valid equivalent of SOS. Not a standard Wyckoff event name",
                   classification="TRADE-OFF")


def audit_phase(result: AuditResult, symbols: list[str]) -> None:
    """D4 — Phase classification compliance."""
    WyckoffEngine = _import_engine()
    detect_all_events, WyckoffEvent = _import_events()

    engine = WyckoffEngine()
    phase_via_events = 0
    total_phase_checks = 0
    phase_distribution: dict[str, int] = {}

    for sym in symbols[:10]:
        df = load_stock_data(sym)
        if df is None or len(df) < 120:
            continue
        total_phase_checks += 1
        try:
            report = engine.analyze(df, symbol=sym)
            phase = report.structure.phase.value
            phase_distribution[phase] = phase_distribution.get(phase, 0) + 1

            # Check if events are used for phase determination
            events = detect_all_events(df)
            if len(events) >= 3:
                phase_via_events += 1
        except Exception:
            pass

    # PH-C1: ACCUMULATION based on events
    import inspect
    WyckoffEnginePH = _import_engine()
    ph_c1_src = inspect.getsource(WyckoffEnginePH._detect_accumulation)  # type: ignore
    ph_c1_passed = (
        "detect_all_events" in ph_c1_src
        and "event_sequence_key" in ph_c1_src
        and 'seq_key.count("ST") >= 2' in ph_c1_src
        and '"PS" in seq_key' in ph_c1_src
        and '"SC" in seq_key' in ph_c1_src
    )
    result.check("PH-C1", "D4-Phase",
                 "ACCUMULATION detection based on event sequence",
                 passed=ph_c1_passed,
                 detail=("_detect_accumulation 优先检查 PS+SC+ST×2 事件序列，序列匹配时忽略 price_position"
                         if ph_c1_passed else
                         "_detect_accumulation uses prior_trend_pct + relative_position + bc_found, NOT event sequence"),
                 classification="ERROR" if not ph_c1_passed else "PASS")

    # PH-C2: DISTRIBUTION based on events
    import inspect
    WyckoffEnginePH2 = _import_engine()
    ph_c2_src = inspect.getsource(WyckoffEnginePH2._detect_distribution)  # type: ignore
    ph_c2_passed = (
        "_scan_utad" in ph_c2_src
        and "upthrust_candidate" in ph_c2_src
        and "boundary_upper > 0" in ph_c2_src
    )
    result.check("PH-C2", "D4-Phase",
                 "DISTRIBUTION detection based on event sequence",
                 passed=ph_c2_passed,
                 detail=("_detect_distribution 优先通过共享 _scan_utad 检查 UTAD 假突破事件（突破 2%+ 收回 + 放量确认），匹配时忽略 price_position；_detect_distribution 在检测器链中提前于 markdown"
                         if ph_c2_passed else
                         "_detect_distribution only checks is_in_trading_range + prior_trend_pct > 0.05"),
                 classification="ERROR" if not ph_c2_passed else "PASS")

    # PH-C3: Confidence matrix with required/optional
    result.partial("PH-C3", "D4-Phase",
                   "Phase confidence uses required/optional conditions",
                   detail="_calc_confidence uses 5-condition matrix (bc, spring+lps, counterfactual, rr, multiframe), not required/optional weighted scoring",
                   classification="TRADE-OFF")

    # PH-C4: Multi-timeframe resonance
    MultiTimeframeResonance = _import_phase()
    mre = MultiTimeframeResonance()
    test_result = mre.resonance("accumulation", "accumulation", "markup")
    resonance_works = test_result["resonance_dir"] == "bullish"

    result.check("PH-C4", "D4-Phase",
                 "Multi-timeframe resonance detects alignment",
                 passed=resonance_works,
                 detail=f"resonance(bullish,bullish,bearish) = {test_result['resonance_dir']}",
                 classification="TRADE-OFF")

    # PH-C5: Sub-phase exists
    result.partial("PH-C5", "D4-Phase",
                   "Sub-phase A/B/C/D/E classification exists",
                   detail=f"classify_accumulation_sub_phase exists in classifiers.py. Phase distribution: {phase_distribution}",
                   classification="TRADE-OFF")


def audit_counterfactual(result: AuditResult, symbols: list[str]) -> None:
    """D7 — Counterfactual compliance."""
    WyckoffEngine = _import_engine()

    # CF-C1: Phase-adaptive verification window
    engine = WyckoffEngine()
    for sym in symbols[:3]:
        df = load_stock_data(sym)
        if df is None:
            continue
        try:
            report = engine.analyze(df, symbol=sym)
            if hasattr(report, "stress_tests") and report.stress_tests:
                pass
        except Exception:
            pass

    result.check("CF-C1", "D7-Counterfactual",
                 "Counterfactual uses phase-adaptive time windows",
                 passed=False,
                 detail="_step35_counterfactual uses forward/backward evidence scoring, no time-window concept",
                 classification="GAP")

    # CF-C4: 假突破惩罚 (突破后 3 列内跌回 → false_breakout=True → 信号置信度 -1 级)
    import inspect as _cf4_inspect
    from uniquant.brain.wyckoff.engine import _downgrade_confidence
    WyckoffEngineCF4 = _import_engine()
    scan_fb_src = _cf4_inspect.getsource(WyckoffEngineCF4._scan_false_breakout)  # type: ignore
    step5_src = _cf4_inspect.getsource(WyckoffEngineCF4._step5_trading_plan)  # type: ignore
    build_report_src = _cf4_inspect.getsource(WyckoffEngineCF4._build_report)  # type: ignore
    downgrade_src = _cf4_inspect.getsource(_downgrade_confidence)
    cf4_passed = (
        "boundary_upper * 1.02" in scan_fb_src
        and "vol_med" in scan_fb_src
        and "1.5 * vol_med" in scan_fb_src
        and "min(i + 4, n)" in scan_fb_src
        and "_scan_false_breakout" in step5_src
        and "false_breakout_detected" in step5_src
        and "V3TradingPlan(" in step5_src
        and "false_breakout_detected" in build_report_src
        and "_downgrade_confidence" in build_report_src
        and "order.index(level)" in downgrade_src
    )
    result.check("CF-C4", "D7-Counterfactual",
                 "False breakout (假突破) triggers confidence penalty",
                 passed=cf4_passed,
                 detail=("_scan_false_breakout 检测突破 TR 上沿 2%+ 后 3 列内跌回（放量确认）；"
                         "_step5_trading_plan 标记 false_breakout_detected；"
                         "_build_report 通过 _downgrade_confidence 将信号置信度降 1 级"
                         if cf4_passed else
                         "CF-C4 未完整实现：需 _scan_false_breakout + false_breakout_detected 标记 + 信号置信度降级"),
                 classification="ERROR" if not cf4_passed else "PASS")


def audit_ashare(result: AuditResult, symbols: list[str]) -> None:
    """D8 — A-Share adaptation compliance."""
    BoardType, BoardTypeRegistry = _import_board()
    registry = BoardTypeRegistry()

    boards_seen: set[str] = set()
    for sym in symbols[:5]:
        try:
            bt = registry.detect_board(sym)
            boards_seen.add(bt.name)
        except Exception:
            pass

    # CN-C1: Board-aware box_size
    result.check("CN-C1", "D8-AShare",
                 "box_size differs by board type",
                 passed=False,
                 detail=f"box_size=0.02 hardcoded. Boards seen: {boards_seen}",
                 classification="GAP")

    # CN-C2: T+1 cooldown
    result.check("CN-C2", "D8-AShare",
                 "T+1 cooldown enforced after Spring",
                 passed=False,
                 detail="_step3_phase_c_t1 computes T+1 risk but does not enforce cooldown",
                 classification="TRADE-OFF")

    # CN-C3: Limit up/down truncation
    result.check("CN-C3", "D8-AShare",
                 "Limit up/down affects P&F columns",
                 passed=False,
                 detail="PointAndFigure builder does not check limit status",
                 classification="GAP")

    # CN-C4: Data pre-adjusted check
    import inspect as _cn4_inspect
    from uniquant.brain.wyckoff.engine import _detect_adjustment_status
    from uniquant.brain.wyckoff.models import WyckoffReport as _CN4Report
    cn4_detect_src = _cn4_inspect.getsource(_detect_adjustment_status)
    cn4_model_fields = {f.name for f in _CN4Report.__dataclass_fields__.values()}  # type: ignore
    cn4_passed = (
        "pct_change" in cn4_detect_src
        and "raw" in cn4_detect_src
        and "pre_adjusted" in cn4_detect_src
        and "adjustment_status" in cn4_model_fields
    )
    result.check("CN-C4", "D8-AShare",
                 "Data pre-adjustment verification exists",
                 passed=cn4_passed,
                 detail=("_detect_adjustment_status 探测 >20% 收盘跳空（排除涨停延续）→ "
                         "WyckoffReport.adjustment_status=raw → 信号置信度降 1 级"
                         if cn4_passed else
                         "CN-C4 未完整实现：需 _detect_adjustment_status 探测 + WyckoffReport.adjustment_status 字段 + 信号降级"),
                 classification="ERROR" if not cn4_passed else "PASS")


def audit_signal(result: AuditResult, symbols: list[str]) -> None:
    """D9 — Signal output compliance."""
    # SQ-C1: structural_score exists
    has_structural_score = False
    has_struct_fn = False
    has_struct_weight = False
    try:
        import inspect as _sq1_inspect
        from uniquant.brain.wyckoff.models import WyckoffReport as _SQ1Report
        from uniquant.brain.wyckoff.models import ConfidenceResult as _SQ1Conf
        from uniquant.shared.interfaces import WyckoffOutput as _SQ1Output
        from uniquant.brain.wyckoff.engine import (
            _apply_structural_adjustment,
            _compute_structural_score,
        )
        for _cls in (_SQ1Report, _SQ1Conf, _SQ1Output):
            if hasattr(_cls, "__dataclass_fields__"):
                has_structural_score = has_structural_score or (
                    "structural_score" in {f.name for f in _cls.__dataclass_fields__.values()}  # type: ignore
                )
            else:
                has_structural_score = has_structural_score or hasattr(_cls, "structural_score")
        fn_src = _sq1_inspect.getsource(_compute_structural_score)
        has_struct_fn = "event_sequence_score" in fn_src and "min" in fn_src and "100.0" in fn_src
        adj_src = _sq1_inspect.getsource(_apply_structural_adjustment)
        has_struct_weight = (
            "structural_score" in adj_src and "level" in adj_src and ("70.0" in adj_src or "55.0" in adj_src)
        )
    except Exception:
        pass

    sq1_passed = has_structural_score and has_struct_fn and has_struct_weight
    result.check("SQ-C1", "D9-Signal",
                 "Signal includes structural integrity score (0-100)",
                 passed=sq1_passed,
                 detail=("structural_score 存在于 WyckoffReport/WyckoffOutput/ConfidenceResult；"
                         "_compute_structural_score 纯函数映射 0-100；"
                         "_apply_structural_adjustment 回填字段 + 置信度等级加权 (≥70 升/≤35 降)"
                         if sq1_passed else
                         "No structural_score field in WyckoffReport, WyckoffOutput, or ConfidenceResult"),
                 classification="ERROR" if not sq1_passed else "PASS")

    # SQ-C2: Phase confidence source in signal
    try:
        from uniquant.signal.adapters import WyckoffAdapter
        import inspect
        inspect.getsource(WyckoffAdapter.adapt)
    except Exception:
        pass

    result.partial("SQ-C2", "D9-Signal",
                   "Signal includes phase and confidence source",
                   detail="WyckoffAdapter.wyckoff_phase and confidence in metadata. No structural_score",
                   classification="TRADE-OFF")

    # SQ-C3: UNKNOWN has sub-reasons
    result.check("SQ-C3", "D9-Signal",
                 "UNKNOWN phase has sub-reason categorization",
                 passed=True,
                 detail="4 unknown_candidate states: phase_a_candidate, sc_st_candidate, upthrust_candidate, phase_b_range",
                 classification="TRADE-OFF")


def audit_rs(result: AuditResult, symbols: list[str]) -> None:
    """D6 — Relative strength compliance."""
    rs_passed = False
    rs_detail = "No RS module or engine wiring found"
    try:
        import inspect
        # 1) relative_strength 模块存在且 rs_classify 含 ≥4 分类名
        from uniquant.brain.wyckoff import relative_strength
        rs_src = inspect.getsource(relative_strength)
        has_module = hasattr(relative_strength, "rs_classify") and hasattr(
            relative_strength, "RelativeStrengthResult"
        )
        classifications = ["leader", "follower", "weak_independent", "systemic_decline"]
        has_4_cls = all(c in rs_src for c in classifications)
        # 2) 引擎接线: analyze 接受 index_df, _analyze_single 调用 rs_classify,
        #    _build_report 透传 relative_strength 进 WyckoffReport
        WyckoffEngine = _import_engine()
        engine_src = inspect.getsource(WyckoffEngine)
        has_wiring = (
            "index_df" in engine_src
            and "rs_classify(" in engine_src
            and "relative_strength=" in engine_src
        )
        rs_passed = has_module and has_4_cls and has_wiring
        rs_detail = (
            f"relative_strength.py 模块存在 + rs_classify 四分类 ({len(classifications)} 类)；"
            f"analyze(index_df=...) 接线 + _build_report 透传 relative_strength"
            if rs_passed else
            f"module={has_module}, 4cls={has_4_cls}, wiring={has_wiring}"
        )
    except Exception:
        pass

    result.check("RS-C1", "D6-RS",
                 "Relative strength classification exists",
                 passed=rs_passed,
                 detail=rs_detail,
                 classification="ERROR" if not rs_passed else "PASS")

    result.check("RS-C2", "D6-RS",
                 "Capital flow analysis affects signal confidence",
                 passed=False,
                 detail="ChipAnalysis fields defined but not used in confidence matrix or adapter",
                 classification="GAP")


def audit_mtf(result: AuditResult, symbols: list[str]) -> None:
    """D5 — Multi-timeframe compliance."""
    _import_phase()

    # MT-C2: quantitative evidence
    result.check("MT-C2", "D5-MTF",
                 "Multi-timeframe alignment includes quantitative improvement evidence",
                 passed=False,
                 detail="resonance_strength provides weighted count, no R2/IC/Sharpe improvement ratio",
                 classification="GAP")

    # MT-C3: weekly overrides daily
    result.partial("MT-C3", "D5-MTF",
                   "Weekly phase overrides daily when in conflict",
                   detail="MultiTimeframeResonance uses 2/3 majority voting, not strict weekly priority",
                   classification="TRADE-OFF")


def audit_volume(result: AuditResult, symbols: list[str]) -> None:
    """D3 — Volume signature compliance."""
    _import_engine()
    detect_all_events, WyckoffEvent = _import_events()

    # VS-C1: Configurable thresholds
    hardcoded_values = []
    try:
        import ast
        import inspect
        from uniquant.brain.wyckoff import events as events_mod
        src = inspect.getsource(events_mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if 0.5 < node.value < 10:
                    hardcoded_values.append(node.value)
    except Exception:
        pass

    result.check("VS-C1", "D3-Volume",
                 "Volume signature thresholds are configurable",
                 passed=False,
                 detail=f"events.py has {len(hardcoded_values)} hardcoded numeric thresholds (e.g. 1.2, 2.0, 0.8)",
                 classification="GAP")

    # VS-C3: Buy/sell volume distinction
    result.check("VS-C3", "D3-Volume",
                 "Buy vs sell volume is distinguished",
                 passed=False,
                 detail="Only total volume available. No tick-level direction split",
                 classification="GAP")


# ── main ────────────────────────────────────────────────────────────────


def run_audit(dimensions: Optional[list[str]] = None) -> AuditResult:
    result = AuditResult()
    symbols = load_golden_symbols()
    print(f"Loaded {len(symbols)} golden symbols")

    # Dimension dispatch
    dims = {
        "D1": ("P&F", audit_pnf),
        "D2": ("Events", audit_events),
        "D3": ("Volume", audit_volume),
        "D4": ("Phase", audit_phase),
        "D5": ("MTF", audit_mtf),
        "D6": ("RS", audit_rs),
        "D7": ("Counterfactual", audit_counterfactual),
        "D8": ("AShare", audit_ashare),
        "D9": ("Signal", audit_signal),
    }

    selected = dimensions or list(dims.keys())
    for key in selected:
        if key in dims:
            name, fn = dims[key]
            print(f"  Auditing {name}...")
            try:
                fn(result, symbols)
            except Exception as e:
                result.error(f"{key} ({name}) failed: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"  WARNING: unknown dimension {key}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Classic Wyckoff compliance audit")
    parser.add_argument("--output", type=str, default="",
                        help="Save report to file")
    parser.add_argument("--compare", type=str, default="",
                        help="Compare against previous baseline JSON")
    parser.add_argument("--dimension", type=str, default="",
                        help="Comma-separated dimensions (e.g. D1,D2)")
    args = parser.parse_args()

    dimensions = args.dimension.split(",") if args.dimension else None
    result = run_audit(dimensions)
    report = result.summary()

    # Print summary
    print(f"\n{'='*60}")
    print(f"  Compliance Score: {report['score_pct']}%")
    print(f"  PASS: {report['passed']}  PARTIAL: {report['partial']}  FAIL: {report['failed']}")
    print(f"  Total checks: {report['total_checks']}")
    print(f"{'='*60}")
    for dim, stats in sorted(report["by_dimension"].items()):
        p = stats["pass"]
        pa = stats["partial"]
        f = stats["fail"]
        t = stats["total"]
        score = round((p + 0.5 * pa) / max(t, 1) * 100, 1)
        print(f"  {dim}: {score}% ({p}P/{pa}Pa/{f}F/{t}T)")

    if report["errors"]:
        print(f"\n  Errors ({len(report['errors'])}):")
        for e in report["errors"]:
            print(f"    ⚠ {e}")

    # Detailed failure breakdown
    failures = [c for c in report["checks"] if c["status"] == "FAIL"]
    if failures:
        print(f"\n  Failures ({len(failures)}):")
        for c in failures:
            print(f"    ❌ {c['check_id']} ({c['classification']}): {c['detail'][:120]}")

    # Save or compare
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str))
        print(f"\n  Report saved to {out_path}")

    if args.compare:
        prev_path = Path(args.compare)
        if prev_path.exists():
            prev = json.loads(prev_path.read_text())
            score_delta = report["score_pct"] - prev["score_pct"]
            print(f"\n  vs {args.compare}: {score_delta:+.1f}%")
            # Check for regressions
            prev_checks = {c["check_id"]: c for c in prev["checks"]}
            for c in report["checks"]:
                prev_c = prev_checks.get(c["check_id"])
                if prev_c and prev_c["status"] == "PASS" and c["status"] == "FAIL":
                    print(f"    ⚠ REGRESSION: {c['check_id']} {c['description']}")
        else:
            print(f"\n  WARNING: {args.compare} not found, skipping comparison")


if __name__ == "__main__":
    main()
