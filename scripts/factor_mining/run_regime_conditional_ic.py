"""Regime 条件化因子 IC 诊断 — 预注册设计 (2026-08-25 冻结)。

动机: P1-P5 全部截面因子在本窗口(2019-10→2026-05)四重门失败, 但窗口被
后 2021 成长崩塌单一 regime 主导。本研究回答: 失败是因子无效,
还是单一状态样本掩盖了条件有效性?

━━━ 预注册 (计算前冻结, 修改须披露) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

状态变量:
  S1 趋势: 沪深300收盘 > MA200 → {trend_on, trend_off}
  S2 波动: 指数收益 20d 滚动标准差, 全样本 33%/67% 分位切三档
     → {vol_low, vol_mid, vol_high}
  组合状态 = S1×S2 共 6 格。已知局限: 分位阈值用全样本分布(轻微后视),
  仅用于诊断分层而非 alpha 构建, 可接受并披露。

视野: fwd5 / fwd21 (预注册双视野)
因子集: composer 全部注册价量因子 + 成长族 5 因子 (c_single_yoy 等)

发现判定规则:
  - 候选条件信号 = 状态格内 n_days≥100 且 |t|≥3 的 IC 单元
  - 高亮规则含符号跨状态翻转检验: 同一因子在两个状态格 |t|≥2 且异号
  - 本诊断为 DIAGNOSTIC: 任何候选信号不直接进入系统, 须走全新四重门验证;
    多重比较 (~300 单元) 通过高亮阈值隐式惩罚 (|t|≥3 ≈ p<0.003)

裁决逻辑:
  - 存在候选信号 → 报告并进入定向验证流程
  - 全灭 → 坐实"本窗口无截面 alpha", regime 分层不改变结论
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

from scripts.canslim.growth_factors import (  # noqa: E402
    build_universe_metrics,
    merge_factors_to_daily,
)
from scripts.factor_mining.data_loader import load_universe  # noqa: E402

GROWTH_COLS = ["c_single_yoy", "c_ttm_yoy", "rev_ttm_yoy", "roe", "a_cagr3"]
HORIZONS = [5, 21]
MIN_DAYS_CELL = 100
T_THRESHOLD = 3.0
FLIP_T = 2.0
OUT_PATH = PROJECT_ROOT / "results" / "factor_mining" / "regime_conditional_ic.json"


def daily_ic(panel: pd.DataFrame, factor_col: str, fwd_col: str) -> pd.Series:
    """逐日横截面 Spearman IC (rank-Pearson 公式)。"""
    ics = {}
    sub = panel[["date", factor_col, fwd_col]].dropna()
    if sub.empty:
        return pd.Series(dtype=float)
    for dt, g in sub.groupby("date"):
        if len(g) < 20:
            continue
        fr = g[factor_col].rank()
        rr = g[fwd_col].rank()
        n = len(g)
        num = n * float(np.dot(fr, rr)) - float(fr.sum()) * float(rr.sum())
        den = np.sqrt(
            (n * float(np.dot(fr, fr)) - float(fr.sum()) ** 2)
            * (n * float(np.dot(rr, rr)) - float(rr.sum()) ** 2)
        )
        if den > 1e-12:
            ics[dt] = num / den
    return pd.Series(ics, name=factor_col)


def index_states(index_df: pd.DataFrame) -> pd.DataFrame:
    """S1 趋势(MA200) × S2 波动三分位 → date→state 表。"""
    idx = index_df.sort_values("date").copy()
    idx["date"] = pd.to_datetime(idx["date"])
    idx["ma200"] = idx["close"].rolling(200).mean()
    idx["trend"] = np.where(idx["close"] > idx["ma200"], "trend_on", "trend_off")
    ret = idx["close"].pct_change(fill_method=None)
    vol20 = ret.rolling(20).std()
    q33, q67 = vol20.quantile([0.33, 0.67])
    idx["vol_state"] = pd.cut(
        vol20, [-np.inf, q33, q67, np.inf], labels=["vol_low", "vol_mid", "vol_high"]
    ).astype(str)
    out = idx[["date", "trend", "vol_state"]]
    return out[out["vol_state"].isin(["vol_low", "vol_mid", "vol_high"])]


def summarize(ic_series: pd.Series, states: pd.DataFrame) -> dict | None:
    """按 6 状态格聚合日频 IC。"""
    df = ic_series.to_frame("ic").join(states.set_index("date"), how="inner")
    df["state"] = df["trend"] + "|" + df["vol_state"]
    out = {}
    for st, g in df.groupby("state"):
        n = len(g)
        if n == 0:
            continue
        mean = float(g["ic"].mean())
        std = float(g["ic"].std(ddof=1))
        t = mean / max(std / np.sqrt(n), 1e-12)
        out[st] = {
            "n_days": int(n), "mean_ic": round(mean, 4),
            "t": round(float(t), 2), "pos_frac": round(float((g["ic"] > 0).mean()), 3),
        }
    out["_overall"] = {
        "n_days": int(len(df)), "mean_ic": round(float(df["ic"].mean()), 4),
    }
    return out


def find_highlights(factor_report: dict) -> list[str]:
    """预注册高亮: |t|>=3 且 n_days>=100 的单元 + 跨状态异号对。"""
    hits = []
    core = {k: v for k, v in factor_report.items() if not k.startswith("_")}
    for st, d in core.items():
        if d["n_days"] >= MIN_DAYS_CELL and abs(d["t"]) >= T_THRESHOLD:
            hits.append(f"{st}:IC={d['mean_ic']:+.4f}(t={d['t']:+.1f},n={d['n_days']})")
    items = [(st, d["mean_ic"], d["t"]) for st, d in core.items() if d["n_days"] >= MIN_DAYS_CELL]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            s1, m1, t1 = items[i]
            s2, m2, t2 = items[j]
            if m1 * m2 < 0 and abs(t1) >= FLIP_T and abs(t2) >= FLIP_T:
                hits.append(f"FLIP {s1}({m1:+.4f},t={t1:+.1f}) vs {s2}({m2:+.4f},t={t2:+.1f})")
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="Regime 条件化因子 IC 诊断")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args(argv)
    n_sample = 100 if args.smoke else 500

    t0 = time.time()

    # 1. 行情面板
    df = load_universe(as_of="2026-05-29", max_workers=16)
    codes_all = sorted(df["code"].unique())
    rng = np.random.RandomState(42)
    selected = rng.choice(codes_all, size=min(n_sample, len(codes_all)), replace=False)
    df = df[df["code"].isin(selected)].reset_index(drop=True)
    cutoff = df["date"].sort_values().unique()[-1600]
    df = df[df["date"] >= cutoff].reset_index(drop=True)
    print(f"[1/5] 行情 {df['code'].nunique()} 只 × {df['date'].nunique()} 天")

    # 2. 价量因子 (composer 全注册集)
    from uniquant.brain.factors.composer import FactorComposer

    comp = FactorComposer()
    fac = comp.compute_all_factors(df, mode="backtest")
    for c in fac.columns:
        if c not in df.columns:
            df[c] = fac[c].to_numpy()
    price_cols = [c for c in fac.columns]

    # 3. 成长因子
    qm = build_universe_metrics(sorted(df["code"].unique()))
    if not qm.empty:
        df = merge_factors_to_daily(df, qm)
    growth_present = [c for c in GROWTH_COLS if c in df.columns]
    print(f"[2/5] 因子: 价量 {len(price_cols)} + 成长 {len(growth_present)}")

    # 4. 前向收益 + 状态标注
    for h in HORIZONS:
        df[f"fwd{h}"] = df.groupby("code")["close"].shift(-h) / df["close"] - 1
    idx_path = PROJECT_ROOT / "data/lake/quotes/daily/000300.SH.parquet"
    states = index_states(pd.read_parquet(idx_path)) if idx_path.exists() else None
    if states is None:
        print("TERMINATE: 无指数数据")
        return 2
    df["date"] = pd.to_datetime(df["date"])
    df = df.merge(states, on="date", how="inner")
    print(f"[3/5] 状态覆盖: {df['date'].nunique()} 天; "
          f"趋势on占比 {(df.groupby('date')['trend'].first()=='trend_on').mean():.2f}")

    # 5. 逐因子 × 视野的状态聚合
    report = {"_meta": {"n_symbols": int(df["code"].nunique()), "horizons": HORIZONS,
                        "elapsed_sec": None},
              "factors": {}}
    all_factor_cols = [c for c in dict.fromkeys(price_cols + growth_present)
                       if c in df.columns]
    for k, fcol in enumerate(all_factor_cols):
        entry = {}
        for h in HORIZONS:
            ics = daily_ic(df, fcol, f"fwd{h}")
            if len(ics) < 200:
                continue
            summ = summarize(ics, states)
            if summ is None:
                continue
            highlights = find_highlights(summ)
            entry[f"fwd{h}"] = {"by_state": summ, "highlights": highlights}
        if entry:
            report["factors"][fcol] = entry
            hl_all = [x for v in entry.values() for x in v["highlights"]]
            tag = " ★ " + "; ".join(hl_all[:3]) if hl_all else ""
            ovr = entry.get("fwd5", {}).get("by_state", {}).get("_overall", {})
            print(f"  [{k+1}/{len(all_factor_cols)}] {fcol:<24} "
                  f"fwd5 overall IC={ovr.get('mean_ic', '—')}{tag}")

    report["_meta"]["elapsed_sec"] = round(time.time() - t0, 1)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    n_hl = sum(len(v.get(h, {}).get("highlights", []))
               for v in report["factors"].values() for h in ("fwd5", "fwd21"))
    print(f"[5/5] 完成: {len(report['factors'])} 因子, 高亮单元 {n_hl} 个, "
          f"{report['_meta']['elapsed_sec']}s → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())