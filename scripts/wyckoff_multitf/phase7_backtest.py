"""
Phase 7 — 威科夫交易模拟 (稳健统计 + 成本 + 回撤)
================================================
对每条信号独立模拟交易: 按信号开仓, 持有 f6 窗口, 扣除成本.
不做组合复利 (事件数据不适合组合复利).

f6 字段已是百分数 (f6=1.91 意为 +1.91%).

流程:
  1. 加载 Phase VI 信号 + f6 收益
  2. Winsorize 极端值 (P1/P99) 消除暂停复牌异常
  3. 按信号模拟交易, 扣除 A 股成本
  4. 报告: 稳健统计 (中位数/胜率/t) + 成本灵敏度 + 策略对比
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.uniquant.shared.cost_model import calculate_sharpe_ratio

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(__file__).parent / "output_v4"
MIN_POSITIONS = 10

# A-share round-trip cost (commission + stamp duty + transfer fee + slippage)
ROUND_TRIP_COST = 0.182  # 0.182% (in same units as f6 = percent)


@dataclass
class SimTrade:
    symbol: str
    date: str
    action: str
    f6_return: float   # already in percent (1.91 = +1.91%)
    net_return: float    # after costs
    cost: float
    signal: str


def robust_stats(returns: np.ndarray, winsorize_pct: float = 1.0) -> dict:
    """Robust statistics: median > mean for fat-tailed return distributions."""
    if len(returns) < MIN_POSITIONS:
        return {}
    n = len(returns)
    # Winsorize at specified percentiles
    lo, hi = np.percentile(returns, [winsorize_pct, 100 - winsorize_pct])
    w = np.clip(returns, lo, hi)

    mean = float(np.mean(returns))
    median = float(np.median(returns))
    wmean = float(np.mean(w))

    wstd = float(np.std(w, ddof=1))
    wse = wstd / math.sqrt(n)
    w_t = wmean / wse if wse > 0 else 0.0

    std = float(np.std(returns, ddof=1))
    se = std / math.sqrt(n)
    t = mean / se if se > 0 else 0.0

    wins = returns[returns > 0]
    losses = returns[returns < 0]
    win_rate = len(wins) / n
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0.0
    gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_loss = abs(float(np.sum(losses))) if len(losses) > 0 else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    sharpe = calculate_sharpe_ratio(returns / 100.0, period_days=126)  # f6 = 126 trading days

    return {
        "n": n, "mean": mean, "median": median,
        "winsorized_mean": wmean, "winsorized_std": wstd,
        "t_stat": t, "winsorized_t_stat": w_t,
        "win_rate": win_rate, "avg_win": avg_win, "avg_loss": avg_loss,
        "profit_factor": pf, "sharpe": sharpe,
        "clip_lo": lo, "clip_hi": hi,
    }


def simulate(
    rows: List[Dict],
    signal_field: str,
    cost: float = ROUND_TRIP_COST,
    winsorize_pct: float = 1.0,
) -> Tuple[List[SimTrade], List[SimTrade], List[SimTrade]]:
    """Simulate trades.

    Returns (all_trades, buy_trades, sell_trades).
    f6 already in percent units.
    """
    f6_all = np.array([r.get("f6", 0.0) for r in rows if math.isfinite(r.get("f6", 0.0))])
    if len(f6_all) == 0:
        return [], [], []
    lo, hi = np.percentile(f6_all, [winsorize_pct, 100 - winsorize_pct])

    all_trades: List[SimTrade] = []
    for r in rows:
        signal = r.get(signal_field, "hold")
        if signal == "hold":
            continue
        f6 = float(np.clip(r.get("f6", 0.0), lo, hi))
        if signal == "buy":
            net_ret = f6 - cost
            action = "BUY"
        elif signal == "sell":
            net_ret = -f6 - cost  # short: gain when stock falls
            action = "SELL"
        else:
            continue
        all_trades.append(SimTrade(
            symbol=r["s"], date=r["c"],
            action=action, f6_return=f6,
            net_return=net_ret, cost=cost, signal=signal,
        ))
    buys = [t for t in all_trades if t.action == "BUY"]
    sells = [t for t in all_trades if t.action == "SELL"]
    return all_trades, buys, sells


def fmt_stats(s: dict, label: str = "") -> str:
    """Format robust_stats dict into a fixed-width line."""
    if not s:
        return f"  (n<{MIN_POSITIONS})"
    lab = f"  {label:>8}" if label else ""
    return (
        f"{lab} n={s['n']:>6,}  "
        f"win={s['win_rate']:>6.2%}  "
        f"med={s['median']:>+8.2f}  "
        f"avg={s['winsorized_mean']:>+8.2f}  "
        f"t={s['winsorized_t_stat']:>+8.4f}  "
        f"sharpe={s['sharpe']:>8.4f}  "
        f"pf={s['profit_factor']:>7.4f}"
    )


def main():
    out = OUTPUT_DIR
    with open(out / "phase6_combined_results.json") as f:
        all_data = json.load(f)
    rows = all_data["data"]
    print(f"加载 {len(rows)} 条观测\n")

    strategies = [
        ("wso_sig", "WSO 纯信号"),
        ("wyckoff_sig", "WSO+WSS 组合"),
        ("wyckoff_res_sig", "WSO+WSS+共振过滤"),
    ]

    # ── 1. Distribution diagnostics ──
    f6_all = np.array([r["f6"] for r in rows if math.isfinite(r.get("f6", 0.0))])
    print(f"{'='*60}")
    print("  f6 收益分布诊断 (已为百分数)")
    print(f"{'='*60}")
    print(f"  N={len(f6_all):,}   Mean={np.mean(f6_all):>+8.2f}   Median={np.median(f6_all):>+8.2f}   Std={np.std(f6_all):.2f}")
    for p in [50, 75, 90, 95, 99, 99.9]:
        print(f"  P{p:>4}: {np.percentile(f6_all, p):>+9.2f}")
    for p in [0.1, 1, 5, 10, 25]:
        print(f"  P{p:>4}: {np.percentile(f6_all, p):>+9.2f}")
    print(f"  Min: {np.min(f6_all):>+9.2f}   Max: {np.max(f6_all):>+9.2f}")
    lo, hi = np.percentile(f6_all, [1, 99])
    print(f"\n  Winsorize 界限: [{lo:+.2f}, {hi:+.2f}]  (P1/P99)")
    clipped = np.clip(f6_all, lo, hi)
    print(f"  Winsorized Mean: {np.mean(clipped):>+8.2f}  (raw: {np.mean(f6_all):>+8.2f})")

    # Count outsized moves
    n_outside = int(np.sum((f6_all < lo) | (f6_all > hi)))
    print(f"  被裁剪观测: {n_outside:,} / {len(f6_all):,} ({n_outside/len(f6_all):.2%})")
    print()

    # ── 2. Cost sensitivity ──
    print(f"{'='*60}")
    print("  成本灵敏度分析 (Winsorized P1/P99)")
    print(f"{'='*60}")
    cost_levels = [0.0, 0.05, 0.1, 0.182, 0.3, 0.5, 1.0]
    for sig_field, name in strategies:
        print(f"\n  {name}:")
        for c in cost_levels:
            all_t, buys, sells = simulate(rows, sig_field, cost=c)
            all_rets = np.array([t.net_return for t in all_t])
            buy_rets = np.array([t.net_return for t in buys])
            sell_rets = np.array([t.net_return for t in sells])
            s = robust_stats(all_rets)
            sb = robust_stats(buy_rets) if len(buy_rets) >= MIN_POSITIONS else None
            ss = robust_stats(sell_rets) if len(sell_rets) >= MIN_POSITIONS else None

            spread_str = ""
            if sb and ss:
                spread = sb["winsorized_mean"] - ss["winsorized_mean"]
                spread_se = math.sqrt(
                    sb["winsorized_std"]**2 / sb["n"] +
                    ss["winsorized_std"]**2 / ss["n"]
                )
                spread_t = spread / spread_se if spread_se > 0 else 0.0
                spread_str = f"  spread={spread:>+8.2f} (t={spread_t:>+7.4f})"

            print(f"    cost={c:>6.3f}  "
                  f"n={s['n']:>6,}  win={s['win_rate']:>6.2%}  "
                  f"med={s['median']:>+8.2f}  avg={s['winsorized_mean']:>+8.2f}  "
                  f"t={s['winsorized_t_stat']:>+8.4f}{spread_str}")
    print()

    # ── 3. Strategy comparison (at standard cost) ──
    print(f"{'='*60}")
    print(f"  策略对比 (cost = {ROUND_TRIP_COST:.3f})")
    print(f"{'='*60}")
    print(f"  {'Strategy':<25} {'Label':>5} {'N':>7} {'Win%':>7} {'Median':>9} {'WMean':>9} {'t':>8} {'Sharpe':>8} {'PF':>8}")
    print(f"  {'-'*25} {'-'*5} {'-'*7} {'-'*7} {'-'*9} {'-'*9} {'-'*8} {'-'*8} {'-'*8}")

    for sig_field, name in strategies:
        all_t, buys, sells = simulate(rows, sig_field)
        all_rets = np.array([t.net_return for t in all_t])
        buy_rets = np.array([t.net_return for t in buys])
        sell_rets = np.array([t.net_return for t in sells])
        sa = robust_stats(all_rets)
        sb = robust_stats(buy_rets) if len(buy_rets) >= MIN_POSITIONS else {}
        ss = robust_stats(sell_rets) if len(sell_rets) >= MIN_POSITIONS else {}

        print(f"  {name:<25} {'所有':>5} {sa['n']:>7,} {sa['win_rate']:>7.2%} "
              f"{sa['median']:>+9.2f} {sa['winsorized_mean']:>+9.2f} "
              f"{sa['winsorized_t_stat']:>+8.4f} {sa['sharpe']:>8.4f} {sa['profit_factor']:>8.4f}")
        if sb:
            print(f"  {'':>25} {'买入':>5} {sb['n']:>7,} {sb['win_rate']:>7.2%} "
                  f"{sb['median']:>+9.2f} {sb['winsorized_mean']:>+9.2f} "
                  f"{sb['winsorized_t_stat']:>+8.4f} {sb['sharpe']:>8.4f} {sb['profit_factor']:>8.4f}")
        if ss:
            print(f"  {'':>25} {'卖出':>5} {ss['n']:>7,} {ss['win_rate']:>7.2%} "
                  f"{ss['median']:>+9.2f} {ss['winsorized_mean']:>+9.2f} "
                  f"{ss['winsorized_t_stat']:>+8.4f} {ss['sharpe']:>8.4f} {ss['profit_factor']:>8.4f}")
        if sb and ss:
            spread = sb["winsorized_mean"] - ss["winsorized_mean"]
            spread_se = math.sqrt(
                sb["winsorized_std"]**2 / sb["n"] + ss["winsorized_std"]**2 / ss["n"]
            )
            spread_t = spread / spread_se if spread_se > 0 else 0.0
            print(f"  {'':>25} {'跨距':>5} {'':>7} {'':>7} {'':>9} {spread:>+9.2f} {spread_t:>+8.4f}")
    print()

    # ── 4. Counterfactual ──
    print(f"{'='*60}")
    print("  反事实检验 (反向信号)")
    print(f"{'='*60}")
    for sig_field, name in strategies:
        all_t, buys, sells = simulate(rows, sig_field, cost=0)
        buy_rets = np.array([t.f6_return for t in buys])
        sell_rets = np.array([t.f6_return for t in sells])
        # Reverse signals: if signal said buy, opposite is sell (get -f6)
        opp_rets = np.concatenate([-buy_rets, sell_rets])
        s = robust_stats(opp_rets)
        if s:
            print(f"  {name:<30} n={s['n']:>6,}  avg={s['winsorized_mean']:>+9.2f}  t={s['winsorized_t_stat']:>+8.4f}  sharpe={s['sharpe']:>8.4f}")
    print()

    # ── 5. Top/bottom trades ──
    print(f"{'='*60}")
    print("  最佳/最差交易 (按 net_return)")
    print(f"{'='*60}")
    for sig_field, name in strategies:
        all_t, _, _ = simulate(rows, sig_field)
        sorted_t = sorted(all_t, key=lambda t: t.net_return)
        print(f"\n  {name} — 最佳 5:")
        for t in reversed(sorted_t[-5:]):
            print(f"    {t.date} {t.symbol:>10} {t.action:>4}  f6={t.f6_return:>+8.2f}  net={t.net_return:>+8.2f}")
        print(f"  {name} — 最差 5:")
        for t in sorted_t[:5]:
            print(f"    {t.date} {t.symbol:>10} {t.action:>4}  f6={t.f6_return:>+8.2f}  net={t.net_return:>+8.2f}")
    print()

    # ── 6. Yearly distribution ──
    print(f"{'='*60}")
    print("  信号年度分布")
    print(f"{'='*60}")
    for sig_field, name in strategies:
        by_year: Dict[str, int] = defaultdict(int)
        for r in rows:
            sig = r.get(sig_field, "hold")
            if sig != "hold":
                by_year[r["c"][:4]] += 1
        years = sorted(by_year.keys())
        print(f"  {name:<25}  {', '.join(f'{y}={c:,}' for y, c in zip(years, [by_year[y] for y in years]))}")
    print()

    # ── 7. Save results ──
    for sig_field, name in strategies:
        all_t, buys, sells = simulate(rows, sig_field)
        all_rets = np.array([t.net_return for t in all_t])
        buy_rets = np.array([t.net_return for t in buys])
        sell_rets = np.array([t.net_return for t in sells])
        sa = robust_stats(all_rets)
        sb = robust_stats(buy_rets) if len(buy_rets) >= MIN_POSITIONS else {}
        ss = robust_stats(sell_rets) if len(sell_rets) >= MIN_POSITIONS else {}

        slug = name.lower().replace("+", "_").replace(" ", "_")
        out_path = out / f"phase7_{slug}.json"
        with open(out_path, "w") as f:
            json.dump({
                "name": name,
                "cost": ROUND_TRIP_COST,
                "winsorize_pct": 1.0,
                "all": sa,
                "buys": sb,
                "sells": ss,
            }, f, indent=2, ensure_ascii=False)
        print(f"  已保存: {out_path}")

    print("\n完成。")


if __name__ == "__main__":
    main()
