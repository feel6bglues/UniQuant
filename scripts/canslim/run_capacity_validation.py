"""D+10 容量与全市场验证 — H-A 工程化第一步 (预注册 2026-08-25 冻结)。

━━━ 预注册扩展 (在 P8 docstring 基础上追加, 先于跑数) ━━━━━━━━━━━━━━

目的:
  E1 样本稳健性: 全市场(~5000只)同参数重跑 STRAT-A, 对照 P8 的 500 采样结果
     —— 若全市场显著劣于采样, 说明此前结论含采样偏倚
  E2 流动性地板: 变体[无地板 | 20日日均成交额>=2000万元], 检验剔除不可交易尾部的影响
  E3 容量画像: 持仓名单的日均成交额分布 -> 以"单边参与率<=10% ADV"折算策略规模上限

共同规则继承 P8: Top30 等权 / 5日再平衡+状态切换日 / 涨停不追 / 单边15bp /
近收盘成交假设 / PIT 状态。新增冻结项:
  - 地板阈值: 2000 万元 (20d 均值)
  - 容量折算: 策略规模 <= 持仓名单 ADV 合计 x 10% x (再平衡周期天数/1)
判定:
  F1 全市场扣成本年化 > 0 且夏普 >= 1.0
  F2 地板版夏普 >= 无地板版 (地板不应损害净收益)
  F3 容量下界报告 (非门, 披露项)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TOP_N = 30
REBALANCE_EVERY = 5
LIMIT_UP_PCT = 0.095
COST_ONE_SIDE = 0.0015
AMOUNT_FLOOR = 2e7          # 2000 万元 20 日均值
CAPACITY_PARTICIPATION = 0.10

OUT_PATH = PROJECT_ROOT / "results/factor_mining/capacity_validation.json"


def load_full_panel(max_workers: int = 16) -> pd.DataFrame:
    from scripts.factor_mining.data_loader import load_universe
    from uniquant.brain.factors.custom_factors import compute_illiq_20d

    df = load_universe(as_of="2026-05-29", max_workers=max_workers)
    cutoff = df["date"].sort_values().unique()[-1600]
    df = df[df["date"] >= cutoff].reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    parts = []
    for _, g in df.groupby("code"):
        s = compute_illiq_20d(g.sort_values("date").reset_index(drop=True))
        gg = g.copy()
        gg["illiq_20d"] = s.to_numpy()
        parts.append(gg)
    out = pd.concat(parts, ignore_index=True)
    return out


def build_wide(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    wide_close = df.pivot(index="date", columns="code", values="close").sort_index()
    wide_illiq = df.pivot(index="date", columns="code",
                          values="illiq_20d").reindex(wide_close.index).sort_index()
    wide_amt_med = (
        df.pivot(index="date", columns="code", values="amount")
        .reindex(wide_close.index).sort_index().rolling(20, min_periods=10).median()
    )
    prev = wide_close.shift(1)
    gap = (wide_close / prev - 1).where(prev.notna())
    return wide_close, wide_illiq, gap, wide_amt_med


def load_hot_days(dates_index: pd.DatetimeIndex) -> pd.Series:
    from scripts.factor_mining.conditional_stats import pit_vol_states

    idx_path = PROJECT_ROOT / "data/lake/quotes/daily/000300.SH.parquet"
    idx = pd.read_parquet(idx_path)
    idx["date"] = pd.to_datetime(idx["date"])
    vol_st = pit_vol_states(idx)
    trend = np.where(idx["close"] > idx["close"].rolling(200).mean(),
                     "trend_on", "trend_off")
    tr = pd.DataFrame({"date": idx["date"], "trend": trend})
    st = vol_st.merge(tr, on="date", how="left").dropna(subset=["trend"])
    st["hot"] = (st["vol_state"] == "vol_high") & (st["trend"] == "trend_on")
    hd = st.set_index("date")["hot"]
    return hd.reindex(dates_index).fillna(False)


def simulate(wide_illiq, wide_ret, eligible_mask, hot_days) -> dict:
    dates = list(wide_ret.index)
    codes = list(wide_ret.columns)
    holdings: list[str] = []
    last_rebal = -10**9
    port_ret, turns = [], []
    for ti, dt in enumerate(dates):
        hot = bool(hot_days.iloc[ti])
        if hot and ((ti - last_rebal) >= REBALANCE_EVERY or not holdings):
            elig = [c for c in codes if eligible_mask.at[dt, c]]
            s = pd.Series({c: wide_illiq.at[dt, c] for c in elig}).dropna()
            new_holdings = list(s.sort_values(ascending=False).index[:TOP_N])
            old, new = set(holdings), set(new_holdings)
            turns.append((len(old - new) + len(new - old)) / (2 * TOP_N))
            holdings = new_holdings
            last_rebal = ti
        elif not hot:
            if holdings:
                turns.append(len(holdings) / (2 * TOP_N))
            holdings = []
            last_rebal = -10**9
        else:
            turns.append(0.0)
        if holdings:
            rets = [wide_ret.at[dt, c] for c in holdings]
            valid = [r for r in rets if np.isfinite(r)]
            r = float(np.mean(valid)) if valid else 0.0
            port_ret.append(r - turns[-1] * 2 * COST_ONE_SIDE)
        else:
            port_ret.append(0.0)
    pr = pd.Series(port_ret, index=pd.DatetimeIndex(dates))
    eq = (1 + pr).cumprod()
    years = len(dates) / 244
    sharpe = float(pr.mean() / pr.std(ddof=1) * np.sqrt(244)) if pr.std() > 0 else 0.0
    return {
        "ann_return": round(float(eq.iloc[-1] ** (1 / years) - 1), 4),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(float((eq / eq.cummax() - 1).min()), 4),
        "in_market_frac": round(float(sum(1 for t in turns if True and False) or np.nan), 4),
        "avg_turnover": round(float(np.mean(turns)), 4),
        "_pr": pr,
    }


def main(argv=None):
    t0 = time.time()

    from scripts.canslim.growth_factors import load_financial_codes

    fin = {f"{c}." + ("SH" if c.startswith(("6",)) else ("BJ" if c.startswith(("4", "8")) else "SZ"))
           for c in load_financial_codes()}

    print("[1/5] 加载全市场面板并计算 illiq...")
    full = load_full_panel()
    n_all = full["code"].nunique()
    full = full[~full["code"].isin(fin)]
    n_net = full["code"].nunique()
    wc, wi, gap, wamt = build_wide(full)
    wr = wc / wc.shift(1) - 1
    hot = load_hot_days(wr.index)
    print(f"    全市场 {n_all} 只, 剔金融后 {n_net} 只; 过热牛 {int(hot.sum())}/{len(hot)} 天")

    results = {}
    variants = {
        "FULL_no_floor": None,
        "FULL_floor2000w": AMOUNT_FLOOR,
    }
    for name, floor in variants.items():
        if floor is None:
            mask = pd.DataFrame(True, index=wr.index, columns=wr.columns)
        else:
            mask = (wamt >= floor) & wi.notna()
        mask = mask & gap.lt(LIMIT_UP_PCT) & wi.notna()
        r = simulate(wi, wr, mask, hot)
        pr = r.pop("_pr")
        # 在场占比
        r["in_market_frac"] = round(float((pr != 0).mean()), 3)
        # 容量画像: 该策略实际持仓名单的 ADV 中位 (用无地板 mask 近似持仓日)
        adv_held = wamt.where(mask).stack()
        r["held_name_adv_median_yi"] = round(float(adv_held.median() / 1e8), 3) if len(adv_held) else None
        r["held_name_adv_p25_yi"] = round(float(adv_held.quantile(0.25) / 1e8), 3) if len(adv_held) else None
        results[name] = r
        print(f"  {name:<18} 年化={r['ann_return']:+.2%} 夏普={r['sharpe']:+.2f} "
              f"回撤={r['max_drawdown']:.2%} 在场={r['in_market_frac']:.0%}")

    print("[3/5] 500 采样对照 (同代码路径)...")
    rng = np.random.RandomState(42)
    sel = rng.choice(sorted(full["code"].unique()), size=min(500, n_net), replace=False)
    sub = full[full["code"].isin(sel)]
    wc5, wi5, gap5, wamt5 = build_wide(sub)
    wr5 = wc5 / wc5.shift(1) - 1
    hot5 = load_hot_days(wr5.index)
    m5 = (gap5.lt(LIMIT_UP_PCT)) & wi5.notna()
    r5 = simulate(wi5, wr5, m5, hot5)
    r5.pop("_pr")
    r5["in_market_frac"] = None
    results["SAMPLE500_no_floor"] = r5
    print(f"  SAMPLE500          年化={r5['ann_return']:+.2%} 夏普={r5['sharpe']:+.2f} "
          f"回撤={r5['max_drawdown']:.2%}")

    f_full = results["FULL_no_floor"]
    f_flr = results["FULL_floor2000w"]
    verdict = {
        "F1_fullnet_positive_and_sharpe_ge1": bool(
            f_full["ann_return"] > 0 and f_full["sharpe"] >= 1.0),
        "F2_floor_not_harmful": bool(f_flr["sharpe"] >= f_full["sharpe"]),
    }
    adv_sum = (f_flr.get("held_name_adv_median_yi") or 0) * TOP_N
    capacity = {
        "note": "规模上限 = 持仓名单ADV合计 x 单边参与率10% x 再平衡周期摊薄",
        "held_adv_sum_median_yi": round(adv_sum, 2),
        "participation": CAPACITY_PARTICIPATION,
        "rough_capacity_per_slot_yi": round(
            (f_flr.get("held_name_adv_median_yi") or 0) * CAPACITY_PARTICIPATION, 4),
    }
    report = {
        "_meta": {"prereg": "docstring §预注册扩展 (2026-08-25)",
                  "elapsed_sec": round(time.time() - t0, 1),
                  "n_universe": int(n_net)},
        "episodes_hot_days": int(hot.sum()),
        "strategies": results,
        "verdict": verdict,
        "capacity": capacity,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[5/5] F1={verdict['F1_fullnet_positive_and_sharpe_ge1']} "
          f"F2={verdict['F2_floor_not_harmful']} | 容量画像 {capacity}")
    print(f"报告 → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
