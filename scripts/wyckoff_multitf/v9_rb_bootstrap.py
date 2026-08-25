#!/usr/bin/env python3
"""Monte Carlo bootstrap validation — vectorized, fast."""
import sys, json, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from scipy import stats

DATA_PATH = Path("scripts/wyckoff_multitf/output_rb_validation/rb_validation_rows.json")
N_BOOT = 500
PHASES = ["accumulation", "markup", "distribution", "markdown", "unknown"]
RNG = np.random.RandomState(42)


def ci_mean(v, n_boot=N_BOOT):
    v = np.asarray(v, dtype=float)
    if len(v) < 5:
        return float(np.mean(v)), (float(np.mean(v)), float(np.mean(v)))
    boots = np.array([np.mean(RNG.choice(v, size=len(v), replace=True)) for _ in range(n_boot)])
    return float(np.mean(v)), (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))


def ci_proportion(series, target, n_boot=N_BOOT):
    arr = np.array(series)
    n = len(arr)
    target_arr = np.array(target)
    props = []
    for _ in range(n_boot):
        boot = RNG.choice(arr, size=n, replace=True)
        props.append(np.mean(boot == target_arr))
    return float(np.mean(props)), (float(np.percentile(props, 2.5)), float(np.percentile(props, 97.5)))


def main():
    with open(DATA_PATH) as f:
        rows = json.load(f)
    n = len(rows)
    print(f"Loaded {n} observations\n")

    # Pre-extract
    chain_phases = np.array([r["chain_phase"] for r in rows])
    engine_phases = np.array([r["engine_phase"] for r in rows])
    fwd3 = np.array([r["fwd3"] for r in rows], dtype=float)
    chain_rets = {p: fwd3[chain_phases == p] for p in PHASES}
    engine_rets = {p: fwd3[engine_phases == p] for p in PHASES}

    # === TEST 1: Bootstrap CI phase returns ===
    print("=" * 70)
    print("TEST 1: Bootstrap CI on phase returns (chain-only)")
    print("=" * 70)
    for p in PHASES:
        v = chain_rets[p]
        if len(v) >= 5:
            m, (lo, hi) = ci_mean(v)
            _, pval = stats.ttest_1samp(v, 0) if len(v) >= 3 else (0, 1)
            print(f"  {p:<12} n={len(v):>6} mean={m:+7.2f} [{lo:+7.2f},{hi:+7.2f}] p={pval:.4f}")

    # === TEST 2: Markup/markdown reversal ===
    print("\n" + "=" * 70)
    print("TEST 2: Markup/markdown direction reversal")
    print("=" * 70)
    for label, rets in [("chain-only", chain_rets), ("current", engine_rets)]:
        mu, md = rets["markup"], rets["markdown"]
        if len(mu) >= 5 and len(md) >= 5:
            m_mu, (lo_u, hi_u) = ci_mean(mu)
            m_md, (lo_d, hi_d) = ci_mean(md)
            t, p = stats.ttest_ind(mu, md, alternative="greater")
            rev = "REVERSED" if m_mu < m_md and p < 0.05 else "NOT REVERSED"
            print(f"  {label:12} mup={m_mu:+7.2f}[{lo_u:+7.2f},{hi_u:+7.2f}] "
                  f"mdn={m_md:+7.2f}[{lo_d:+7.2f},{hi_d:+7.2f}] t={t:.3f} p={p:.4f} {rev}")

    # === TEST 3: Phase distribution (one-shot) ===
    print("\n" + "=" * 70)
    print("TEST 3: Phase distribution bootstrap CI")
    print("=" * 70)
    for label, phases in [("chain-only", chain_phases), ("current", engine_phases)]:
        cnt = collections.Counter(phases.tolist())
        props = {p: [] for p in PHASES}
        for _ in range(N_BOOT):
            boot = RNG.choice(phases, size=len(phases), replace=True)
            bc = collections.Counter(boot.tolist())
            for p in PHASES:
                props[p].append(bc.get(p, 0) / len(phases))
        print(f"  {label}:")
        for p in PHASES:
            prop = cnt.get(p, 0) / len(phases)
            lo, hi = np.percentile(props[p], [2.5, 97.5])
            print(f"    {p:<12} {prop*100:6.2f}% [{lo*100:6.2f}%, {hi*100:6.2f}%]")

    # === TEST 4: P&F new thresholds ===
    print("\n" + "=" * 70)
    print("TEST 4: Bootstrap CI on P&F proposed new thresholds")
    print("=" * 70)
    new_hints = np.array([r["pnf_hint_new"] for r in rows])
    new_cnt = collections.Counter(new_hints.tolist())
    props = {}
    for p in ["accumulation", "distribution", "unknown"]:
        ps = []
        for _ in range(N_BOOT):
            boot = RNG.choice(new_hints, size=len(new_hints), replace=True)
            ps.append(np.mean(boot == p))
        props[p] = ps
    for p in ["accumulation", "distribution", "unknown"]:
        prop = new_cnt.get(p, 0) / len(new_hints)
        lo, hi = np.percentile(props[p], [2.5, 97.5])
        print(f"    {p:<12} {prop*100:6.2f}% [{lo*100:6.2f}%, {hi*100:6.2f}%]")

    # === TEST 5: Regime-split ===
    print("\n" + "=" * 70)
    print("TEST 5: Regime-split — markup/markdown across sub-periods")
    print("=" * 70)
    for label, start, end in [("2020-2021", "2020-01-31", "2021-12-31"),
                              ("2022-2023", "2022-01-31", "2023-12-31"),
                              ("2024", "2024-01-31", "2024-06-28")]:
        mask = np.array([start <= r["cutoff"] <= end for r in rows])
        sub = fwd3[mask]
        sub_phases = chain_phases[mask]
        print(f"  {label} (n={len(sub)}):")
        for p in ["markup", "markdown"]:
            v = sub[sub_phases == p]
            if len(v) >= 5:
                m, (lo, hi) = ci_mean(v)
                print(f"    {p:<12} n={len(v):>5} mean={m:+7.2f} [{lo:+7.2f},{hi:+7.2f}]")

    # === TEST 6: P&F current hint distribution ===
    print("\n" + "=" * 70)
    print("TEST 6: P&F current hint distribution (bootstrap)")
    print("=" * 70)
    hints = np.array([r["pnf_hint"] for r in rows])
    cnt = collections.Counter(hints.tolist())
    props = {}
    for p in ["accumulation", "distribution", "unknown"]:
        ps = []
        for _ in range(N_BOOT):
            boot = RNG.choice(hints, size=len(hints), replace=True)
            ps.append(np.mean(boot == p))
        props[p] = ps
    for p in ["accumulation", "distribution", "unknown"]:
        prop = cnt.get(p, 0) / len(hints)
        lo, hi = np.percentile(props[p], [2.5, 97.5])
        print(f"    {p:<12} {prop*100:6.2f}% [{lo*100:6.2f}%, {hi*100:6.2f}%]")

    # === TEST 7: Override analysis ===
    print("\n" + "=" * 70)
    print("TEST 7: P&F override analysis")
    print("=" * 70)
    pnf_hints = np.array([r["pnf_hint"] for r in rows])
    forced = np.sum(np.isin(pnf_hints, ["accumulation", "distribution"]))
    disagree = np.sum(np.isin(pnf_hints, ["accumulation", "distribution"])
                      & (pnf_hints != chain_phases))
    print(f"  P&F could override: {forced}/{n} = {forced/n*100:.1f}%")
    print(f"  Override disagrees w/chain: {disagree}/{forced} = {disagree/forced*100:.1f}%")
    print(f"  Override agrees w/chain: {forced-disagree}/{forced} = {(forced-disagree)/forced*100:.1f}%")

    # === SUMMARY ===
    print("\n" + "=" * 70)
    print("S U M M A R Y  J U D G M E N T")
    print("=" * 70)
    for label, rets in [("Chain-only", chain_rets), ("Current", engine_rets)]:
        print(f"  {label}:")
        for p in PHASES:
            v = rets[p]
            if len(v):
                print(f"    {p:<12} {len(v):>6} obs  mean={np.mean(v):+7.2f}%")

    accum_pct = (chain_phases == "accumulation").mean() * 100
    new_accum_pct = (new_hints == "accumulation").mean() * 100
    print(f"\n  Chain-only accumulation: {accum_pct:.1f}%"
          f"  {'(TOO LOW — Phase 1 tightens further? WRONG)' if accum_pct < 5 else '(within range)'}")
    print(f"  P&F new thresholds accum: {new_accum_pct:.1f}%"
          f"  {'(KILLED — recalibrate!)' if new_accum_pct < 5 else '(acceptable)'}")
    print(f"  P&F new thresholds unknown: {new_cnt.get('unknown',0)/len(new_hints)*100:.1f}%"
          f"  {'(P&F hint dead)' if new_cnt.get('unknown',0)/len(new_hints)*100 > 80 else '(alive)'}")

    out = Path("scripts/wyckoff_multitf/output_rb_validation")
    out.mkdir(parents=True, exist_ok=True)
    print(f"\nDone: {n} obs, {N_BOOT} iterations.")


if __name__ == "__main__":
    main()