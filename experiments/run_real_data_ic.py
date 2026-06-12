"""
Phase 2: 真实环境 IC/IR 体检
拉取 50 只活跃 A 股 2018-2025 日线数据, 计算 4 个逻辑因子的 IC/ICIR/相关性
"""

import os
import sys
from pathlib import Path
os.environ["PYTHONWARNINGS"] = "ignore"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uniquant.data.sources.tdx import TdxSource
from uniquant.brain.factors.registry import FactorRegistry
from uniquant.brain.factors.composer import FactorComposer
from uniquant.brain.factors.analyzer import FactorAnalyzer, AnalysisMode

LOGIC_FACTORS = [
    "illiq_20d",
    "pv_divergence_20d",
    "cs_momentum_20d",
    "idiosyncratic_vol_20d",
]

STOCKS = [
    # 银行保险
    "601398.SH", "601939.SH", "601288.SH", "601988.SH", "600036.SH",
    "601166.SH", "600016.SH", "600000.SH", "002142.SZ", "601318.SH",
    # 消费白酒
    "600519.SH", "000858.SZ", "000568.SZ", "600809.SH", "002304.SZ",
    "600887.SH", "000333.SZ", "000651.SZ", "600690.SH", "002415.SZ",
    # 医药
    "600276.SH", "300760.SZ", "002007.SZ", "000538.SZ", "300122.SZ",
    # 新能源/制造
    "300750.SZ", "601012.SH", "300274.SZ", "600585.SH", "600031.SH",
    # 科技
    "002475.SZ", "300124.SZ", "002230.SZ", "300059.SZ", "002916.SZ",
    # 地产/建筑
    "000002.SZ", "001979.SZ", "600048.SH", "601668.SH", "600895.SH",
    # 能源/公用
    "601857.SH", "600028.SH", "601088.SH", "600900.SH", "601985.SH",
    # 有色/钢铁
    "601899.SH", "600019.SH", "000831.SZ", "002460.SZ", "600111.SH",
]


def fetch_all_stock_data(tdx, start="2018-01-01", end="2025-12-31"):
    all_data = []
    failed = []
    for code in STOCKS:
        try:
            df = tdx.fetch_daily(code, start, end)
            if df is not None and not df.empty:
                df["code"] = code
                all_data.append(df)
            else:
                failed.append(code)
        except Exception as e:
            failed.append(f"{code} ({e})")
    if not all_data:
        print("No data fetched from any source. Aborting.")
        sys.exit(1)
    result = pd.concat(all_data, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"])
    print(f"  Fetched {result['code'].nunique()} stocks, {len(failed)} failed")
    if failed:
        print(f"  Failed: {failed[:5]}...")
    print(f"  Rows: {len(result)}, dates: {result['date'].min().date()} to {result['date'].max().date()}")
    return result


def compute_factor_ic(merged, factor_cols):
    analyzer = FactorAnalyzer()
    ic_results = analyzer.compute_ic_ir(
        merged,
        factor_cols=factor_cols,
        holding_periods=[1, 5, 20],
        date_col="date",
        code_col="code",
        price_col="close",
        mode=AnalysisMode.BACKTEST,
    )
    rows = []
    for fname in factor_cols:
        if fname not in ic_results:
            continue
        for period, res in ic_results[fname].items():
            rows.append({
                "factor": fname,
                "period": period,
                "ic_mean": res.ic_mean,
                "ic_std": res.ic_std,
                "icir": res.icir,
                "ic_pos_ratio": res.ic_positive_ratio,
                "t_stat": res.ic_t_stat,
                "n_periods": res.n_periods,
            })
    return pd.DataFrame(rows)


def compute_factor_correlations(merged, factor_cols):
    date_groups = merged.groupby("date")
    corr_list = []
    for date, group in date_groups:
        fv = group[factor_cols].dropna()
        if len(fv) >= 10:
            corr_list.append(fv.rank().corr(method="pearson").values)
    if not corr_list:
        return pd.DataFrame(index=factor_cols, columns=factor_cols, dtype=float)
    avg_corr = np.nanmean(corr_list, axis=0)
    return pd.DataFrame(avg_corr, index=factor_cols, columns=factor_cols)


def main():
    print("=" * 60)
    print("Phase 2: 真实环境 IC/IR 体检")
    print("=" * 60)

    # Step 1: Fetch real data
    print("\n[1/4] 拉取真实 A 股数据...")
    tdx = TdxSource()
    df = fetch_all_stock_data(tdx)

    # Step 2: Compute factors
    print("\n[2/4] 计算 4 个逻辑因子...")
    composer = FactorComposer(orthogonalize=False)
    factor_df = composer.compute_all_factors(df, mode="backtest")
    merged = pd.concat([df, factor_df], axis=1)
    factor_cols = [c for c in LOGIC_FACTORS if c in factor_df.columns]
    print(f"  Computed factors: {factor_cols}")

    if not factor_cols:
        print("  No factors computed. Aborting.")
        return

    # Step 3: Compute IC/IR
    print("\n[3/4] 计算 IC/ICIR (持有期 1/5/20 天)...")
    ic_df = compute_factor_ic(merged, factor_cols)

    print(f"\n  {'Factor':25s} {'Period':>6s} {'IC Mean':>10s} {'ICIR':>10s} {'IC>0%':>8s}")
    print("  " + "-" * 65)
    for _, row in ic_df.iterrows():
        print(f"  {row['factor']:25s} {row['period']:>6d}d {row['ic_mean']:>+10.4f} {row['icir']:>+10.4f} {row['ic_pos_ratio']:>7.1%}")

    best_icirs = ic_df.groupby("factor")["icir"].apply(lambda x: x.abs().max())
    print(f"\n  Best |ICIR| per factor:")
    for fname in factor_cols:
        val = best_icirs.get(fname, 0)
        marker = "✅" if abs(val) > 0.5 else "⚠️"
        print(f"    {marker} {fname}: best |ICIR| = {val:+.4f}")

    # Step 4: Factor correlation (orthogonality check)
    print("\n[4/4] 计算因子横截面 Spearman 相关性 (平均)...")
    corr_mat = compute_factor_correlations(merged, factor_cols)
    if not corr_mat.empty:
        print(f"\n  平均横截面 Spearman 相关性矩阵:\n")
        print(f"  {'':20s}", end="")
        for c in factor_cols:
            print(f"{c:>22s}", end="")
        print()
        for r in factor_cols:
            print(f"  {r:20s}", end="")
            for c in factor_cols:
                v = corr_mat.loc[r, c]
                print(f"{v:>22.4f}", end="")
            print()

        # Check for highly correlated pairs
        mask = np.triu(np.ones(len(factor_cols), dtype=bool), k=1)
        high_corr = []
        for i, r in enumerate(factor_cols):
            for j, c in enumerate(factor_cols):
                if j > i:
                    val = abs(corr_mat.loc[r, c])
                    if val > 0.5:
                        high_corr.append((r, c, val))
        if high_corr:
            print(f"\n  ⚠️ 高相关性 (|ρ|>0.5) 因子对:")
            for r, c, v in high_corr:
                print(f"    {r} x {c}: ρ={v:.4f}")
        else:
            print(f"\n  ✅ 所有因子间 |ρ|<0.5, 正交性良好")

    # Write report
    report_path = Path("docs/reshaping_logs/14_real_world_ic.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 14 — 真实环境 IC/IR 报告\n\n")
        f.write(f"> **生成时间**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **数据源**: TDX (通达信本地数据)\n")
        f.write(f"> **股票池**: {len(STOCKS)} 只活跃 A 股\n")
        f.write(f"> **时间范围**: {df['date'].min().date()} 至 {df['date'].max().date()}\n")
        f.write(f"> **数据行数**: {len(df)}\n\n")

        f.write("## IC/ICIR 明细\n\n")
        f.write("| 因子 | 持有期 | IC 均值 | IC 标准差 | ICIR | IC>0 比例 | t 统计量 |\n")
        f.write("|------|--------|---------|----------|------|-----------|---------|\n")
        for _, row in ic_df.iterrows():
            f.write(f"| {row['factor']} | {row['period']}d | {row['ic_mean']:+.4f} | {row['ic_std']:.4f} | {row['icir']:+.4f} | {row['ic_pos_ratio']:.1%} | {row['t_stat']:.2f} |\n")

        f.write("\n## 最佳 ICIR 汇总\n\n")
        f.write("| 因子 | 最佳 |ICIR| | 目标 ICIR>0.5 |\n")
        f.write("|------|------|----------------|\n")
        for fname in factor_cols:
            val = best_icirs.get(fname, 0)
            mark = "✅" if abs(val) > 0.5 else "❌"
            f.write(f"| {fname} | {val:+.4f} | {mark} |\n")

        if not corr_mat.empty:
            f.write("\n## 因子相关性矩阵 (平均横截面 Spearman)\n\n")
            f.write(f"| {'':20s} |")
            for c in factor_cols:
                f.write(f" {c:>20s} |")
            f.write("\n|" + "-" * 22 + "|")
            for _ in factor_cols:
                f.write("-" * 22 + "|")
            f.write("\n")
            for r in factor_cols:
                f.write(f"| {r:20s} |")
                for c in factor_cols:
                    v = corr_mat.loc[r, c]
                    f.write(f" {v:>+20.4f} |")
                f.write("\n")

            f.write("\n## 正交性评估\n\n")
            if high_corr:
                f.write("⚠️ 存在高相关性因子对:\n")
                for r, c, v in high_corr:
                    f.write(f"- {r} × {c}: ρ={v:.4f}\n")
            else:
                f.write("✅ 所有因子间 |ρ|<0.5, 正交性良好, 提供不同来源的 Alpha\n\n")

        f.write("\n---\n")
        f.write("*报告自动生成, 用于阶段 3 Walk-Forward 验证前检*")

    print(f"\n  Report → {report_path}")
    print("\n✅ Phase 2 complete.")


if __name__ == "__main__":
    main()
