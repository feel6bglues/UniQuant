#!/usr/bin/env python3
"""CROSS-SECTIONAL VERIFICATION OF WYCKOFF_PLAN_RESEARCH_20260807.md (red-team harness)

E1 排序力: structural_score / confidence / RS 是否有 cross-sectional 前向收益排序力
   → Spearman IC, IC_pvalue, 5分位单调性(含 Q5-Q1 spread)
E2 方向解耦: phase 作为方向指令是否成立 (accum 应涨 / dist 应跌) — 报告声称 dist 背离
E3 RS gate: leader 过滤是否提升策略夏普

输入: wyckoff_full_scan.py --as-of 的全量CSV
用法: python3 scripts/wyckoff_experiments/validate_ranking.py <scan.csv>
"""
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from _symbols import is_index_symbol  # noqa: E402

ANNUAL_20D = np.sqrt(13.0)


def sharpe(x) -> float:
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return 0.0
    sd = float(x.std())
    if sd == 0:
        return 0.0
    return float(x.mean()) / sd * ANNUAL_20D


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["fwd_20d"].notna()].copy()
    df["fwd_20d"] = df["fwd_20d"].astype(float)
    if "is_etf" in df.columns:
        df = df[~df["is_etf"].fillna(False).astype(bool)]
    if "symbol" in df.columns:
        df = df[~df["symbol"].map(lambda s: is_index_symbol(str(s)) if pd.notna(s) else False)]
    return df


def ic_report(df: pd.DataFrame, factor: str, target: str = "fwd_20d") -> dict:
    valid = df[[factor, target]].dropna()
    if len(valid) < 20:
        return {"factor": factor, "n": len(valid), "ic": np.nan, "p": np.nan}
    rho, p = spearmanr(valid[factor], valid[target])
    return {"factor": factor, "n": int(len(valid)), "ic": round(float(rho), 4), "p": round(float(p), 4)}


def quantile_table(df: pd.DataFrame, factor: str, target: str = "fwd_20d", q: int = 5) -> pd.DataFrame:
    su = df[[factor, target]].dropna().sort_values(factor)
    if len(su) < q * 4:
        return pd.DataFrame()
    grps = np.array_split(su, q)
    rows = []
    for i, g in enumerate(grps):
        rows.append({
            "bucket": f"Q{i + 1}",
            "n": len(g),
            "mu_20d": round(float(g[target].mean()), 2),
            "sharpe": round(sharpe(g[target].to_numpy()), 2),
        })
    rows.append({
        "bucket": "Q5-Q1 spread",
        "n": len(grps[-1]) + len(grps[0]),
        "mu_20d": round(float(grps[-1][target].mean() - grps[0][target].mean()), 2),
        "sharpe": round(sharpe(grps[-1][target].to_numpy()) - sharpe(grps[0][target].to_numpy()), 2),
    })
    return pd.DataFrame(rows)


def direction_test(df: pd.DataFrame, phase: str, expected_up: bool) -> dict:
    sub = df[df["phase"] == phase]["fwd_20d"]
    if len(sub) == 0:
        return {"phase": phase, "n": 0, "emp_20d": np.nan, "expected": "", "consistent": None, "sharpe": np.nan}
    emp = float(sub.mean())
    consistent = (emp > 0.0) if expected_up else (emp < 0.0)
    return {
        "phase": phase,
        "n": int(len(sub)),
        "emp_20d": round(emp, 2),
        "expected": "UP" if expected_up else "DOWN",
        "consistent": bool(consistent),
        "sharpe": round(sharpe(sub.to_numpy()), 2),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: validate_ranking.py <scan.csv>")
        return 1
    df = clean(pd.read_csv(sys.argv[1]))
    print(f"样本: {len(df)} 只 (fwd_20d 非空, 已剔除指数/ETF)")
    print(f"年化: 20d 窗口 × sqrt(13)={ANNUAL_20D:.2f}\n")

    print("=" * 78)
    print("E1 排序力 (Spearman IC + 5分位夏普)")
    print("=" * 78)
    df["_cnum"] = df["confidence_level"].map({"A": 4, "B": 3, "C": 2, "D": 1})
    for factor in ["structural_score", "_cnum", "relative_strength"]:
        r = ic_report(df, factor)
        sig = "***" if r["p"] < 0.01 else "**" if r["p"] < 0.05 else "" if r["p"] < 0.1 else ""
        print(f"  [{factor:<18}] IC={r['ic']:>7.4f}  p={r['p']:<9.4g}  n={r['n']}  {sig}")

    print("\n  structural_score → 20d 前向 5 分位:")
    qt = quantile_table(df, "structural_score")
    print(qt.to_string(index=False))

    print("\n  confidence_level → 20d 前向 5 分位(用数值映射):")
    qt2 = quantile_table(df, "_cnum")
    print(qt2.to_string(index=False))

    print("\n  RS 分组实证边际收益:")
    for label in ["leader", "follower", "weak_independent", "systemic_decline"]:
        sub = df[df["relative_strength"] == label]["fwd_20d"]
        if len(sub) == 0:
            continue
        print(f"    {label:<20} n={len(sub):>5}  mu={sub.mean():>7.2f}%  sharpe={sharpe(sub.to_numpy()):>5.2f}")

    print("\n" + "=" * 78)
    print("E2 方向解耦: phase 作为方向标签的实证一致性")
    print("=" * 78)
    for ph, up in [("accumulation", True), ("markup", True), ("distribution", False), ("markdown", False)]:
        r = direction_test(df, ph, up)
        if r["n"] == 0:
            continue
        verdict = "一致" if r["consistent"] else "背离"
        print(f"    {ph:<16} n={r['n']:>5}  emp20d={r['emp_20d']:>8.2f}%  theor={r['expected']:<4}  {verdict}  sharpe={r['sharpe']:.2f}")

    print("\n" + "=" * 78)
    print("E3 RS gate 策略效应 (leader 过滤前后)")
    print("=" * 78)
    base = df["fwd_20d"]
    ld = df[df["relative_strength"] == "leader"]["fwd_20d"]
    print(f"  全池:            n={len(base):>5}  mu={base.mean():>7.2f}%  sharpe={sharpe(base.to_numpy()):>5.2f}")
    print(f"  leader:          n={len(ld):>5}  mu={ld.mean():>7.2f}%  sharpe={sharpe(ld.to_numpy()):>5.2f}")
    hd = df[(df["relative_strength"] == "leader") & (df["structural_score"] > df["structural_score"].median())]["fwd_20d"]
    print(f"  leader+高分:     n={len(hd):>5}  mu={hd.mean():>7.2f}%  sharpe={sharpe(hd.to_numpy()):>5.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())