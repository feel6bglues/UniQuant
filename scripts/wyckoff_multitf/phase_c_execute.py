#!/usr/bin/env python3
"""Phase C Execution: BH benchmark, parameter stability, market state decomposition."""

import json, sys
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

SRC = Path(__file__).resolve().parent
OUT = SRC / "output_v4"
SH_PATH = Path.home() / "Documents/Project/UniQuant/data/lake/quotes/daily/000001.SH.parquet"

REPORT = []

def log(title, *lines):
    REPORT.append(f"\n{'='*60}")
    REPORT.append(f"  {title}")
    REPORT.append(f"{'='*60}")
    for l in lines:
        REPORT.append(f"  {l}")


# ═══════════════════════════════════════════════════════════════
# C1: BH Benchmark Comparison
# ═══════════════════════════════════════════════════════════════

def task_c1_bh_benchmark(data: list):
    """Compare Spring strategy returns vs SH index buy-and-hold."""
    # Build per-date SH index returns
    sh = pd.read_parquet(SH_PATH)
    sh['date'] = pd.to_datetime(sh['date'])
    sh = sh.set_index('date').sort_index()
    sh_monthly = sh['close'].resample('ME').last()
    sh_6m_rets = sh_monthly.pct_change(6).dropna() * 100

    # Match each observation's cutoff date to SH 6m return
    # We need to query: what was SH's 6m return ending at this cutoff?
    def get_sh_6m(cutoff_str):
        cutoff = pd.Timestamp(cutoff_str)
        # Find the month-end on or before cutoff
        me = cutoff.replace(day=28) + pd.offsets.MonthEnd(0)
        if me in sh_6m_rets.index:
            return sh_6m_rets.loc[me]
        # Nearest
        idx = sh_6m_rets.index.get_indexer([me], method='ffill')[0]
        if idx >= 0:
            return sh_6m_rets.iloc[idx]
        return np.nan

    spring_ret = []
    spring_excess = []
    nonspring_ret = []
    nonspring_excess = []

    for o in data:
        ret_6m = o.get('f6', 0)
        is_spring = o.get('ds', False)
        bh_6m = get_sh_6m(o['c'])
        if np.isnan(bh_6m):
            continue
        excess = ret_6m - bh_6m
        if is_spring:
            spring_ret.append(ret_6m)
            spring_excess.append(excess)
        else:
            nonspring_ret.append(ret_6m)
            nonspring_excess.append(excess)

    log(
        "C1: BH Benchmark Comparison (vs SH Index)",
        f"  Observations with BH data: {len(spring_ret) + len(nonspring_ret)}",
        f"",
        f"  Spring (N={len(spring_ret)}):",
        f"    Raw 6m:       {np.mean(spring_ret):+.2f}%",
        f"    Excess vs SH: {np.mean(spring_excess):+.2f}%",
        f"    Excess t-test (vs 0): t={scipy_stats.ttest_1samp(spring_excess, 0)[0]:.2f} p={scipy_stats.ttest_1samp(spring_excess, 0)[1]:.4f}",
        f"",
        f"  No-Spring (N={len(nonspring_ret)}):",
        f"    Raw 6m:       {np.mean(nonspring_ret):+.2f}%",
        f"    Excess vs SH: {np.mean(nonspring_excess):+.2f}%",
        f"",
        f"  === KEY INSIGHT ===",
        f"  Spring excess vs SH index: {np.mean(spring_excess):+.2f}%",
        f"  {'✅ Spring beats SH index' if np.mean(spring_excess) > 0 else '❌ Spring lags SH index'}",
        f"  Excess source: {'SH index was negative during Spring events' if np.mean(spring_ret) - np.mean(spring_excess) < 0 else ''}",
    )
    return {
        'spring_n': len(spring_ret),
        'spring_excess_vs_sh': np.mean(spring_excess) if spring_excess else 0,
        'spring_excess_t': scipy_stats.ttest_1samp(spring_excess, 0)[0] if spring_excess else 0,
        'spring_excess_p': scipy_stats.ttest_1samp(spring_excess, 0)[1] if spring_excess else 1,
    }


# ═══════════════════════════════════════════════════════════════
# C2: Parameter Stability
# ═══════════════════════════════════════════════════════════════

def task_c2_param_stability():
    """Analyze stability across 4 existing strategy parameter sets."""
    strat_file = OUT / "phase3_strategy_results.json"
    results = json.loads(strat_file.read_text())

    log("C2: Parameter Stability Analysis")
    log("", f"  {'Params':<20} {'N':<5} {'Mean%':<10} {'Median%':<10} {'Pos%':<8} {'WinRate':<8} {'Worst':<10}")
    log("", f"  {'-'*71}")

    param_data = []
    for key, val in results.items():
        details = val.get('details', [])
        pnls = np.array([d.get('total_return_pct', 0) for d in details])
        wrs = np.array([d.get('win_rate', 0) for d in details])
        pos_pct = sum(1 for p in pnls if p > 0) / len(pnls) * 100 if len(pnls) > 0 else 0
        worst = min(pnls) if len(pnls) > 0 else 0
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(12) if np.std(pnls) > 0 else 0

        log("", f"  {key:<20} {len(pnls):<5} {np.mean(pnls):<+10.2f} {np.median(pnls):<+10.2f} {pos_pct:<8.1f} {np.mean(wrs):<8.1f} {worst:<+10.2f}")
        param_data.append({
            'key': key, 'mean': np.mean(pnls), 'median': np.median(pnls),
            'pos_pct': pos_pct, 'win_rate': np.mean(wrs), 'worst': worst,
            'sharpe': sharpe, 'std': np.std(pnls),
        })

    # Parse param values
    for p in param_data:
        parts = p['key'].replace('ST=', '').replace('TP=', '').replace('H=', '').split()
        try:
            p['st'] = int(parts[0].replace(',', '').replace('=', ''))
            p['tp'] = int(parts[1].replace(',', '').replace('=', ''))
            p['hold'] = int(parts[2].replace(',', ''))
        except Exception:
            p['st'] = p['tp'] = p['hold'] = 0

    # Best params
    best = max(param_data, key=lambda x: x['sharpe'])
    log(
        "",
        f"  Best by Sharpe: {best['key']} (Sharpe={best['sharpe']:.3f})",
        f"  Best by Mean:   {max(param_data, key=lambda x: x['mean'])['key']}",
        f"  Best by Median: {max(param_data, key=lambda x: x['median'])['key']}",
        f"  Best by Pos%:   {max(param_data, key=lambda x: x['pos_pct'])['key']}",
        "",
        f"  === STABILITY ASSESSMENT ===",
    )

    sharpe_vals = [p['sharpe'] for p in param_data]
    mean_vals = [p['mean'] for p in param_data]
    log(
        "",
        f"  Sharpe range: {min(sharpe_vals):.3f} - {max(sharpe_vals):.3f}",
        f"  Sharpe std:   {np.std(sharpe_vals):.3f}",
        f"  Mean range:   {min(mean_vals):+.2f}% - {max(mean_vals):+.2f}%",
        f"",
        f"  {'✅ PARAMS STABLE' if np.std(sharpe_vals) < 0.3 else '⚠️ PARAMS MODERATELY VARIABLE' if np.std(sharpe_vals) < 0.6 else '❌ PARAMS UNSTABLE'}",
    )
    return {'best': best['key'], 'sharpe_std': np.std(sharpe_vals)}


# ═══════════════════════════════════════════════════════════════
# C4: Market State Decomposition
# ═══════════════════════════════════════════════════════════════

def task_c4_market_state(data: list):
    """Decompose Spring returns by SH index market regime."""
    sh = pd.read_parquet(SH_PATH)
    sh['date'] = pd.to_datetime(sh['date'])
    sh = sh.set_index('date').sort_index()
    monthly = sh['close'].resample('ME').last()
    monthly_rets = monthly.pct_change().dropna() * 100

    def classify(m):
        if m > 3: return 'bull'
        elif m < -3: return 'bear'
        else: return 'sideways'

    # Get the regime for each observation's cutoff month
    def get_regime(cutoff_str):
        cutoff = pd.Timestamp(cutoff_str)
        me = cutoff.replace(day=28) + pd.offsets.MonthEnd(0)
        if me in monthly_rets.index:
            return classify(monthly_rets.loc[me])
        idx = monthly_rets.index.get_indexer([me], method='ffill')[0]
        if idx >= 0:
            return classify(monthly_rets.iloc[idx])
        return 'unknown'

    regime_spring_ret = defaultdict(list)
    regime_nonspring_ret = defaultdict(list)
    regime_counts = defaultdict(int)

    for o in data:
        regime = get_regime(o['c'])
        regime_counts[regime] += 1
        ret = o.get('f6', 0)
        if o.get('ds'):
            regime_spring_ret[regime].append(ret)
        else:
            regime_nonspring_ret[regime].append(ret)

    log(
        "C4: Market State Decomposition",
        f"  {'Regime':<12} {'Obs':<8} {'Spring':<8} {'Spring%':<10} {'SpringRaw':<12} {'NoSpring':<12} {'Diff':<10}",
        f"  {'-'*72}",
    )

    results = {}
    for regime in ['bull', 'bear', 'sideways', 'unknown']:
        if regime not in regime_spring_ret:
            continue
        sp = regime_spring_ret[regime]
        nsp = regime_nonspring_ret[regime]
        sp_mean = np.mean(sp) if sp else 0
        nsp_mean = np.mean(nsp) if nsp else 0
        diff = sp_mean - nsp_mean
        n_spring = len(sp)

        # T-test
        t_val, p_val = 0, 1
        if len(sp) > 5 and len(nsp) > 5:
            t_val, p_val = scipy_stats.ttest_ind(sp, nsp, alternative='greater')

        log(
            "",
            f"  {regime:<12} {regime_counts.get(regime, 0):<8} {n_spring:<8} {n_spring/max(1,regime_counts.get(regime,0))*100:<10.1f} {sp_mean:<+12.2f} {nsp_mean:<+12.2f} {diff:<+10.2f}",
            f"  t={t_val:.2f} p={p_val:.4f} {'✅' if p_val < 0.05 else '❌'}",
        )
        results[regime] = {
            'n_obs': regime_counts.get(regime, 0),
            'n_spring': n_spring,
            'spring_raw_mean': sp_mean,
            'nonspring_mean': nsp_mean,
            'diff': diff,
            't': t_val,
            'p': p_val,
        }

    # Summary
    regimes_found = [r for r in ['bull', 'bear', 'sideways'] if r in results]
    if regimes_found:
        diffs = [results[r]['diff'] for r in regimes_found]
        log(
            "",
            f"  === REGIME DEPENDENCE === ",
            f"  Spring advantage by regime:",
        )
        for r in regimes_found:
            log("", f"    {r}: {results[r]['diff']:+.2f}% ({results[r]['n_spring']} events, t={results[r]['t']:.2f})")
        log(
            "",
            f"  Std dev of regime advantage: {np.std(diffs):.2f}%",
            f"  {'✅ Regime-dependent (Std > 1%)' if np.std(diffs) > 1.0 else '⚠️ Regime-independent (Std < 1%)'}",
        )

    return results


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    data_file = OUT / "v4_results.json"
    data = json.loads(data_file.read_text())
    obs = data.get('data', [])
    print(f"Phase C: Loaded {len(obs)} observations")

    print("\n── C1: BH Benchmark (vs SH Index) ──")
    r_c1 = task_c1_bh_benchmark(obs)

    print("\n── C2: Parameter Stability ──")
    r_c2 = task_c2_param_stability()

    print("\n── C4: Market State Decomposition ──")
    r_c4 = task_c4_market_state(obs)

    # Summary
    print(f"\n{'='*60}")
    print(f"  PHASE C SUMMARY")
    print(f"{'='*60}")
    print(f"  C1 Spring excess vs SH: {r_c1['spring_excess_vs_sh']:+.2f}% (t={r_c1['spring_excess_t']:.2f}, p={r_c1['spring_excess_p']:.4f})")
    print(f"  C2 Best params: {r_c2['best']}, Sharpe std: {r_c2['sharpe_std']:.3f}")
    for regime, r in r_c4.items():
        print(f"  C4 {regime}: Spring raw={r['spring_raw_mean']:+.2f}%, diff={r['diff']:+.2f}% (t={r['t']:.2f})")

    # Save report
    report_path = OUT / "phase_c_report.txt"
    with open(report_path, 'w') as f:
        f.write('\n'.join(REPORT))
    print(f"\n  Report saved to {report_path}")

    results = {'c1_bh': r_c1, 'c2_params': r_c2, 'c4_regime': r_c4}
    json.dump(results, open(OUT / "phase_c_results.json", 'w'), indent=2)
    print(f"  Results saved to {OUT / 'phase_c_results.json'}")


if __name__ == '__main__':
    main()
