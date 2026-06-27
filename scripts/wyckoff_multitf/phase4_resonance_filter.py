#!/usr/bin/env python3
"""Phase IV: Multi-timeframe resonance filter for WSO signals.

Applies phase resonance (bullish/bearish/conflicting) to refine WSO signals.
Exports filtered results and validates improvement over pure WSO.

Usage:
    python3 scripts/wyckoff_multitf/phase4_resonance_filter.py
"""

import sys, json
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from scipy import stats

OUTPUT_DIR = Path(__file__).resolve().parent / "output_v4"


def apply_resonance_filter(wso_sig: str, resonance: str) -> str:
    """Apply multi-timeframe resonance rule to refine a WSO signal.

    Empirical basis (22,148 obs):
      - buy  + bullish   → -2.85%  (filter: downgrade)
      - buy  + bearish   → +2.48%  (keep)
      - sell + bullish   → -6.28%  (keep)
      - sell + bearish   → -1.47%  (downgrade)
    """
    if wso_sig == 'buy' and resonance == 'bullish':
        return 'hold'
    if wso_sig == 'sell' and resonance == 'bearish':
        return 'hold'
    return wso_sig


def run():
    path = OUTPUT_DIR / 'phase3_wso_results.json'
    print(f"Loading {path} ...")
    with open(path) as f:
        data = json.load(f)['data']
    print(f"  {len(data)} observations")

    for obs in data:
        wso_sig = obs.get('wso_sig', 'hold')
        rd = obs.get('rd', 'conflicting')
        obs['wso_resonance_sig'] = apply_resonance_filter(wso_sig, rd)

    out_path = OUTPUT_DIR / 'phase4_resonance_results.json'
    meta = {'n_obs': len(data)}
    with open(out_path, 'w') as f:
        json.dump({'meta': meta, 'data': data}, f, indent=2, default=str)
    print(f"Saved to {out_path}")

    analyze(data)


def analyze(data):
    n = len(data)
    print(f"\n{'=' * 70}")
    print("Phase IV: Resonance Filter Validation")
    print(f"{'=' * 70}")

    sig_counts = Counter(obs['wso_resonance_sig'] for obs in data)
    print(f"\n── Filtered Signal Distribution ──")
    print(f"  {'Signal':<8} {'Count':<8} {'%':<8}")
    for sig in ['buy', 'hold', 'sell']:
        c = sig_counts.get(sig, 0)
        print(f"  {sig:<8} {c:<8} {c / n * 100:.1f}%")

    print(f"\n── Forward Returns by Filtered Signal ──")
    print(f"  {'Signal':<8} {'N':<8} {'f1_mean':<10} {'f3_mean':<10} {'f6_mean':<10} {'f6_t':<8} {'Sig':<6}")
    for sig in ['buy', 'hold', 'sell']:
        group = [o for o in data if o.get('wso_resonance_sig') == sig]
        if not group:
            continue
        f6 = np.array([o.get('f6', 0) for o in group])
        f3 = np.array([o.get('f3', 0) for o in group])
        f1 = np.array([o.get('f1', 0) for o in group])
        t_s, p_s = stats.ttest_1samp(f6, 0)
        sig_m = '✅' if p_s < 0.05 else '❌'
        print(f"  {sig:<8} {len(group):<8} {np.mean(f1):+>7.2f}% {np.mean(f3):+>7.2f}% {np.mean(f6):+>7.2f}% {t_s:+>7.2f} {sig_m}")

    buy_rets = np.array([o['f6'] for o in data if o.get('wso_resonance_sig') == 'buy'])
    sell_rets = np.array([o['f6'] for o in data if o.get('wso_resonance_sig') == 'sell'])
    if len(buy_rets) > 5 and len(sell_rets) > 5:
        t2, p2 = stats.ttest_ind(buy_rets, sell_rets)
        print(f"\n── Filtered Buy vs Sell Spread ──")
        print(f"  Buy mean:  {np.mean(buy_rets):+.2f}% (N={len(buy_rets)})")
        print(f"  Sell mean: {np.mean(sell_rets):+.2f}% (N={len(sell_rets)})")
        print(f"  Spread:    {np.mean(buy_rets) - np.mean(sell_rets):+.2f}% t={t2:.2f} {'✅' if p2 < 0.05 else '❌'}")

    print(f"\n── Improvement vs Pure WSO ──")
    wso_buy = np.array([o['f6'] for o in data if o.get('wso_sig') == 'buy'])
    filt_buy = np.array([o['f6'] for o in data if o.get('wso_resonance_sig') == 'buy'])
    print(f"  WSO buy:    {np.mean(wso_buy):+.2f}% (N={len(wso_buy)})")
    print(f"  Filter buy: {np.mean(filt_buy):+.2f}% (N={len(filt_buy)})")
    print(f"  Buy gain:   {np.mean(filt_buy) - np.mean(wso_buy):+.2f}%")
    if len(wso_buy) > 5 and len(filt_buy) > 5:
        t_diff, p_diff = stats.ttest_ind(filt_buy, wso_buy)
        print(f"  Buy diff t: {t_diff:.2f} {'✅' if p_diff < 0.05 else '❌'}")

    wso_sell = np.array([o['f6'] for o in data if o.get('wso_sig') == 'sell'])
    filt_sell = np.array([o['f6'] for o in data if o.get('wso_resonance_sig') == 'sell'])
    if len(wso_sell) > 5:
        print(f"  WSO sell:    {np.mean(wso_sell):+.2f}% (N={len(wso_sell)})")
        print(f"  Filter sell: {np.mean(filt_sell):+.2f}% (N={len(filt_sell)})")

    print(f"\n── Transition Summary ──")
    downgrades = sum(1 for o in data if o.get('wso_sig') != o.get('wso_resonance_sig'))
    print(f"  Signals changed: {downgrades}/{n} ({downgrades/n*100:.1f}%)")
    buy2hold = sum(1 for o in data if o.get('wso_sig') == 'buy' and o.get('wso_resonance_sig') == 'hold')
    sell2hold = sum(1 for o in data if o.get('wso_sig') == 'sell' and o.get('wso_resonance_sig') == 'hold')
    print(f"  buy → hold: {buy2hold}")
    print(f"  sell → hold: {sell2hold}")

    save_report(data, sig_counts, buy_rets, sell_rets, wso_buy, filt_buy)


def save_report(data, sig_counts, buy_rets, sell_rets, wso_buy, filt_buy):
    lines = []
    lines.append("Phase IV: Resonance Filter Validation Report")
    lines.append(f"Total obs: {len(data)}")
    lines.append("")
    for sig in ['buy', 'hold', 'sell']:
        c = sig_counts.get(sig, 0)
        lines.append(f"  {sig}: {c} ({c/len(data)*100:.1f}%)")
    lines.append("")
    lines.append("Filtered Buy vs Sell:")
    lines.append(f"  Buy: N={len(buy_rets)} f6={np.mean(buy_rets):+.2f}%")
    lines.append(f"  Sell: N={len(sell_rets)} f6={np.mean(sell_rets):+.2f}%")
    if len(buy_rets) > 5 and len(sell_rets) > 5:
        spread = np.mean(buy_rets) - np.mean(sell_rets)
        lines.append(f"  Spread: {spread:+.2f}%")
    lines.append("")
    lines.append("vs WSO baseline:")
    lines.append(f"  WSO buy: {np.mean(wso_buy):+.2f}% → Filter buy: {np.mean(filt_buy):+.2f}%")
    with open(OUTPUT_DIR / 'phase4_report.txt', 'w') as f:
        f.write('\n'.join(lines))
    print(f"\nReport saved to {OUTPUT_DIR / 'phase4_report.txt'}")


if __name__ == '__main__':
    run()
