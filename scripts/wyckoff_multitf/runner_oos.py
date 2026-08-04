#!/usr/bin/env python3
"""C3 OOS Runner: Wyckoff Spring detection on 2015-2019 (out-of-sample)."""

import sys
import time
import json
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
OUTPUT_DIR = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"
CHECKPOINT_DIR = OUTPUT_DIR / "checkpoints"
CHECKPOINT_INTERVAL = 200
N_JOBS = max(1, len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1)


def classify_monthly_phase(monthly_12: pd.DataFrame) -> str:
    """A-share adapted Wyckoff phase classification (same as runner_v4)."""
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
    if tr < -15 or (r6 < -10 and pp < 0.3):
        return 'markdown'
    if pp < 0.35 and vt < -0.15 and rp < 80 and vr < 0.85:
        return 'accumulation'
    if tr > 10 and pp > 0.5 and vt > 0:
        return 'markup'
    if pp > 0.6 and vp_c < -0.2 and rp > 80:
        return 'distribution'
    if pp > 0.6 and obv_t < -5 and r6 < 5:
        return 'distribution'
    if pp < 0.4 and obv_t > 5 and r6 > -5:
        return 'accumulation'
    return 'unknown'


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
    """Generate monthly OHLCV bars from daily data (no look-ahead)."""
    df = df.copy()
    df['mk'] = df['date'].dt.to_period('M').astype(str)
    m = df.groupby('mk', sort=False).agg(
        open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
        close=('close', 'last'), volume=('volume', 'sum'),
        date=('date', 'min')).reset_index().sort_values('date').reset_index(drop=True)
    return m


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
    from uniquant.brain.wyckoff.engine import WyckoffEngine
    daily = load_daily_data(symbol)
    if daily is None:
        return []

    engine = WyckoffEngine(lookback_days=120)
    day_close = daily['close'].values
    obs = []

    stride = 20
    for i in range(200, len(daily) - 60, stride):
        cutoff = daily['date'].iloc[i]
        # OOS period: 2015-01-01 to 2019-12-31
        if cutoff < pd.Timestamp('2015-01-01') or cutoff > pd.Timestamp('2019-12-31'):
            continue

        d = daily.iloc[:i+1]
        # Generate monthly bars from available data only (NO look-ahead)
        m = _synthesize_monthly(d)
        if len(m) < 12 or len(d) < 120:
            continue
        m12 = m.iloc[-12:]

        mp = classify_monthly_phase(m12)

        try:
            dr = engine.analyze(d, symbol=symbol, period='日线')
            sig = getattr(dr, 'signal', None)
            ds = getattr(sig, 'spring_date', None) is not None
        except Exception:
            ds = False

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
    print(f"Building OOS panel: {len(stocks)} stocks × ~60 cutoffs")
    checkpoint_path = CHECKPOINT_DIR / "checkpoint_oos.json"
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
    print(f"OOS Panel: {len(all_obs)} obs in {time.time()-t0:.0f}s")
    return all_obs


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Load the existing stock universe and filter to those with pre-2014 data
    import pyarrow.parquet as pq
    from datetime import datetime

    with open(OUTPUT_DIR / 'v4_results.json') as f:
        raw = json.load(f)

    stocks_500 = set()
    for obs in raw['data']:
        stocks_500.add(obs['s'])

    print(f"Checking data availability for {len(stocks_500)} stocks...")
    oos_stocks = []
    for s in sorted(stocks_500):
        fp = DATA_LAKE / f"{s}.parquet"
        if fp.exists():
            try:
                tbl = pq.read_table(fp, columns=['date'])
                dates = tbl.column('date').to_pylist()
                d0 = dates[0]
                if isinstance(d0, datetime):
                    d0_str = d0.strftime('%Y-%m-%d')
                elif hasattr(d0, 'strftime'):
                    d0_str = d0.strftime('%Y-%m-%d')
                else:
                    d0_str = str(d0)[:10]
                if d0_str <= '2014-08-01':
                    oos_stocks.append(s)
            except Exception:
                pass

    print(f"OOS universe: {len(oos_stocks)} stocks with pre-2014 data")

    # Panel
    obs = run_panel(oos_stocks)

    # Save
    out = {
        'meta': {'n_stocks': len(oos_stocks), 'n_obs': len(obs), 'period': '2015-01-01 to 2019-12-31'},
        'data': [{'s': o.symbol, 'c': o.cutoff, 'p': o.month_phase,
                  'ds': o.day_spring, 'f1': o.fwd_1m, 'f3': o.fwd_3m, 'f6': o.fwd_6m}
                 for o in obs],
    }
    out_path = OUTPUT_DIR / 'oos_results.json'
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved OOS results to {out_path}")
    print(f"Total elapsed: {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
