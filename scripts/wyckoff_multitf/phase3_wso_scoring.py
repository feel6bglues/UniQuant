#!/usr/bin/env python3
"""Phase III: WSO scoring and signal validation.

Loads Phase II event results, computes WSO scores for each observation,
and analyzes signal → f6 forward return quality.

Usage:
    python3 scripts/wyckoff_multitf/phase3_wso_scoring.py
"""

import sys
import json
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from scipy import stats

from src.uniquant.brain.wyckoff.sequence import WSOScorer

OUTPUT_DIR = Path(__file__).resolve().parent / "output_v4"


def run():
    src = OUTPUT_DIR / 'phase2_event_results.json'
    print(f"Loading {src} ...")
    with open(src) as f:
        data = json.load(f)['data']
    print(f"  {len(data)} observations")

    # Score every observation
    for obs in data:
        events = obs.get('events', [])
        spring = obs.get('ds', False)
        n_spring_events = len([e for e in events if e != 'Spring'])
        wso, sig = WSOScorer.score_and_signal(events, spring, n_spring_events)
        obs['wso'] = wso
        obs['wso_sig'] = sig

    # Save scored results
    out_path = OUTPUT_DIR / 'phase3_wso_results.json'
    meta = {'n_obs': len(data)}
    with open(out_path, 'w') as f:
        json.dump({'meta': meta, 'data': data}, f, indent=2, default=str)
    print(f"Saved to {out_path}")

    # Analyze
    analyze(data)


def analyze(data):
    n = len(data)
    print(f"\n{'=' * 70}")
    print("Phase III: WSO Scoring Validation")
    print(f"{'=' * 70}")
    print(f"  Total observations: {n}")

    # Signal distribution
    sig_counts = Counter(obs['wso_sig'] for obs in data)
    print("\n── Signal Distribution ──")
    print(f"  {'Signal':<8} {'Count':<8} {'%':<8}")
    for sig in ['buy', 'hold', 'sell']:
        c = sig_counts.get(sig, 0)
        print(f"  {sig:<8} {c:<8} {c / n * 100:<.1f}%")

    # Forward returns by signal
    print("\n── Forward Returns by Signal ──")
    print(f"  {'Signal':<8} {'N':<8} {'f1_mean':<10} {'f3_mean':<10} {'f6_mean':<10} {'f6_t':<8} {'f6_sig':<6}")
    for sig in ['buy', 'hold', 'sell']:
        group = [o for o in data if o.get('wso_sig') == sig]
        if not group:
            continue
        f6 = np.array([o.get('f6', 0) for o in group])
        f3 = np.array([o.get('f3', 0) for o in group])
        f1 = np.array([o.get('f1', 0) for o in group])
        t_s, p_s = stats.ttest_1samp(f6, 0)
        sig_m = '✅' if p_s < 0.05 else '❌'
        print(f"  {sig:<8} {len(group):<8} {np.mean(f1):+>7.2f}% {np.mean(f3):+>7.2f}% {np.mean(f6):+>7.2f}% {t_s:+>7.2f} {sig_m}")

    # Buy vs Sell spread
    buy_rets = np.array([o['f6'] for o in data if o.get('wso_sig') == 'buy'])
    sell_rets = np.array([o['f6'] for o in data if o.get('wso_sig') == 'sell'])
    np.array([o['f6'] for o in data if o.get('wso_sig') == 'hold'])
    if len(buy_rets) > 5 and len(sell_rets) > 5:
        t2, p2 = stats.ttest_ind(buy_rets, sell_rets)
        print("\n── Buy vs Sell Spread (f6) ──")
        print(f"  Buy mean:  {np.mean(buy_rets):+.2f}%  (N={len(buy_rets)})")
        print(f"  Sell mean: {np.mean(sell_rets):+.2f}%  (N={len(sell_rets)})")
        print(f"  Spread:    {np.mean(buy_rets) - np.mean(sell_rets):+.2f}%  t={t2:.2f}  {'✅' if p2 < 0.05 else '❌'}")

    # WSO score deciles → f6
    print("\n── WSO Score Deciles → f6 Return ──")
    scores = np.array([o['wso'] for o in data])
    f6s = np.array([o.get('f6', 0) for o in data])
    np.percentile(scores, [10, 20, 30, 40, 50, 60, 70, 80, 90])
    print(f"  {'Decile':<8} {'Score':<10} {'N':<8} {'f6_mean':<10} {'f6_t':<8} {'Sig':<6}")
    for pct in range(0, 100, 10):
        lo = np.percentile(scores, max(0, pct - 10)) if pct > 0 else -np.inf
        hi = np.percentile(scores, pct + 10) if pct < 90 else np.inf
        mask = (scores >= lo) & (scores < hi)
        grp = f6s[mask]
        if len(grp) < 5:
            continue
        t_s, p_s = stats.ttest_1samp(grp, 0)
        sig_m = '✅' if p_s < 0.05 else '❌'
        print(f"  {pct+1}-{pct+10:<5} {np.mean(scores[mask]):+>7.4f} {len(grp):<8} {np.mean(grp):+>7.2f}% {t_s:+>7.2f} {sig_m}")

    # WSO vs Spring comparison
    print("\n── WSO vs Spring (f6) ──")
    spring_data = [o for o in data if o.get('ds', False)]
    spring_buy = [o for o in spring_data if o.get('wso_sig') == 'buy']
    spring_sell = [o for o in spring_data if o.get('wso_sig') == 'sell']
    if spring_buy:
        sb = np.array([o['f6'] for o in spring_buy])
        t_s, _ = stats.ttest_1samp(sb, 0)
        print(f"  Spring + WSO buy:  N={len(sb)} mean={np.mean(sb):+.2f}% t={t_s:.2f}")
    if spring_sell:
        ss = np.array([o['f6'] for o in spring_sell])
        t_s, _ = stats.ttest_1samp(ss, 0)
        print(f"  Spring + WSO sell: N={len(ss)} mean={np.mean(ss):+.2f}% t={t_s:.2f}")

    # Correlation: WSO score vs f6
    score_arr = np.array([o['wso'] for o in data])
    f6_arr = np.array([o.get('f6', 0) for o in data])
    r, p_val = stats.pearsonr(score_arr, f6_arr)
    print("\n── WSO-f6 Correlation ──")
    print(f"  Pearson r: {r:.4f}  p={p_val:.6f}  {'✅' if p_val < 0.05 else '❌'}")

    # Save report
    save_report(data, sig_counts)


def save_report(data, sig_counts):
    n = len(data)
    lines = []
    lines.append("Phase III: WSO Scoring Validation Report")
    lines.append(f"Total obs: {n}")
    lines.append("")
    lines.append("Signal Distribution:")
    for sig in ['buy', 'hold', 'sell']:
        c = sig_counts.get(sig, 0)
        lines.append(f"  {sig}: {c} ({c/n*100:.1f}%)")
    lines.append("")
    lines.append("Forward Returns by Signal:")
    for sig in ['buy', 'hold', 'sell']:
        group = [o for o in data if o.get('wso_sig') == sig]
        if not group:
            continue
        f6 = np.mean([o.get('f6', 0) for o in group])
        lines.append(f"  {sig}: f6={f6:+.2f}% (N={len(group)})")
    lines.append("")
    buy_rets = np.array([o['f6'] for o in data if o.get('wso_sig') == 'buy'])
    sell_rets = np.array([o['f6'] for o in data if o.get('wso_sig') == 'sell'])
    if len(buy_rets) > 5 and len(sell_rets) > 5:
        t2, p2 = stats.ttest_ind(buy_rets, sell_rets)
        spread = np.mean(buy_rets) - np.mean(sell_rets)
        lines.append(f"Buy vs Sell spread: {spread:+.2f}% (t={t2:.2f}, p={p2:.4f})")
    with open(OUTPUT_DIR / 'phase3_report.txt', 'w') as f:
        f.write('\n'.join(lines))
    print(f"\nReport saved to {OUTPUT_DIR / 'phase3_report.txt'}")


if __name__ == '__main__':
    run()
