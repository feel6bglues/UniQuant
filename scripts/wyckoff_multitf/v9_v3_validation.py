#!/usr/bin/env python3
"""v3.0 Plan Medium-Scale Validation — Phase 1+2 combined simulation.

Uses existing 52K obs from v2_medium_validation + CSI 300 market state.

Simulates:
  Phase 1: markdown rp constraint (rp < 0.20 → filtered to unknown)
  Phase 2: market state adaptive detection
    - Bear: suppress markup (short_trend < 0.03 AND no rp condition)
    - Bull: suppress markdown (short_trend > -0.05 AND no rp condition)
  Combined: Phase 1 + Phase 2 together

Run: python3 scripts/wyckoff_multitf/v9_v3_validation.py
"""
import sys, json, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
from scipy import stats

DATA_PATH = Path("scripts/wyckoff_multitf/output_v2_validation/v2_medium_rows.json")
CSI300_PATH = Path("data/lake/quotes/daily/000300.SH.parquet")
N_BOOT = 1000
PHASES = ["accumulation", "markup", "distribution", "markdown", "unknown"]
RNG = np.random.RandomState(42)


def load_market_states():
    """Load CSI 300 and compute market state for each cutoff (month-end)."""
    df = pd.read_parquet(CSI300_PATH)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["mk"] = df["date"].dt.to_period("M").astype(str)
    agg = df.groupby("mk").agg(
        close=("close", "last"),
        date=("date", "last")
    ).reset_index().sort_values("date")

    idx = pd.date_range(agg["date"].min(), agg["date"].max(), freq="ME")
    states = {}
    for cutoff_me in idx:
        cutoff_str = cutoff_me.strftime("%Y-%m-%d")
        # Find the last trading day on or before this month-end
        subset = agg[agg["date"] <= cutoff_me]
        if len(subset) < 6:
            states[cutoff_str] = "neutral"
            continue
        lookback = subset.tail(12)
        if len(lookback) < 6:
            states[cutoff_str] = "neutral"
            continue
        ma6 = lookback["close"].iloc[-6:].mean()
        ma12 = lookback["close"].mean()
        ratio = ma6 / ma12
        if ratio > 1.05:
            states[cutoff_str] = "bull"
        elif ratio < 0.95:
            states[cutoff_str] = "bear"
        else:
            states[cutoff_str] = "neutral"
    return states


def ci_mean(v, n_boot=N_BOOT):
    v = np.asarray(v, dtype=float)
    if len(v) < 5:
        return float(np.mean(v)), (float(np.mean(v)), float(np.mean(v)))
    boots = np.array([np.mean(RNG.choice(v, size=len(v), replace=True)) for _ in range(n_boot)])
    return float(np.mean(v)), (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))


def main():
    with open(DATA_PATH) as f:
        rows = json.load(f)
    n = len(rows)
    print(f"Loaded {n} observations\n")

    # Load market states
    market_states = load_market_states()
    print(f"Market states: {len(market_states)} cutoffs loaded")
    state_counts = collections.Counter(market_states.values())
    for s, c in state_counts.most_common():
        print(f"  {s}: {c} ({c/len(market_states)*100:.1f}%)")
    print()

    # Add market state to each row
    for r in rows:
        r["market_state"] = market_states.get(r["cutoff"], "neutral")

    # Extract arrays
    chain_phases = np.array([r["chain_phase"] for r in rows])
    fwd3 = np.array([r["fwd3"] for r in rows], dtype=float)
    rp = np.array([r["relative_position"] for r in rows], dtype=float)
    st = np.array([r["short_trend"] for r in rows], dtype=float)
    ms = np.array([r["market_state"] for r in rows])

    # ═══════════════════════════════════════════════════════════════
    # TEST 1: Phase 1 — markdown rp constraint
    # ═══════════════════════════════════════════════════════════════
    print("=" * 70)
    print("TEST 1: Phase 1 — markdown rp constraint")
    print("=" * 70)

    md_mask = chain_phases == "markdown"
    md_rp = rp[md_mask]
    md_fwd = fwd3[md_mask]
    print(f"  Current markdown: {md_mask.sum():>6} ({md_mask.sum()/n*100:.1f}%)")
    print(f"  Current markdown 3m mean: {np.mean(md_fwd):+.2f}%")

    # rp threshold scan
    for rp_thresh in [0.10, 0.15, 0.20, 0.25, 0.30]:
        filtered = md_rp < rp_thresh
        kept = md_mask & (rp >= rp_thresh)
        filtered_fwd = md_fwd[filtered]
        kept_fwd = fwd3[kept]
        print(f"\n  rp >= {rp_thresh:.2f}:")
        print(f"    kept: {kept.sum():>6} ({kept.sum()/n*100:.1f}%)")
        print(f"    filtered out: {filtered.sum():>6} ({filtered.sum()/md_mask.sum()*100:.1f}% of markdown)")
        if len(kept_fwd) >= 5:
            km, (klo, khi) = ci_mean(kept_fwd)
            print(f"    kept fwd3: {km:+.2f}% [{klo:+.2f},{khi:+.2f}]")
        if len(filtered_fwd) >= 5:
            fm, (flo, fhi) = ci_mean(filtered_fwd)
            print(f"    filtered fwd3: {fm:+.2f}% [{flo:+.2f},{fhi:+.2f}]")

    # ═══════════════════════════════════════════════════════════════
    # TEST 2: Phase 2 — market state adaptive markup/markdown
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("TEST 2: Phase 2 — market state adaptive detection")
    print("=" * 70)

    for state in ["bull", "bear", "neutral"]:
        state_mask = ms == state
        state_n = state_mask.sum()
        if state_n < 100:
            continue
        print(f"\n  Market state: {state} (n={state_n})")
        for p in ["markup", "markdown"]:
            p_mask = chain_phases == p
            combined = state_mask & p_mask
            v = fwd3[combined]
            if len(v) >= 5:
                m, (lo, hi) = ci_mean(v)
                t, pval = stats.ttest_1samp(v, 0) if len(v) >= 3 else (0, 1)
                correct = (p == "markup" and m > 0) or (p == "markdown" and m < 0)
                print(f"    {p:<10} n={len(v):>5} mean={m:+8.2f} [{lo:+8.2f},{hi:+8.2f}] p={pval:.4f} {'✅' if correct else '❌'}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 3: Phase 2 simulation — suppress markup in bear, markdown in bull
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("TEST 3: Phase 2 simulation — adaptive suppression")
    print("=" * 70)

    # Simulated phases
    sim_phases = []
    for r in rows:
        orig = r["chain_phase"]
        state = r["market_state"]
        ctx_st = r["short_trend"]
        ctx_rp = r["relative_position"]

        if orig == "markup" and state == "bear":
            # Bear market: require strong evidence
            if ctx_st >= 0.03 and r["ma5"] >= r["ma20"]:
                sim_phases.append("markup")
            else:
                sim_phases.append("unknown")
        elif orig == "markdown" and state == "bull":
            # Bull market: require strong evidence
            if ctx_st <= -0.05 and ctx_rp >= 0.30:
                sim_phases.append("markdown")
            else:
                sim_phases.append("unknown")
        else:
            sim_phases.append(orig)

    sim_phases = np.array(sim_phases)
    print(f"  {'Phase':<12} {'Chain':<8} {'Adaptive':<10} {'Change':<10}")
    chain_cnt = collections.Counter(chain_phases.tolist())
    sim_cnt = collections.Counter(sim_phases.tolist())
    for p in PHASES:
        chain_c = chain_cnt.get(p, 0)
        sim_c = sim_cnt.get(p, 0)
        print(f"  {p:<12} {chain_c:>6} {sim_c:>8} {sim_c-chain_c:>+8}")

    # Forward returns by adaptive phase
    print(f"\n  {'Phase':<12} {'n':<8} {'mean_fwd3':<12} {'pos_pct':<8}")
    for p in PHASES:
        v = fwd3[sim_phases == p]
        if len(v) >= 5:
            m, (lo, hi) = ci_mean(v)
            print(f"  {p:<12} {len(v):<8} {m:+8.2f} [{lo:+8.2f},{hi:+8.2f}]  {(v>0).mean()*100:5.1f}%")

    # ═══════════════════════════════════════════════════════════════
    # TEST 4: Combined Phase 1 + Phase 2
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("TEST 4: Combined Phase 1 (rp≥0.20) + Phase 2 (adaptive)")
    print("=" * 70)

    combined_phases = []
    for r in rows:
        orig = r["chain_phase"]
        state = r["market_state"]
        ctx_st = r["short_trend"]
        ctx_rp = r["relative_position"]

        # Phase 1: markdown rp constraint
        if orig == "markdown" and ctx_rp < 0.20:
            orig = "unknown"

        # Phase 2: adaptive suppression
        if orig == "markup" and state == "bear":
            if ctx_st >= 0.03 and r["ma5"] >= r["ma20"]:
                combined_phases.append("markup")
            else:
                combined_phases.append("unknown")
        elif orig == "markdown" and state == "bull":
            if ctx_st <= -0.05 and ctx_rp >= 0.30:
                combined_phases.append("markdown")
            else:
                combined_phases.append("unknown")
        else:
            combined_phases.append(orig)

    combined_phases = np.array(combined_phases)
    comb_cnt = collections.Counter(combined_phases.tolist())
    print(f"  {'Phase':<12} {'Chain':<8} {'Combined':<10} {'Target':<10}")
    for p in PHASES:
        chain_c = chain_cnt.get(p, 0)
        comb_c = comb_cnt.get(p, 0)
        targets = {"accumulation": "8-12%", "markup": "15-20%", "distribution": "10-15%",
                    "markdown": "15-25%", "unknown": "25-40%"}
        print(f"  {p:<12} {chain_c/len(rows)*100:>6.1f}% {comb_c/len(rows)*100:>8.1f}%  target={targets[p]}")

    # Forward returns by combined phase
    print(f"\n  {'Phase':<12} {'n':<8} {'mean_fwd3':<12} {'pos_pct':<8} {'direction':<12}")
    for p in PHASES:
        v = fwd3[combined_phases == p]
        if len(v) >= 5:
            m, (lo, hi) = ci_mean(v)
            correct = (p == "markup" and m > 0) or (p == "markdown" and m < 0) or \
                      (p == "accumulation" and m > 0) or (p == "distribution" and m < 0)
            print(f"  {p:<12} {len(v):<8} {m:+8.2f} [{lo:+8.2f},{hi:+8.2f}]  {(v>0).mean()*100:5.1f}%  {'✅' if correct else '❌'}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 5: Bootstrap on combined distribution
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("TEST 5: Bootstrap CI on combined Phase 1+2 distribution")
    print("=" * 70)
    props = {p: [] for p in PHASES}
    for _ in range(N_BOOT):
        boot = RNG.choice(combined_phases, size=n, replace=True)
        bc = collections.Counter(boot.tolist())
        for p in PHASES:
            props[p].append(bc.get(p, 0) / n)
    for p in PHASES:
        prop = comb_cnt.get(p, 0) / n
        lo, hi = np.percentile(props[p], [2.5, 97.5])
        print(f"  {p:<12} {prop*100:6.2f}% [{lo*100:6.2f}%, {hi*100:6.2f}%]")

    # ═══════════════════════════════════════════════════════════════
    # TEST 6: Regime-split on combined phases
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("TEST 6: Regime-split — combined Phase 1+2 direction")
    print("=" * 70)
    regimes = [
        ("2020-2021 (bull)", "2020-01-31", "2021-12-31"),
        ("2022-2023 (bear)", "2022-01-31", "2023-12-31"),
        ("2024 (bear)", "2024-01-31", "2024-06-28"),
    ]
    for label, s, e in regimes:
        mask = np.array([s <= r["cutoff"] <= e for r in rows])
        sub_fwd = fwd3[mask]
        sub_phases = combined_phases[mask]
        print(f"\n  {label} (n={mask.sum()}):")
        for p in ["markup", "markdown"]:
            v = sub_fwd[sub_phases == p]
            if len(v) >= 5:
                m, (lo, hi) = ci_mean(v)
                t, pval = stats.ttest_1samp(v, 0) if len(v) >= 3 else (0, 1)
                correct = (p == "markup" and m > 0) or (p == "markdown" and m < 0)
                print(f"    {p:<10} n={len(v):>5} mean={m:+8.2f} [{lo:+8.2f},{hi:+8.2f}] "
                      f"p={pval:.4f} {'✅' if correct else '❌'}")

    # ═══════════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("S U M M A R Y  —  v3.0 Plan Validation")
    print("=" * 70)
    print(f"  Phase 1 rp=0.20: markdown {md_mask.sum()/n*100:.1f}% → "
          f"{(chain_phases=='markdown')[rp>=0.20].sum()/n*100:.1f}% (filtered)")
    print(f"  Phase 2 adaptive: markup {chain_cnt.get('markup',0)/n*100:.1f}% → "
          f"{sim_cnt.get('markup',0)/n*100:.1f}%")
    print(f"  Combined: markdown {comb_cnt.get('markdown',0)/n*100:.1f}% "
          f"(target 15-25%)")
    print(f"  Combined: markup {comb_cnt.get('markup',0)/n*100:.1f}% "
          f"(target 15-20%)")
    print(f"  Combined: unknown {comb_cnt.get('unknown',0)/n*100:.1f}% "
          f"(target 25-40%)")

    # Direction check
    for label, phases in [("Chain-only", chain_phases), ("Combined", combined_phases)]:
        mu = np.mean(fwd3[phases == "markup"]) if (phases == "markup").sum() >= 5 else 0
        md = np.mean(fwd3[phases == "markdown"]) if (phases == "markdown").sum() >= 5 else 0
        print(f"  {label}: markup={mu:+.2f}% markdown={md:+.2f}% "
              f"{'✅ direction fixed' if mu > 0 and md < 0 else '⚠️ partially fixed' if mu > md else '❌ direction reversed'}")

    # Save summary
    out = Path("scripts/wyckoff_multitf/output_v3_validation")
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "n_obs": n,
        "chain_distribution": {p: chain_cnt.get(p, 0) / n for p in PHASES},
        "combined_distribution": {p: comb_cnt.get(p, 0) / n for p in PHASES},
        "chain_returns": {p: float(np.mean(fwd3[chain_phases == p])) if (chain_phases == p).sum() > 0 else 0 for p in PHASES},
        "combined_returns": {p: float(np.mean(fwd3[combined_phases == p])) if (combined_phases == p).sum() > 0 else 0 for p in PHASES},
    }
    with open(out / "v3_validation_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()