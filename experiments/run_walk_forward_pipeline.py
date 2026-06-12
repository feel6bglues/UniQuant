"""
Phase 2: Walk-Forward OOS Validation (optimized)

Pre-computes factors once, then rolls windows for OOS IC evaluation.
Computes PBO and weight stability across windows.

Output: docs/reshaping_logs/10_walk_forward_results.md
"""

import os
import sys
from pathlib import Path

# Suppress noisy warnings from RegimeAnalyzer entropy computation
os.environ["PYTHONWARNINGS"] = "ignore"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uniquant.brain.factors.registry import FactorRegistry
from uniquant.brain.factors.composer import FactorComposer
from uniquant.brain.factors.analyzer import FactorAnalyzer


def generate_mock_universe(n_stocks=5, n_days=504, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start="2021-01-01", periods=n_days)
    rows = []
    for si in range(n_stocks):
        code = f"{600000 + si}.SH"
        price = 20.0 + rng.random() * 30.0
        for d in dates:
            ret = rng.normal(0.0005, 0.025)
            o = price * (1 + rng.normal(0, 0.005))
            c = o * (1 + ret)
            h = max(o, c) * 1.005
            l = min(o, c) * 0.995
            v = int(abs(rng.normal(1e6, 3e5)))
            rows.append({
                "code": code, "date": d, "open": o, "high": h, "low": l,
                "close": c, "volume": v,
            })
            price = c
    return pd.DataFrame(rows)


def main():
    print("=" * 60)
    print("Phase 2: Walk-Forward OOS Validation")
    print("=" * 60)

    df = generate_mock_universe()
    print(f"\n[1/4] Data: {df['code'].nunique()} stocks x {df['date'].nunique()} days ({len(df)} rows)")

    # Pre-compute factors once
    print("[2/4] Computing factors...")
    composer = FactorComposer(orthogonalize=False)
    factor_df = composer.compute_all_factors(df, mode="backtest")
    enabled = [f.name for f in composer.registry.get_enabled()]
    print(f"  Enabled factors ({len(enabled)}): {enabled}")

    if factor_df.empty:
        print("  No factors. Aborting.")
        return

    merged = pd.concat([df, factor_df], axis=1)
    factor_cols = list(factor_df.columns)

    # Manual walk-forward: train=252, test=63 → 4 windows
    train_w = 252
    test_w = 63
    all_dates = sorted(merged["date"].unique())
    n = len(all_dates)
    windows = []
    for start in range(train_w, n - test_w + 1, test_w):
        if start + test_w > n:
            break
        windows.append((
            all_dates[start - train_w], all_dates[start - 1],
            all_dates[start], all_dates[start + test_w - 1],
        ))

    print(f"\n[3/4] Walk-forward: {len(windows)} windows (train={train_w}d, test={test_w}d)")
    analyzer = FactorAnalyzer()

    window_ic_means = []
    window_weights_list = []
    weight_stability = {c: [] for c in factor_cols}

    for wi, (ts, te, ss, se) in enumerate(windows):
        train = merged[(merged["date"] >= ts) & (merged["date"] <= te)].copy()
        test = merged[(merged["date"] >= ss) & (merged["date"] <= se)].copy()

        # Train: compute IC + weights
        ic_res = analyzer.compute_ic_ir(
            train, factor_cols=factor_cols,
            holding_periods=[5], date_col="date", code_col="code", price_col="close",
        )
        wsum = 0
        weights = {}
        for fc in factor_cols:
            ir = 0
            if fc in ic_res and 5 in ic_res[fc]:
                ir = abs(ic_res[fc][5].icir)
            weights[fc] = max(ir, 0.01)
            wsum += weights[fc]
        for fc in factor_cols:
            weights[fc] /= wsum
            weight_stability[fc].append(weights[fc])
        window_weights_list.append(weights)

        # Test: compute composite OOS IC
        test_factor_values = test[factor_cols]
        composite = pd.Series(0.0, index=test.index, dtype=float)
        for fc in factor_cols:
            z = (test_factor_values[fc] - test_factor_values[fc].mean()) / max(test_factor_values[fc].std(), 1e-10)
            composite += z.fillna(0) * weights[fc]

        test_with_comp = test.copy()
        test_with_comp["composite_score"] = composite

        oos_ic = analyzer.compute_ic_ir(
            test_with_comp, factor_cols=["composite_score"],
            holding_periods=[5], date_col="date", code_col="code", price_col="close",
        )
        oos_val = 0
        if "composite_score" in oos_ic and 5 in oos_ic["composite_score"]:
            oos_val = oos_ic["composite_score"][5].ic_mean

        window_ic_means.append(oos_val)
        print(f"  Window {wi+1}: train={ts.date()}..{te.date()} test={ss.date()}..{se.date()}  OOS IC={oos_val:+.4f}")

    if not window_ic_means:
        print("  No valid windows. Aborting.")
        return

    # Aggregate
    oos_arr = np.array(window_ic_means)
    oos_mean = float(np.mean(oos_arr)) if len(oos_arr) > 0 else 0
    oos_std = float(np.std(oos_arr)) if len(oos_arr) > 1 else 0
    oos_icir = oos_mean / oos_std if oos_std > 0 else 0

    print(f"\n  OOS IC Mean: {oos_mean:+.4f}")
    print(f"  OOS IC Std:  {oos_std:.4f}")
    print(f"  OOS ICIR:    {oos_icir:+.4f}")

    # PBO via Monte Carlo: generate random factor combos and rank actual strategy
    print("\n[4/4] Computing PBO (Monte Carlo rank method)...")

    n_rands = 200
    n_factors = len(factor_cols)
    rng_mc = np.random.default_rng(42)

    all_rand_oos = []
    for ri in range(n_rands):
        rand_w = rng_mc.dirichlet(np.ones(n_factors))
        win_oos = []
        for wi, (ts, te, ss, se) in enumerate(windows):
            train = merged[(merged["date"] >= ts) & (merged["date"] <= te)].copy()
            test = merged[(merged["date"] >= ss) & (merged["date"] <= se)].copy()
            test_fv = test[factor_cols]
            comp = pd.Series(0.0, index=test.index, dtype=float)
            for fi, fc in enumerate(factor_cols):
                z = (test_fv[fc] - test_fv[fc].mean()) / max(test_fv[fc].std(), 1e-10)
                comp += z.fillna(0) * rand_w[fi]
            twc = test.copy()
            twc["comp"] = comp
            ric = analyzer.compute_ic_ir(
                twc, factor_cols=["comp"],
                holding_periods=[5], date_col="date", code_col="code", price_col="close",
            )
            v = 0
            if "comp" in ric and 5 in ric["comp"]:
                v = ric["comp"][5].ic_mean
            win_oos.append(v)
        all_rand_oos.append(float(np.mean(win_oos)) if win_oos else 0)

    actual_mean_oos = float(np.mean(oos_arr))
    pbo_val = float(np.mean([1 for r in all_rand_oos if r >= actual_mean_oos]))
    print(f"  Actual mean OOS IC: {actual_mean_oos:+.4f}")
    print(f"  Random strategies (n={n_rands}): mean OOS IC = {float(np.mean(all_rand_oos)):+.4f}")
    print(f"  PBO (fraction of random strategies better than actual): {pbo_val:.3f}")
    print(f"  Is overfit: {'YES' if pbo_val > 0.3 else 'NO (pbo <= 0.3 threshold)'}")

    # Weight stability
    ws_std = {c: float(np.std(v)) for c, v in weight_stability.items() if len(v) > 1}
    final_weights = window_weights_list[-1] if window_weights_list else {}

    # --- Write report ---
    report_path = Path("docs/reshaping_logs/10_walk_forward_results.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 10 Walk-Forward OOS Validation Results\n\n")
        f.write(f"生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("## 配置\n\n")
        f.write(f"- 训练窗口: {train_w}d, 测试窗口: {test_w}d\n")
        f.write(f"- 窗口数: {len(windows)}\n")
        f.write(f"- 因子: {len(enabled)} survivors\n\n")

        f.write("## OOS IC 汇总\n\n")
        f.write("| Metric | Value |\n|--------|-------|\n")
        f.write(f"| OOS IC Mean | {oos_mean:+.4f} |\n")
        f.write(f"| OOS IC Std | {oos_std:.4f} |\n")
        f.write(f"| OOS ICIR | {oos_icir:+.4f} |\n\n")

        f.write("## PBO (Monte Carlo)\n\n")
        f.write("| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Actual OOS IC | {actual_mean_oos:+.4f} |\n")
        f.write(f"| Random OOS IC (mean) | {float(np.mean(all_rand_oos)):+.4f} |\n")
        f.write(f"| PBO | {pbo_val:.3f} |\n")
        f.write(f"| Overfit | {'YES' if pbo_val > 0.3 else 'No'} |\n\n")

        f.write("## 各窗口 OOS IC\n\n")
        for i, (val, (ts, te, ss, se)) in enumerate(zip(window_ic_means, windows)):
            f.write(f"- Window {i+1}: train={ts.date()}..{te.date()} test={ss.date()}..{se.date()} → OOS IC={val:+.4f}\n")

        f.write("\n## 最终权重\n\n")
        f.write("| Factor | Final Weight | Std Across Windows |\n|--------|-------------|-------------------|\n")
        for fc in factor_cols:
            w = final_weights.get(fc, 0)
            s = ws_std.get(fc, 0)
            f.write(f"| {fc} | {w:.4f} | {s:.4f} |\n")

        f.write("\n## 存活因子 (传递至 Phase 3)\n\n")
        for s in enabled:
            f.write(f"- `{s}`\n")

    print(f"\n  Report → {report_path}")
    print("\n✅ Phase 2 complete.")


if __name__ == "__main__":
    main()
