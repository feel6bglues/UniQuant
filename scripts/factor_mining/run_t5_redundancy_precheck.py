"""T5 — P14 因子冗余预检 + 覆盖率披露 (真实数据)。

目标:
  1. 冗余预检: fcf_yield vs cfp_ttm 截面 spearman (>0.9 → fcf_yield 记非独立增量)
  2. 选择性披露: cash_ratio (净利>0 过滤) 截面覆盖率; real_dy 覆盖率

用法:
    python3 scripts/factor_mining/run_t5_redundancy_precheck.py --smoke
    python3 scripts/factor_mining/run_t5_redundancy_precheck.py          # sample 500
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

from scripts.factor_mining.data_loader import (  # noqa: E402
    EXTRA_FINANCIAL_FIELDS, load_universe, merge_financial_metrics,
)
from uniquant.brain.factors.custom_factors import (  # noqa: E402
    compute_cash_ratio, compute_fcf_yield, compute_real_dy,
)
from uniquant.brain.factors.custom_factors import compute_cfp_ttm  # noqa: E402
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("factor_mining.t5_redundancy")

# P14 新增财务列 (含 capex_ttm; dividend_dps_ttm 由脚本侧合并)
EXTRA = EXTRA_FINANCIAL_FIELDS + ["capex_ttm"]

DEFAULT_OUT = PROJECT_ROOT / "results" / "factor_mining" / "t5_redundancy_precheck.json"


def merge_dividend(df: pd.DataFrame) -> pd.DataFrame:
    """把 data/lake/dividend/{code}.parquet 的每股股息合并进日线。

    dividend_dps_ttm(t) = 过去 365 天内实际除权派现合计 (真实 TTM 股息,
    无未来函数; 茅台 2024-12-20 后 = 30.876+23.882 = 54.76 元/股 ≈ 年度派现)。
    """
    div_dir = PROJECT_ROOT / "data" / "lake" / "dividend"
    frames = {}
    for sym in df["code"].unique():
        p = div_dir / f"{sym}.parquet"
        if p.exists():
            d = pd.read_parquet(p)
            d = d[["code", "ex_date", "dps"]].copy()
            d = d[d["dps"].notna() & (d["dps"] > 0)]
            d["ex_dt"] = pd.to_datetime(d["ex_date"].astype(str), format="%Y%m%d")
            frames[sym] = d[["code", "ex_dt", "dps"]]
    if not frames:
        df["dividend_dps_ttm"] = np.nan
        return df

    df = df.copy()
    df["date_dt"] = pd.to_datetime(df["date"])
    out = np.full(len(df), np.nan, dtype=float)
    for sym, div in frames.items():
        if div.empty:
            continue
        m = (df["code"] == sym).to_numpy()
        if not m.any():
            continue
        t = df.loc[m, "date_dt"].to_numpy()
        e = div["ex_dt"].to_numpy()
        d = div["dps"].to_numpy()
        order = np.argsort(e)
        e, d = e[order], d[order]
        ps = np.concatenate([[0.0], np.cumsum(d)])
        lo = np.searchsorted(e, t - pd.Timedelta(days=365), side="left")
        hi = np.searchsorted(e, t, side="right")
        out[m] = ps[hi] - ps[lo]
    df["dividend_dps_ttm"] = out
    return df


def spearman(a: pd.Series, b: pd.Series) -> float | None:
    s = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(s) < 50:
        return None
    return s["a"].rank().corr(s["b"].rank())


def run(load_sample: int, full: bool, max_workers: int = 32):
    t0 = time.time()
    df = load_universe(as_of="2026-05-29", max_workers=max_workers)
    if not full:
        codes = sorted(df["code"].unique())
        rng = np.random.RandomState(42)
        selected = rng.choice(codes, size=min(load_sample, len(codes)), replace=False)
        df = df[df["code"].isin(selected)].reset_index(drop=True)
        logger.info(f"采样 {len(selected)} 只 (seed=42)")
    lookback = 1600
    if df["date"].nunique() > lookback:
        cutoff = df["date"].sort_values().unique()[-lookback]
        df = df[df["date"] >= cutoff].reset_index(drop=True)

    df = merge_financial_metrics(df, extra_fields=EXTRA, max_workers=max_workers)
    df = merge_dividend(df)

    # 因子列
    factors = pd.DataFrame(index=df.index)
    factors["fcf_yield"] = compute_fcf_yield(df)
    factors["cfp_ttm"] = compute_cfp_ttm(df)
    factors["cash_ratio"] = compute_cash_ratio(df)
    factors["real_dy"] = compute_real_dy(df)

    # 截面: 取最后交易日
    last_date = df["date"].max()
    mask = df["date"] == last_date
    print(f"\n截面: {last_date} ({int(mask.sum())} 行)")
    coverage = {}
    for c in factors.columns:
        cov = float(factors.loc[mask, c].notna().mean())
        coverage[c] = round(cov, 4)
        print(f"  {c}: 覆盖率 {cov:.1%}  | 非空 {int(factors.loc[mask, c].notna().sum())}")
        vals = factors.loc[mask, c].dropna()
        if len(vals):
            print(f"     值域 [{vals.min():.4g}, {vals.max():.4g}] 中位 {vals.median():.4g}")

    print("\n冗余预检 (fcf_yield vs cfp_ttm, 截面 spearman):")
    r_fcf_cfp = spearman(factors.loc[mask, "fcf_yield"], factors.loc[mask, "cfp_ttm"])
    print(f"  spearman(fcf_yield, cfp_ttm) = {r_fcf_cfp:.4f}" if r_fcf_cfp else "  None (样本不足)")
    r_cash_ep = spearman(factors.loc[mask, "cash_ratio"], factors.loc[mask, "cfp_ttm"])
    print(f"  spearman(cash_ratio, cfp_ttm) = {r_cash_ep:.4f}" if r_cash_ep else "  None")
    r_dy_ep = spearman(factors.loc[mask, "real_dy"], factors.loc[mask, "cfp_ttm"])
    print(f"  spearman(real_dy, cfp_ttm)    = {r_dy_ep:.4f}" if r_dy_ep else "  None")

    report = {
        "_meta": {"prereg": "docs/analysis/P14_CASH_FCF_DY_PREREGISTRATION.md",
                  "as_of": "2026-05-29", "lookback_days": lookback,
                  "sample": not full, "n_symbols": int(df["code"].nunique()),
                  "elapsed_sec": round(time.time() - t0, 1)},
        "cross_section": str(last_date),
        "coverage": coverage,
        "redundancy": {
            "fcf_yield_vs_cfp_ttm_spearman": r_fcf_cfp,
            "cash_ratio_vs_cfp_ttm_spearman": r_cash_ep,
            "real_dy_vs_cfp_ttm_spearman": r_dy_ep,
            "note": "spearman > 0.9 判 fcf_yield 为 cfp_ttm 冗余 (非独立增量, 退出五门)",
        },
        "verdict": {
            "fcf_yield_is_redundant": bool(r_fcf_cfp is not None and r_fcf_cfp > 0.9),
        },
    }
    out = Path(DEFAULT_OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告 → {out}")


def main():
    ap = argparse.ArgumentParser(description="P14 因子冗余预检 (T5)")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--sample", type=int, default=500)
    ap.add_argument("--max-workers", type=int, default=32)
    args = ap.parse_args()
    run(60 if args.smoke else args.sample, args.full, args.max_workers)


if __name__ == "__main__":
    main()
