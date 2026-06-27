#!/usr/bin/env python3
"""
Wyckoff Verification: Multi-threaded diagnostic execution.

Reads v4_results.json + phase3_strategy_results.json,
computes all Phase B + D diagnostics from the step plan.

Batch 1: A3, B1, B2, B4, D2 (all read-only)
"""

import json, sys, math, itertools
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
from scipy import stats as scipy_stats

SRC = Path(__file__).resolve().parent
OUT = SRC / "output_v4"
REPORT = []


def log(title: str, *lines: str):
    REPORT.append(f"\n{'='*60}")
    REPORT.append(f"  {title}")
    REPORT.append(f"{'='*60}")
    for l in lines:
        REPORT.append(f"  {l}")


# ═══════════════════════════════════════════════════════════════
# Task B2: Stride overlap quantification
# ═══════════════════════════════════════════════════════════════

def task_b2_stride_overlap(data: list):
    """Quantify how many independent Spring events exist given stride=20 overlap."""
    spring_dates = defaultdict(list)
    for obs in data:
        if obs.get('ds'):
            spring_dates[obs['s']].append(obs['c'])

    total_reported = sum(len(dates) for dates in spring_dates.values())
    total_independent = 0
    cluster_sizes = []

    for sym, dates in spring_dates.items():
        dates = sorted(set(dates))
        i = 0
        while i < len(dates):
            cluster_start = dates[i]
            j = i
            while j + 1 < len(dates):
                d1 = dates[j]
                d2 = dates[j+1]
                try:
                    from datetime import datetime
                    dd1 = datetime.strptime(d1, '%Y-%m-%d')
                    dd2 = datetime.strptime(d2, '%Y-%m-%d')
                    gap = (dd2 - dd1).days
                except Exception:
                    gap = 999
                if gap <= 60:
                    j += 1
                else:
                    break
            total_independent += 1
            cluster_sizes.append(j - i + 1)
            i = j + 1

    bias = total_reported / total_independent if total_independent > 0 else 0
    p90 = sorted(cluster_sizes)[-len(cluster_sizes)//10] if cluster_sizes else 0

    log(
        "B2: Stride=20 Event Overlap Quantification",
        f"  Total reported Spring events: {total_reported}",
        f"  Independent event clusters:   {total_independent}",
        f"  Bias factor:                  {bias:.2f}x",
        f"  Cluster size mean:            {np.mean(cluster_sizes):.2f}" if cluster_sizes else "",
        f"  Cluster size max:             {max(cluster_sizes)}" if cluster_sizes else "",
        f"  Cluster size P90:             {p90}" if cluster_sizes else "",
        "",
        f"  Interpretation:",
        f"    bias < 2x  → mild overlap, t statistics mildly inflated",
        f"    bias 2-3x  → moderate overlap, t statistics may be 1.4-1.7x inflated",
        f"    bias > 3x  → severe overlap, t statistics unreliable",
        f"    Actual: {bias:.1f}x → {'MODERATE' if bias < 3 else 'SEVERE' if bias > 3 else 'MODERATE'} overlap",
    )
    return {'reported': total_reported, 'independent': total_independent, 'bias': bias}


# ═══════════════════════════════════════════════════════════════
# Task B4: Excess vs Raw Return Decomposition
# ═══════════════════════════════════════════════════════════════

def task_b4_excess_decomposition(data: list):
    """Analyze whether excess returns come from true alpha or methodological bias."""
    spring_raw = [o['f6'] for o in data if o.get('ds')]
    nonspring_raw = [o['f6'] for o in data if not o.get('ds')]

    # Since we don't have per-observation market median, approximate
    # by computing the per-date average return and subtracting
    date_avg = defaultdict(list)
    for o in data:
        date_avg[o['c']].append(o['f6'])
    date_mkt = {d: np.mean(v) for d, v in date_avg.items()}

    spring_excess = [o['f6'] - date_mkt.get(o['c'], 0) for o in data if o.get('ds')]
    nonspring_excess = [o['f6'] - date_mkt.get(o['c'], 0) for o in data if not o.get('ds')]
    spring_date_returns = [date_mkt.get(o['c'], 0) for o in data if o.get('ds')]

    log(
        "B4: Excess vs Raw Return Decomposition",
        f"  Spring (N={len(spring_raw)}):",
        f"    Raw 6m mean:  {np.mean(spring_raw):+.2f}%",
        f"    Raw t-test (vs 0): t={scipy_stats.ttest_1samp(spring_raw, 0)[0]:.2f}, p={scipy_stats.ttest_1samp(spring_raw, 0)[1]:.4f}",
        f"    Excess 6m mean: {np.mean(spring_excess):+.2f}%",
        f"    Excess t (vs 0): t={scipy_stats.ttest_1samp(spring_excess, 0)[0]:.2f}",
        f"    Date-mkt mean on Spring days: {np.mean(spring_date_returns):+.2f}%",
        "",
        f"  No-Spring (N={len(nonspring_raw)}):",
        f"    Raw 6m mean:  {np.mean(nonspring_raw):+.2f}%",
        f"    Excess 6m mean: {np.mean(nonspring_excess):+.2f}%",
        "",
        f"  === KEY INSIGHT ===",
        f"  Raw Spring 6m:    {np.mean(spring_raw):+.2f}% (vs 0: {'NOT significant' if scipy_stats.ttest_1samp(spring_raw,0)[1] > 0.05 else 'SIGNIFICANT'})",
        f"  Excess Spring 6m: {np.mean(spring_excess):+.2f}%",
        f"  Decomposition:",
        f"    Total excess = {np.mean(spring_excess):+.2f}%",
        f"    = Raw Spring ({np.mean(spring_raw):+.2f}%) - Date avg ({np.mean(spring_date_returns):+.2f}%)",
        f"    = {np.mean(spring_raw):+.2f}% - {np.mean(spring_date_returns):+.2f}% = {np.mean(spring_raw) - np.mean(spring_date_returns):+.2f}%",
        "",
        f"  Conclusion: {'Excess comes primarily from lower market baseline on Spring days' if np.mean(spring_date_returns) < -0.5 else 'Excess comes from Spring alpha'}",
    )
    return {
        'spring_raw_mean': np.mean(spring_raw),
        'spring_excess_mean': np.mean(spring_excess),
        'spring_date_avg': np.mean(spring_date_returns),
        'n_spring': len(spring_raw),
    }


# ═══════════════════════════════════════════════════════════════
# Task B1: positive_stocks_pct=100% Diagnosis
# ═══════════════════════════════════════════════════════════════

def task_b1_positive_pct():
    """Verify the positive_stocks_pct=100% claim from strategy results."""
    strat_file = OUT / "phase3_strategy_results.json"
    if not strat_file.exists():
        log("B1: positive_stocks_pct=100% Diagnosis", "  ERROR: phase3_strategy_results.json not found")
        return {}

    results = json.loads(strat_file.read_text())

    log("B1: positive_stocks_pct=100% Diagnosis")

    findings = {}
    for param_key, result in results.items():
        details = result.get('details', [])
        n_stocks = len(details)
        positive = sum(1 for d in details if d.get('total_return_pct', 0) > 0)
        negative = sum(1 for d in details if d.get('total_return_pct', 0) <= 0)
        claimed_pct = result.get('positive_stocks_pct', 0)

        # Negative stocks analysis
        neg_stocks = [(d['symbol'], d['total_return_pct'], d['n_trades'])
                      for d in details if d.get('total_return_pct', 0) <= 0]

        # Worst performers
        neg_sorted = sorted(neg_stocks, key=lambda x: x[1])

        # Mean reversion check: do negative stocks have mostly losing trades?
        neg_win_rates = [d.get('avg_pnl_pct', 0) for d in details if d.get('total_return_pct', 0) <= 0]

        log(
            f"  === Strategy: {param_key} ===",
            f"  Stocks with trades: {n_stocks}",
            f"  Claimed positive%:   {claimed_pct}%",
            f"  Actual positive:     {positive}/{n_stocks} ({positive/n_stocks*100:.1f}%)",
            f"  Negative stocks:     {len(neg_stocks)}",
            f"  Negative avg PnL:    {np.mean(neg_win_rates):+.2f}%" if neg_win_rates else "  No negative stocks",
            f"",
            f"  Worst 5 negative stocks:",
        )
        for sym, pnl, nt in neg_sorted[:5]:
            log("", f"    {sym}: total_return={pnl:+.2f}%, trades={nt}")

        findings[param_key] = {
            'positive_pct': claimed_pct,
            'true_positive': positive,
            'true_negative': len(neg_stocks),
            'n_stocks': n_stocks,
            'worst_5': [{'symbol': s, 'pnl': p, 'trades': t} for s, p, t in neg_sorted[:5]],
        }

        # Check if 100% is legitimate
        if len(neg_stocks) > 0:
            log(
                f"",
                f"  ⚠️  Found {len(neg_stocks)} stock(s) with negative total_return_pct!",
                f"  positive_stocks_pct should be {positive}/{n_stocks} = {positive/n_stocks*100:.1f}%",
                f"  DISCREPANCY: claimed {claimed_pct}% vs actual {positive/n_stocks*100:.1f}%",
            )
        else:
            log("", f"  ✅ All {n_stocks} stocks positive - 100% claim verified")

    return findings


# ═══════════════════════════════════════════════════════════════
# Task D2: Entry Delay Analysis (using observation dates)
# ═══════════════════════════════════════════════════════════════

def task_d2_entry_delay(data: list):
    """Analyze how often Spring events cluster and what delays occur."""
    from datetime import datetime, timedelta

    spring_obs = [(o['s'], o['c']) for o in data if o.get('ds')]
    spring_obs.sort(key=lambda x: (x[0], x[1]))

    # Compute gap distribution between consecutive Spring observations per stock
    gaps = []
    for sym, group in itertools.groupby(spring_obs, key=lambda x: x[0]):
        dates = sorted(set(g[1] for g in group))
        for i in range(1, len(dates)):
            try:
                d1 = datetime.strptime(dates[i-1], '%Y-%m-%d')
                d2 = datetime.strptime(dates[i], '%Y-%m-%d')
                gaps.append((d2 - d1).days)
            except Exception:
                pass

    log(
        "D2: Entry Delay Analysis (Spring event gap distribution)",
        f"  Total Spring events: {len(spring_obs)}",
        f"  Unique stocks: {len(set(s for s, _ in spring_obs))}",
        f"  Consecutive Spring gap (days):" if gaps else "  No multi-Spring stocks",
    )
    if gaps:
        log(
            "",
            f"    Mean:  {np.mean(gaps):.1f} days",
            f"    Median:{np.median(gaps):.1f} days",
            f"    P10:   {np.percentile(gaps, 10):.1f} days",
            f"    P90:   {np.percentile(gaps, 90):.1f} days",
            f"    Min:   {min(gaps)} days",
            f"    Max:   {max(gaps)} days",
            f"",
            f"    Gap <= 20 days (same stride window): {sum(1 for g in gaps if g <= 20)} / {len(gaps)} = {sum(1 for g in gaps if g <= 20)/len(gaps)*100:.1f}%",
            f"    Interpretation:",
            f"      stride=20 means entry delay ~10 days avg",
            f"      {np.median(gaps):.1f}-day median gap → repeated Spring detection within same trend",
            f"      delay cost = gap / 2 = {np.median(gaps)/2:.1f} days of potential return slippage",
        )
    return {'spring_count': len(spring_obs), 'mean_gap': np.mean(gaps) if gaps else 0}


# ═══════════════════════════════════════════════════════════════
# Task A3: Phase-wise return verification
# ═══════════════════════════════════════════════════════════════

def task_a3_phase_analysis(data: list):
    """Verify phase distribution and returns match document claims."""
    phase_rets = defaultdict(list)
    phase_spring = defaultdict(list)
    phase_nonspring = defaultdict(list)

    for o in data:
        p = o.get('p', 'unknown')
        ret = o.get('f6', 0)
        phase_rets[p].append(ret)
        if o.get('ds'):
            phase_spring[p].append(ret)
        else:
            phase_nonspring[p].append(ret)

    # Phase distribution
    total = len(data)
    log(
        "A3: Phase Distribution & Return Verification",
        f"  Total observations: {total}",
        f"",
        f"  {'Phase':<15} {'N':<8} {'%':<6} {'Raw6m':<10} {'Spring%':<10} {'SpringN':<10}",
        f"  {'-'*59}",
    )
    for p in ['accumulation', 'markup', 'distribution', 'markdown', 'unknown']:
        if p not in phase_rets:
            continue
        n = len(phase_rets[p])
        raw_mean = np.mean(phase_rets[p])
        sp_n = len(phase_spring.get(p, []))
        sp_pct = sp_n / n * 100 if n > 0 else 0
        log("", f"  {p:<15} {n:<8} {n/total*100:<6.1f} {raw_mean:<+10.2f} {sp_pct:<10.1f} {sp_n:<10}")

    # Spring overall
    all_spring = [o['f6'] for o in data if o.get('ds')]
    all_nonspring = [o['f6'] for o in data if not o.get('ds')]
    t_s, p_s = scipy_stats.ttest_ind(all_spring, all_nonspring, alternative='greater')

    log(
        "",
        f"  Spring overall:",
        f"    N={len(all_spring)}, raw 6m mean: {np.mean(all_spring):+.2f}%",
        f"    No-Spring:     N={len(all_nonspring)}, raw 6m mean: {np.mean(all_nonspring):+.2f}%",
        f"    Spring vs No-Spring: t={t_s:.2f} p={p_s:.4f}",
        f"    {'✅ SIGNIFICANT' if p_s < 0.05 else '❌ NOT significant'} (alpha=0.05, one-tailed)",
        "",
        f"  Document claims:",
        f"    §3.1 says Spring raw 6m = +0.23% / t=0.59 → {'MATCHES' if abs(np.mean(all_spring) - 0.23) < 0.5 else 'DIFFERS'}",
        f"    Actual raw mean: {np.mean(all_spring):+.2f}%",
    )
    return {
        'spring_mean': np.mean(all_spring),
        'spring_t': t_s,
        'spring_p': p_s,
        'n_spring': len(all_spring),
    }


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    data_file = OUT / "v4_results.json"
    if not data_file.exists():
        print(f"ERROR: {data_file} not found. Run runner_v4.py first.")
        sys.exit(1)

    data = json.loads(data_file.read_text())
    obs = data.get('data', [])
    print(f"Loaded {len(obs)} observations from v4_results.json")

    # Run all tasks
    print("\n[Batch 1] Running all diagnostics in parallel-sequential mode...")

    print("\n── Task A3: Phase Analysis ──")
    r_a3 = task_a3_phase_analysis(obs)

    print("\n── Task B2: Stride Overlap ──")
    r_b2 = task_b2_stride_overlap(obs)

    print("\n── Task B4: Excess Decomposition ──")
    r_b4 = task_b4_excess_decomposition(obs)

    print("\n── Task D2: Entry Delay ──")
    r_d2 = task_d2_entry_delay(obs)

    print("\n── Task B1: positive_stocks_pct Diagnosis ──")
    r_b1 = task_b1_positive_pct()

    # Summary
    print(f"\n{'='*60}")
    print(f"  VERIFICATION SUMMARY")
    print(f"{'='*60}")
    print(f"  Data: {len(obs)} observations, {r_a3['n_spring']} Spring events")
    print(f"  Spring raw 6m: {r_a3['spring_mean']:+.2f}% (t={r_a3['spring_t']:.2f}, p={r_a3['spring_p']:.4f})")
    print(f"  Spring vs No-Spring: {'SIGNIFICANT ✅' if r_a3['spring_p'] < 0.05 else 'NOT significant ❌'}")
    print(f"  Overlap bias: {r_b2['bias']:.1f}x")
    print(f"  Spring date avg: {r_b4['spring_date_avg']:+.2f}%")
    print(f"  Spring excess: {r_b4['spring_excess_mean']:+.2f}%")

    # Save report
    report_path = OUT / "verification_report.txt"
    with open(report_path, 'w') as f:
        f.write('\n'.join(REPORT))
    print(f"\n  Full report saved to {report_path}")

    # Save structured results
    results = {
        'meta': {'n_obs': len(obs), 'n_spring': r_a3['n_spring']},
        'a3_phase': {'spring_mean': r_a3['spring_mean'], 'spring_t': r_a3['spring_t'], 'spring_p': r_a3['spring_p']},
        'b2_overlap': r_b2,
        'b4_excess': r_b4,
        'd2_delay': r_d2,
        'b1_strategy': r_b1,
    }
    results_path = OUT / "verification_results.json"
    json.dump(results, open(results_path, 'w'), indent=2)
    print(f"  Structured results saved to {results_path}")


if __name__ == '__main__':
    main()
