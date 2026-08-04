#!/usr/bin/env python3
"""Phase VI: WSS (Wyckoff Statistical Score) — data‑driven sequence scoring.

Scans all event sequences from Phase II results, builds a statistical score
based on empirical forward‑return distributions (n, mean, t‑stat, win‑rate).

Usage:
    python3 scripts/wyckoff_multitf/phase6_wss_scoring.py
"""

import sys
import json
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from scipy import stats

OUTPUT_DIR = Path(__file__).resolve().parent / "output_v4"


def build_wss_lookup(data, min_obs=15) -> dict:
    """Build WSS lookup table from empirical sequence returns.

    For each unique event sequence (2‑4 events), compute:
      - mean f6 return
      - t‑statistic vs 0
      - win‑rate (% of obs with f6 > 0)
      - WSS score = t * (mean / |max_t_mean|) * win_rate_bonus

    Returns dict[sequence_key] = wss_weight
    """
    seq_returns = defaultdict(list)
    for obs in data:
        seq = obs.get('seq', 'NONE')
        if seq in ('NONE', 'LOW_CONF'):
            continue
        seq_returns[seq].append(obs.get('f6', 0))

    lookup = {}
    max_abs_t = 0.0
    for seq, rets in seq_returns.items():
        if len(rets) < min_obs:
            continue
        arr = np.array(rets)
        t_s, p_s = stats.ttest_1samp(arr, 0)
        mean_r = float(np.mean(arr))
        win_r = float(np.mean(arr > 0))
        max_abs_t = max(max_abs_t, abs(t_s))
        lookup[seq] = {
            'n': len(rets), 'mean': mean_r, 't': float(t_s),
            'p': float(p_s), 'win_rate': win_r,
            'std': float(np.std(arr)),
        }

    # Normalize t‑stat and compute WSS score
    max_t = max_abs_t if max_abs_t > 0 else 1.0
    for seq in lookup:
        info = lookup[seq]
        t_norm = abs(info['t']) / max_t       # [0, 1]
        mean_norm = info['mean'] / 100.0       # decimal
        wr_bonus = (info['win_rate'] - 0.5) * 2  # [-1, 1]
        info['wss'] = t_norm * mean_norm + 0.3 * wr_bonus * t_norm

    return lookup


def wss_score(seq: str, lookup: dict, fallback: float = 0.0) -> float:
    """Look up the WSS score for a sequence."""
    if seq in lookup:
        return lookup[seq]['wss']
    return fallback


def run():
    src = OUTPUT_DIR / 'phase2_event_results.json'
    print(f"Loading {src} ...")
    with open(src) as f:
        data = json.load(f)['data']
    print(f"  {len(data)} observations")

    print("\nBuilding WSS lookup ...")
    lookup = build_wss_lookup(data, min_obs=15)
    print(f"  {len(lookup)} qualifying sequences")

    # Apply WSS to every observation
    for obs in data:
        seq = obs.get('seq', 'NONE')
        wss = wss_score(seq, lookup)
        obs['wss'] = wss

    out_path = OUTPUT_DIR / 'phase6_wss_results.json'
    with open(out_path, 'w') as f:
        json.dump({'meta': {'n_obs': len(data), 'n_seqs': len(lookup)},
                   'data': data}, f, indent=2, default=str)
    print(f"Saved to {out_path}")

    analyze(data, lookup)


def analyze(data, lookup):
    len(data)

    print(f"\n{'=' * 70}")
    print("WSS: Wyckoff Statistical Score — Sequence Performance")
    print(f"{'=' * 70}")
    print(f"  Sequences scored: {len(lookup)}")

    print("\n── Top 20 Sequences by WSS Score ──")
    ranked = sorted(lookup.items(), key=lambda x: -x[1]['wss'])
    print(f"  {'Sequence':<28} {'N':<6} {'f6%':<8} {'t':<8} {'Win%':<8} {'WSS':<8}")
    for seq, info in ranked[:20]:
        print(f"  {seq:<28} {info['n']:<6} {info['mean']:+>7.2f} {info['t']:+>7.2f} {info['win_rate']*100:<7.1f} {info['wss']:+>7.4f}")

    print("\n── Bottom 20 Sequences by WSS Score ──")
    for seq, info in ranked[-20:]:
        print(f"  {seq:<28} {info['n']:<6} {info['mean']:+>7.2f} {info['t']:+>7.2f} {info['win_rate']*100:<7.1f} {info['wss']:+>7.4f}")

    # WSS decile analysis
    wss_vals = np.array([o.get('wss', 0) for o in data])
    f6_vals = np.array([o.get('f6', 0) for o in data])
    print("\n── WSS Deciles → f6 Return ──")
    print(f"  {'Decile':<8} {'WSS':<10} {'N':<8} {'f6%':<10} {'t':<8} {'Sig':<6}")
    for pct in range(0, 100, 10):
        lo = np.percentile(wss_vals, max(0, pct - 10)) if pct > 0 else -np.inf
        hi = np.percentile(wss_vals, pct + 10) if pct < 90 else np.inf
        mask = (wss_vals >= lo) & (wss_vals < hi)
        grp = f6_vals[mask]
        if len(grp) < 5:
            continue
        t_s, p_s = stats.ttest_1samp(grp, 0)
        sig = '✅' if p_s < 0.05 else '❌'
        print(f"  {pct+1}-{pct+10:<5} {np.mean(wss_vals[mask]):+>8.4f} {len(grp):<8} {np.mean(grp):+>8.2f}% {t_s:+>7.2f} {sig}")

    # Correlation: WSS vs f6
    r, p_val = stats.pearsonr(wss_vals, f6_vals)
    print("\n── WSS-f6 Correlation ──")
    print(f"  Pearson r: {r:.4f}  p={p_val:.6f}  {'✅' if p_val < 0.05 else '❌'}")

    # WSS vs WSO comparison
    wso_vals = np.array([o.get('wso', 0) for o in data])
    print("\n── WSS vs WSO ──")
    r_wso, _ = stats.pearsonr(wso_vals, f6_vals)
    r_wss, _ = stats.pearsonr(wss_vals, f6_vals)
    print(f"  WSO–f6 r: {r_wso:.4f}")
    print(f"  WSS–f6 r: {r_wss:.4f}")

    # Combined: α*WSO + β*WSS
    print("\n── Combined (α·WSO + β·WSS) Optimisation ──")
    best_r = -1
    best_a = best_b = 0
    for a in np.arange(0, 1.1, 0.1):
        for b in np.arange(0, 1.1, 0.1):
            if a + b == 0:
                continue
            combined = a * wso_vals + b * wss_vals
            cr, _ = stats.pearsonr(combined, f6_vals)
            if cr > best_r:
                best_r = cr
                best_a, best_b = a, b
    print(f"  Best combo: α={best_a:.1f} β={best_b:.1f}  r={best_r:.4f}")
    print(f"  WSO alone:  r={r_wso:.4f}")
    print(f"  WSS alone:  r={r_wss:.4f}")
    print(f"  Combined gain: {best_r - max(r_wso, r_wss):+.4f}")

    # Signal quality: top WSS decile vs bottom
    top_mask = wss_vals >= np.percentile(wss_vals, 80)
    bot_mask = wss_vals <= np.percentile(wss_vals, 20)
    if sum(top_mask) > 5 and sum(bot_mask) > 5:
        top_f6 = f6_vals[top_mask]
        bot_f6 = f6_vals[bot_mask]
        t_sp, _ = stats.ttest_ind(top_f6, bot_f6)
        print("\n── WSS Top 20% vs Bottom 20% ──")
        print(f"  Top 20%:    N={sum(top_mask):<6} f6={np.mean(top_f6):+>7.2f}%")
        print(f"  Bottom 20%: N={sum(bot_mask):<6} f6={np.mean(bot_f6):+>7.2f}%")
        print(f"  Spread:     {np.mean(top_f6)-np.mean(bot_f6):+>7.2f}% t={t_sp:.2f}")

    save_report(data, lookup, wso_vals, f6_vals, wss_vals)


def save_report(data, lookup, wso_vals, f6_vals, wss_vals):
    lines = ["WSS: Statistical Sequence Scoring Report"]
    lines.append(f"Total obs: {len(data)}")
    lines.append(f"Sequences scored: {len(lookup)}")
    lines.append("")
    r_wso, _ = stats.pearsonr(wso_vals, f6_vals)
    r_wss, _ = stats.pearsonr(wss_vals, f6_vals)
    lines.append(f"WSO–f6 r: {r_wso:.4f}")
    lines.append(f"WSS–f6 r: {r_wss:.4f}")
    with open(OUTPUT_DIR / 'phase6_report.txt', 'w') as f:
        f.write('\n'.join(lines))
    print(f"\nReport saved to {OUTPUT_DIR / 'phase6_report.txt'}")


if __name__ == '__main__':
    run()
