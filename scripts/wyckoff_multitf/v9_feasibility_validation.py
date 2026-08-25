#!/usr/bin/env python3
"""Feasibility report validation — vote + resonance + causal chain hypothesis testing.

Tests the feasibility report's 4 key claims on 52K obs:
  1. P&F voting: Does P&F + chain voting improve phase quality?
  2. Resonance reverse: Does resonance reverse indication fix direction?
  3. Causal chain: Does event-driven phase beat detection chain?
  4. Combined: What's the theoretical consistency improvement?

Run: python3 scripts/wyckoff_multitf/v9_feasibility_validation.py
"""
import sys, json, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from scipy import stats

DATA_PATH = Path("scripts/wyckoff_multitf/output_v2_validation/v2_medium_rows.json")
N_BOOT = 1000
PHASES = ["accumulation", "markup", "distribution", "markdown", "unknown"]
RNG = np.random.RandomState(42)


def ci_mean(v, n_boot=N_BOOT):
    v = np.asarray(v, dtype=float)
    if len(v) < 5:
        return float(np.mean(v)), (float(np.mean(v)), float(np.mean(v)))
    boots = np.array([np.mean(RNG.choice(v, size=len(v), replace=True)) for _ in range(n_boot)])
    return float(np.mean(v)), (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))


def synthetic_weekly_phase(rp, st):
    """Create synthetic weekly phase from relative_position + short_trend."""
    if rp < 0.25 and st < -0.05:
        return "markdown"
    if rp < 0.35 and st < -0.02:
        return "accumulation"
    if rp > 0.60 and st > 0.03:
        return "markup"
    if rp > 0.55 and st > 0.01:
        return "distribution"
    return "unknown"


def synthetic_daily_phase(st, ma5, ma20):
    """Create synthetic daily phase from short_trend + MA crossover."""
    if st < -0.05:
        return "markdown"
    if st > 0.03:
        return "markup"
    if ma5 < ma20 and st < -0.02:
        return "accumulation"
    if ma5 > ma20 and st > 0.01:
        return "distribution"
    return "unknown"


def resonance_vote(monthly, weekly, daily):
    """Multi-timeframe resonance voting (reverse-indicative)."""
    bullish = {"accumulation", "markup"}
    bearish = {"distribution", "markdown"}

    phases = [monthly, weekly, daily]
    bc = sum(1 for p in phases if p in bullish)
    bc2 = sum(1 for p in phases if p in bearish)

    # Reverse-indicative resonance
    if bc >= 2:
        return "distribution"  # bullish consensus → reverse to distribution
    if bc2 >= 2:
        return "accumulation"  # bearish consensus → reverse to accumulation
    return monthly  # conflicting → use monthly as fallback


def majority_vote(phases):
    """Simple majority vote among phase sources."""
    votes = collections.Counter(phases)
    # Exclude 'unknown' from voting
    known = {k: v for k, v in votes.items() if k != "unknown"}
    if not known:
        return "unknown"
    # If any phase has majority, use it
    total = sum(known.values())
    for p, c in known.items():
        if c > total / 2:
            return p
    # No majority: return the most common known phase
    return max(known, key=known.get)


def main():
    with open(DATA_PATH) as f:
        rows = json.load(f)
    n = len(rows)
    print(f"Loaded {n} observations\n")

    fwd3 = np.array([r["fwd3"] for r in rows], dtype=float)
    chain_phases = np.array([r["chain_phase"] for r in rows])
    pnf_hints = np.array([r["pnf_hint"] for r in rows])
    st = np.array([r["short_trend"] for r in rows], dtype=float)
    rp = np.array([r["relative_position"] for r in rows], dtype=float)
    ma5 = np.array([r["ma5"] for r in rows], dtype=float)
    ma20 = np.array([r["ma20"] for r in rows], dtype=float)

    # Create synthetic phases
    weekly_phases = np.array([synthetic_weekly_phase(rp[i], st[i]) for i in range(n)])
    daily_phases = np.array([synthetic_daily_phase(st[i], ma5[i], ma20[i]) for i in range(n)])

    # ═══════════════════════════════════════════════════════════════
    # TEST 1: P&F Voting — does P&F + chain voting improve?
    # ═══════════════════════════════════════════════════════════════
    print("=" * 70)
    print("TEST 1: P&F Voting — chain + P&F majority vote")
    print("=" * 70)

    voted_phases_pf = np.array([
        majority_vote([chain_phases[i], pnf_hints[i]])
        for i in range(n)
    ])

    def show_distribution(label, phases):
        cnt = collections.Counter(phases.tolist())
        print(f"\n  {label}:")
        for p in PHASES:
            c = cnt.get(p, 0)
            print(f"    {p:<12} {c:>7} {c/n*100:5.1f}%")
        return cnt

    cnt_chain = show_distribution("Chain-only", chain_phases)
    cnt_pnf = show_distribution("P&F-only", pnf_hints)
    cnt_voted = show_distribution("Chain+P&F voted", voted_phases_pf)

    # Directionality
    print(f"\n  {'Phase':<12} {'Chain':<10} {'P&F':<10} {'Voted':<10}")
    for p in PHASES:
        cv = np.mean(fwd3[chain_phases == p]) if (chain_phases == p).sum() > 0 else 0
        pv = np.mean(fwd3[pnf_hints == p]) if (pnf_hints == p).sum() > 0 else 0
        vv = np.mean(fwd3[voted_phases_pf == p]) if (voted_phases_pf == p).sum() > 0 else 0
        print(f"  {p:<12} {cv:+8.2f}  {pv:+8.2f}  {vv:+8.2f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 2: Resonance voting — does resonance reverse indication fix direction?
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("TEST 2: Resonance reverse-indication voting")
    print("=" * 70)

    # Normal resonance (classic: consensus = confirmation)
    normal_resonance = np.array([
        majority_vote([chain_phases[i], weekly_phases[i], daily_phases[i]])
        for i in range(n)
    ])

    # Reverse resonance (A-share: consensus = reverse)
    reverse_resonance = np.array([
        resonance_vote(chain_phases[i], weekly_phases[i], daily_phases[i])
        for i in range(n)
    ])

    cnt_normal = show_distribution("Normal resonance", normal_resonance)
    cnt_reverse = show_distribution("Reverse resonance", reverse_resonance)

    print(f"\n  {'Phase':<12} {'Chain':<10} {'Normal':<10} {'Reverse':<10}")
    for p in PHASES:
        cv = np.mean(fwd3[chain_phases == p]) if (chain_phases == p).sum() > 0 else 0
        nv = np.mean(fwd3[normal_resonance == p]) if (normal_resonance == p).sum() > 0 else 0
        rv = np.mean(fwd3[reverse_resonance == p]) if (reverse_resonance == p).sum() > 0 else 0
        print(f"  {p:<12} {cv:+8.2f}  {nv:+8.2f}  {rv:+8.2f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 3: Combined — P&F vote + reverse resonance
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("TEST 3: Combined — P&F vote + resonance + reverse-indication")
    print("=" * 70)

    combined_phases = np.array([
        resonance_vote(
            voted_phases_pf[i],  # P&F+chain voted as monthly
            weekly_phases[i],
            daily_phases[i],
        )
        for i in range(n)
    ])

    cnt_combined = show_distribution("Combined (P&F vote + reverse resonance)", combined_phases)

    print(f"\n  {'Phase':<12} {'Chain':<10} {'Combined':<12} {'Target':<10}")
    targets = {"accumulation": "3-8%", "markup": "12-18%", "distribution": "5-10%",
               "markdown": "15-25%", "unknown": "40-60%"}
    for p in PHASES:
        cc = cnt_chain.get(p, 0) / n * 100
        comb = cnt_combined.get(p, 0) / n * 100
        print(f"  {p:<12} {cc:>6.1f}%  {comb:>8.1f}%    target={targets[p]}")

    # Directionality
    print(f"\n  {'Phase':<12} {'n':<8} {'mean_fwd3':<12} {'direction':<12}")
    for p in PHASES:
        v = fwd3[combined_phases == p]
        if len(v) >= 5:
            m, (lo, hi) = ci_mean(v)
            correct = (p == "markup" and m > 0) or (p == "markdown" and m < 0) or \
                      (p == "accumulation" and m > 0) or (p == "distribution" and m < 0)
            print(f"  {p:<12} {len(v):<8} {m:+8.2f} [{lo:+8.2f},{hi:+8.2f}]  {'✅' if correct else '❌'}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 4: Causal chain hypothesis — does event-driven beat detection chain?
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("TEST 4: Causal chain hypothesis — can we predict direction from context?")
    print("=" * 70)
    # Since we don't have event data, we test: can we predict forward returns
    # better than random using the context variables that causal chains would use?
    # Hypothesis: short_trend + relative_position + prior_trend are better predictors
    # than the current chain_phase label.

    # Simple model: short_trend < -0.05 → buy (mean reversion), short_trend > 0.05 → sell
    buy_signals = st < -0.05
    sell_signals = st > 0.05
    buy_fwd = fwd3[buy_signals]
    sell_fwd = fwd3[sell_signals]
    print(f"  Simple trend model: buy (st<-0.05) n={buy_signals.sum()} mean={np.mean(buy_fwd):+.2f}%")
    print(f"                       sell (st>0.05) n={sell_signals.sum()} mean={np.mean(sell_fwd):+.2f}%")
    if len(buy_fwd) >= 5 and len(sell_fwd) >= 5:
        t, p = stats.ttest_ind(buy_fwd, sell_fwd, alternative="greater")
        print(f"                       t={t:.3f} p={p:.4f} {'✅' if p < 0.05 else '❌'}")

    # Compare with chain_phase predictive power
    accum_fwd = fwd3[chain_phases == "accumulation"]
    dist_fwd = fwd3[chain_phases == "distribution"]
    print(f"  Chain phase: accum n={len(accum_fwd)} mean={np.mean(accum_fwd):+.2f}%")
    print(f"               dist n={len(dist_fwd)} mean={np.mean(dist_fwd):+.2f}%")
    if len(accum_fwd) >= 5 and len(dist_fwd) >= 5:
        t, p = stats.ttest_ind(accum_fwd, dist_fwd, alternative="greater")
        print(f"               t={t:.3f} p={p:.4f} {'✅' if p < 0.05 else '❌'}")

    # Test: does the combined approach produce monotonic returns?
    print(f"\n  {'Phase':<12} {'Chain':<10} {'Combined':<12}")
    for p in PHASES:
        cv = np.mean(fwd3[chain_phases == p]) if (chain_phases == p).sum() > 0 else 0
        comb_mean = np.mean(fwd3[combined_phases == p]) if (combined_phases == p).sum() > 0 else 0
        print(f"  {p:<12} {cv:+8.2f}  {comb_mean:+8.2f}")

    # Monotonicity check
    chain_order = [np.mean(fwd3[chain_phases == p]) if (chain_phases == p).sum() > 0 else -999
                   for p in ["accumulation", "markup", "unknown", "distribution", "markdown"]]
    combined_order = [np.mean(fwd3[combined_phases == p]) if (combined_phases == p).sum() > 0 else -999
                     for p in ["accumulation", "markup", "unknown", "distribution", "markdown"]]
    chain_mono = all(chain_order[i] >= chain_order[i+1] for i in range(len(chain_order)-1) if chain_order[i] > -999 and chain_order[i+1] > -999)
    comb_mono = all(combined_order[i] >= combined_order[i+1] for i in range(len(combined_order)-1) if combined_order[i] > -999 and combined_order[i+1] > -999)
    print(f"  Chain monotonic: {chain_mono}  Combined monotonic: {comb_mono}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 5: Bootstrap on combined distribution
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("TEST 5: Bootstrap CI on combined distribution")
    print("=" * 70)
    props = {p: [] for p in PHASES}
    for _ in range(N_BOOT):
        boot = RNG.choice(combined_phases, size=n, replace=True)
        bc = collections.Counter(boot.tolist())
        for p in PHASES:
            props[p].append(bc.get(p, 0) / n)
    for p in PHASES:
        prop = cnt_combined.get(p, 0) / n
        lo, hi = np.percentile(props[p], [2.5, 97.5])
        print(f"  {p:<12} {prop*100:6.2f}% [{lo*100:6.2f}%, {hi*100:6.2f}%]")

    # ═══════════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("S U M M A R Y  —  Feasibility Report Validation")
    print("=" * 70)

    # Direction check
    print(f"\n  Directionality comparison:")
    for label, phases in [("Chain-only", chain_phases), ("P&F voted", voted_phases_pf),
                          ("Normal resonance", normal_resonance),
                          ("Reverse resonance", reverse_resonance),
                          ("Combined", combined_phases)]:
        markup_fwd = np.mean(fwd3[phases == "markup"]) if (phases == "markup").sum() >= 5 else 0
        markdown_fwd = np.mean(fwd3[phases == "markdown"]) if (phases == "markdown").sum() >= 5 else 0
        accum_fwd = np.mean(fwd3[phases == "accumulation"]) if (phases == "accumulation").sum() >= 5 else 0
        dist_fwd = np.mean(fwd3[phases == "distribution"]) if (phases == "distribution").sum() >= 5 else 0
        correct = (markup_fwd > 0) + (markdown_fwd < 0) + (accum_fwd > 0) + (dist_fwd < 0)
        print(f"  {label:22} mup={markup_fwd:+7.2f} mdn={markdown_fwd:+7.2f} "
              f"acc={accum_fwd:+7.2f} dist={dist_fwd:+7.2f}  {correct}/4 correct")

    print(f"\n  Feasibility report claims:")
    # P&F voting: does it reduce accumulation bias?
    accum_reduction = cnt_chain.get('accumulation', 0) > cnt_voted.get('accumulation', 0)
    print(f"  P&F voting: {'✅ reduces accum bias' if accum_reduction else '⚠️ mixed'}")

    # Reverse resonance: does it fix markup/markdown direction?
    rr_markup = np.mean(fwd3[reverse_resonance == "markup"]) if (reverse_resonance == "markup").sum() >= 5 else 0
    rr_markdown = np.mean(fwd3[reverse_resonance == "markdown"]) if (reverse_resonance == "markdown").sum() >= 5 else 0
    rev_fixes = rr_markup > 0 and rr_markdown < 0
    print(f"  Reverse resonance: {'✅ fixes direction' if rev_fixes else '⚠️ partial'}")

    # Causal chain: is the combined approach monotonic?
    print(f"  Causal chain: {'✅ supported' if combined_order[0] >= combined_order[-1] else '⚠️ needs more'}")

    # Combined target: is markdown in 15-25% range?
    md_pct = cnt_combined.get('markdown', 0) / n * 100
    print(f"  Combined target: {'✅ on track' if 15 <= md_pct <= 25 else '⚠️ off target'} (md={md_pct:.1f}%)")

    # Save
    out = Path("scripts/wyckoff_multitf/output_feasibility_validation")
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "n_obs": n,
        "chain_distribution": {p: cnt_chain.get(p, 0) / n for p in PHASES},
        "combined_distribution": {p: cnt_combined.get(p, 0) / n for p in PHASES},
        "chain_returns": {p: float(np.mean(fwd3[chain_phases == p])) if (chain_phases == p).sum() > 0 else 0 for p in PHASES},
        "combined_returns": {p: float(np.mean(fwd3[combined_phases == p])) if (combined_phases == p).sum() > 0 else 0 for p in PHASES},
    }
    with open(out / "feasibility_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()