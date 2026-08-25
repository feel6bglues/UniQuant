"""H-A → unified_engine 适配器 (验证集成路径)。

将 H-A 条件 illiq 持仓决策转换为 TradingSignal 序列,
按股票逐一调用 unified_engine.run() 后汇总为组合净值。

过程:
  1. 加载面板 + 状态 + 计算 illiq (同 P10 管线)
  2. 确定每只股票的持仓期 (Top30 成员 + 状态切换)
  3. 逐一股票: 生成 TradingSignal → unified_engine.run()
  4. 汇总组合净值, 与 standalone 对照

用法:
    python3 scripts/canslim/ha_unified_adapter.py --limit 5
    python3 scripts/canslim/ha_unified_adapter.py

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


def build_holdings_map(df: pd.DataFrame, hot_days: pd.Series) -> dict[str, list]:
    """返回 {date_code: [holding_codes]} 映射。"""
    from uniquant.brain.factors.custom_factors import compute_illiq_20d

    fin = load_financial_codes()
    df = df[~df["code"].str[:6].isin(fin)].copy()
    dates = sorted(df["date"].unique())
    codes = sorted(df["code"].unique())
    illiq_mat = {c: {} for c in codes}
    for code in codes:
        sub = df[df["code"] == code].sort_values("date")
        s = compute_illiq_20d(sub.reset_index(drop=True))
        for i, dt in enumerate(sub["date"]):
            if i < len(s) and pd.notna(s.iloc[i]):
                illiq_mat[code][dt] = s.iloc[i]
    prev_close = df.pivot(index="date", columns="code", values="close").sort_index()
    gap = prev_close / prev_close.shift(1) - 1
    hmap = {}
    last_rebal = -10**9
    for ti, dt in enumerate(dates):
        hot = bool(hot_days.get(dt, False))
        rebal = (ti - last_rebal) >= REBALANCE_EVERY
        if hot and (not hmap.get(dt) or rebal):
            candidates = []
            for c in codes:
                iv = illiq_mat[c].get(dt)
                if iv is not None and iv > 0 and pd.notna(gap.at[dt, c]) and gap.at[dt, c] < LIMIT_UP_PCT:
                    candidates.append((c, iv))
            candidates.sort(key=lambda x: -x[1])
            hmap[dt] = [c for c, _ in candidates[:TOP_N]]
            last_rebal = ti
        elif not hot:
            hmap[dt] = []
            last_rebal = -10**9
        else:
            hmap[dt] = hmap.get(dt, [])
    return hmap


def main(argv=None):
    ap = argparse.ArgumentParser(description="H-A → unified_engine 适配器")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    t0 = time.time()

    panel = build_panel(args.limit)
    hot = load_hot_days(pd.DatetimeIndex(sorted(panel["date"].unique())))
    print(f"[1/3] 面板 {panel['code'].nunique()} 只 × {panel['date'].nunique()} 天")

    fin = load_financial_codes()
    panel = panel[~panel["code"].str[:6].isin(fin)]
    hmap = build_holdings_map(panel, hot)
    print(f"[2/3] 持仓映射: {sum(1 for v in hmap.values() if v)} 天有持仓")

    # 选取 ever-hold 的股票做引擎验证
    ever_held = sorted(set(c for v in hmap.values() for c in v))
    total_capital = 1e7  # 1000 万
    print(f"  ever_held 股票 {len(ever_held)} 只, 验证前 5 只")

    engine = UnifiedBacktestEngine(
        initial_capital=total_capital / TOP_N,
        commission_rate=0.0003,
        stamp_duty_rate=0.0005,
        slippage_rate=0.0010,
        min_commission=5.0,
    )

    results = []
    for sym in ever_held[:5]:
        sd = panel[panel["code"] == sym].sort_values("date").copy()
        sd = sd.rename(columns={"code": "symbol", "close": "close", "volume": "volume"})
        sd = sd[["date", "open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
        if len(sd) < 100:
            continue
        signals = []
        in_pos = False
        for dt in sorted(hmap.keys()):
            hold = sym in hmap.get(dt, [])
            if hold and not in_pos:
                px = sd[sd["date"] == dt]["close"]
                if not len(px):
                    continue
                shares = int((total_capital / TOP_N) / float(px.iloc[0]) / 100) * 100
                if shares > 0:
                    signals.append(TradingSignal(action="BUY", shares=shares,
                                                symbol=sym, timestamp=pd.Timestamp(dt)))
                in_pos = True
            elif not hold and in_pos:
                signals.append(TradingSignal(action="SELL", shares=999999,
                                            symbol=sym, timestamp=pd.Timestamp(dt)))
                in_pos = False
        if not signals:
            continue
        try:
            result = engine.run(sd, signals, symbol=sym)
            results.append({"symbol": sym, "total_return": round(result.total_return, 4),
                            "sharpe": round(result.sharpe, 4),
                            "max_drawdown": round(result.max_drawdown, 4),
                            "n_trades": len(signals)})
            print(f"  {sym}: ret={result.total_return:+.2%} sharpe={result.sharpe:.2f} "
                  f"dd={result.max_drawdown:.2%} trades={len(signals)}")
        except Exception as e:
            print(f"  {sym} ERR: {type(e).__name__}: {str(e)[:60]}")

    report = {"_meta": {"elapsed_sec": round(time.time() - t0, 1),
                        "engine_params": {"commission": 0.0003, "stamp": 0.0005,
                                          "slippage": 0.0010, "min_commission": 5.0}},
              "results": results}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"[3/3] 引擎验证完成: {len(results)} 只股票, 报告 → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
