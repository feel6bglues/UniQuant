#!/usr/bin/env python3
"""D1: Volume Climax enhancement analysis for Spring strategy.

For each Spring event in v4_results, checks if a Volume Climax (SC/Selling Climax)
pattern occurred in the preceding 30 bars. Compares forward returns of
Spring+VC vs Spring-only events.

VC detection heuristic:
1. Look at 30 bars before Spring cutoff
2. Find any bar where volume > 2x MA20 volume AND price declines >= 4%
3. Check that price recovered within 10 bars after that bar (low of VC bar not broken)
"""

import json
import sys
import time
import warnings
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
OUTPUT_DIR = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"
V4_RESULTS = OUTPUT_DIR / "v4_results.json"


def detect_vc_before_spring(df: pd.DataFrame, cutoff_idx: int) -> bool:
    """Detect Volume Climax in the 30 bars before the Spring cutoff.
    
    VC criteria:
    - Volume > 2x MA(20) volume
    - Price decline (close-to-close or close-to-low) >= 4%
    - Recovery within 10 bars: low of VC bar not broken
    
    Returns True if a valid VC pattern is found.
    """
    if cutoff_idx < 35:
        return False
    
    window = df.iloc[max(0, cutoff_idx - 30):cutoff_idx + 1].copy()
    if len(window) < 20:
        return False
    
    window = window.reset_index(drop=True)
    vol = window['volume'].values
    close = window['close'].values
    low = window['low'].values
    window['high'].values
    
    ma20_vol = pd.Series(vol).rolling(20, min_periods=10).mean().values
    
    for i in range(20, len(window)):
        if ma20_vol[i] <= 0:
            continue
        vol_ratio = vol[i] / ma20_vol[i]
        if vol_ratio < 2.0:
            continue
        
        prev_close = close[i-1] if i > 0 else close[i]
        price_decline = (prev_close - low[i]) / prev_close * 100
        
        if price_decline < 4.0:
            continue
        
        recovery_window = window.iloc[i+1:min(i+11, len(window))]
        if len(recovery_window) < 3:
            continue
        
        lows_broken = (recovery_window['low'].min() < low[i] * 0.995)
        if lows_broken:
            continue
        
        close_recovery = recovery_window['close'].iloc[-1] > low[i]
        if not close_recovery:
            continue
        
        return True
    
    return False


def main():
    t0 = time.time()
    print("=" * 70)
    print("D1: Volume Climax Enhancement Analysis")
    print("=" * 70)
    
    if not V4_RESULTS.exists():
        print(f"ERROR: {V4_RESULTS} not found")
        sys.exit(1)
    
    with open(V4_RESULTS) as f:
        raw = json.load(f)
    
    print(f"Loaded {len(raw['data'])} observations across {raw['meta']['n_stocks']} stocks")
    
    # Build per-stock observation list, sorted by date
    stock_obs = defaultdict(list)
    for obs in raw['data']:
        stock_obs[obs['s']].append(obs)
    
    for s in stock_obs:
        stock_obs[s].sort(key=lambda x: x['c'])
    
    # Find all Spring events
    spring_events = []
    for s, obss in stock_obs.items():
        for obs in obss:
            if obs['ds']:
                spring_events.append((s, obs['c'], obs['f1'], obs['f3'], obs['f6']))
    
    print(f"Spring events to analyze: {len(spring_events)}")
    
    # Load data and detect VC for each Spring event
    vc_found = 0
    vc_ret = {'f1': [], 'f3': [], 'f6': []}
    no_vc_ret = {'f1': [], 'f3': [], 'f6': []}
    
    symbol_cache = {}
    phase_lookup = {}
    vc_cache = {}
    
    done = 0
    for s, cutoff, f1, f3, f6 in spring_events:
        done += 1
        if done % 500 == 0:
            elapsed = time.time() - t0
            print(f"  {done}/{len(spring_events)} ({elapsed:.0f}s)")
        
        if s not in symbol_cache:
            fp = DATA_LAKE / f"{s}.parquet"
            if fp.exists():
                try:
                    df = pd.read_parquet(fp)
                    df['date'] = pd.to_datetime(df['date'])
                    df = df.sort_values('date').reset_index(drop=True)
                    symbol_cache[s] = df
                except Exception:
                    symbol_cache[s] = None
            else:
                symbol_cache[s] = None
        
        if s not in phase_lookup:
            phase_lookup[s] = {obs['c']: obs['p'] for obs in stock_obs.get(s, [])}
        
        df = symbol_cache[s]
        if df is None:
            continue
        
        cutoff_dt = pd.Timestamp(cutoff)
        cut_idx = df[df['date'] <= cutoff_dt].index.max()
        if cut_idx is None or cut_idx < 35:
            continue
        
        cache_key = (s, cutoff)
        has_vc = detect_vc_before_spring(df, cut_idx)
        vc_cache[cache_key] = has_vc
        
        if has_vc:
            vc_found += 1
            vc_ret['f1'].append(f1)
            vc_ret['f3'].append(f3)
            vc_ret['f6'].append(f6)
        else:
            no_vc_ret['f1'].append(f1)
            no_vc_ret['f3'].append(f3)
            no_vc_ret['f6'].append(f6)
    
    elapsed = time.time() - t0
    print(f"\nAnalyzed {len(spring_events)} Spring events in {elapsed:.0f}s")
    print(f"  With VC: {vc_found} ({vc_found/len(spring_events)*100:.1f}%)")
    print(f"  Without VC: {len(spring_events) - vc_found} ({(len(spring_events)-vc_found)/len(spring_events)*100:.1f}%)")
    
    # Compare forward returns
    print(f"\n{'='*70}")
    print("Forward Return Comparison: Spring+VC vs Spring-only")
    print(f"{'='*70}")
    print(f"  {'Metric':<12} {'Spring+VC':>12} {'Spring-only':>12} {'Diff':>10} {'t':>8} {'p':>8}")
    print(f"  {'-'*62}")
    
    for label, key in [('1m', 'f1'), ('3m', 'f3'), ('6m', 'f6')]:
        v = np.array(vc_ret[key])
        nv = np.array(no_vc_ret[key])
        if len(v) < 5 or len(nv) < 5:
            continue
        diff = np.mean(v) - np.mean(nv)
        t_stat, p_val = stats.ttest_ind(v, nv, alternative='greater')
        print(f"  {label:<12} {np.mean(v):>+12.2f}% {np.mean(nv):>+12.2f}% {diff:>+10.2f}% {t_stat:>8.2f} {p_val:>8.4f}")
    
    # VC rate by phase (uses cached VC results)
    print(f"\n{'='*70}")
    print("VC Detection by Phase")
    print(f"{'='*70}")
    
    phase_vc = defaultdict(lambda: {'total': 0, 'with_vc': 0, 'f6_vc': [], 'f6_no_vc': []})
    for s, cutoff, f1, f3, f6 in spring_events:
        cache_key = (s, cutoff)
        has_vc_result = vc_cache.get(cache_key)
        if has_vc_result is None:
            continue
        
        phase = phase_lookup.get(s, {}).get(cutoff, 'unknown')
        phase_vc[phase]['total'] += 1
        if has_vc_result:
            phase_vc[phase]['with_vc'] += 1
            phase_vc[phase]['f6_vc'].append(f6)
        else:
            phase_vc[phase]['f6_no_vc'].append(f6)
    
    if phase_vc:
        print(f"  {'Phase':<15} {'Spring':<8} {'VC':<6} {'VC%':<8} {'VC F6':>10} {'NoVC F6':>10} {'Diff':>10}")
        print(f"  {'-'*67}")
        for p in ['accumulation', 'markdown', 'markup', 'distribution', 'unknown']:
            pv = phase_vc.get(p)
            if not pv or pv['total'] == 0:
                continue
            vc_pct = pv['with_vc'] / pv['total'] * 100
            vc_m = np.mean(pv['f6_vc']) if pv['f6_vc'] else 0
            nvc_m = np.mean(pv['f6_no_vc']) if pv['f6_no_vc'] else 0
            diff = vc_m - nvc_m
            print(f"  {p:<15} {pv['total']:<8} {pv['with_vc']:<6} {vc_pct:<8.1f} {vc_m:>+10.2f}% {nvc_m:>+10.2f}% {diff:>+10.2f}%")
    
    # Save structured results
    out = {
        'meta': {
            'n_spring_events': len(spring_events),
            'n_stocks_analyzed': len(symbol_cache),
            'n_with_vc': vc_found,
            'vc_rate': round(vc_found / len(spring_events) * 100, 1) if spring_events else 0,
            'elapsed_seconds': round(elapsed),
        },
        'vc_returns': {k: [round(x, 4) for x in v] for k, v in vc_ret.items()},
        'no_vc_returns': {k: [round(x, 4) for x in v] for k, v in no_vc_ret.items()},
    }
    
    out_path = OUTPUT_DIR / 'd1_vc_results.json'
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved structured results to {out_path}")
    print(f"Total elapsed: {elapsed:.0f}s")


if __name__ == '__main__':
    main()
