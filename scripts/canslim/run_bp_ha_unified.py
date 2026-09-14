"""P15 — bp 组合生产引擎验证 (UnifiedMatchingEngine 全口径)。

复用 ha_unified_adapter 的引擎路径 (T+1/涨停拒单/lot取整/万三佣金/万五印花/
千一滑点/单笔最低5元), 将条件 bp Top30 持仓映射转为 TradingSignal 逐股过引擎。

对照: H-A 条件 illiq 生产引擎样本500 +7.43%/0.68/−14.99% (P13 D+13 对账修正后)。

用法:
    python3 scripts/canslim/run_bp_ha_unified.py --limit 5   # 冒烟
    python3 scripts/canslim/run_bp_ha_unified.py --full      # 全 ever_held 聚合
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.canslim.ha_unified_adapter import (  # noqa: E402
    aggregate_portfolio,
    load_hot_days,
    run_stock_engine,
)
from scripts.canslim.run_bp_ha_portfolio import build_panel  # noqa: E402
from scripts.canslim.growth_factors import load_financial_codes  # noqa: E402
from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine  # noqa: E402

TOP_N = 30
REBALANCE_EVERY = 5
LIMIT_UP_PCT = 0.095
OUT_PATH = PROJECT_ROOT / "results" / "factor_mining" / "bp_ha_unified.json"


def build_bp_holdings_map(df: pd.DataFrame, hot_days: pd.Series) -> dict[str, set]:
    """{date: bp Top30 set}. bp 降序=高账面市值比 (低估值)。"""
    fin = load_financial_codes()
    df = df[~df["code"].str[:6].isin(fin)].copy()
    dates = sorted(df["date"].unique())
    bp_lookup: dict = {dt: {} for dt in dates}
    sub = df[df["bp"].notna() & (df["bp"] > 0)]
    for dt, c, v in zip(sub["date"].to_numpy(), sub["code"].to_numpy(),
                        sub["bp"].to_numpy(dtype=float)):
        bp_lookup[dt][c] = v
    prev_close = df.pivot(index="date", columns="code", values="close").sort_index()
    gap = prev_close / prev_close.shift(1) - 1
    hmap = {}
    last_rebal = -10**9
    for ti, dt in enumerate(dates):
        hot = bool(hot_days.get(dt, False))
        rebal = (ti - last_rebal) >= REBALANCE_EVERY
        carried = hmap.get(dates[ti - 1], set()) if ti > 0 else set()
        if hot and rebal:
            day_gap = gap.loc[dt] if dt in gap.index else pd.Series(dtype=float)
            candidates = [
                (c, v) for c, v in bp_lookup[dt].items()
                if c in day_gap.index and pd.notna(day_gap[c])
                and day_gap[c] < LIMIT_UP_PCT
            ]
            candidates.sort(key=lambda x: -x[1])
            hmap[dt] = {c for c, _ in candidates[:TOP_N]}
            last_rebal = ti
        elif not hot:
            hmap[dt] = set()
            last_rebal = -10**9
        else:
            hmap[dt] = carried
    return hmap


def main(argv=None):
    ap = argparse.ArgumentParser(description="P15 bp 生产引擎验证")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args(argv)
    t0 = time.time()

    panel = build_panel(None if args.full else (args.limit or 500))
    hot = load_hot_days(pd.DatetimeIndex(sorted(panel["date"].unique())))
    print(f"[1/3] 面板 {panel['code'].nunique()} 只 × {panel['date'].nunique()} 天")

    hmap = build_bp_holdings_map(panel, hot)
    print(f"[2/3] bp 持仓映射: {sum(1 for v in hmap.values() if v)} 天有持仓")

    ever_held = sorted(set(c for v in hmap.values() for c in v))
    total_capital = 1e7
    n_run = len(ever_held) if args.full else min(5, len(ever_held))
    print(f"  ever_held {len(ever_held)} 只, 本次运行 {n_run} 只 "
          f"({'FULL' if args.full else 'smoke'})")

    stock_returns: dict[str, tuple] = {}
    per_stock_stats = []
    for k, sym in enumerate(ever_held[:n_run]):
        engine = UnifiedBacktestEngine(
            initial_capital=total_capital / TOP_N,
            commission_rate=0.0003,
            stamp_duty_rate=0.0005,
            slippage_rate=0.0010,
            min_commission=5.0,
        )
        out = run_stock_engine(sym, panel, hmap, total_capital / TOP_N, engine)
        if out is None:
            continue
        rets, dts, result = out
        stock_returns[sym] = (rets, dts)
        per_stock_stats.append({
            "symbol": sym, "total_return": round(result.total_return, 4),
            "sharpe": round(result.sharpe, 4),
            "max_drawdown": round(result.max_drawdown, 4),
            "n_trades": len(result.trades),
        })
        if (k + 1) % 25 == 0:
            print(f"  ... {k+1}/{n_run} 只完成")

    agg = aggregate_portfolio(stock_returns) if (len(stock_returns) > 2) else None
    report = {
        "_meta": {"prereg": "docs/analysis/P15_BP_HA_PORTFOLIO_PREREGISTRATION.md",
                  "elapsed_sec": round(time.time() - t0, 1),
                  "engine_params": {"commission": 0.0003, "stamp": 0.0005,
                                    "slippage": 0.0010, "min_commission": 5.0},
                  "reference_ha_illiq_prod": {"universe": 500, "ann": 0.0743,
                                              "sharpe": 0.68, "mdd": -0.1499}},
        "per_stock": per_stock_stats,
        "aggregate": agg,
    }
    if agg:
        sp, sc = agg["slot_pool"], agg["scaled_30"]
        print(f"[3/3] 聚合 ({agg['n_slots']} slots × {agg['n_days']} 天)")
        print(f"  slot_pool : 年化 {sp['ann_return']:+.2%} 夏普 {sp['sharpe']:.2f} "
              f"回撤 {sp['max_drawdown']:.2%}")
        print(f"  scaled_30 : 年化 {sc['ann_return']:+.2%} 夏普 {sc['sharpe']:.2f} "
              f"回撤 {sc['max_drawdown']:.2%}")
        print("  [H-A illiq 生产引擎对照] +7.43%/0.68/−14.99%")
    else:
        print(f"[3/3] 引擎验证完成: {len(per_stock_stats)} 只股票")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"报告 → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
