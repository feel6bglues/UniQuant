"""H-A → unified_engine 适配器 (集成路径验证 + 全市场聚合回测)。

将 H-A 条件 illiq 持仓决策转换为 TradingSignal 序列,
按股票逐一调用 unified_engine.run() 后汇总为组合净值。

过程:
  1. 加载面板 + 状态 + 计算 illiq (同 P10 管线)
  2. 确定每只股票的持仓期 (Top30 成员 + 状态切换)
  3. 逐一股票: 生成 TradingSignal → unified_engine.run()
  4. 汇总组合净值, 与 standalone 对照

--full 模式 (2026-08-26 工程化第二件: 全股票聚合回测):
  - 不采样, 全净化池参与; 全部 ever_held 股票过生产引擎
  - 聚合口径 (冻结): N=len(ever_held) 个等权子账户池,
    组合日收益 = mean(slot 日收益; 缺失日填 0=停牌资金冻结),
    与 P8 的 30-slot 轮换再平衡口径不同 —— 无换股资金回流复利,
    属保守口径; 目的为验证生产引擎成本模型下的量级一致性
  - 对照参照 (研究脚本口径, 冻结): P8 STRAT-A 500只 +15.82%/夏普1.33/
    回撤−12.9%; P10 FULL 4943只 +9.98%/0.93/−22.2%
  - 引擎成本: 万三佣金+万五印花税+千一滑点+单笔最低5元 (≈单边18bp+
    滑点), 近收盘成交假设同 P8

用法:
    python3 scripts/canslim/ha_unified_adapter.py --limit 5   # 冒烟
    python3 scripts/canslim/ha_unified_adapter.py --full      # 全市场聚合

输出: results/factor_mining/ha_unified_adapter.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.canslim.growth_factors import load_financial_codes  # noqa: E402
from scripts.factor_mining.conditional_stats import pit_vol_states  # noqa: E402
from scripts.factor_mining.data_loader import load_universe  # noqa: E402
from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine  # noqa: E402
from uniquant.shared.interfaces import TradingSignal  # noqa: E402

TOP_N = 30
REBALANCE_EVERY = 5
LIMIT_UP_PCT = 0.095
AMOUNT_FLOOR = None
OUT_PATH = PROJECT_ROOT / "results/factor_mining/ha_unified_adapter.json"


def build_panel(n_sample: int | None = None) -> pd.DataFrame:
    from uniquant.brain.factors.custom_factors import compute_illiq_20d

    df = load_universe(as_of="2026-05-29", max_workers=16)
    if n_sample:
        rng = np.random.RandomState(42)
        sel = rng.choice(sorted(df["code"].unique()), n_sample, replace=False)
        df = df[df["code"].isin(sel)].reset_index(drop=True)
    cutoff = df["date"].sort_values().unique()[-1600]
    df = df[df["date"] >= cutoff].reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    parts = []
    for _, g in df.groupby("code"):
        s = compute_illiq_20d(g.sort_values("date").reset_index(drop=True))
        gg = g.copy()
        gg["illiq_20d"] = s.to_numpy()
        parts.append(gg)
    return pd.concat(parts, ignore_index=True)


def load_hot_days(dates_index: pd.DatetimeIndex) -> pd.Series:
    idx_path = PROJECT_ROOT / "data/lake/quotes/daily/000300.SH.parquet"
    idx = pd.read_parquet(idx_path)
    idx["date"] = pd.to_datetime(idx["date"])
    vs = pit_vol_states(idx)
    tr = pd.DataFrame({"date": idx["date"],
                       "trend": np.where(idx["close"] > idx["close"].rolling(200).mean(),
                                         "trend_on", "trend_off")})
    st = vs.merge(tr, on="date", how="left").dropna(subset=["trend"])
    st["hot"] = (st["vol_state"] == "vol_high") & (st["trend"] == "trend_on")
    return st.set_index("date")["hot"].reindex(dates_index).fillna(False)


def build_holdings_map(df: pd.DataFrame, hot_days: pd.Series,
                       amount_floor: float | None = None) -> dict[str, set]:
    """返回 {date: holding_codes_set} 映射 (复用 panel 已算的 illiq_20d 列)。

    amount_floor: 成交额地板 (元)。None=不限; 2e7 = P10 F2 地板变体
    (45 日中位成交额, daily_signal 同款)。
    """
    fin = load_financial_codes()
    df = df[~df["code"].str[:6].isin(fin)].copy()
    dates = sorted(df["date"].unique())
    # illiq 查询表: {date: {code: value}} — 复用 build_panel 预计算列, 免逐股重算
    illiq_lookup: dict = {dt: {} for dt in dates}
    sub = df[df["illiq_20d"].notna() & (df["illiq_20d"] > 0)]
    for dt, c, v in zip(sub["date"].to_numpy(), sub["code"].to_numpy(),
                        sub["illiq_20d"].to_numpy(dtype=float)):
        illiq_lookup[dt][c] = v
    prev_close = df.pivot(index="date", columns="code", values="close").sort_index()
    gap = prev_close / prev_close.shift(1) - 1
    # 45 日中位成交额 (地板过滤; 与 daily_signal 口径一致)
    floor_lookup: dict = {}
    if amount_floor:
        amt = df.pivot_table(index="date", columns="code", values="amount",
                             aggfunc="last").sort_index()
        amt_med = amt.rolling(45, min_periods=20).median()
        floor_lookup = {dt: set(amt_med.loc[dt].dropna()[
            amt_med.loc[dt] >= amount_floor].index)
            for dt in amt_med.index}
    hmap = {}
    last_rebal = -10**9
    for ti, dt in enumerate(dates):
        hot = bool(hot_days.get(dt, False))
        rebal = (ti - last_rebal) >= REBALANCE_EVERY
        # 非再平衡热日沿用前一交易日持仓 (5 日再平衡鞍律; P8 同款)
        carried = hmap.get(dates[ti - 1], set()) if ti > 0 else set()
        if hot and rebal:
            day_gap = gap.loc[dt] if dt in gap.index else pd.Series(dtype=float)
            allowed = floor_lookup.get(dt) if floor_lookup else None
            candidates = [
                (c, iv) for c, iv in illiq_lookup[dt].items()
                if c in day_gap.index and pd.notna(day_gap[c])
                and day_gap[c] < LIMIT_UP_PCT
                and (allowed is None or c in allowed)
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


def run_stock_engine(sym: str, panel: pd.DataFrame, hmap: dict,
                     slot_capital: float, engine: UnifiedBacktestEngine):
    """单只股票: 持仓映射 → TradingSignal → 引擎。返回 (daily_returns, dates) | None。"""
    sd = panel[panel["code"] == sym].sort_values("date").copy()
    sd = sd.rename(columns={"code": "symbol", "close": "close", "volume": "volume"})
    sd = sd[["date", "open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
    if len(sd) < 100:
        return None
    signals = []
    in_pos = False
    for dt in sorted(hmap.keys()):
        hold = sym in hmap.get(dt, [])
        if hold and not in_pos:
            px = sd[sd["date"] == dt]["close"]
            if not len(px):
                continue
            shares = int(slot_capital / float(px.iloc[0]) / 100) * 100
            if shares > 0:
                signals.append(TradingSignal(action="BUY", shares=shares,
                                             symbol=sym, timestamp=pd.Timestamp(dt)))
            in_pos = True
        elif not hold and in_pos:
            signals.append(TradingSignal(action="SELL", shares=999999,
                                         symbol=sym, timestamp=pd.Timestamp(dt)))
            in_pos = False
    if not signals:
        return None
    try:
        result = engine.run(sd, signals, symbol=sym)
        return result.daily_returns, list(pd.to_datetime(sd["date"])), result
    except Exception as e:
        print(f"  {sym} ERR: {type(e).__name__}: {str(e)[:60]}")
        return None


def aggregate_portfolio(stock_returns: dict[str, tuple[list, list]]) -> dict:
    """等权子账户池聚合: 组合日收益 = mean(slot 收益; 缺失日填 0)。

    双口径 (2026-08-26 对账固化):
    - slot_pool: 原始口径, 任一时刻仅 ~TOP_N/N slot 在场
    - scaled_30: 资金效率归一 ×(N/TOP_N), 近似 P8/P10 30-slot 轮换;
      线性缩放不改变夏普, 仅放大收益/回撤
    """
    mat = {}
    for sym, (rets, dts) in stock_returns.items():
        s = pd.Series(rets, index=pd.DatetimeIndex(dts), dtype=float)
        mat[sym] = s
    frame = pd.DataFrame(mat).fillna(0.0).sort_index()
    port_daily = frame.mean(axis=1)

    def _stats(r: pd.Series) -> tuple:
        equity = (1.0 + r).cumprod()
        roll_max = equity.cummax()
        mdd = float(((roll_max - equity) / roll_max).max())
        n_years = len(r) / 244.0
        ann = float(equity.iloc[-1] ** (1.0 / max(n_years, 1e-9)) - 1.0)
        sharpe = float(r.mean() / max(r.std(), 1e-12) * np.sqrt(244))
        return ann, sharpe, -mdd

    ann, sharpe, mdd = _stats(port_daily)
    scale = len(stock_returns) / TOP_N
    ann_s, _, mdd_s = _stats(port_daily * scale)
    return {
        "slot_pool": {"ann_return": round(ann, 4), "sharpe": round(sharpe, 4),
                      "max_drawdown": round(mdd, 4)},
        "scaled_30": {"ann_return": round(ann_s, 4), "sharpe": round(sharpe, 4),
                      "max_drawdown": round(mdd_s, 4), "scale": round(scale, 3),
                      "note": "~P8/P10 30-slot rotation convention"},
        "n_slots": len(stock_returns), "n_days": int(len(port_daily)),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="H-A → unified_engine 适配器")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--full", action="store_true",
                    help="全市场聚合回测 (不采样, 全部 ever_held 过引擎)")
    args = ap.parse_args(argv)
    t0 = time.time()

    panel = build_panel(None if args.full else (args.limit or 500))
    hot = load_hot_days(pd.DatetimeIndex(sorted(panel["date"].unique())))
    print(f"[1/3] 面板 {panel['code'].nunique()} 只 × {panel['date'].nunique()} 天")

    fin = load_financial_codes()
    panel = panel[~panel["code"].str[:6].isin(fin)]
    hmap = build_holdings_map(panel, hot)
    print(f"[2/3] 持仓映射: {sum(1 for v in hmap.values() if v)} 天有持仓")

    ever_held = sorted(set(c for v in hmap.values() for c in v))
    total_capital = 1e7  # 1000 万
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
        if (k + 1) % 50 == 0:
            print(f"  ... {k+1}/{n_run} 只完成")

    agg = aggregate_portfolio(stock_returns) if (
        args.full and len(stock_returns) > 2) else None

    report = {
        "_meta": {"elapsed_sec": round(time.time() - t0, 1),
                  "full": bool(args.full),
                  "n_ever_held": len(ever_held),
                  "engine_params": {"commission": 0.0003, "stamp": 0.0005,
                                    "slippage": 0.0010, "min_commission": 5.0},
                  "aggregate_convention": "equal-weight slot pool, NaN->0",
                  "reference_p8_strat_a": {"universe": 500, "ann": 0.1582,
                                           "sharpe": 1.33, "mdd": -0.129},
                  "reference_p10_full": {"universe": 4943, "ann": 0.0998,
                                         "sharpe": 0.93, "mdd": -0.222}},
        "per_stock": per_stock_stats,
        "aggregate": agg,
    }
    if agg:
        sp, sc = agg["slot_pool"], agg["scaled_30"]
        print(f"[3/3] 聚合 ({agg['n_slots']} slots × {agg['n_days']} 天)")
        print(f"  slot_pool : 年化 {sp['ann_return']:+.2%} 夏普 {sp['sharpe']:.2f} "
              f"回撤 {sp['max_drawdown']:.2%}")
        print(f"  scaled_30 : 年化 {sc['ann_return']:+.2%} 夏普 {sc['sharpe']:.2f} "
              f"回撤 {sc['max_drawdown']:.2%} (×{sc['scale']}, ~P10 口径 "
              f"+9.98%/0.93/−22.2%)")
    else:
        print(f"[3/3] 引擎验证完成: {len(per_stock_stats)} 只股票")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"报告 → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
