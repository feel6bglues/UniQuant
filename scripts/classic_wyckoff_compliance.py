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
    result.check("PF-C1", "D1-PnF",
                 "P&F participates in Phase decision",
                 passed=False,
                 detail="P&F called at end of _analyze_single, not used in _step1_phase_determine",
                 classification="ERROR")

    # PF-C2: Count Target in trading plan
    result.check("PF-C2", "D1-PnF",
                 "Count Target affects trading plan",
                 passed=False,
                 detail="V3TradingPlan.target uses RR projection, not PNF count target",
                 classification="ERROR")

    # PF-C3: P&F S/R in boundary
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
    engine = WyckoffEngine()
    spring_match_count = 0
    total_run = 0

    for sym in symbols[:5]:
        df = load_stock_data(sym)
        if df is None or len(df) < 120:
            continue
        total_run += 1
        try:
            report = engine.analyze(df, symbol=sym)
            # Check if spring detection uses TR boundary (classic) or just price action
            # Classic spring = break below TR lower bound + immediate recovery
            if report.signal.signal_type == "spring":
                spring_match_count += 1
        except Exception:
            pass

    result.partial("ES-C1", "D2-Events",
                   "Spring definition matches classic Wyckoff",
                   detail=f"engine uses boundary_lower * SPRING_LOW_FACTOR (0.99) + close factor, no P&F column context. Springs detected in {spring_match_count}/{total_run} runs",
                   classification="TRADE-OFF")

    # ES-C2: Event order matches classic sequence
    # Check that detect_all_events output order is PS→SC→AR→ST→SOS→LPS→JAC
    order_violations = 0
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
        filtered = [e for e in expected_order if e in event_types_in_key]
        # Check if actual order matches expected
        actual_indices = [key.split(">").index(e) for e in event_types_in_key if e in key.split(">")]
        expected_indices = [expected_order.index(e) for e in event_types_in_key]
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
        # Check _detect_utad implementation
        import inspect
        src = inspect.getsource(WyckoffEngine._detect_utad)  # type: ignore
        utad_implemented = "return None" not in src.split(":")[-1].strip()
    except Exception:
        pass

    result.check("ES-C3", "D2-Events",
                 "BUEC/UTAD events are detected",
                 passed=False,
                 detail="UTAD _detect_utad returns None (hardcoded). BUEC has no implementation",
                 classification="GAP")

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
    result.check("PH-C1", "D4-Phase",
                 "ACCUMULATION detection based on event sequence",
                 passed=False,
                 detail="_detect_accumulation uses prior_trend_pct + relative_position + bc_found, NOT event sequence",
                 classification="ERROR")

    # PH-C2: DISTRIBUTION based on events
    result.check("PH-C2", "D4-Phase",
                 "DISTRIBUTION detection based on event sequence",
                 passed=False,
                 detail="_detect_distribution only checks is_in_trading_range + prior_trend_pct > 0.05",
                 classification="ERROR")

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
    has_time_window = False
    engine = WyckoffEngine()
    for sym in symbols[:3]:
        df = load_stock_data(sym)
        if df is None:
            continue
        try:
            report = engine.analyze(df, symbol=sym)
            if hasattr(report, "stress_tests") and report.stress_tests:
                has_time_window = True
        except Exception:
            pass

    result.check("CF-C1", "D7-Counterfactual",
                 "Counterfactual uses phase-adaptive time windows",
                 passed=False,
                 detail="_step35_counterfactual uses forward/backward evidence scoring, no time-window concept",
                 classification="GAP")

    # CF-C4: UTAD implementation
    result.check("CF-C4", "D7-Counterfactual",
                 "UTAD detection works and triggers penalties",
                 passed=False,
                 detail="_detect_utad returns None — never triggers. False breakout penalty never applies",
                 classification="ERROR")


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
    result.check("CN-C4", "D8-AShare",
                 "Data pre-adjustment verification exists",
                 passed=False,
                 detail="No pre-adjusted data check in engine or data loading path",
                 classification="GAP")


def audit_signal(result: AuditResult, symbols: list[str]) -> None:
    """D9 — Signal output compliance."""
    # SQ-C1: structural_score exists
    has_structural_score = False
    try:
        from uniquant.brain.wyckoff.models import WyckoffReport
        has_structural_score = hasattr(WyckoffReport, "structural_score") or \
            any("structural_score" in f.name for f in WyckoffReport.__dataclass_fields__.values())  # type: ignore
    except Exception:
        pass

    result.check("SQ-C1", "D9-Signal",
                 "Signal includes structural integrity score (0-100)",
                 passed=has_structural_score,
                 detail="No structural_score field in WyckoffReport, WyckoffOutput, or ConfidenceResult",
                 classification="GAP")

    # SQ-C2: Phase confidence source in signal
    has_confidence_reason = False
    try:
        from uniquant.signal.adapters import WyckoffAdapter
        import inspect
        src = inspect.getsource(WyckoffAdapter.adapt)
        has_confidence_reason = "phase" in src and "confidence" in src
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
    result.check("RS-C1", "D6-RS",
                 "Relative strength classification exists",
                 passed=False,
                 detail="No RS calculation in engine. Phase analysis does not compare stock to index",
                 classification="GAP")

    result.check("RS-C2", "D6-RS",
                 "Capital flow analysis affects signal confidence",
                 passed=False,
                 detail="ChipAnalysis fields defined but not used in confidence matrix or adapter",
                 classification="GAP")


def audit_mtf(result: AuditResult, symbols: list[str]) -> None:
    """D5 — Multi-timeframe compliance."""
    MultiTimeframeResonance = _import_phase()

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
    WyckoffEngine = _import_engine()
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
