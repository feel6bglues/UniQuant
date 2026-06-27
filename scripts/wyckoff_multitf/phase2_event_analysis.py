#!/usr/bin/env python3
"""Phase II: Wyckoff event chain detection on v4 panel data.

Detects PS/SC/AR/ST/SOS/LPS/JAC events in the 120-day window before
each observation, records event sequences, and analyzes forward returns.

Usage:
    python3 scripts/wyckoff_multitf/phase2_event_analysis.py
"""

import sys, time, json, os
from pathlib import Path
from collections import defaultdict, Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np
from scipy import stats
from concurrent.futures import ProcessPoolExecutor, as_completed

from src.uniquant.brain.wyckoff.events import (
    detect_all_events, event_sequence_key, WyckoffEvent,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
OUTPUT_DIR = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"
N_JOBS = max(1, len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1)


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


def process_stock(symbol: str, observations: List[dict]) -> List[dict]:
    daily = load_daily(symbol)
    if daily is None:
        return []

    date_arr = daily['date'].values
    n_daily = len(daily)

    def window_before(cutoff_ts, lookback=120):
        pos = int(np.searchsorted(date_arr, np.datetime64(cutoff_ts), side='right')) - 1
        if pos < lookback:
            return None
        return daily.iloc[pos - lookback + 1:pos + 1].reset_index(drop=True)

    results = []
    for obs in observations:
        try:
            cutoff = pd.Timestamp(obs['c'])
            window = window_before(cutoff, lookback=120)
            if window is None or len(window) < 60:
                continue

            events = detect_all_events(window)
            seq_key = event_sequence_key(events)

            event_types = []
            for wyckoff_event in events:
                if wyckoff_event.confidence > 0.3:
                    event_types.append(wyckoff_event.event_type)
            event_confidences = {}
            for et in set(event_types):
                max_conf = 0.0
                for wyckoff_event in events:
                    if wyckoff_event.event_type == et and wyckoff_event.confidence > max_conf:
                        max_conf = wyckoff_event.confidence
                event_confidences[et] = max_conf

            results.append({
                's': obs['s'], 'c': obs['c'],
                'p': obs.get('p', ''), 'wp': obs.get('wp', ''),
                'dp': obs.get('dp', ''), 'rc': obs.get('rc', 0),
                'rd': obs.get('rd', ''),
                'ds': obs.get('ds', False),
                'f1': obs.get('f1', 0), 'f3': obs.get('f3', 0),
                'f6': obs.get('f6', 0),
                'n_events': len(event_types),
                'events': event_types,
                'seq': seq_key,
                'conf': event_confidences,
            })
        except Exception:
            continue
    return results


def run():
    src = OUTPUT_DIR / 'phase1_results.json'
    if not src.exists():
        src = OUTPUT_DIR / 'v4_results.json'

    print(f"Loading {src} ...")
    with open(src) as f:
        v4 = json.load(f)

    obs_list = v4['data']
    print(f"  {len(obs_list)} observations")

    obs_by_symbol = defaultdict(list)
    for o in obs_list:
        obs_by_symbol[o['s']].append(o)
    symbols = list(obs_by_symbol.keys())
    print(f"  {len(symbols)} unique symbols")

    all_results = []
    t0 = time.time()

    print(f"Processing {len(symbols)} stocks with {N_JOBS} workers...")
    with ProcessPoolExecutor(max_workers=N_JOBS) as pool:
        fut = {pool.submit(process_stock, sym, obs_by_symbol[sym]): sym for sym in symbols}
        done = 0
        for f in as_completed(fut):
            done += 1
            try:
                all_results.extend(f.result())
            except Exception as e:
                print(f"  Error {fut[f]}: {e}")
            if done % 50 == 0 or done == len(symbols):
                print(f"  {done}/{len(symbols)} done, {len(all_results)} obs, "
                      f"{time.time() - t0:.0f}s")

    print(f"\nDone: {len(all_results)} obs in {time.time() - t0:.0f}s")

    out = {'meta': {'n_stocks': v4['meta']['n_stocks'], 'n_obs': len(all_results)}, 'data': all_results}
    out_path = OUTPUT_DIR / 'phase2_event_results.json'
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"Saved to {out_path}")

    analyze(all_results)


def analyze(data: List[dict]):
    n = len(data)
    print(f"\n{'=' * 70}")
    print(f"Phase II: Wyckoff Event Chain Detection")
    print(f"{'=' * 70}")
    print(f"  Total observations: {n}")

    event_counter = Counter()
    seq_counter = Counter()
    seq_returns = defaultdict(list)
    spring_event_returns = defaultdict(list)
    resonance_event_returns = defaultdict(list)

    for obs in data:
        for et in obs['events']:
            event_counter[et] += 1
        seq_counter[obs['seq']] += 1
        seq_returns[obs['seq']].append(obs['f6'])
        if obs['ds']:
            spring_event_returns[obs['seq']].append(obs['f6'])
        rd = obs.get('rd', 'conflicting')
        resonance_event_returns[rd].append(obs['f6'])

    print(f"\n── Event Frequency ──")
    print(f"  {'Event':<8} {'Count':<8} {'% of Obs':<10} {'Avg/Stock':<10}")
    for et in ['PS', 'SC', 'AR', 'ST', 'SOS', 'LPS', 'JAC']:
        c = event_counter.get(et, 0)
        print(f"  {et:<8} {c:<8} {c / n * 100:<10.1f} {c / 500:<10.1f}")

    print(f"\n── Event Count Distribution ──")
    cnt_dist = Counter(obs['n_events'] for obs in data)
    for k in sorted(cnt_dist.keys()):
        print(f"  {k} events: {cnt_dist[k]:>6} ({cnt_dist[k] / n * 100:.1f}%)")

    print(f"\n── Top 20 Event Sequences (by frequency) ──")
    top_seqs = seq_counter.most_common(20)
    print(f"  {'Sequence':<30} {'Count':<8} {'Mean%':<8} {'t':<8} {'Sig':<6}")
    for seq, cnt in top_seqs:
        rets = np.array(seq_returns[seq])
        if len(rets) < 5:
            continue
        t_stat, p_val = stats.ttest_1samp(rets, 0)
        sig = '✅' if p_val < 0.05 else '❌'
        print(f"  {seq:<30} {cnt:<8} {np.mean(rets):+>7.2f}% {t_stat:+>7.2f} {sig:<6}")

    fallback = Counter()
    for s in seq_counter:
        if s not in ('NONE', 'LOW_CONF') and seq_counter[s] >= 10:
            fallback[s] = seq_counter[s]
    print(f"\n── Event Sequences with Spring ──")
    spring_seqs = [(s, c) for s, c in seq_counter.items()
                   if c >= 10 and s not in ('NONE', 'LOW_CONF')
                   and spring_event_returns[s]]
    spring_seqs.sort(key=lambda x: -x[1])
    print(f"  {'Sequence':<30} {'N_Spring':<10} {'Mean%':<10} {'t':<8}")
    for seq, cnt in spring_seqs[:15]:
        rets = np.array(spring_event_returns[seq])
        if len(rets) < 5:
            continue
        t_stat, _ = stats.ttest_1samp(rets, 0)
        print(f"  {seq:<30} {len(rets):<10} {np.mean(rets):+>7.2f}% {t_stat:+>7.2f}")

    print(f"\n── Event Returns vs No Events (Spring only) ──")
    spring_with_events = []
    spring_no_events = []
    for obs in data:
        if not obs.get('ds', False):
            continue
        if obs['seq'] not in ('NONE', 'LOW_CONF'):
            spring_with_events.append(obs['f6'])
        else:
            spring_no_events.append(obs['f6'])
    if spring_with_events and spring_no_events:
        wa = np.array(spring_with_events)
        na = np.array(spring_no_events)
        t2, p2 = stats.ttest_ind(wa, na)
        print(f"  Spring + events: N={len(wa)} mean={np.mean(wa):+.2f}%")
        print(f"  Spring alone:    N={len(na)} mean={np.mean(na):+.2f}%")
        print(f"  Diff: {np.mean(wa) - np.mean(na):+.2f}% t={t2:.2f} {'✅' if p2 < 0.05 else '❌'}")

    print(f"\n── Event Returns by Resonance Direction ──")
    for rd in ['bullish', 'bearish', 'conflicting']:
        rets = resonance_event_returns.get(rd, [])
        if not rets:
            continue
        arr = np.array(rets)
        t_s, p_s = stats.ttest_1samp(arr, 0)
        print(f"  {rd:<14}: N={len(arr):>6} mean={np.mean(arr):+>7.2f}% t={t_s:+>7.2f}")

    save_report(data, seq_returns, event_counter, seq_counter)


def save_report(data, seq_returns, event_counter, seq_counter):
    lines = []
    lines.append("Phase II: Wyckoff Event Chain Detection Report")
    lines.append(f"Total obs: {len(data)}")
    lines.append("")
    lines.append("Event Frequency:")
    for et in ['PS', 'SC', 'AR', 'ST', 'SOS', 'LPS', 'JAC']:
        c = event_counter.get(et, 0)
        lines.append(f"  {et}: {c} ({c / len(data) * 100:.1f}%)")
    lines.append("")
    lines.append("Top 20 Sequences:")
    for seq, cnt in seq_counter.most_common(20):
        rets = seq_returns.get(seq, [])
        if len(rets) < 5:
            continue
        lines.append(f"  {seq}: N={cnt} mean={np.mean(np.array(rets)):+.2f}%")
    with open(OUTPUT_DIR / 'phase2_report.txt', 'w') as f:
        f.write('\n'.join(lines))
    print(f"\nReport saved to {OUTPUT_DIR / 'phase2_report.txt'}")


if __name__ == '__main__':
    run()
