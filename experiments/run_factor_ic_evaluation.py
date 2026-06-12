"""
Phase 1: Factor Pool IC/IR Evaluation & Collinearity Pruning

Computes Rank IC@5d and IC@20d for all registered factors,
builds a Spearman correlation matrix, and applies |r| > 0.75 pruning.

Output: docs/reshaping_logs/09_factor_purge.md
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uniquant.brain.factors.registry import FactorRegistry
from uniquant.brain.factors.analyzer import FactorAnalyzer


def generate_mock_universe(
    n_stocks: int = 20, n_days: int = 252, seed: int = 42
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start="2022-01-01", periods=n_days)
    rows = []
    for si in range(n_stocks):
        code = f"{600000 + si}.SH"
        price = 20.0 + rng.random() * 30.0
        for d in dates:
            ret = rng.normal(0.0005, 0.025)
            o = price * (1 + rng.normal(0, 0.005))
            c = o * (1 + ret)
            h = max(o, c) * (1 + abs(rng.normal(0, 0.003)))
            l = min(o, c) * (1 - abs(rng.normal(0, 0.003)))
            v = int(abs(rng.normal(1e6, 3e5)))
            rows.append({
                "code": code, "date": d, "open": o, "high": h, "low": l,
                "close": c, "volume": v, "pre_close": price,
            })
            price = c
    df = pd.DataFrame(rows)
    df["avg_daily_volume"] = df.groupby("code")["volume"].transform(
        lambda x: x.rolling(20).mean()
    ).fillna(df["volume"])
    return df


def main():
    print("=" * 60)
    print("Phase 1: Factor Pool IC/IR Evaluation & Collinearity Pruning")
    print("=" * 60)

    df = generate_mock_universe(n_stocks=20, n_days=252)
    print(f"\n[1/3] Mock universe: {df['code'].nunique()} stocks x {df['date'].nunique()} days ({len(df)} rows)")

    from uniquant.brain.factors.composer import FactorComposer
    composer = FactorComposer(orthogonalize=False)
    factor_df = composer.compute_all_factors(df, mode="backtest")
    print(f"\n[2/3] Computed {len(factor_df.columns)} factors: {list(factor_df.columns)}")

    merged = pd.concat([df, factor_df], axis=1)
    factor_cols = list(factor_df.columns)

    analyzer = FactorAnalyzer()
    results = analyzer.compute_ic_ir(
        merged, factor_cols=factor_cols,
        holding_periods=[5, 20],
        date_col="date", code_col="code", price_col="close",
    )

    # Build report table
    rows_rpt = []
    for fname, period_results in results.items():
        for period, r in period_results.items():
            rows_rpt.append({
                "factor": fname, "period": f"IC@{period}d",
                "ic_mean": r.ic_mean, "ic_std": r.ic_std,
                "icir": r.icir, "ic_pos": r.ic_positive_ratio,
            })
    ic_df = pd.DataFrame(rows_rpt)
    print(f"\n  Evaluated {ic_df['factor'].nunique()} factors")

    for period in ["IC@5d", "IC@20d"]:
        subset = ic_df[ic_df["period"] == period].sort_values("icir", key=abs, ascending=False)
        print(f"\n  --- {period} ---")
        for _, row in subset.iterrows():
            print(f"    {row['factor']:30s}  IC={row['ic_mean']:+.4f}  IR={row['icir']:+.4f}")

    # Correlation + pruning
    print("\n[3/3] Collinearity pruning (|r| > 0.75)...")
    corr_df = factor_df[factor_cols].corr(method="spearman")

    best_icir = {}
    for fname, periods in results.items():
        vals = [abs(r.icir) for r in periods.values()]
        best_icir[fname] = max(vals) if vals else 0.0

    survivors = list(factor_cols)
    discarded = []
    for i in range(len(factor_cols)):
        for j in range(i + 1, len(factor_cols)):
            a, b = factor_cols[i], factor_cols[j]
            if a not in survivors or b not in survivors:
                continue
            r_val = corr_df.loc[a, b]
            if abs(r_val) > 0.75:
                if best_icir.get(a, 0) >= best_icir.get(b, 0):
                    if b in survivors:
                        survivors.remove(b)
                        discarded.append(b)
                else:
                    if a in survivors:
                        survivors.remove(a)
                        discarded.append(a)

    print(f"\n  Survivors ({len(survivors)}): {survivors}")
    print(f"  Discarded ({len(discarded)}): {discarded}")

    # Disable discarded factors in registry
    for name in discarded:
        FactorRegistry.disable(name)
        print(f"    DISABLED: {name}")

    # --- Write report ---
    report_path = Path("docs/reshaping_logs/09_factor_purge.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 09 Factor Purge Report\n\n")
        f.write(f"生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("## 数据源\n\n")
        f.write(f"- Mock 股票池: {df['code'].nunique()} 只, {df['date'].nunique()} 个交易日\n")
        f.write(f"- 持有期: 5d / 20d\n")
        f.write(f"- 相关系数阈值: |r| > 0.75 的因子簇只保留 IC/IR 最高者\n\n")

        f.write("## 因子 IC/IR 明细\n\n")
        f.write("| Factor | Period | IC Mean | ICIR | IC>0 Ratio |\n")
        f.write("|--------|--------|--------|------|------------|\n")
        for _, row in ic_df.sort_values(["factor", "period"]).iterrows():
            f.write(f"| {row['factor']} | {row['period']} | {row['ic_mean']:+.4f} | {row['icir']:+.4f} | {row['ic_pos']:.1%} |\n")

        f.write("\n## 共线性剔除结果\n\n")
        f.write(f"- 阈值: |r| > 0.75\n")
        f.write(f"- 存活因子数: {len(survivors)}\n")
        f.write(f"- 剔除因子数: {len(discarded)}\n")

        if discarded:
            f.write("\n### 已剔除因子\n\n")
            for d in discarded:
                f.write(f"- `{d}`\n")

        f.write("\n### 存活因子清单\n\n")
        for s in survivors:
            f.write(f"- `{s}`\n")

        f.write("\n## IC/IR 排行榜\n\n")
        for period in ["IC@5d", "IC@20d"]:
            subset = ic_df[ic_df["period"] == period].sort_values("icir", key=abs, ascending=False)
            f.write(f"### {period}\n\n")
            f.write("| Rank | Factor | IC Mean | ICIR |\n")
            f.write("|------|--------|---------|------|\n")
            for rank, (_, row) in enumerate(subset.iterrows(), 1):
                f.write(f"| {rank} | {row['factor']} | {row['ic_mean']:+.4f} | {row['icir']:+.4f} |\n")
            f.write("\n")

        f.write("\n## 共线性矩阵\n\n")
        f.write(f"```\n{corr_df.to_string()}\n```\n")

    print(f"\n  Report → {report_path}")
    print("\n✅ Phase 1 complete. Survivors written to registry.")


if __name__ == "__main__":
    main()
