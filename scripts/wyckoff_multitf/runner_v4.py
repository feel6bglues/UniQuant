#!/usr/bin/env python3
"""Wyckoff v4: Corrected verification using rule-based monthly phase + engine Spring detection."""

import sys
import time
import json
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np
from scipy import stats
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
OUTPUT_DIR = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"
CHECKPOINT_DIR = OUTPUT_DIR / "checkpoints"
CHECKPOINT_INTERVAL = 200  # save checkpoint every N stocks
N_JOBS = max(1, len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1)


# ── Monthly Phase Classifier (A-share adapted, validated on 76K snapshots) ──

def classify_monthly_phase(
    monthly_12: pd.DataFrame,  # 12 monthly bars
) -> str:
    """A-share adapted Wyckoff phase classification.
    
    Thresholds derived from 500 stocks × 76K monthly snapshots analysis:
    - range_pct P25=60%, P50=91% → TR detection at 80%
    - trend_pct P25=-24%, P50=-3% → trend thresholds at ±10%
    """
    c = monthly_12['close'].values
    v = monthly_12['volume'].values
    lo, hi = monthly_12['low'].min(), monthly_12['high'].max()
    pp = (c[-1] - lo) / (hi - lo) if hi > lo else 0.5
    tr = (c[-1] / c[0] - 1) * 100 if c[0] > 0 else 0
    vt = (v[-1] / v[0] - 1) if v[0] > 0 else 0
    rp = (hi / lo - 1) * 100
    vr = v[-3:].mean() / v.mean() if v.mean() > 0 else 1
    r6 = (c[-1] / c[-7] - 1) * 100 if len(c) >= 7 else 0
    vp_c = np.corrcoef(c, v)[0, 1] if len(c) > 2 and np.std(v) > 0 else 0
    obv = 0
    for j in range(1, len(c)):
        obv += v[j] if c[j] > c[j-1] else -v[j] if c[j] < c[j-1] else 0
    obv_t = obv / v.mean() / len(c) if v.mean() > 0 else 0

    # Markdown: strong downtrend (negative prior 6m return is the defining characteristic)
    if tr < -15 or (r6 < -10 and pp < 0.3):
        return 'markdown'
    # Accumulation: low range position, volume declining, tight range
    if pp < 0.35 and vt < -0.15 and rp < 80 and vr < 0.85:
        return 'accumulation'
    # Markup: trending up, volume confirming, above mid-range
    if tr > 10 and pp > 0.5 and vt > 0:
        return 'markup'
    # Distribution: high price, negative VP correlation (divergence), wide range
    if pp > 0.6 and vp_c < -0.2 and rp > 80:
        return 'distribution'
    # OBV divergence signals
    if pp > 0.6 and obv_t < -5 and r6 < 5:
        return 'distribution'
    if pp < 0.4 and obv_t > 5 and r6 > -5:
        return 'accumulation'
    return 'unknown'


# ── Data Loading ──

def load_daily_data(symbol: str) -> Optional[pd.DataFrame]:
    fp = DATA_LAKE / f"{symbol}.parquet"
    if not fp.exists():
        return None
    try:
        daily = pd.read_parquet(fp)
        daily['date'] = pd.to_datetime(daily['date'])
        daily = daily.sort_values('date').reset_index(drop=True)
        if len(daily) < 200:
            return None
        return daily
    except Exception:
        return None


def _synthesize_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Generate monthly OHLCV bars from daily data (no look-ahead: only uses data in df)."""
    df = df.copy()
    df['mk'] = df['date'].dt.to_period('M').astype(str)
    m = df.groupby('mk', sort=False).agg(
        open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
        close=('close', 'last'), volume=('volume', 'sum'),
        date=('date', 'min')).reset_index().sort_values('date').reset_index(drop=True)
    return m


# ── Rolling Panel Generator ──

@dataclass
class Obs:
    symbol: str
    cutoff: str
    month_phase: str
    day_spring: bool
    fwd_1m: float
    fwd_3m: float
    fwd_6m: float


def process_stock(symbol: str) -> List[Obs]:
    """Event-based: detect Springs from engine, compute monthly phase at each Spring date."""
    from uniquant.brain.wyckoff.engine import WyckoffEngine
    daily = load_daily_data(symbol)
    if daily is None:
        return []

    engine = WyckoffEngine(lookback_days=120)
    day_close = daily['close'].values
    obs = []

    # Run engine in rolling windows to detect Springs
    stride = 20
    for i in range(200, len(daily) - 60, stride):
        cutoff = daily['date'].iloc[i]
        if cutoff < pd.Timestamp('2015-01-01') or cutoff > pd.Timestamp('2024-12-31'):
            continue

        d = daily.iloc[:i+1]
        # Generate monthly bars from available data only (NO look-ahead)
        m = _synthesize_monthly(d)
        if len(m) < 12 or len(d) < 120:
            continue
        m12 = m.iloc[-12:]

        # Monthly phase
        mp = classify_monthly_phase(m12)

        # Daily Spring  
        try:
            dr = engine.analyze(d, symbol=symbol, period='日线')
            sig = getattr(dr, 'signal', None)
            ds = getattr(sig, 'spring_date', None) is not None
        except Exception:
            ds = False

        # Forward returns from cutoff
        ci = i
        if ci >= len(day_close) - 20:
            continue

        def fwd(days):
            idx = min(ci + days, len(day_close) - 1)
            return (day_close[idx] / day_close[ci] - 1) * 100

        obs.append(Obs(symbol=symbol, cutoff=str(cutoff.date()),
                       month_phase=mp, day_spring=ds,
                       fwd_1m=fwd(21), fwd_3m=fwd(63), fwd_6m=fwd(126)))
    return obs


def save_checkpoint(all_obs: List[Obs], completed: set, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        'completed': list(completed),
        'obs': [{'s': o.symbol, 'c': o.cutoff, 'p': o.month_phase,
                 'ds': o.day_spring, 'f1': o.fwd_1m, 'f3': o.fwd_3m, 'f6': o.fwd_6m}
                for o in all_obs],
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, default=str)


def load_checkpoint(path: Path) -> tuple[list, set]:
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        obs = [Obs(s=o['s'], cutoff=o['c'], month_phase=o['p'], day_spring=o['ds'],
                   fwd_1m=o['f1'], fwd_3m=o['f3'], fwd_6m=o['f6'])
               for o in data['obs']]
        completed = set(data['completed'])
        print(f"Resumed: {len(obs)} obs from {len(completed)} completed stocks")
        return obs, completed
    return [], set()


def run_panel(stocks: List[str]) -> List[Obs]:
    print(f"Building panel: {len(stocks)} stocks")
    checkpoint_path = CHECKPOINT_DIR / "checkpoint_v4.json"
    all_obs, completed = load_checkpoint(checkpoint_path)
    pending = [s for s in stocks if s not in completed]
    print(f"  Completed: {len(completed)}, Pending: {len(pending)}")
    if not pending:
        print(f"  All done, loaded {len(all_obs)} obs")
        return all_obs

    t0 = time.time()
    with ProcessPoolExecutor(max_workers=N_JOBS) as pool:
        fut = {pool.submit(process_stock, s): s for s in pending}
        done = len(completed)
        for f in as_completed(fut):
            done += 1
            try:
                obs = f.result()
                sym = fut[f]
                completed.add(sym)
                if obs:
                    all_obs.extend(obs)
            except Exception:
                pass
            if done % CHECKPOINT_INTERVAL == 0 or done == len(stocks):
                save_checkpoint(all_obs, completed, checkpoint_path)
                print(f"  {done}/{len(stocks)} stocks, {len(all_obs)} obs, {time.time()-t0:.0f}s")
    save_checkpoint(all_obs, completed, checkpoint_path)
    print(f"Panel: {len(all_obs)} obs in {time.time()-t0:.0f}s")
    return all_obs


# ── Analysis ──

def analyze(obs: List[Obs]):
    print(f"\n{'='*70}")
    print("v4 Results: Rule-based Monthly Phase + Engine Daily Spring (Event-based)")
    print(f"{'='*70}")

    # Compute market return as cross-sectional median at each cutoff
    cutoff_rets = defaultdict(list)
    for o in obs:
        cutoff_rets[o.cutoff].append(o.fwd_6m)
    mkt_rets = {c: np.median(v) for c, v in cutoff_rets.items()}

    # Phase distribution
    phase_rets = defaultdict(list)
    phase_excess = defaultdict(list)
    phase_springs = defaultdict(int)
    phase_spring_ret = defaultdict(list)
    phase_spring_excess = defaultdict(list)

    for o in obs:
        mkt = mkt_rets.get(o.cutoff, 0)
        excess = o.fwd_6m - mkt
        phase_rets[o.month_phase].append(o.fwd_6m)
        phase_excess[o.month_phase].append(excess)
        if o.day_spring:
            phase_springs[o.month_phase] += 1
            phase_spring_ret[o.month_phase].append(o.fwd_6m)
            phase_spring_excess[o.month_phase].append(excess)

    print("\n── Phase Distribution & 6-month Forward Returns ──")
    print(f"  {'Phase':<15} {'N':<8} {'Raw%':<10} {'Excess%':<10} {'PosEx%':<9} {'Spring%':<9}")
    print(f"  {'-'*61}")
    for p in ['accumulation', 'markup', 'distribution', 'markdown', 'unknown']:
        rv = np.array(phase_rets.get(p, []))
        ev = np.array(phase_excess.get(p, []))
        if len(rv) == 0:
            continue
        sp = phase_springs.get(p, 0) / len(rv) * 100
        print(f"  {p:<15} {len(rv):<8} {np.mean(rv):<+10.2f} {np.mean(ev):<+10.2f} {(ev>0).mean()*100:<9.1f} {sp:<9.1f}")

    # Spring analysis
    all_springs = [o.fwd_6m for o in obs if o.day_spring]
    all_excess_s = [o.fwd_6m - mkt_rets.get(o.cutoff, 0) for o in obs if o.day_spring]
    all_nonsprings = [o.fwd_6m for o in obs if not o.day_spring]
    print("\n── Spring Analysis ──")
    print(f"  Events: {len(all_springs)}")
    print(f"  Raw 60d: {np.mean(all_springs):+.2f}%  Excess: {np.mean(all_excess_s):+.2f}%")
    t_s, p_s = stats.ttest_1samp(all_excess_s, 0) if len(all_excess_s) > 10 else (0, 1)
    print(f"  Spring excess t={t_s:.2f} p={p_s:.4f}")

    # Spring + Phase combo with excess
    print("\n── Spring + Phase (Excess Returns) ──")
    for p in ['accumulation', 'markup', 'distribution', 'markdown', 'unknown']:
        sv = np.array(phase_spring_excess.get(p, []))
        nv = np.array([mkt_rets.get(o.cutoff, 0) for o in obs if o.month_phase == p and not o.day_spring])
        if len(sv) < 5:
            continue
        print(f"  {p}: +Spring N={len(sv)} excess={np.mean(sv):+.2f}%")
        if len(nv) > 5:
            t2, p2 = stats.ttest_1samp(sv, 0)
            print(f"    t={t2:.2f} p={p2:.4f} {'✅' if p2<0.05 else '❌'}")

    # Spring-only analysis (across all phases)
    all_springs = [o.fwd_6m for o in obs if o.day_spring]
    all_nonsprings = [o.fwd_6m for o in obs if not o.day_spring]
    print("\n── Spring Analysis (all phases) ──")
    print(f"  Total events: {len(all_springs)}")
    print(f"  Spring 60d: {np.mean(all_springs):+.2f}% median={np.median(all_springs):+.2f}% pos={(np.array(all_springs)>0).mean()*100:.1f}%")
    print(f"  No-Spring 60d: {np.mean(all_nonsprings):+.2f}%")
    t_s, p_s = stats.ttest_ind(all_springs, all_nonsprings, alternative='greater') if len(all_springs) > 10 and len(all_nonsprings) > 10 else (0, 1)
    print(f"  Spring vs No-Spring: t={t_s:.2f} p={p_s:.4f} {'✅' if p_s < 0.05 else '❌'}")

    # Spring + Accumulation (the best combo)
    print("\n── Spring + Phase Combo ──")
    for p in ['accumulation', 'markup', 'distribution', 'markdown', 'unknown']:
        sv = np.array(phase_spring_ret.get(p, []))
        if len(sv) < 5:
            continue
        nv = np.array([o.fwd_6m for o in obs if o.month_phase == p and not o.day_spring])
        print(f"  {p}:")
        print(f"    +Spring N={len(sv)}: {np.mean(sv):+.2f}% {(sv>0).mean()*100:.1f}%")
        if len(nv) > 5:
            print(f"    -Spring N={len(nv)}: {np.mean(nv):+.2f}% {(nv>0).mean()*100:.1f}%")
            t2, p2 = stats.ttest_ind(sv, nv, alternative='greater')
            print(f"    Diff: {np.mean(sv)-np.mean(nv):+.2f}% t={t2:.2f} p={p2:.4f} {'✅' if p2<0.05 else '❌'}")

    # H1: Phase predicts returns (ANOVA)
    groups = [np.array(phase_rets[p]) for p in ['accumulation', 'markup', 'distribution', 'markdown'] if len(phase_rets.get(p, [])) >= 5]
    if len(groups) >= 2:
        f_val, p_val = stats.f_oneway(*groups)
        print(f"\n── H1: Phase ANOVA F={f_val:.2f} p={p_val:.4f} {'✅' if p_val<0.05 else '❌'}")

    # Strategy backtest: Spring + Accum/Markup only
    print("\n── Strategy: Long Spring in Accum/Markup ──")
    valid_phases = {'accumulation', 'markup'}
    strat_rets = [o.fwd_1m for o in obs if o.month_phase in valid_phases and o.day_spring]
    bh_rets = [o.fwd_1m for o in obs]
    if strat_rets:
        sr = np.array(strat_rets)
        br = np.array(bh_rets)
        gross = np.mean(sr)
        net = gross - 0.38  # ~0.38%/mo cost estimate
        bh_m = np.mean(br)
        ann_s = ((1 + net/100) ** 12 - 1) * 100
        ann_b = ((1 + bh_m/100) ** 12 - 1) * 100
        sharpe = np.mean(sr) / np.std(sr) * np.sqrt(12) if np.std(sr) > 0 else 0
        t_s, p_s = stats.ttest_ind(sr, br, alternative='greater')
        print(f"  Signals: {len(strat_rets)}")
        print(f"  Gross: {gross:+.2f}%/mo  Net(after cost): {net:+.2f}%/mo  BH: {bh_m:+.2f}%/mo")
        print(f"  Ann: Strat={ann_s:+.2f}% BH={ann_b:+.2f}% Excess={ann_s-ann_b:+.2f}%")
        print(f"  Sharpe: {sharpe:.3f}")
        print(f"  t={t_s:.2f} p={p_s:.4f} {'✅' if p_s<0.05 else '❌'}")

    # Relaxed strategy: All Springs
    all_sr = np.array(all_springs) / 6  # convert 6m to monthly approx
    all_br = np.array([o.fwd_1m for o in obs])
    if len(all_sr) > 10:
        t_a, p_a = stats.ttest_ind(all_sr, all_br, alternative='greater')
        ann_as = ((1 + np.mean(all_sr)/100) ** 12 - 1) * 100
        print("\n── Strategy: All Springs (no phase filter) ──")
        print(f"  Signals: {len(all_sr)}")
        print(f"  Gross: {np.mean(all_sr):+.2f}%/mo  BH: {np.mean(all_br):+.2f}%/mo")
        print(f"  Ann: Strat={ann_as:+.2f}% BH={ann_b:+.2f}%")
        print(f"  t={t_a:.2f} p={p_a:.4f}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Universe
    from scripts.wyckoff_multitf.a_universe import scan_universe, stratified_sample
    from scripts.wyckoff_multitf.config import VerifierConfig
    cfg = VerifierConfig()
    records = scan_universe(cfg)
    sampled = stratified_sample(records, seed=42)
    stocks = [r.symbol for r in sampled]
    print(f"Universe: {len(stocks)} stocks")

    # Panel
    obs = run_panel(stocks)

    # Analyze
    analyze(obs)

    # Save
    out = {
        'meta': {'n_stocks': len(stocks), 'n_obs': len(obs)},
        'data': [{'s': o.symbol, 'c': o.cutoff, 'p': o.month_phase,
                  'ds': o.day_spring, 'f1': o.fwd_1m, 'f3': o.fwd_3m, 'f6': o.fwd_6m}
                 for o in obs],
    }
    out_path = OUTPUT_DIR / 'v4_results.json'
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")


if __name__ == '__main__':
    main()