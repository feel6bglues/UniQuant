#!/usr/bin/env python3
"""Train WSS lookup table from Phase II event detection results.

Output: JSON with sequence → {n, mean, t, win_rate, wss}

Usage:
    python3 scripts/wyckoff_multitf/train_wss_lookup.py
"""

import sys, json
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from scipy import stats

OUTPUT_DIR = Path(__file__).resolve().parent / "output_v4"


def train(min_obs: int = 15) -> dict:
    src = OUTPUT_DIR / 'phase2_event_results.json'
    with open(src) as f:
        data = json.load(f)['data']

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

    max_t = max_abs_t if max_abs_t > 0 else 1.0
    for seq in lookup:
        info = lookup[seq]
        t_norm = abs(info['t']) / max_t
        mean_norm = info['mean'] / 100.0
        wr_bonus = (info['win_rate'] - 0.5) * 2
        info['wss'] = round(t_norm * mean_norm + 0.3 * wr_bonus * t_norm, 6)

    return lookup


if __name__ == '__main__':
    lookup = train(min_obs=15)
    out_path = OUTPUT_DIR / 'wss_lookup.json'
    with open(out_path, 'w') as f:
        json.dump(lookup, f, indent=2)
    print(f"WSS lookup saved to {out_path} ({len(lookup)} sequences)")
