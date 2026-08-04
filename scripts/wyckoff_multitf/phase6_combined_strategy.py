#!/usr/bin/env python3
"""Phase VI: Combined WSO+WSS strategy engine.

Loads pre‑trained WSS lookup, scores all observations with WyckoffScorer,
applies resonance filter, and backtests against WSO‑only baseline.

Usage:
    python3 scripts/wyckoff_multitf/phase6_combined_strategy.py
"""

import sys
import json
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from scipy import stats

from src.uniquant.brain.wyckoff.sequence import WyckoffScorer

OUTPUT_DIR = Path(__file__).resolve().parent / "output_v4"


def resonance_filter(wso_sig: str, resonance: str) -> str:
    """Same rule as Phase IV."""
    if wso_sig == 'buy' and resonance == 'bullish':
        return 'hold'
    if wso_sig == 'sell' and resonance == 'bearish':
        return 'hold'
    return wso_sig


def run():
    # Load Phase II event data
    src = OUTPUT_DIR / 'phase2_event_results.json'
    print(f"Loading {src} ...")
    with open(src) as f:
        data = json.load(f)['data']
    print(f"  {len(data)} observations")

    # Load WSS lookup
    wss_path = OUTPUT_DIR / 'wss_lookup.json'
    print(f"Loading WSS lookup from {wss_path} ...")
    scorer = WyckoffScorer(wss_path=str(wss_path), alpha=0.3, beta=0.7)

    # Score every observation
    for obs in data:
        event_types = obs.get('events', [])
        seq = obs.get('seq', 'NONE')
        spring = obs.get('ds', False)
        n_spring_events = len([e for e in event_types if e != 'Spring'])

        wso_score = scorer.wso.score_events(event_types, spring, n_spring_events)
        full_score, full_sig = scorer.score_sequence(
            event_types, seq, spring, n_spring_events)

        obs['wso_score'] = wso_score
        obs['wso_sig'] = scorer.wso.signal(wso_score)
        obs['wyckoff_score'] = full_score
        obs['wyckoff_sig'] = full_sig

        resonance = obs.get('rd', 'conflicting')
        obs['wyckoff_res_sig'] = resonance_filter(full_sig, resonance)

    out_path = OUTPUT_DIR / 'phase6_combined_results.json'
    with open(out_path, 'w') as f:
        json.dump({'meta': {'n_obs': len(data)}, 'data': data}, f, indent=2, default=str)
    print(f"Saved to {out_path}")

    analyze(data)


def analyze(data):
    len(data)

    print(f"\n{'=' * 70}")
    print("Phase VI: Combined WSO+WSS Strategy  vs  Phase V: WSO‑only")
    print(f"{'=' * 70}")

    # Phase V baseline: WSO ≥ 0.04
    [o for o in data if o.get('wso_score', 0) >= 0.04]
    [o for o in data if o.get('wso_score', 0) <= -0.03]

    # Phase VI: combined score
    vi_sig_counts = Counter(o.get('wyckoff_sig', 'hold') for o in data)
    vi_res_counts = Counter(o.get('wyckoff_res_sig', 'hold') for o in data)

    print("\n── Signal Distribution ──")
    print(f"  {'Signal':<8} {'WSO':<10} {'WSO+WSS':<10} {'+Resonance':<12}")
    for sig in ['buy', 'hold', 'sell']:
        v5_c = Counter(o.get('wso_sig', 'hold') for o in data).get(sig, 0)
        vi_c = vi_sig_counts.get(sig, 0)
        vr_c = vi_res_counts.get(sig, 0)
        print(f"  {sig:<8} {v5_c:<10} {vi_c:<10} {vr_c:<12}")

    print("\n── Forward Returns (f6) by Signal ──")
    print(f"  {'Signal':<10} {'WSO‑only':<16} {'WSO+WSS':<16} {'+Resonance':<16}")
    for sig in ['buy', 'sell']:
        v5_g = [o for o in data if o.get('wso_sig') == sig]
        vi_g = [o for o in data if o.get('wyckoff_sig') == sig]
        vr_g = [o for o in data if o.get('wyckoff_res_sig') == sig]
        v5_m = np.mean([o['f6'] for o in v5_g]) if v5_g else 0
        vi_m = np.mean([o['f6'] for o in vi_g]) if vi_g else 0
        vr_m = np.mean([o['f6'] for o in vr_g]) if vr_g else 0

        v5_t = stats.ttest_1samp(np.array([o['f6'] for o in v5_g]), 0).statistic if len(v5_g) > 5 else 0
        vi_t = stats.ttest_1samp(np.array([o['f6'] for o in vi_g]), 0).statistic if len(vi_g) > 5 else 0
        vr_t = stats.ttest_1samp(np.array([o['f6'] for o in vr_g]), 0).statistic if len(vr_g) > 5 else 0
        print(f"  {sig:<10} {v5_m:+>7.2f}% t={v5_t:>6.2f} {vi_m:+>7.2f}% t={vi_t:>6.2f} {vr_m:+>7.2f}% t={vr_t:>6.2f}")

    # Buy–Sell spread comparison
    def spread(group, sig_field):
        buys = np.array([o['f6'] for o in group if o.get(sig_field) == 'buy'])
        sells = np.array([o['f6'] for o in group if o.get(sig_field) == 'sell'])
        if len(buys) > 5 and len(sells) > 5:
            return np.mean(buys) - np.mean(sells), stats.ttest_ind(buys, sells).statistic
        return 0, 0

    print("\n── Buy–Sell Spread ──")
    for label, sig_field in [('WSO‑only', 'wso_sig'), ('WSO+WSS', 'wyckoff_sig'),
                              ('+Resonance', 'wyckoff_res_sig')]:
        sp, t_s = spread(data, sig_field)
        print(f"  {label:<12}: {sp:+>7.2f}% t={t_s:>6.2f}")

    # Score vs f6 correlation
    scores_wso = np.array([o.get('wso_score', 0) for o in data])
    scores_wss = np.array([o.get('wyckoff_score', 0) for o in data])
    f6 = np.array([o.get('f6', 0) for o in data])
    r_wso, _ = stats.pearsonr(scores_wso, f6)
    r_wss, _ = stats.pearsonr(scores_wss, f6)
    print("\n── f6 Correlation ──")
    print(f"  WSO‑only:  r={r_wso:.4f}")
    print(f"  WSO+WSS:   r={r_wss:.4f}")
    print(f"  Gain:      {r_wss - r_wso:+.4f}")

    save_report(data)


def save_report(data):
    lines = ["Phase VI: Combined WSO+WSS Strategy Report"]
    lines.append(f"Total obs: {len(data)}")
    lines.append("")
    for sig_field, label in [('wso_sig', 'WSO-only'), ('wyckoff_sig', 'WSO+WSS'),
                              ('wyckoff_res_sig', '+Resonance')]:
        buys = [o for o in data if o.get(sig_field) == 'buy']
        sells = [o for o in data if o.get(sig_field) == 'sell']
        if buys:
            lines.append(f"{label} buy: N={len(buys)} f6={np.mean([o['f6'] for o in buys]):+.2f}%")
        if sells:
            lines.append(f"{label} sell: N={len(sells)} f6={np.mean([o['f6'] for o in sells]):+.2f}%")
        if buys and sells:
            b = np.mean([o['f6'] for o in buys])
            s = np.mean([o['f6'] for o in sells])
            lines.append(f"{label} spread: {b-s:+.2f}%")
        lines.append("")
    with open(OUTPUT_DIR / 'phase6_combined_report.txt', 'w') as f:
        f.write('\n'.join(lines))
    print(f"\nReport saved to {OUTPUT_DIR / 'phase6_combined_report.txt'}")


if __name__ == '__main__':
    run()
