"""Hypothesis tests H1-H7 with proper cutoff-based forward return computation."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np
from scipy import stats
from dataclasses import dataclass
from typing import List, Dict, Optional
from collections import defaultdict

from .config import VerifierConfig
from .data_synthesis import load_and_synthesize
from .a_universe import StockRecord
from .b_multitf import (
    analyze_batch
)


CUTOFF_DATE = "2024-12-31"  # 6 months before data end for forward return computation


@dataclass
class HypothesisResult:
    hypothesis: str
    supported: bool
    p_value: float
    effect_size: float
    details: dict


def compute_cutoff_returns(
    symbol: str, data_path: Path, cutoff_date: str
) -> Optional[Dict]:
    """Compute forward returns from cutoff date to end of data."""
    data = load_and_synthesize(symbol, data_path)
    if data is None:
        return None
    daily, _, _ = data
    close = daily["close"].values
    dates = daily["date"].values

    # Find cutoff index
    cutoff = pd.Timestamp(cutoff_date)
    cutoff_idx = None
    for i in range(len(dates) - 1, -1, -1):
        if pd.Timestamp(dates[i]) <= cutoff:
            cutoff_idx = i
            break
    if cutoff_idx is None or cutoff_idx >= len(close) - 20:
        return None

    # Forward returns at 1m, 3m, 6m
    fwd = {}
    for label, days in [("1m", 21), ("3m", 63), ("6m", 126)]:
        idx = min(cutoff_idx + days, len(close) - 1)
        ret = (close[idx] / close[cutoff_idx] - 1) * 100
        fwd[label] = ret

    return {"cutoff_idx": cutoff_idx, "cutoff_price": float(close[cutoff_idx]), "forward_returns": fwd}


def run_h1_monthly_phase_predicts(
    records: List[StockRecord], config: VerifierConfig
) -> HypothesisResult:
    """H1: Monthly phase predicts 6-month forward returns.
    H2: Accumulation > 0, Distribution < 0.
    """
    print(f"\n=== H1/H2: Monthly Phase Forward Returns (cutoff={CUTOFF_DATE}) ===")

    # Run multi-TF analysis at cutoff
    cutoff_results = analyze_batch(records, config, cutoff_date=CUTOFF_DATE)

    # Compute forward returns for each stock
    phase_returns = defaultdict(list)

    for r in cutoff_results:
        fwd_data = compute_cutoff_returns(r.symbol, config.data_lake, CUTOFF_DATE)
        if fwd_data is None:
            continue
        ret_6m = fwd_data["forward_returns"].get("6m", 0)
        phase_returns[r.monthly.phase].append(ret_6m)

    print(f"  {'Phase':<15} {'N':<6} {'Mean%':<10} {'Median%':<10} {'Pos%':<8} {'t-stat':<8}")
    print(f"  {'-'*57}")
    f_stats = []
    for phase in ["accumulation", "markup", "distribution", "markdown", "unknown"]:
        vals = np.array(phase_returns.get(phase, []))
        if len(vals) < 5:
            continue
        t, p = stats.ttest_1samp(vals, 0)
        pos = (vals > 0).mean() * 100
        f_stats.append(vals)
        print(f"  {phase:<15} {len(vals):<6} {np.mean(vals):<+10.2f} {np.median(vals):<+10.2f} {pos:<8.1f} {t:<+8.2f}")

    # ANOVA for monotonicity
    if len(f_stats) >= 3:
        f_val, p_anova = stats.f_oneway(*f_stats)
    else:
        f_val, p_anova = 0, 1.0

    h1_supported = p_anova < 0.05
    acc_vals = np.array(phase_returns.get("accumulation", [0]))
    dist_vals = np.array(phase_returns.get("distribution", [0]))
    h2_supported = len(acc_vals) > 0 and np.mean(acc_vals) > 0 and len(dist_vals) > 0 and np.mean(dist_vals) < 0

    print(f"  H1 (ANOVA): F={f_val:.3f}, p={p_anova:.4f} → {'✅' if h1_supported else '❌'}")
    if len(acc_vals) > 0 and len(dist_vals) > 0:
        print(f"  H2: accum={np.mean(acc_vals):+.2f}%, dist={np.mean(dist_vals):+.2f}% → {'✅' if h2_supported else '❌'}")

    return HypothesisResult(
        hypothesis="H1+H2",
        supported=h1_supported and h2_supported,
        p_value=p_anova,
        effect_size=float(np.mean(acc_vals) - np.mean(dist_vals)) if len(dist_vals) > 0 else 0,
        details={"phase_returns": {k: {"mean": float(np.mean(v)), "n": len(v)} for k, v in phase_returns.items()},
                 "cutoff_date": CUTOFF_DATE},
    )


def run_h3_multitf_consistency(records: List[StockRecord], config: VerifierConfig) -> HypothesisResult:
    """H3: Multi-timeframe consistent signals outperform inconsistent ones."""
    print(f"\n=== H3: Multi-TF Consistency (cutoff={CUTOFF_DATE}) ===")
    cutoff_results = analyze_batch(records, config, cutoff_date=CUTOFF_DATE)

    consistent_returns = []
    inconsistent_returns = []

    for r in cutoff_results:
        fwd_data = compute_cutoff_returns(r.symbol, config.data_lake, CUTOFF_DATE)
        if fwd_data is None:
            continue
        ret_3m = fwd_data["forward_returns"].get("3m", 0)
        if r.monthly.phase == r.weekly.phase:
            consistent_returns.append(ret_3m)
        else:
            inconsistent_returns.append(ret_3m)

    ca = np.array(consistent_returns)
    ia = np.array(inconsistent_returns)
    if len(ca) < 5 or len(ia) < 5:
        return HypothesisResult("H3", False, 1.0, 0,
                                {"consistent_n": len(ca), "inconsistent_n": len(ia)})

    t, p = stats.ttest_ind(ca, ia, alternative="greater")
    eff = np.mean(ca) - np.mean(ia)
    print(f"  Consistent ({len(ca)}): {np.mean(ca):+.2f}%")
    print(f"  Inconsistent ({len(ia)}): {np.mean(ia):+.2f}%")
    print(f"  Diff: {eff:+.2f}%, t={t:.3f}, p={p:.4f} → {'✅' if p < 0.05 else '❌'}")

    return HypothesisResult("H3", p < 0.05, p, eff, {
        "consistent_mean": float(np.mean(ca)), "inconsistent_mean": float(np.mean(ia)),
        "consistent_n": len(ca), "inconsistent_n": len(ia),
    })


def run_h4_hierarchical_levels(records: List[StockRecord], config: VerifierConfig) -> HypothesisResult:
    """H4: Level A/B signals outperform Level D."""
    print(f"\n=== H4: Hierarchical Signal Levels (cutoff={CUTOFF_DATE}) ===")
    cutoff_results = analyze_batch(records, config, cutoff_date=CUTOFF_DATE)

    level_returns = defaultdict(list)
    for r in cutoff_results:
        fwd_data = compute_cutoff_returns(r.symbol, config.data_lake, CUTOFF_DATE)
        if fwd_data is None:
            continue
        ret_3m = fwd_data["forward_returns"].get("3m", 0)
        level, _ = r.signal_level()
        level_returns[level].append(ret_3m)

    print(f"  {'Level':<10} {'N':<6} {'Mean%':<10} {'Median%':<10} {'Pos%':<8}")
    print(f"  {'-'*44}")
    for level in ["S+", "A", "B", "B_hold", "C", "C_reduce", "D"]:
        vals = level_returns.get(level, [])
        if not vals:
            continue
        pos = (np.array(vals) > 0).mean() * 100
        print(f"  {level:<10} {len(vals):<6} {np.mean(vals):<+10.2f} {np.median(vals):<+10.2f} {pos:<8.1f}")

    active = np.array(level_returns.get("S+", []) + level_returns.get("A", []) + level_returns.get("B", []))
    level_d = np.array(level_returns.get("D", [0]))
    if len(active) < 5 or len(level_d) < 5:
        return HypothesisResult("H4", False, 1.0, 0, {"active_n": len(active), "d_n": len(level_d)})

    t, p = stats.ttest_ind(active, level_d, alternative="greater")
    eff = np.mean(active) - np.mean(level_d)
    print(f"  Active (S+/A/B, N={len(active)}): {np.mean(active):+.2f}%")
    print(f"  Level D (N={len(level_d)}): {np.mean(level_d):+.2f}%")
    print(f"  Diff: {eff:+.2f}%, t={t:.3f}, p={p:.4f} → {'✅' if p < 0.05 else '❌'}")

    return HypothesisResult("H4", p < 0.05, p, eff, {
        "active_mean": float(np.mean(active)), "d_mean": float(np.mean(level_d)),
        "active_n": len(active), "d_n": len(level_d),
    })


def run_h7_full_strategy(records: List[StockRecord], config: VerifierConfig) -> HypothesisResult:
    """H7: Stocks in Wyckoff-favorable phases outperform BH."""
    print(f"\n=== H7: Phase-Driven Strategy vs BH (cutoff={CUTOFF_DATE}) ===")
    cutoff_results = analyze_batch(records, config, cutoff_date=CUTOFF_DATE)

    strategy_rets = []
    bh_rets = []

    for r in cutoff_results:
        fwd_data = compute_cutoff_returns(r.symbol, config.data_lake, CUTOFF_DATE)
        if fwd_data is None:
            continue
        ret_6m = fwd_data["forward_returns"].get("6m", 0)
        if r.monthly.phase in ("accumulation", "markup"):
            strategy_rets.append(ret_6m)
        bh_rets.append(ret_6m)

    sa = np.array(strategy_rets)
    ba = np.array(bh_rets)
    if len(sa) < 5 or len(ba) < 5:
        return HypothesisResult("H7", False, 1.0, 0,
                                {"strategy_n": len(sa), "bh_n": len(ba)})

    eff = np.mean(sa) - np.mean(ba)
    t, p = stats.ttest_ind(sa, ba, alternative="greater")

    print(f"  Strategy (accum+markup, N={len(sa)}): {np.mean(sa):+.2f}%")
    print(f"  BH (all, N={len(ba)}): {np.mean(ba):+.2f}%")
    print(f"  Excess: {eff:+.2f}%, t={t:.3f}, p={p:.4f} → {'✅' if p < 0.05 else '❌'}")

    return HypothesisResult("H7", p < 0.05, p, eff, {
        "strategy_mean": float(np.mean(sa)), "bh_mean": float(np.mean(ba)),
        "strategy_n": len(sa), "bh_n": len(ba),
    })


def run_all_hypotheses(
    records: List[StockRecord], config: VerifierConfig
) -> Dict[str, HypothesisResult]:
    h1 = run_h1_monthly_phase_predicts(records, config)
    h3 = run_h3_multitf_consistency(records, config)
    h4 = run_h4_hierarchical_levels(records, config)
    h7 = run_h7_full_strategy(records, config)
    return {"H1+H2": h1, "H3": h3, "H4": h4, "H7": h7}
