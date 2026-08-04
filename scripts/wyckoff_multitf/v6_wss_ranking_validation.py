#!/usr/bin/env python3
"""V6: WSS 排名质量验证

假设: WSS 统计分数增强 WSO, 混合后的 WyckoffScore 
      比纯 WSO Score 对 f6 的排序预测能力更强。

方法:
  1. 加载 phase6_combined_results.json (22K 观测)
  2. 按 WSO Score 和 WyckoffScore 分别排序为五分位
  3. 比较各五分位的 f6 均值 + 单调性
  4. 计算秩相关 (Spearman) 
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, kendalltau, pearsonr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"
PHASE6 = OUTPUT / "phase6_combined_results.json"


def main():
    print("=" * 60)
    print("  V6: WSS 排名质量验证")
    print("=" * 60)

    with open(PHASE6) as f:
        data = json.load(f)
    rows = data["data"]
    print(f"\nPhase6 观测数: {len(rows)}")

    df = pd.DataFrame(rows)
    df = df[(df["wso_score"] != 0) | (df["wyckoff_score"] != 0)].copy()

    print(f"  有效观测 (含非零分数): {len(df)}\n")

    # ── 1. Score distributions ──
    print("=" * 60)
    print("  1. Score 分布统计")
    print("=" * 60)
    for col, label in [("wso_score", "WSO Score"),
                       ("wyckoff_score", "WyckoffScore")]:
        vals = df[col].values
        print(f"  {label}: "
              f"均值={np.mean(vals):.4f}, 中位数={np.median(vals):.4f}, "
              f"std={np.std(vals):.4f}")

    # ── 2. Quintile analysis ──
    print("\n" + "=" * 60)
    print("  2. 五分位 f6 分析")
    print("=" * 60)
    from scipy.stats import kruskal
    for col, label in [("wso_score", "WSO Score"),
                       ("wyckoff_score", "WyckoffScore"),
                       ("wso_score", "WSO Score (buy/sell only)")]:
        is_bs = "buy/sell only" in label
        d = df[df["wso_sig"].isin(["buy", "sell"])] if is_bs else df
        if len(d) < 50:
            continue
        d = d.copy()
        d["quintile"] = pd.qcut(d[col], 5, labels=["Q1(low)", "Q2", "Q3", "Q4", "Q5(high)"],
                                duplicates="drop")
        print(f"\n  {label}:")
        quint_stats = []
        for q in ["Q1(low)", "Q2", "Q3", "Q4", "Q5(high)"]:
            mask = d["quintile"] == q
            n = mask.sum()
            if n < 3:
                continue
            f6_v = d.loc[mask, "f6"].values
            quint_stats.append(np.mean(f6_v))
            print(f"    {q:>10}: n={n:>4}, f6={np.mean(f6_v):>+8.2f}±{np.std(f6_v):.2f}")
        if len(quint_stats) >= 3:
            monotonic = all(quint_stats[i] <= quint_stats[i+1]
                            for i in range(len(quint_stats)-1)) or \
                       all(quint_stats[i] >= quint_stats[i+1]
                            for i in range(len(quint_stats)-1))
            spread = quint_stats[-1] - quint_stats[0]
            print(f"    {'多空跨距':>10}: {spread:>+8.2f}")
            print(f"    {'单调性':>10}: {'✅ 单调' if monotonic else '⚠️ 非单调'}")
            # Kruskal-Wallis test (non-parametric ANOVA)
            groups = [d.loc[d["quintile"] == q, "f6"].values for q in
                      ["Q1(low)", "Q2", "Q3", "Q4", "Q5(high)"] if (d["quintile"] == q).sum() >= 3]
            if len(groups) >= 3:
                h, p_kw = kruskal(*groups)
                print(f"    {'KW-test':>10}: H={h:.2f}, p={p_kw:.4f}")

    # ── 3. Rank correlation ──
    print("\n" + "=" * 60)
    print("  3. 排序相关 (Spearman)")
    print("=" * 60)
    for col, label in [("wso_score", "WSO Score"),
                       ("wyckoff_score", "WyckoffScore")]:
        valid = df[col].notna() & df["f6"].notna()
        d = df[valid]
        rho, p_rho = spearmanr(d[col], d["f6"])
        tau, p_tau = kendalltau(d[col], d["f6"])
        r, p_p = pearsonr(d[col], d["f6"])
        print(f"  {label}:")
        print(f"    Spearman ρ = {rho:+.4f}, p = {p_rho:.6f}")
        print(f"    Kendall τ = {tau:+.4f}, p = {p_tau:.6f}")
        print(f"    Pearson  r = {r:+.4f}, p = {p_p:.6f}")

    # ── 4. WSS contribution ──
    print("\n" + "=" * 60)
    print("  4. WSS 边际贡献")
    print("=" * 60)
    diff = df["wyckoff_score"] - df["wso_score"]
    print(f"  WyckoffScore - WSO Score 均值: {np.mean(diff):.6f}")
    print(f"  差异 std: {np.std(diff):.6f}")
    print(f"  差异 > 0.01: {(diff > 0.01).sum()} ({(diff > 0.01).sum()/len(diff):.1%})")
    print(f"  差异 < -0.01: {(diff < -0.01).sum()} ({(diff < -0.01).sum()/len(diff):.1%})")
    print(f"  差异 ≈ 0 (±0.01): {((diff >= -0.01) & (diff <= 0.01)).sum()} "
          f"({((diff >= -0.01) & (diff <= 0.01)).sum()/len(diff):.1%})")

    # Where WSS makes a difference, does it improve?
    meaningful_diff = abs(diff) > 0.01
    if meaningful_diff.sum() > 50:
        df_m = df[meaningful_diff].copy()
        df_m["wss_improves"] = ((df_m["wyckoff_score"] > df_m["wso_score"]) &
                                 (df_m["f6"] > 0)) | \
                                ((df_m["wyckoff_score"] < df_m["wso_score"]) &
                                 (df_m["f6"] < 0))
        improve_rate = df_m["wss_improves"].mean()
        print(f"  WSS 方向正确率: {improve_rate:.1%}")

    print("\n" + "=" * 60)
    print("  V6 验证结论")
    print("=" * 60)
    print("""
  WSS 排名质量:
    - WSO Score 五分位 f6 跨距 (单调性)
    - WyckoffScore 排名 vs Spearman ρ
    - WSS 边际贡献的方向正确率
""")

    out_path = OUTPUT / "v6_wss_ranking_results.json"
    summary = {"n_obs": len(df)}
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  结果已保存: {out_path}")


if __name__ == "__main__":
    main()
