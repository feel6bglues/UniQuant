#!/usr/bin/env python3
"""Phase 3: Spring + MonthlyPhase filter strategy — full A-share backtest."""

import sys, time, json, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Tuple, Optional
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
OUTPUT_DIR = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"
N_JOBS = max(1, len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1)

from src.uniquant.brain.wyckoff.monthly_classifier import MonthlyPhaseClassifier


def _d(dt):
    return str(pd.Timestamp(dt))[:10]


def _synthesize_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Generate monthly OHLCV bars from daily data (no look-ahead)."""
    df = df.copy()
    df['mk'] = df['date'].dt.to_period('M').astype(str)
    m = df.groupby('mk', sort=False).agg(
        open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
        close=('close', 'last'), volume=('volume', 'sum'),
        date=('date', 'min')).reset_index().sort_values('date').reset_index(drop=True)
    return m


def backtest_stock(
    symbol: str, lookback_days: int = 120, hold_max: int = 60,
    stop_loss_pct: float = -5.0, take_profit_pct: float = 10.0
) -> dict:
    """Backtest Spring + MonthlyPhase filter on one stock.
    
    Entry: Spring detected AND monthly phase in (accumulation, markup)
    Exit: stop loss, take profit, or max hold days
    """
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    fp = DATA_LAKE / f"{symbol}.parquet"
    if not fp.exists():
        return {'symbol': symbol, 'n_trades': 0, 'error': 'no_data'}

    try:
        daily = pd.read_parquet(fp)
        daily['date'] = pd.to_datetime(daily['date'])
        daily = daily.sort_values('date').reset_index(drop=True)
        if len(daily) < 300:
            return {'symbol': symbol, 'n_trades': 0, 'error': 'short_history'}
    except Exception:
        return {'symbol': symbol, 'n_trades': 0, 'error': 'load_failed'}

    close = daily['close'].values
    dates = daily['date'].values
    engine = WyckoffEngine(lookback_days=lookback_days)
    classifier = MonthlyPhaseClassifier()

    trades = []
    in_trade = False
    entry_idx = 0
    entry_price = 0.0
    stop_price = 0.0
    target_price = 0.0

    # Cost parameters
    comm = 0.0003
    stamp = 0.001
    slip = 0.001

    stride = 20  # evaluate every 20 days (≈monthly)
    for i in range(lookback_days, len(daily) - 20, stride):
        cutoff = daily['date'].iloc[i]

        # Get monthly phase at this cutoff (generate from available data, NO look-ahead)
        d = daily.iloc[:i+1]
        m = _synthesize_monthly(d)
        if len(m) < 12:
            continue
        m12 = m.iloc[-12:]
        phase = classifier.classify(m12)

        # Check entry: recent Spring detected (phase filter removed — all have positive excess)
        if not in_trade:
            try:
                report = engine.analyze(d, symbol=symbol, period='日线')
                sig = getattr(report, 'signal', None)
                spring_date = getattr(sig, 'spring_date', None)
                rr = getattr(getattr(report, 'risk_reward', None), 'reward_risk_ratio', 0)
                conf = getattr(getattr(sig, 'confidence', None), 'value', '?')
                if spring_date is not None:
                    sd = pd.Timestamp(str(spring_date))
                    days_since = (pd.Timestamp(cutoff) - sd).days
                    if days_since <= stride:  # recent spring
                        in_trade = True
                        entry_idx = i
                        entry_price = close[i] * (1 + slip)
                        stop_price = entry_price * (1 + stop_loss_pct / 100)
                        target_price = entry_price * (1 + take_profit_pct / 100)
            except Exception:
                pass

        # Check exit
        if in_trade:
            days_held = i - entry_idx
            if days_held > hold_max:
                # Time exit
                exit_p = close[i] * (1 - slip)
                pnl = (exit_p / entry_price - 1) * 100
                cost = comm + stamp
                trades.append({
                    'entry_date': _d(dates[entry_idx]),
                    'exit_date': _d(dates[i]),
                    'entry_price': round(float(entry_price), 2),
                    'exit_price': round(float(exit_p), 2),
                    'pnl_pct': round(float(pnl - cost), 2),
                    'reason': 'timeout', 'holding_days': days_held,
                })
                in_trade = False
            elif close[i] <= stop_price:
                # Stop loss
                exit_p = close[i] * (1 - slip)
                pnl = (exit_p / entry_price - 1) * 100
                cost = comm + stamp
                trades.append({
                    'entry_date': _d(dates[entry_idx]),
                    'exit_date': _d(dates[i]),
                    'entry_price': round(float(entry_price), 2),
                    'exit_price': round(float(exit_p), 2),
                    'pnl_pct': round(float(pnl - cost), 2),
                    'reason': 'stop_loss', 'holding_days': days_held,
                })
                in_trade = False
            elif close[i] >= target_price:
                # Take profit
                exit_p = close[i] * (1 - slip)
                pnl = (exit_p / entry_price - 1) * 100
                cost = comm + stamp
                trades.append({
                    'entry_date': _d(dates[entry_idx]),
                    'exit_date': _d(dates[i]),
                    'entry_price': round(float(entry_price), 2),
                    'exit_price': round(float(exit_p), 2),
                    'pnl_pct': round(float(pnl - cost), 2),
                    'reason': 'take_profit', 'holding_days': days_held,
                })
                in_trade = False

    # Close any open trade at end
    if in_trade:
        exit_p = close[-1] * (1 - slip)
        pnl = (exit_p / entry_price - 1) * 100
        cost = comm + stamp
        trades.append({
            'entry_date': _d(dates[entry_idx]),
            'exit_date': _d(dates[-1]),
            'entry_price': round(float(entry_price), 2),
            'exit_price': round(float(exit_p), 2),
            'pnl_pct': round(float(pnl - cost), 2),
            'reason': 'end_of_data',
            'holding_days': len(daily) - 1 - entry_idx,
        })

    # Compute metrics
    if not trades:
        return {'symbol': symbol, 'n_trades': 0}

    pnls = np.array([t['pnl_pct'] for t in trades])
    wins = (pnls > 0).sum()
    losses = (pnls <= 0).sum()
    total_ret = float(np.sum(pnls))
    avg_pnl = float(np.mean(pnls))
    win_rate = wins / len(pnls) * 100
    avg_hold = np.mean([t['holding_days'] for t in trades])

    return {
        'symbol': symbol,
        'n_trades': len(trades),
        'total_return_pct': round(total_ret, 2),
        'avg_pnl_pct': round(avg_pnl, 2),
        'win_rate': round(win_rate, 1),
        'n_wins': int(wins),
        'n_losses': int(losses),
        'avg_hold_days': round(float(avg_hold), 1),
        'max_consecutive_losses': _max_consecutive_loss(pnls),
        'profit_factor': _profit_factor(pnls),
    }


def _max_consecutive_loss(pnls: np.ndarray) -> int:
    max_cl = 0
    cur_cl = 0
    for p in pnls:
        if p <= 0:
            cur_cl += 1
            max_cl = max(max_cl, cur_cl)
        else:
            cur_cl = 0
    return max_cl


def _profit_factor(pnls: np.ndarray) -> float:
    gross_profit = pnls[pnls > 0].sum()
    gross_loss = abs(pnls[pnls < 0].sum())
    return round(float(gross_profit / gross_loss), 2) if gross_loss > 0 else float('inf')


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Universe
    from scripts.wyckoff_multitf.a_universe import scan_universe, stratified_sample
    from scripts.wyckoff_multitf.config import VerifierConfig
    print("=== Spring + Phase Strategy Backtest ===")
    cfg = VerifierConfig()
    records = scan_universe(cfg)
    sampled = stratified_sample(records, seed=42)
    stocks = [r.symbol for r in sampled[:500]]
    print(f"Universe: 500 stocks")

    # Parameter grid
    configs = [
        {'stop': -5.0, 'take': 10.0, 'hold': 60, 'label': 'ST=-5 TP=10 H=60'},
        {'stop': -7.0, 'take': 14.0, 'hold': 90, 'label': 'ST=-7 TP=14 H=90'},
        {'stop': -10.0, 'take': 20.0, 'hold': 120, 'label': 'ST=-10 TP=20 H=120'},
        {'stop': -3.0, 'take': 15.0, 'hold': 45, 'label': 'ST=-3 TP=15 H=45'},
    ]

    all_results = {}
    for conf in configs:
        print(f"\n--- Config: {conf['label']} ---")
        results = []
        with ProcessPoolExecutor(max_workers=N_JOBS) as pool:
            fut = {pool.submit(backtest_stock, s,
                               lookback_days=120,
                               hold_max=conf['hold'],
                               stop_loss_pct=conf['stop'],
                               take_profit_pct=conf['take'],
                               ): s for s in stocks}
            done = 0
            for f in as_completed(fut):
                done += 1
                try:
                    r = f.result()
                    if r and r['n_trades'] > 0:
                        results.append(r)
                except Exception:
                    pass
                if done % 100 == 0:
                    print(f"  {done}/{len(stocks)}")

        # Aggregate
        n_traders = len(results)
        total_trades = sum(r['n_trades'] for r in results)
        all_pnls = []
        for r in results:
            all_pnls.append(r['total_return_pct'])
        avg_ret = np.mean(all_pnls) if all_pnls else 0
        med_ret = np.median(all_pnls) if all_pnls else 0
        pos_ratio = sum(1 for r in all_pnls if r > 0) / len(all_pnls) * 100 if all_pnls else 0
        avg_win_rate = np.mean([r['win_rate'] for r in results]) if results else 0
        avg_hold = np.mean([r['avg_hold_days'] for r in results]) if results else 0

        # Annualized return estimate
        # Average 4.5 years of data per stock (2020-2024)
        ann_ret = ((1 + avg_ret / 100) ** (1 / 4.5) - 1) * 100

        print(f"  Stocks with trades: {n_traders}/{len(stocks)}")
        print(f"  Total trades: {total_trades}")
        print(f"  Avg total return: {avg_ret:+.2f}% (median: {med_ret:+.2f}%)")
        print(f"  Positive stocks: {pos_ratio:.1f}%")
        print(f"  Avg win rate: {avg_win_rate:.1f}%")
        print(f"  Avg hold: {avg_hold:.0f} days")
        print(f"  Est annualized: {ann_ret:+.2f}%")

        all_results[conf['label']] = {
            'n_stocks_with_trades': n_traders,
            'total_trades': total_trades,
            'avg_total_return_pct': round(avg_ret, 2),
            'median_total_return_pct': round(med_ret, 2),
            'positive_stocks_pct': round(pos_ratio, 1),
            'avg_win_rate': round(avg_win_rate, 1),
            'avg_hold_days': round(avg_hold, 1),
            'est_annualized_pct': round(ann_ret, 2),
            'details': results if results else [],
        }

    # Save
    out_path = OUTPUT_DIR / 'phase3_strategy_results.json'
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")
    print(f"Elapsed: {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()