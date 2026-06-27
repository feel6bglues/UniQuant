#!/usr/bin/env python3
"""Phase V: Wyckoff Strategy Engine — full pipeline signal generation + backtest.

Combines WSO scoring + resonance filter into trade decisions, then
backtests the strategy against the Spring-alone baseline.

Usage:
    python3 scripts/wyckoff_multitf/phase5_strategy.py
"""

import sys, json
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from scipy import stats

OUTPUT_DIR = Path(__file__).resolve().parent / "output_v4"


def wyckoff_strategy_signal(
    wso: float,
    wso_sig: str,
    resonance: str,
    has_spring: bool,
    spring_event_count: int,
    buy_threshold: float = 0.04,
    sell_threshold: float = -0.03,
) -> dict:
    """Generate a strategy decision from WSO + resonance.

    Args:
        wso: raw WSO score [-1, 1]
        wso_sig: 'buy' | 'hold' | 'sell'
        resonance: 'bullish' | 'bearish' | 'conflicting'
        has_spring: whether Spring event is present
        spring_event_count: number of non-Spring events near Spring
        buy_threshold: minimum WSO score for buy
        sell_threshold: minimum negative WSO for sell

    Returns:
        {'decision': str, 'strength': float, 'reason': str}
    """
    decision = 'hold'
    strength = 0.0
    reason = 'no signal'

    # Apply stricter thresholds first
    if wso_sig == 'buy' and wso >= buy_threshold:
        if resonance == 'bearish':
            decision = 'buy'
            strength = 1.0
            reason = 'WSO buy + bearish resonance (contrarian bull)'
        elif resonance == 'conflicting':
            decision = 'buy'
            strength = 0.5
            reason = 'WSO buy + conflicting resonance'
        else:
            decision = 'hold'
            strength = 0.2
            reason = 'WSO buy filtered: bullish resonance is bearish'

        # Spring boost: isolated Spring + bearish resonance → very strong buy
        if has_spring and spring_event_count <= 1 and resonance == 'bearish':
            strength = 1.5
            reason = 'Spring isolated + bearish resonance + WSO buy'

    elif wso_sig == 'sell' and wso <= sell_threshold:
        if resonance == 'bullish':
            decision = 'sell'
            strength = 1.5
            reason = 'WSO sell + bullish resonance (strong reversals)'
        elif resonance == 'conflicting':
            decision = 'sell'
            strength = 1.0
            reason = 'WSO sell + conflicting resonance'
        else:
            decision = 'sell'
            strength = 0.5
            reason = 'WSO sell + bearish resonance (mixed)'

    elif has_spring and spring_event_count <= 1:
        # Spring alone (no WSO signal but isolated Spring)
        decision = 'buy'
        strength = 0.4
        reason = 'Spring alone (standalone entry)'

    return {'decision': decision, 'strength': strength, 'reason': reason}


def backtest_signal(data: list, decision_fn, label: str) -> dict:
    """Backtest a signal against f6 forward returns."""
    buys = []
    sells = []
    for obs in data:
        sig = decision_fn(obs)
        if sig == 'hold':
            continue
        elif sig == 'buy':
            buys.append(obs.get('f6', 0))
        elif sig == 'sell':
            sells.append(obs.get('f6', 0))

    result = {'label': label, 'n_buy': len(buys), 'n_sell': len(sells)}

    if buys:
        b_arr = np.array(buys)
        result['buy_mean'] = float(np.mean(b_arr))
        result['buy_t'] = float(stats.ttest_1samp(b_arr, 0).statistic)
        result['buy_sig'] = stats.ttest_1samp(b_arr, 0).pvalue < 0.05
    if sells:
        s_arr = np.array(sells)
        result['sell_mean'] = float(np.mean(s_arr))
        result['sell_t'] = float(stats.ttest_1samp(s_arr, 0).statistic)
        result['sell_sig'] = stats.ttest_1samp(s_arr, 0).pvalue < 0.05

    if buys and sells:
        b_arr = np.array(buys)
        s_arr = np.array(sells)
        t2, p2 = stats.ttest_ind(b_arr, s_arr)
        result['spread'] = float(np.mean(b_arr) - np.mean(s_arr))
        result['spread_t'] = float(t2)
        result['spread_sig'] = p2 < 0.05

    return result


def run():
    path = OUTPUT_DIR / 'phase4_resonance_results.json'
    print(f"Loading {path} ...")
    with open(path) as f:
        data = json.load(f)['data']
    print(f"  {len(data)} observations")

    print(f"\n{'=' * 70}")
    print("Phase V: Wyckoff Strategy Engine")
    print(f"{'=' * 70}")

    # Generate strategy signals
    for obs in data:
        sig = wyckoff_strategy_signal(
            wso=obs.get('wso', 0),
            wso_sig=obs.get('wso_resonance_sig', 'hold'),
            resonance=obs.get('rd', 'conflicting'),
            has_spring=obs.get('ds', False),
            spring_event_count=len([e for e in obs.get('events', []) if e != 'Spring']),
            buy_threshold=0.04,
            sell_threshold=-0.03,
        )
        obs['strategy'] = sig['decision']
        obs['strength'] = sig['strength']
        obs['reason'] = sig['reason']

    out_path = OUTPUT_DIR / 'phase5_strategy_results.json'
    meta = {'n_obs': len(data)}
    with open(out_path, 'w') as f:
        json.dump({'meta': meta, 'data': data}, f, indent=2, default=str)
    print(f"Saved to {out_path}")

    analyze(data)


def analyze(data):
    n = len(data)

    dec_counts = Counter(obs['strategy'] for obs in data)
    print(f"\n── Strategy Signal Distribution ──")
    for dec in ['buy', 'hold', 'sell']:
        c = dec_counts.get(dec, 0)
        print(f"  {dec:<6}: {c:>6} ({c / n * 100:.1f}%)")

    print(f"\n── Strategy Forward Returns (f6) ──")
    print(f"  {'Decision':<8} {'N':<8} {'Mean%':<10} {'t':<8} {'Sig':<6} {'f1':<8} {'f3':<8}")
    for dec in ['buy', 'hold', 'sell']:
        grp = [o for o in data if o.get('strategy') == dec]
        if not grp:
            continue
        f6 = np.array([o.get('f6', 0) for o in grp])
        f3 = np.array([o.get('f3', 0) for o in grp])
        f1 = np.array([o.get('f1', 0) for o in grp])
        t_s, p_s = stats.ttest_1samp(f6, 0)
        sig = '✅' if p_s < 0.05 else '❌'
        print(f"  {dec:<8} {len(grp):<8} {np.mean(f6):+>8.2f}% {t_s:+>7.2f} {sig} {np.mean(f1):+>7.2f}% {np.mean(f3):+>7.2f}%")

    buy = [o for o in data if o.get('strategy') == 'buy']
    sell = [o for o in data if o.get('strategy') == 'sell']
    if buy and sell:
        b = np.array([o['f6'] for o in buy])
        s = np.array([o['f6'] for o in sell])
        t_s, p_s = stats.ttest_ind(b, s)
        print(f"\n── Strategy Buy vs Sell Spread ──")
        print(f"  Buy:  {np.mean(b):+.2f}% (N={len(b)})")
        print(f"  Sell: {np.mean(s):+.2f}% (N={len(s)})")
        print(f"  Spread: {np.mean(b)-np.mean(s):+.2f}% t={t_s:.2f} {'✅' if p_s<0.05 else '❌'}")

    # Strength-weighted return (simulates position sizing)
    print(f"\n── Strength-Weighted Portfolio ──")
    long_rets = []
    short_rets = []
    for obs in data:
        if obs.get('strategy') == 'buy':
            long_rets.append(obs['strength'] * obs.get('f6', 0) / 100)
        elif obs.get('strategy') == 'sell':
            short_rets.append(obs['strength'] * -obs.get('f6', 0) / 100)

    if long_rets:
        lr = np.array(long_rets)
        t_s, _ = stats.ttest_1samp(lr, 0)
        print(f"  Long signals:  N={len(lr)} mean={np.mean(lr)*100:+.2f}% t={t_s:.2f}")
    if short_rets:
        sr = np.array(short_rets)
        t_s, _ = stats.ttest_1samp(sr, 0)
        print(f"  Short signals: N={len(sr)} mean={np.mean(sr)*100:+.2f}% t={t_s:.2f}")

    # Cross-tab: strategy vs resonance
    print(f"\n── Strategy × Resonance ──")
    print(f"  {'Strategy':<10} {'Bearish':<12} {'Bullish':<12} {'Conflicting':<14}")
    for dec in ['buy', 'hold', 'sell']:
        grp = [o for o in data if o.get('strategy') == dec]
        r_counts = Counter(o.get('rd', 'conflicting') for o in grp)
        print(f"  {dec:<10} {r_counts.get('bearish', 0):<12} {r_counts.get('bullish', 0):<12} {r_counts.get('conflicting', 0):<14}")

    # Reason breakdown
    print(f"\n── Top Strategy Reasons ──")
    reason_counts = Counter(obs.get('reason', 'unknown') for obs in data)
    for reason, cnt in reason_counts.most_common(10):
        grp = [o for o in data if o.get('reason') == reason]
        f6 = np.mean([o.get('f6', 0) for o in grp])
        print(f"  {reason:<52} N={cnt:<6} f6={f6:+.2f}%")

    # Backtest baseline comparisons
    print(f"\n── Baseline Backtest (f6) ──")
    baselines = {
        'Spring alone': lambda o: 'buy' if o.get('ds', False) and len([e for e in o.get('events', []) if e != 'Spring']) == 0 else 'hold',
        'Pure WSO (≥0.04)': lambda o: 'buy' if o.get('wso', 0) >= 0.04 else 'hold',
        'WSO + Resonance': lambda o: o.get('strategy'),
    }
    for label, fn in baselines.items():
        buys = [o.get('f6', 0) for o in data if fn(o) == 'buy']
        if len(buys) < 5:
            print(f"  {label:<22}: N={len(buys):<6} — insufficient data")
            continue
        b_arr = np.array(buys)
        t_s, p_s = stats.ttest_1samp(b_arr, 0)
        sig = '✅' if p_s < 0.05 else '❌'
        print(f"  {label:<22}: N={len(buys):<6} f6={np.mean(b_arr):+>7.2f}% t={t_s:+>7.2f} {sig}")

    save_report(data)


def save_report(data):
    lines = []
    lines.append("Phase V: Wyckoff Strategy Engine Report")
    lines.append(f"Total obs: {len(data)}")
    lines.append("")
    for dec in ['buy', 'hold', 'sell']:
        grp = [o for o in data if o.get('strategy') == dec]
        if not grp:
            continue
        f6 = np.mean([o.get('f6', 0) for o in grp])
        lines.append(f"  {dec}: N={len(grp)} f6={f6:+.2f}%")
    lines.append("")
    buy = [o for o in data if o.get('strategy') == 'buy']
    sell = [o for o in data if o.get('strategy') == 'sell']
    if buy and sell:
        b = np.mean([o['f6'] for o in buy])
        s = np.mean([o['f6'] for o in sell])
        lines.append(f"Spread: {b-s:+.2f}%")
    with open(OUTPUT_DIR / 'phase5_report.txt', 'w') as f:
        f.write('\n'.join(lines))
    print(f"\nReport saved to {OUTPUT_DIR / 'phase5_report.txt'}")


if __name__ == '__main__':
    run()
