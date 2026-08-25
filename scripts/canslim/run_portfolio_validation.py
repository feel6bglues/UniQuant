"""D+9 组合层验证 — H-A (illiq_20d @ 过热牛) 可交易性判定。

━━━ 预注册 (2026-08-25 冻结, 先于任何组合回测) ━━━━━━━━━━━━━━━━━━━━

策略族 (同一引擎、同一约束):
  STRAT-A   条件 illiq: 仅当 状态=trend_on∧vol_high 时持有 illiq_20d Top30
  CTRL-B    无条件 illiq: 全程持有 illiq_20d Top30 (隔离"状态择时"贡献)
  CTRL-C    状态内随机: 同状态下每月重抽随机30只 (隔离"因子选股"贡献)

共同规则 (冻结):
  股票池     = P1-P7 同款 500 只 seed=42 面板; 剔金融 (静态名单);
               剔当日收盘涨停(close/close_prev-1 >= +9.5%)不可追买
  组合       = 等权 30 只; 再平衡每 5 个交易日 + 状态切换日
  执行       = 决策用截至 t 收盘信息, 权重作用于 t 日 close→close 收益
               (近收盘成交假设, 与 15bp 单边成本合并披露为乐观项)
  成本       = 单边 15bp (佣金+均摊印花税+小市值滑点), 双边合计 30bp×单边换手;
               现金期收益 0 (不计利息)
  状态       = PIT 点时状态 (滚动750日波动分位, min_periods=250; MA200 趋势)

判定问题 (按重要性):
  Q1 STRAT-A 扣成本后年化是否仍为正且夏普 > 无条件基准?
  Q2 状态择时贡献: A vs B 的收益/回撤差
  Q3 因子选股贡献: A vs C 的收益差
  Q4 暴露画像: 在场天数占比 / 平均连场长度 / 换手率

边界声明: 500 只采样面板非全市场容量结论; 未含幸存者偏差下界修正
(价量因子受影响小于财务因子, 披露即可); 结果为研究判定而非实盘承诺。
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

from scripts.factor_mining.conditional_stats import pit_vol_states  # noqa: E402
from scripts.factor_mining.data_loader import load_universe  # noqa: E402

TOP_N = 30
REBALANCE_EVERY = 5
LIMIT_UP_PCT = 0.095
COST_ONE_SIDE = 0.0015
OUT_PATH = PROJECT_ROOT / "results" / "factor_mining" / "portfolio_validation_ha.json"


def build_panel(n_sample: int) -> pd.DataFrame:
    from uniquant.brain.factors.composer import FactorComposer

    df = load_universe(as_of="2026-05-29", max_workers=16)
    codes_all = sorted(df["code"].unique())
    rng = np.random.RandomState(42)
    selected = rng.choice(codes_all, size=min(n_sample, len(codes_all)), replace=False)
    df = df[df["code"].isin(selected)].reset_index(drop=True)
    cutoff = df["date"].sort_values().unique()[-1600]
    df = df[df["date"] >= cutoff].reset_index(drop=True)
    comp = FactorComposer()
    fac = comp.compute_all_factors(df, mode="backtest")
    df["illiq_20d"] = fac["illiq_20d"].to_numpy()
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_states() -> pd.DataFrame:
    idx_path = PROJECT_ROOT / "data/lake/quotes/daily/000300.SH.parquet"
    idx = pd.read_parquet(idx_path)
    idx["date"] = pd.to_datetime(idx["date"])
    vol_st = pit_vol_states(idx)
    trend = np.where(
        idx["close"] > idx["close"].rolling(200).mean(), "trend_on", "trend_off"
    )
    tr = pd.DataFrame({"date": idx["date"], "trend": trend})
    st = vol_st.merge(tr, on="date", how="left").dropna(subset=["trend"])
    st["hot_bull"] = (st["vol_state"] == "vol_high") & (st["trend"] == "trend_on")
    return st


def simulate(
    wide_illiq: pd.DataFrame,
    wide_close: pd.DataFrame,
    wide_open_prev_close_gap: pd.DataFrame,
    hot_days: pd.Series,
    mode: str,
    rng: np.random.RandomState | None = None,
) -> dict:
    """统一模拟器。mode ∈ {cond_illiq, uncond_illiq, random_in_state}. """
    dates = list(wide_close.index)
    codes = list(wide_close.columns)

    holdings: list[str] = []
    last_rebal = -10**9
    port_ret = []
    turnover_list = []
    in_market = []

    for ti, dt in enumerate(dates):
        hot = bool(hot_days.get(dt, False))
        want_rebalance = (ti - last_rebal) >= REBALANCE_EVERY
        if hot and (not holdings or want_rebalance):
            elig = [
                c for c in codes
                if np.isfinite(wide_illiq.at[dt, c])
                and wide_open_prev_close_gap.at[dt, c] < LIMIT_UP_PCT
            ]
            if mode == "random_in_state":
                rng2 = np.random.default_rng(42 + ti // 5)
                k = min(TOP_N, len(elig))
                new_holdings = list(rng2.choice(elig, size=k, replace=False)) if k else []
            else:
                s = pd.Series(
                    {c: wide_illiq.at[dt, c] for c in elig}
                ).dropna().sort_values(ascending=False)
                new_holdings = list(s.index[:TOP_N])
            old_set = set(holdings)
            new_set = set(new_holdings)
            turn = (len(old_set - new_set) + len(new_set - old_set)) / (2 * max(TOP_N, 1))
            turnover_list.append(turn)
            holdings = new_holdings
            last_rebal = ti
        elif not hot:
            if holdings:
                turnover_list.append(len(holdings) / (2 * TOP_N))
            holdings = []
            last_rebal = -10**9
        else:
            turnover_list.append(0.0)

        if holdings:
            rets = [wide_open_prev_close_gap.at[dt, c] for c in holdings]
            valid = [r for r in rets if np.isfinite(r)]
            r = float(np.mean(valid)) if valid else 0.0
            cost = turnover_list[-1] * 2 * COST_ONE_SIDE
            port_ret.append(r - cost)
            in_market.append(True)
        else:
            port_ret.append(0.0)
            in_market.append(False)

    pr = pd.Series(port_ret, index=pd.DatetimeIndex(dates))
    eq = (1 + pr).cumprod()
    years = len(dates) / 244
    ann = eq.iloc[-1] ** (1 / years) - 1
    vol_a = pr.std(ddof=1) * np.sqrt(244)
    dd = (eq / eq.cummax() - 1).min()
    sharpe = (pr.mean() / pr.std(ddof=1) * np.sqrt(244)) if pr.std() > 0 else 0.0
    return {
        "ann_return": round(float(ann), 4),
        "ann_vol": round(float(vol_a), 4),
        "sharpe": round(float(sharpe), 3),
        "max_drawdown": round(float(dd), 4),
        "total_return": round(float(eq.iloc[-1] - 1), 4),
        "in_market_frac": round(float(np.mean(in_market)), 3),
        "avg_daily_turnover_onesided": round(
            float(np.mean(turnover_list)) if turnover_list else 0.0, 4),
        "n_rebalances": int(sum(1 for t in turnover_list if t > 0)),
    }


def count_episodes(hot_days: pd.Series) -> tuple[int, float]:
    vals = hot_days.reindex(sorted(hot_days.index)).fillna(False).astype(bool).values
    eps = int(np.sum(vals & ~np.concatenate([[False], vals[:-1]])))
    avg_len = float(vals.sum() / eps) if eps else 0.0
    return eps, avg_len


def main(argv=None):
    ap = argparse.ArgumentParser(description="D+9 组合层验证 (预注册)")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args(argv)
    n_sample = 100 if args.smoke else 500

    t0 = time.time()
    df = build_panel(n_sample)
    print(f"[1/4] 面板 {df['code'].nunique()} 只 × {df['date'].nunique()} 天")

    from scripts.canslim.growth_factors import load_financial_codes

    fin_codes = load_financial_codes()
    df = df[~df["code"].str[:6].isin(fin_codes)]

    wide_close = df.pivot(index="date", columns="code", values="close").sort_index()
    wide_illiq = df.pivot(index="date", columns="code", values="illiq_20d").reindex(
        wide_close.index
    ).sort_index()
    prev_close = wide_close.shift(1)
    gap = (wide_close / prev_close - 1).where(prev_close.notna())

    st = load_states()
    hot_days = st.set_index("date")["hot_bull"]
    hot_days = hot_days.reindex(wide_close.index).fillna(False)
    print(f"[2/4] 过热牛天数 {int(hot_days.sum())}/{len(hot_days)} "
          f"({hot_days.mean():.1%}); 金融剔除后股票数 {wide_close.shape[1]}")

    results = {}
    results["STRAT_A_cond_illiq"] = simulate(
        wide_illiq, wide_close, gap, hot_days, "cond_illiq"
    )
    results["CTRL_B_uncond_illiq"] = simulate_uncond(wide_illiq, wide_close, gap)
    results["CTRL_C_random_in_state"] = simulate(
        wide_illiq, wide_close, gap, hot_days, "random_in_state"
    )

    eps, avg_len = count_episodes(hot_days)
    print(f"[3/4] 状态片段: {eps} 次, 平均长度 {avg_len:.1f} 天")

    report = {
        "_meta": {"prereg": "本文件 docstring §预注册 (2026-08-25)",
                  "top_n": TOP_N, "cost_one_side_bp": COST_ONE_SIDE * 1e4,
                  "rebalance_every": REBALANCE_EVERY,
                  "elapsed_sec": round(time.time() - t0, 1)},
        "episodes": {"count": eps, "avg_days": round(avg_len, 1)},
        "strategies": results,
        "verdict": {},
    }
    a, b, c = (results["STRAT_A_cond_illiq"], results["CTRL_B_uncond_illiq"],
               results["CTRL_C_random_in_state"])
    report["verdict"] = {
        "Q1_net_positive": bool(a["ann_return"] > 0),
        "Q2b_timing_value_sharpe": round(a["sharpe"] - b["sharpe"], 3),
        "Q2c_timing_value_ann": round(a["ann_return"] - b["ann_return"], 4),
        "Q3_selection_value_sharpe": round(a["sharpe"] - c["sharpe"], 3),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for k, v in results.items():
        print(f"  {k:<26} 年化={v['ann_return']:+.2%} 夏普={v['sharpe']:+.2f} "
              f"回撤={v['max_drawdown']:.2%} 在场={v['in_market_frac']:.0%} "
              f"日均单边换手={v['avg_daily_turnover_onesided']:.3f}")
    print(f"[4/4] Q1 正收益={report['verdict']['Q1_net_positive']} "
          f"择时增量(夏普)={report['verdict']['Q2b_timing_value_sharpe']:+.2f} "
          f"选股增量(夏普)={report['verdict']['Q3_selection_value_sharpe']:+.2f}")
    print(f"报告 → {OUT_PATH}")
    return 0


def simulate_uncond(
    wide_illiq: pd.DataFrame,
    wide_close: pd.DataFrame,
    gap: pd.DataFrame,
) -> dict:
    """无条件 illiq Top30 (全程在场)。"""
    dates = list(wide_close.index)
    codes = list(wide_close.columns)
    holdings: list[str] = []
    port_ret, turnover_list = [], []
    for ti, dt in enumerate(dates):
        if (ti % REBALANCE_EVERY == 0) or not holdings:
            elig = [
                c for c in codes
                if np.isfinite(wide_illiq.at[dt, c])
                and gap.at[dt, c] < LIMIT_UP_PCT
            ]
            s = pd.Series({c: wide_illiq.at[dt, c] for c in elig}).dropna()
            s = s.sort_values(ascending=False)
            new_holdings = list(s.index[:TOP_N])
            old_set, new_set = set(holdings), set(new_holdings)
            turnover_list.append(
                (len(old_set - new_set) + len(new_set - old_set)) / (2 * TOP_N)
            )
            holdings = new_holdings
        else:
            turnover_list.append(0.0)
        rets = [gap.at[dt, c] for c in holdings]
        valid = [r for r in rets if np.isfinite(r)]
        r = float(np.mean(valid)) if valid else 0.0
        port_ret.append(r - turnover_list[-1] * 2 * COST_ONE_SIDE)
    pr = pd.Series(port_ret, index=pd.DatetimeIndex(dates))
    eq = (1 + pr).cumprod()
    years = len(dates) / 244
    return {
        "ann_return": round(float(eq.iloc[-1] ** (1 / years) - 1), 4),
        "ann_vol": round(float(pr.std(ddof=1) * np.sqrt(244)), 4),
        "sharpe": round(float(pr.mean() / pr.std(ddof=1) * np.sqrt(244)), 3)
        if pr.std() > 0 else 0.0,
        "max_drawdown": round(float((eq / eq.cummax() - 1).min()), 4),
        "total_return": round(float(eq.iloc[-1] - 1), 4),
        "in_market_frac": 1.0,
        "avg_daily_turnover_onesided": round(float(np.mean(turnover_list)), 4),
        "n_rebalances": int(sum(1 for t in turnover_list if t > 0)),
    }


if __name__ == "__main__":
    sys.exit(main())