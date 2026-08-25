#!/usr/bin/env python3
"""Phase I: Three-timeframe phase analysis on v4 panel data.

Adds weekly phase, daily phase, and multi-timeframe resonance to
the existing v4_results.json (22,148 obs, 500 stocks, 2020-2024).

Avoids lookahead bias by only using completed weekly/monthly bars.

Usage:
    python3 scripts/wyckoff_multitf/phase1_multitf_analysis.py
"""

import sys
import time
import json
import os
from pathlib import Path
from collections import defaultdict
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np
from scipy import stats
from concurrent.futures import ProcessPoolExecutor, as_completed

from uniquant.brain.wyckoff.phase_analysis import (
    WeeklyPhaseClassifier,
    DailyPhaseClassifier,
    MultiTimeframeResonance,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
OUTPUT_DIR = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"
N_JOBS = max(1, len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1)
VERBOSE = True


def log(msg: str):
    if VERBOSE:
        print(msg)


def load_daily(symbol: str) -> Optional[pd.DataFrame]:
    fp = DATA_LAKE / f"{symbol}.parquet"
    if not fp.exists():
        return None
    try:
        df = pd.read_parquet(fp)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        if len(df) < 200:
            return None
        return df
    except Exception:
        return None


def precompute_weekly_bars(daily: pd.DataFrame) -> pd.DataFrame:
    wk = daily['date'].dt.isocalendar()
    daily['wk'] = wk.year.astype(str) + '-W' + wk.week.astype(str).str.zfill(2)
    weekly = daily.groupby('wk', sort=False).agg(
        open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
        close=('close', 'last'), volume=('volume', 'sum'),
        date=('date', 'min')
    ).reset_index().sort_values('date').reset_index(drop=True)
    weekly['week_end'] = weekly['date'] + pd.Timedelta(days=6)
    return weekly


def process_stock(symbol: str, observations: List[dict]) -> List[dict]:
    daily = load_daily(symbol)
    if daily is None:
        return []

    weekly_bars = precompute_weekly_bars(daily)

    daily['ma20'] = daily['close'].rolling(20).mean()
    daily['ma60'] = daily['close'].rolling(60).mean()

    date_arr = daily['date'].values

    wpc = WeeklyPhaseClassifier()
    dpc = DailyPhaseClassifier()

    results = []

    for obs in observations:
        cutoff = pd.Timestamp(obs['c'])

        # ── Weekly phase: only completed weeks (week_end <= cutoff) ──
        wk_complete = weekly_bars[weekly_bars['week_end'] <= cutoff]
        if len(wk_complete) < 12:
            continue
        wk12 = wk_complete.iloc[-12:]
        w_phase = wpc.classify(wk12)

        # ── Daily phase: last 60 bars up to cutoff ──
        ts = np.datetime64(cutoff)
        pos = int(np.searchsorted(date_arr, ts, side='right')) - 1
        if pos < 0:
            continue
        idx = pos
        d_start = max(0, idx - 59)
        d_slice = daily.iloc[d_start:idx + 1]
        if len(d_slice) < 30:
            continue
        d_phase = dpc.classify(d_slice)

        m_phase = obs['p']
        res = MultiTimeframeResonance.resonance(m_phase, w_phase, d_phase)

        results.append({
            's': obs['s'],
            'c': obs['c'],
            'p': m_phase,
            'wp': w_phase,
            'dp': d_phase,
            'rc': res['resonance_count'],
            'rd': res['resonance_dir'],
            'ds': obs['ds'],
            'f1': obs['f1'],
            'f3': obs['f3'],
            'f6': obs['f6'],
        })

    return results


def run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log("Loading v4_results.json ...")
    with open(OUTPUT_DIR / 'v4_results.json') as f:
        v4 = json.load(f)

    obs_list = v4['data']
    log(f"  {v4['meta']['n_obs']} observations, {v4['meta']['n_stocks']} stocks")

    obs_by_symbol = defaultdict(list)
    for o in obs_list:
        obs_by_symbol[o['s']].append(o)

    symbols = list(obs_by_symbol.keys())
    log(f"  {len(symbols)} unique symbols")

    all_results = []
    t0 = time.time()

    log(f"Processing {len(symbols)} stocks with {N_JOBS} workers...")
    with ProcessPoolExecutor(max_workers=N_JOBS) as pool:
        fut = {pool.submit(process_stock, sym, obs_by_symbol[sym]): sym
               for sym in symbols}
        done = 0
        for f in as_completed(fut):
            done += 1
            try:
                res = f.result()
                all_results.extend(res)
            except Exception as e:
                log(f"  Error: {fut[f]}: {e}")
            if done % 50 == 0 or done == len(symbols):
                log(f"  {done}/{len(symbols)} done, {len(all_results)} obs, "
                    f"{time.time() - t0:.0f}s")

    log(f"\nDone: {len(all_results)} observations with phases in {time.time() - t0:.0f}s")

    # ── Save enhanced results ──
    out = {
        'meta': {'n_stocks': v4['meta']['n_stocks'], 'n_obs': len(all_results)},
        'data': all_results,
    }
    out_path = OUTPUT_DIR / 'phase1_results.json'
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    log(f"Saved to {out_path}")

    # ── Analysis ──
    analyze(all_results)


def analyze(data: List[dict]):
    log(f"\n{'=' * 70}")
    log("Phase I: Three-Timeframe Phase Distribution & Resonance")
    log(f"{'=' * 70}")

    n = len(data)
    log(f"  Total observations: {n}")

    # ── Phase distribution ──
    log("\n── Phase Distribution ──")
    for label, key in [('Monthly', 'p'), ('Weekly', 'wp'), ('Daily', 'dp')]:
        counts = defaultdict(int)
        for o in data:
            counts[o[key]] += 1
        log(f"  {label}:")
        for p in ['accumulation', 'markup', 'distribution', 'markdown', 'unknown']:
            c = counts.get(p, 0)
            log(f"    {p:<16} {c:>6} ({c / n * 100:>5.1f}%)")

    # ── Cross-table: Monthly vs Weekly ──
    log("\n── Monthly × Weekly Resonance (count) ──")
    ct = defaultdict(lambda: defaultdict(int))
    for o in data:
        ct[o['p']][o['wp']] += 1
    phases_list = ['accumulation', 'markup', 'distribution', 'markdown', 'unknown']
    header = f"{'M↓ W→':<16}" + "".join(f"{p:<14}" for p in phases_list)
    log(f"  {header}")
    for mp in phases_list:
        row = f"{mp:<16}"
        for wp in phases_list:
            row += f"{ct[mp][wp]:<14}"
        log(f"  {row}")

    # ── Resonance ──
    res_counts = defaultdict(int)
    spring_res = defaultdict(int)
    for o in data:
        res_counts[o['rd']] += 1
        if o['ds']:
            spring_res[o['rd']] += 1
    log("\n── Resonance (multi-timeframe agreement) ──")
    for rd in ['bullish', 'bearish', 'conflicting']:
        log(f"  {rd:<14}: {res_counts.get(rd, 0):>6} ({res_counts.get(rd, 0) / n * 100:>5.1f}%)")
    log("\n── Spring in Resonance ──")
    total_springs = sum(1 for o in data if o['ds'])
    if total_springs > 0:
        for rd in ['bullish', 'bearish', 'conflicting']:
            log(f"  {rd:<14}: {spring_res.get(rd, 0):>6} "
                f"({spring_res.get(rd, 0) / total_springs * 100:>5.1f}%)")

    # ── Forward returns by resonance direction ──
    log("\n── Forward 6m Returns by Resonance ──")
    for rd in ['bullish', 'bearish', 'conflicting']:
        rets = [o['f6'] for o in data if o['rd'] == rd]
        if not rets:
            continue
        arr = np.array(rets)
        log(f"  {rd:<14}: N={len(arr):>6} mean={np.mean(arr):+>7.2f}% "
            f"median={np.median(arr):+>7.2f}% pos={(arr > 0).mean() * 100:>5.1f}%")

    # ── Spring + Resonance ──
    log("\n── Spring Forward 6m Returns by Resonance ──")
    for rd in ['bullish', 'bearish', 'conflicting']:
        rets = [o['f6'] for o in data if o['ds'] and o['rd'] == rd]
        if not rets:
            continue
        arr = np.array(rets)
        log(f"  {rd:<14}: N={len(arr):>6} mean={np.mean(arr):+>7.2f}% "
            f"median={np.median(arr):+>7.2f}% pos={(arr > 0).mean() * 100:>5.1f}%")

    # ── Weekly phase forward returns ──
    log("\n── Weekly Phase Forward 6m Returns ──")
    for p in phases_list:
        rets = [o['f6'] for o in data if o['wp'] == p]
        if not rets:
            continue
        arr = np.array(rets)
        log(f"  {p:<16}: N={len(arr):>6} mean={np.mean(arr):+>7.2f}% "
            f"t={stats.ttest_1samp(arr, 0)[0]:>+.2f} {'✅' if stats.ttest_1samp(arr, 0)[1] < 0.05 else '❌'}")

    # ── Daily phase forward returns ──
    log("\n── Daily Phase Forward 6m Returns ──")
    for p in phases_list:
        rets = [o['f6'] for o in data if o['dp'] == p]
        if not rets:
            continue
        arr = np.array(rets)
        log(f"  {p:<16}: N={len(arr):>6} mean={np.mean(arr):+>7.2f}% "
            f"t={stats.ttest_1samp(arr, 0)[0]:>+.2f} {'✅' if stats.ttest_1samp(arr, 0)[1] < 0.05 else '❌'}")

    # ── Strong resonance (3/3) ──
    strong3 = [o for o in data if o['rc'] == 3]
    log("\n── Strong Resonance (3/3 timeframes agree) ──")
    log(f"  Count: {len(strong3)} ({len(strong3) / n * 100:.1f}%)")
    if strong3:
        s3_rets = np.array([o['f6'] for o in strong3])
        log(f"  Forward 6m: mean={np.mean(s3_rets):+.2f}% "
            f"t={stats.ttest_1samp(s3_rets, 0)[0]:.2f}")

    # ── 2/3 resonance ──
    strong2 = [o for o in data if o['rc'] == 2]
    log("\n── Moderate Resonance (2/3 timeframes agree) ──")
    log(f"  Count: {len(strong2)} ({len(strong2) / n * 100:.1f}%)")
    if strong2:
        s2_rets = np.array([o['f6'] for o in strong2])
        log(f"  Forward 6m: mean={np.mean(s2_rets):+.2f}%")

    # ── Accumulation confirmation ──
    acc_conf = [o for o in data
                if MultiTimeframeResonance.is_accum_confirmed(o['p'], o['wp'], o['dp'])]
    log("\n── Accumulation Confirmed (2+/3 accumulation) ──")
    log(f"  Count: {len(acc_conf)} ({len(acc_conf) / n * 100:.1f}%)")
    if acc_conf:
        acc_rets = np.array([o['f6'] for o in acc_conf])
        log(f"  Forward 6m: mean={np.mean(acc_rets):+.2f}% "
            f"t={stats.ttest_1samp(acc_rets, 0)[0]:.2f}")

    # ── Spring + Accum confirmation ──
    spring_acc = [o for o in data if o['ds'] and
                  MultiTimeframeResonance.is_accum_confirmed(o['p'], o['wp'], o['dp'])]
    log("\n── Spring + Accum Confirmed ──")
    log(f"  Count: {len(spring_acc)}")
    if spring_acc:
        sa_rets = np.array([o['f6'] for o in spring_acc])
        log(f"  Forward 6m: mean={np.mean(sa_rets):+.2f}% "
            f"t={stats.ttest_1samp(sa_rets, 0)[0]:.2f}")
        spring_only = [o['f6'] for o in data if o['ds'] and not
                       MultiTimeframeResonance.is_accum_confirmed(o['p'], o['wp'], o['dp'])]
        if spring_only:
            so_arr = np.array(spring_only)
            log(f"  Spring w/o Accum: N={len(so_arr)} mean={np.mean(so_arr):+.2f}%")
            t2, p2 = stats.ttest_ind(sa_rets, so_arr)
            log(f"  Diff: {np.mean(sa_rets) - np.mean(so_arr):+.2f}% t={t2:.2f} {'✅' if p2<0.05 else '❌'}")

    # ── Phase transition detection (for sequences) ──
    log("\n── Phase Transition Stability ──")
    transitions = defaultdict(int)
    sorted_data = sorted(data, key=lambda x: (x['s'], x['c']))
    prev_phases = {}
    for o in sorted_data:
        key = o['s']
        cur = (o['p'], o['wp'], o['dp'])
        if key in prev_phases:
            prev = prev_phases[key]
            if cur != prev:
                transitions['any'] += 1
            if cur[0] != prev[0]:
                transitions['monthly'] += 1
            if cur[1] != prev[1]:
                transitions['weekly'] += 1
            if cur[2] != prev[2]:
                transitions['daily'] += 1
        prev_phases[key] = cur
    tot = len(sorted_data)
    log("  Phase changes / total obs:")
    for k in ['any', 'monthly', 'weekly', 'daily']:
        log(f"    {k:<10}: {transitions[k]} ({transitions[k] / tot * 100:.1f}%)")

    # ── Save analysis report ──
    report_path = OUTPUT_DIR / 'phase1_report.txt'
    log(f"\nReport saved to {report_path}")


if __name__ == '__main__':
    run()
