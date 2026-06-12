"""
Phase 3: Walk-Forward 防伪测试 (optimized)
252d train / 63d test, real 50-stock data 2018-2025
PBO < 0.3 gate — pre-computed factors, fast ICIR lookup
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
from uniquant.brain.factors.composer import FactorComposer
from uniquant.brain.factors.analyzer import FactorAnalyzer, AnalysisMode

LOGIC_FACTORS = [
    "illiq_20d", "pv_divergence_20d",
    "cs_momentum_20d", "idiosyncratic_vol_20d",
]

STOCKS = [
    "601398.SH", "601939.SH", "601288.SH", "601988.SH", "600036.SH",
    "601166.SH", "600016.SH", "600000.SH", "002142.SZ", "601318.SH",
    "600519.SH", "000858.SZ", "000568.SZ", "600809.SH", "002304.SZ",
    "600887.SH", "000333.SZ", "000651.SZ", "600690.SH", "002415.SZ",
    "600276.SH", "300760.SZ", "002007.SZ", "000538.SZ",
    "300750.SZ", "601012.SH", "300274.SZ", "600585.SH",
    "002475.SZ", "300124.SZ", "002230.SZ", "300059.SZ",
    "000002.SZ", "601668.SH", "601857.SH", "600028.SH",
    "601088.SH", "600900.SH", "601985.SH", "601899.SH",
    "600019.SH", "000831.SZ", "002460.SZ", "600111.SH",
]


def fetch_data():
    tdx = TdxSource()
    all_data = []
    for code in STOCKS:
        try:
            df = tdx.fetch_daily(code, "2018-01-01", "2025-12-31")
            if df is not None and not df.empty:
                df["code"] = code
                all_data.append(df)
        except Exception:
            pass
    result = pd.concat(all_data, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"])
    return result


def compute_window_ic(merged, factor_cols, date_mask, analyzer, holding=5):
    sub = merged[date_mask].copy()
    return analyzer.compute_ic_ir(
        sub, factor_cols=factor_cols,
        holding_periods=[holding],
        date_col="date", code_col="code", price_col="close",
        mode=AnalysisMode.BACKTEST,
    )


def extract_icir(ic_res, factor, period=5):
    if factor in ic_res and period in ic_res.get(factor, {}):
        return ic_res[factor][period].icir
    return 0.0


def extract_ic_mean(ic_res, factor, period=5):
    if factor in ic_res and period in ic_res.get(factor, {}):
        return ic_res[factor][period].ic_mean
    return 0.0


def main():
    print("=" * 60)
    print("Phase 3: Walk-Forward 滚动防伪测试")
    print("=" * 60)

    print("\n[1/4] 拉取数据并计算因子 (一次加载, 全流程复用)...")
    df = fetch_data()
    print(f"  {df['code'].nunique()} stocks, {len(df)} rows, "
          f"{df['date'].min().date()} → {df['date'].max().date()}")

    composer = FactorComposer(orthogonalize=False)
    factor_df = composer.compute_all_factors(df, mode="backtest")
    merged = pd.concat([df, factor_df], axis=1)
    factor_cols = [c for c in LOGIC_FACTORS if c in factor_df.columns]

    # Pre-compute daily z-scores for all factors (used repeatedly)
    print("  Pre-computing cross-sectional z-scores...")
    z_scores = {}
    for date, g in merged.groupby("date"):
        for fc in factor_cols:
            vals = g[fc].dropna()
            if len(vals) >= 5:
                mu, s = vals.mean(), vals.std()
                if s > 0:
                    z_scores.setdefault(date, {})[fc] = (g[fc] - mu) / s

    # Build z-score DataFrame aligned with merged index
    z_df = pd.DataFrame(index=merged.index, dtype=float)
    for date, g in merged.groupby("date"):
        zvals = z_scores.get(date, {})
        if not zvals:
            continue
        for fc in factor_cols:
            if fc in zvals:
                z_df.loc[g.index, fc] = zvals[fc].values
    z_df = z_df.fillna(0)

    # Walk-forward windows
    train_w, test_w = 252, 63
    all_dates = sorted(merged["date"].unique())
    n = len(all_dates)
    windows = []
    for start in range(train_w, n - test_w + 1, test_w):
        windows.append((
            all_dates[start - train_w], all_dates[start - 1],
            all_dates[start], all_dates[start + test_w - 1],
        ))

    print(f"\n[2/4] Walk-Forward ({len(windows)} windows, train={train_w}d, test={test_w}d)...")
    analyzer = FactorAnalyzer()
    window_results = []

    for wi, (ts, te, ss, se) in enumerate(windows):
        train_mask = (merged["date"] >= ts) & (merged["date"] <= te)
        test_mask = (merged["date"] >= ss) & (merged["date"] <= se)

        # Train weights from ICIR(5d) — with SIGN preserved
        train_ic = compute_window_ic(merged, factor_cols, train_mask, analyzer, holding=5)
        weights = {}
        signs = {}
        wsum = 0
        for fc in factor_cols:
            ir = abs(extract_icir(train_ic, fc, 5))
            ic_mean = extract_ic_mean(train_ic, fc, 5)
            weights[fc] = max(ir, 0.0)
            signs[fc] = 1.0 if ic_mean >= 0 else -1.0  # flip sign if IC is negative
            wsum += weights[fc]
        for fc in factor_cols:
            weights[fc] /= max(wsum, 1e-10)

        # Test composite = weighted z-scores with sign correction
        test_idx = merged[test_mask].index
        composite = pd.Series(
            sum(z_df.loc[test_idx, fc].values * weights[fc] * signs[fc] for fc in factor_cols),
            index=test_idx,
        )

        test_comp = merged.loc[test_idx].copy()
        test_comp["composite_score"] = composite.values

        # OOS IC
        oos_ic = analyzer.compute_ic_ir(
            test_comp, factor_cols=["composite_score"],
            holding_periods=[5],
            date_col="date", code_col="code", price_col="close",
            mode=AnalysisMode.BACKTEST,
        )
        oos_val = extract_ic_mean(oos_ic, "composite_score", 5)

        window_results.append({
            "train": (ts, te), "test": (ss, se),
            "oos_ic_5d": oos_val,
            "weights": weights,
        })
        print(f"  W{wi+1}: train={ts.date()}..{te.date()} "
              f"test={ss.date()}..{se.date()} "
              f"IC(5d)={oos_val:+.4f}  w={ {k:f'{signs[k]*v:.2f}' for k,v in weights.items()} }")

    # Aggregate
    oos_arr = np.array([w["oos_ic_5d"] for w in window_results])
    oos_mean = float(np.mean(oos_arr))
    oos_std = float(np.std(oos_arr)) if len(oos_arr) > 1 else 0
    oos_icir = oos_mean / max(oos_std, 1e-10)

    print(f"\n  OOS IC(5d) mean={oos_mean:+.4f}  std={oos_std:.4f}  ICIR={oos_icir:+.4f}")

    # PBO Monte Carlo (n=200, fast with pre-computed z-scores)
    print(f"\n[3/4] PBO Monte Carlo (n=200)...")
    n_rands = 200
    rng_mc = np.random.default_rng(42)
    nf = len(factor_cols)

    rand_oos_all = []
    for ri in range(n_rands):
        rand_w = rng_mc.dirichlet(np.ones(nf))
        rand_signs = rng_mc.choice([-1, 1], size=nf)  # random sign per factor
        rand_oos_windows = []
        for wi, (_, _, ss, se) in enumerate(windows):
            test_mask = (merged["date"] >= ss) & (merged["date"] <= se)
            test_idx = merged[test_mask].index
            comp = pd.Series(
                sum(z_df.loc[test_idx, fc].values * rand_w[fi] * rand_signs[fi] for fi, fc in enumerate(factor_cols)),
                index=test_idx,
            )
            tc = merged.loc[test_idx].copy()
            tc["cs"] = comp.values
            ric = analyzer.compute_ic_ir(
                tc, factor_cols=["cs"],
                holding_periods=[5],
                date_col="date", code_col="code", price_col="close",
                mode=AnalysisMode.BACKTEST,
            )
            rand_oos_windows.append(extract_ic_mean(ric, "cs", 5))
        rand_oos_all.append(float(np.mean(rand_oos_windows)))
        if (ri + 1) % 50 == 0:
            print(f"  PBO progress: {ri+1}/{n_rands}")

    rand_arr = np.array(rand_oos_all)
    pbo_val = float(np.mean(rand_arr >= oos_mean))

    print(f"\n  Actual OOS IC(5d): {oos_mean:+.4f}")
    print(f"  Random OOS IC: mean={float(np.mean(rand_arr)):+.4f} std={float(np.std(rand_arr)):.4f}")
    print(f"  PBO = {pbo_val:.4f}  ({'✅ PASS < 0.3' if pbo_val < 0.3 else '❌ FAIL >= 0.3'})")

    # Write report
    print(f"\n[4/4] 写入报告...")
    report_path = Path("docs/reshaping_logs/15_true_oos_validation.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 15 — 真实 Walk-Forward OOS 验证\n\n")
        f.write(f"> **生成时间**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> **数据**: {df['code'].nunique()} 只 A 股, {df['date'].min().date()} → {df['date'].max().date()}\n")
        f.write(f"> **配置**: 训练窗 {train_w}d / 测试窗 {test_w}d, {len(windows)} 个窗口\n\n")

        f.write("## OOS IC(5d) 汇总\n\n")
        f.write(f"| 指标 | 值 |\n|------|------|\n")
        f.write(f"| IC 均值 (OOS) | {oos_mean:+.4f} |\n")
        f.write(f"| IC 标准差 | {oos_std:.4f} |\n")
        f.write(f"| ICIR | {oos_icir:+.4f} |\n\n")

        f.write("## 各窗口 OOS IC\n\n")
        f.write("| 窗口 | 训练区间 | 测试区间 | OOS IC(5d) |\n")
        f.write("|------|----------|----------|------------|\n")
        for wi, w in enumerate(window_results):
            f.write(f"| {wi+1} | {w['train'][0].date()}→{w['train'][1].date()} | "
                    f"{w['test'][0].date()}→{w['test'][1].date()} | {w['oos_ic_5d']:+.4f} |\n")

        f.write("\n## PBO 评估\n\n")
        f.write(f"| 指标 | 值 |\n|------|------|\n")
        f.write(f"| 随机策略数 | {n_rands} |\n")
        f.write(f"| 实际 OOS IC | {oos_mean:+.4f} |\n")
        f.write(f"| 随机 OOS IC 均值 | {float(np.mean(rand_arr)):+.4f} |\n")
        f.write(f"| **PBO** | **{pbo_val:.4f}** |\n")
        f.write(f"| PBO < 0.3 | {'✅ 通过' if pbo_val < 0.3 else '❌ 未通过'} |\n")
        f.write(f"| OOS IC Mean > 0 | {'✅ 通过' if oos_mean > 0 else '❌ 未通过'} |\n\n")

        f.write("## 最终权重\n\n")
        last_w = window_results[-1]["weights"] if window_results else {}
        f.write("| 因子 | 权重 |\n|------|------|\n")
        for fc in factor_cols:
            f.write(f"| {fc} | {last_w.get(fc, 0):.4f} |\n")

        f.write(f"\n## 判定\n\n")
        passed = pbo_val < 0.3 and oos_mean > 0
        verdict = "**✅ 及格 — 可进入 Phase 4 风险加权组合回测**"
        if pbo_val >= 0.3:
            verdict = "**❌ PBO ≥ 0.3, 过拟合风险偏高**"
        if oos_mean <= 0:
            verdict = "**❌ OOS IC ≤ 0, 因子反向**"
        f.write(f"{verdict}\n\n---\n*报告自动生成*")

    print(f"  Report → {report_path}")
    print(f"\n{'='*60}")
    print(f"Phase 3 Verdict: {verdict}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
