#!/usr/bin/env python3
"""V3: X4 单窗显著性多重检验审计。

对 X4 窗 (2025-06-30) BUY 集动量残差显著性做：
  A. 多重检验校正（主判定）：收集 5 窗 × (M2 + R3) = 10 p 值，对 X4 R3 做 Bonferroni/Holm/BH
  B. regime 子时段分拆：relmom 5 分位桶内 BUY 增量符号
  C. 稳健性：relmom^3 拟合 + 绝对右尾剔除

判定（预注册）：
  V3 PASS(维持候选) ⇔ 校正后 X4 R3 不再显著 (Bonferroni p≥0.05)
    或 子时段/稳健性显示为动量驱动
  V3 UPGRADE(需复验) ⇔ Bonferroni 校正后仍显著
    且 非单一 relmom 桶驱动 且 剔除右尾后仍显著
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "wyckoff_deep_verify"))

from _common import WINDOWS, BUY_DIRECTIONS, load_window, write_out  # noqa: E402
from wyckoff_experiments.momentum_residual_analysis import (  # noqa: E402
    load_cache,
    load_index,
    relmom_for,
)


CONF_GATE = 0.40
WINDOW_NAMES = list(WINDOWS.keys())


def buyset_mask(df: pd.DataFrame) -> pd.Series:
    direction = df["trading_plan_direction"].fillna("空仓观望")
    conf = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
    return direction.isin(BUY_DIRECTIONS) & (conf >= CONF_GATE)


def _ols_resid_for(
    df: pd.DataFrame, mask: pd.Series, degree: int = 2
) -> tuple[float, float, int]:
    d = df[["fwd_20d", "relmom"]].dropna().copy()
    if len(d) < 30:
        return np.nan, np.nan, 0
    terms = [np.ones(len(d))]
    for deg in range(1, degree + 1):
        terms.append(d["relmom"] ** deg)
    x = np.column_stack(terms).astype(float)
    y = d["fwd_20d"].astype(float).to_numpy()
    try:
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        resid = y - x @ beta
        resid_by_sym = dict(zip(d.index.tolist(), resid))
        sig_idx = [i for i in df.index[mask] if i in resid_by_sym]
        resid_sig = np.array([resid_by_sym[i] for i in sig_idx])
        resid_all = np.array([r for r in resid_by_sym.values()])
        if len(resid_sig) > 5:
            _, p = mannwhitneyu(resid_sig, resid_all, alternative="two-sided")
            return float(resid_sig.mean()), float(p), len(resid_sig)
    except Exception:
        pass
    return np.nan, np.nan, 0


def _holm_correction(p_values: list[float]) -> list[float]:
    m = len(p_values)
    sorted_idx = np.argsort(p_values)
    sorted_p = np.array(p_values)[sorted_idx]
    holm = np.ones(m)
    for i, idx in enumerate(sorted_idx):
        holm[idx] = min(sorted_p[i] * (m - i), 1.0)
    for i in range(1, m):
        if holm[sorted_idx[i]] < holm[sorted_idx[i - 1]]:
            holm[sorted_idx[i]] = holm[sorted_idx[i - 1]]
    return holm.tolist()


def _bh_correction(p_values: list[float]) -> list[float]:
    m = len(p_values)
    sorted_idx = np.argsort(p_values)
    sorted_p = np.array(p_values)[sorted_idx]
    bh = np.ones(m)
    for i, idx in enumerate(sorted_idx):
        bh[idx] = min(sorted_p[i] * m / (i + 1), 1.0)
    # enforce monotonicity
    for i in range(m - 2, -1, -1):
        bh[sorted_idx[i]] = min(bh[sorted_idx[i]], bh[sorted_idx[i + 1]])
    return bh.tolist()


def _clean(x):
    if isinstance(x, (np.floating, float)):
        return float(x)
    if isinstance(x, (np.integer, int)):
        return int(x)
    if isinstance(x, list):
        return [_clean(i) for i in x]
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    return x


def main() -> int:
    idx = load_index()
    cache = load_cache()
    print(f"缓存股票数: {len(cache)}", file=sys.stderr)

    # --- Step 1: compute p-values for all 5 windows (M2 + R3) ---
    family: dict[str, dict] = {}
    all_p_values: list[float] = []
    p_labels: list[str] = []

    for nm in WINDOW_NAMES:
        asof = pd.Timestamp(WINDOWS[nm][1])
        df = load_window(nm)
        df["fwd_20d"] = df["fwd_20d"].astype(float)
        print(f"  [{nm}] computing relmom for {len(df)} symbols...", file=sys.stderr)
        df["relmom"] = [relmom_for(s, cache, asof, idx) for s in df["symbol"]]
        df = df[df["relmom"].notna()].copy()

        buy = buyset_mask(df)
        m2mean, m2p, m2n = _ols_resid_for(df, buy, degree=2)

        th = df["relmom"].quantile(0.90)
        trimmed = df[df["relmom"] <= th].copy()
        buy_t = buyset_mask(trimmed)
        r3mean, r3p, r3n = _ols_resid_for(trimmed, buy_t, degree=2)

        family[nm] = {
            "as_of": WINDOWS[nm][1],
            "n": len(df),
            "n_buy": int(buy.sum()),
            "m2_resid_mean": m2mean,
            "m2_p": m2p,
            "m2_n": m2n,
            "r3_trim_P90_resid_mean": r3mean,
            "r3_p": r3p,
            "r3_n": r3n,
        }
        if m2p is not None and not np.isnan(m2p):
            all_p_values.append(m2p)
            p_labels.append(f"{nm}_M2")
        if r3p is not None and not np.isnan(r3p):
            all_p_values.append(r3p)
            p_labels.append(f"{nm}_R3")

    print(f"\n多重检验族: {len(all_p_values)} p-values", file=sys.stderr)
    for lbl, pv in zip(p_labels, all_p_values):
        print(f"  {lbl}: p={pv:.6f}", file=sys.stderr)

    # --- Step 2: Multiple testing correction for X4 R3 ---
    x4_r3_idx = None
    for i, lbl in enumerate(p_labels):
        if lbl == "X4_R3":
            x4_r3_idx = i
            break

    raw_p = all_p_values[x4_r3_idx] if x4_r3_idx is not None else np.nan
    m = len(all_p_values)

    if x4_r3_idx is not None and m > 0:
        bonf = min(raw_p * m, 1.0)
        holm_all = _holm_correction(all_p_values)
        bh_all = _bh_correction(all_p_values)
        holm = holm_all[x4_r3_idx]
        bh = bh_all[x4_r3_idx]
    else:
        bonf = holm = bh = np.nan

    correction = {
        "family_size": m,
        "p_labels": p_labels,
        "all_p_values": [round(v, 6) for v in all_p_values],
        "x4_r3_raw_p": round(raw_p, 6) if not np.isnan(raw_p) else None,
        "bonferroni_adj_p": round(bonf, 6) if not np.isnan(bonf) else None,
        "holm_adj_p": round(holm, 6) if not np.isnan(holm) else None,
        "bh_q": round(bh, 6) if not np.isnan(bh) else None,
        "bonferroni_significant": bool(bonf < 0.05) if not np.isnan(bonf) else None,
        "holm_significant": bool(holm < 0.05) if not np.isnan(holm) else None,
        "bh_significant": bool(bh < 0.05) if not np.isnan(bh) else None,
    }

    # --- Step 3: Regime sub-period (relmom quintile bucket analysis) ---
    x4_df = load_window("X4")
    x4_asof = pd.Timestamp(WINDOWS["X4"][1])
    x4_df["fwd_20d"] = x4_df["fwd_20d"].astype(float)
    x4_df["relmom"] = [relmom_for(s, cache, x4_asof, idx) for s in x4_df["symbol"]]
    x4_df = x4_df[x4_df["relmom"].notna()].copy()
    x4_buy = buyset_mask(x4_df)

    x4_df["q5"] = pd.qcut(x4_df["relmom"], 5, labels=False, duplicates="drop")
    quintile_rows = []
    for q in sorted(x4_df["q5"].unique()):
        g = x4_df[x4_df["q5"] == q]
        s = g[x4_buy.loc[g.index]]
        if len(s) < 5 or len(g) - len(s) < 5:
            continue
        other = g[~x4_buy.loc[g.index]]
        buy_mean = s["fwd_20d"].mean()
        other_mean = other["fwd_20d"].mean()
        effect = buy_mean - other_mean
        _, p_eff = mannwhitneyu(
            s["fwd_20d"].values, other["fwd_20d"].values, alternative="two-sided"
        )
        quintile_rows.append({
            "quintile": int(q),
            "relmom_range": (
                f"{g['relmom'].min():.2f} to {g['relmom'].max():.2f}"
            ),
            "n_buy": int(len(s)),
            "n_other": int(len(g) - len(s)),
            "buy_mean_fwd_20d": round(float(buy_mean), 4),
            "other_mean_fwd_20d": round(float(other_mean), 4),
            "buy_vs_other_effect": round(float(effect), 4),
            "mwu_p": round(float(p_eff), 6),
        })

    # determine if single bucket drives the overall effect
    overall_buy_mean = x4_df.loc[x4_buy, "fwd_20d"].mean()
    overall_other_mean = x4_df.loc[~x4_buy, "fwd_20d"].mean()
    overall_effect = overall_buy_mean - overall_other_mean
    dominant_bucket = None
    for r in quintile_rows:
        if r["n_buy"] >= 10 and abs(r["buy_vs_other_effect"]) > abs(overall_effect) * 1.5:
            dominant_bucket = r
            break

    # --- Step 4: Robustness checks on X4 ---
    # R3c: cubic term (relmom^3)
    r3c_mean, r3c_p, r3c_n = _ols_resid_for(x4_df, x4_buy, degree=3)

    # R3t: trim |fwd_20d| > P95 before running R3
    fwd_p95 = x4_df["fwd_20d"].abs().quantile(0.95)
    trim_tail = x4_df[x4_df["fwd_20d"].abs() <= fwd_p95].copy()
    # then apply R3 (trim relmom > P90) on top
    relmom_p90_tail = trim_tail["relmom"].quantile(0.90)
    trim_both = trim_tail[trim_tail["relmom"] <= relmom_p90_tail].copy()
    buy_both = buyset_mask(trim_both)
    r3t_mean, r3t_p, r3t_n = _ols_resid_for(trim_both, buy_both, degree=2)

    robustness = {
        "r3c_cubic_resid_mean": round(float(r3c_mean), 4) if not np.isnan(r3c_mean) else None,
        "r3c_p": round(float(r3c_p), 6) if r3c_p is not None else None,
        "r3c_n": r3c_n,
        "r3t_trim_abs_fwd_P95_P90_resid_mean": round(float(r3t_mean), 4) if not np.isnan(r3t_mean) else None,
        "r3t_p": round(float(r3t_p), 6) if r3t_p is not None else None,
        "r3t_n": r3t_n,
        "abs_fwd_p95_threshold": round(float(fwd_p95), 4),
    }

    # --- Step 5: Verdict ---
    bonf_sig = correction["bonferroni_significant"]
    single_bucket = dominant_bucket is not None
    robust_after_tail = (
        robustness["r3t_p"] is not None
        and robustness["r3t_p"] < 0.05
        and (robustness["r3t_trim_abs_fwd_P95_P90_resid_mean"] or 0) > 0
    )

    # Pre-registered rules:
    # V3 PASS ⇔ Bonferroni p ≥ 0.05 OR sub-period/robustness shows momentum-driven
    # V3 UPGRADE ⇔ Bonferroni p < 0.05 AND not single-bucket AND robust after tail removal
    momentum_driven = single_bucket or (robustness["r3t_p"] is not None and robustness["r3t_p"] >= 0.05)

    if not bonf_sig or momentum_driven:
        verdict = "V3 PASS (维持候选)"
        verdict_detail = (
            "Bonferroni 校正后不再显著 或 子时段/稳健性显示为动量驱动"
            if not bonf_sig
            else "Bonferroni 显著但子时段/稳健性显示为动量驱动"
        )
    else:
        # Check UPGRADE conditions
        if not single_bucket and robust_after_tail:
            verdict = "V3 UPGRADE (需复验)"
            verdict_detail = "Bonferroni 校正后仍显著, 非单一 relmom 桶驱动, 且剔除右尾后仍显著"
        else:
            verdict = "V3 PASS (维持候选)"
            verdict_detail = "Bonferroni 显著但不满足全部 UPGRADE 条件"

    payload = {
        "meta": {
            "script": "v3_x4_multitest.py",
            "description": "X4 单窗显著性多重检验审计",
            "windows": WINDOW_NAMES,
            "family": "5 窗 × (M2 + R3) = 最多 10 p 值",
            "pre_registered_rules": {
                "V3_PASS": "Bonferroni 校正后 p≥0.05 或 子时段/稳健性显示为动量驱动",
                "V3_UPGRADE": "Bonferroni 校正后仍显著 且 非单一 relmom 桶驱动 且 剔除右尾后仍显著",
            },
        },
        "family_p_values": {
            "note": "所有 5 窗的 M2 和 R3 p 值（双侧 MWU）",
            "windows": family,
            "p_label_order": p_labels,
            "p_values": [round(v, 6) for v in all_p_values],
        },
        "section_A_multitest_correction": correction,
        "section_B_quintile_analysis": {
            "overall_buy_mean_fwd_20d": round(float(overall_buy_mean), 4),
            "overall_other_mean_fwd_20d": round(float(overall_other_mean), 4),
            "overall_buy_vs_other_effect": round(float(overall_effect), 4),
            "dominant_bucket": dominant_bucket,
            "quintiles": quintile_rows,
        },
        "section_C_robustness": robustness,
        "verdict": {
            "verdict": verdict,
            "detail": verdict_detail,
            "bonferroni_significant_at_0.05": bonf_sig,
            "single_bucket_driven": single_bucket,
            "robust_after_tail_removal": robust_after_tail,
        },
    }

    payload = _clean(payload)
    path = write_out("v3_x4_multitest", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nWritten to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())