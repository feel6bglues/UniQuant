"""动量残差门机制分解 — P14 因子为何被动量门灭 (真实数据实证)。

对每个因子逐日 (截面) 计算四量:
  rho(f, m)  = 因子 vs mom20 截面秩相关   (因子与动量共线度)
  rho(m, r)  = mom20 vs fwd5 截面秩相关    (A股动量结构: 反转应为负)
  IC_raw     = 因子 vs fwd5 原始秩相关
  IC_res     = 残差化(因子~动量OLS)后 vs fwd5 秩相关

理论: 动量门 "IC_res ≈ IC_raw - rho(f,m)*rho(m,r)" 方向可预测。
- 若 rho(m,r)<0 (动量反转) 且 |rho(f,m)| 显著 → 残差化会大幅削减甚至翻转 IC_raw。
- 翻负条件: rho(f,m)*rho(m,r) > IC_raw (即因子-动量共线贡献超过原始IC)。

用法: python3 scripts/factor_mining/run_diag_momentum_gate.py [--sample N]
"""
from __future__ import annotations

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
from scripts.factor_mining.run_cash_fcf_dy_test import merge_dividend  # noqa: E402
from scripts.factor_mining.run_t5_redundancy_precheck import merge_dividend as _md  # noqa: F401
from uniquant.brain.factors.custom_factors import (  # noqa: E402
    compute_cash_ratio, compute_cfp_ttm, compute_fcf_yield, compute_illiq_20d,
    compute_real_dy,
)
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("factor_mining.diag_momentum_gate")

EXTRA = EXTRA_FINANCIAL_FIELDS + ["capex_ttm"]
FACTOR_COLS = ["cash_ratio", "fcf_yield", "real_dy", "cfp_ttm", "illiq_20d"]


def _sr(a: np.ndarray, b: np.ndarray) -> float:
    """秩相关 (输入已为秩向量)。"""
    n = len(a)
    num = n * float(np.dot(a, b)) - float(a.sum()) * float(b.sum())
    den = np.sqrt(
        (n * float(np.dot(a, a)) - float(a.sum()) ** 2)
        * (n * float(np.dot(b, b)) - float(b.sum()) ** 2)
    )
    return num / den if den > 1e-12 else 0.0


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=500)
    ap.add_argument("--max-workers", type=int, default=32)
    args = ap.parse_args()
    t0 = time.time()

    df = load_universe(as_of="2026-05-29", max_workers=args.max_workers)
    codes = sorted(df["code"].unique())
    rng = np.random.RandomState(42)
    selected = rng.choice(codes, size=min(args.sample, len(codes)), replace=False)
    df = df[df["code"].isin(selected)].reset_index(drop=True)
    lookback = 1600
    if df["date"].nunique() > lookback:
        cutoff = df["date"].sort_values().unique()[-lookback]
        df = df[df["date"] >= cutoff].reset_index(drop=True)

    logger.info("合并财务 + 分红...")
    df = merge_financial_metrics(df, extra_fields=EXTRA, max_workers=args.max_workers)
    df = merge_dividend(df)

    panel = df.set_index(["code", "date"], drop=False)
    panel.index = panel.index.set_names(["code_idx", "date_idx"])
    panel["fwd5"] = panel["close"].groupby(level=0).shift(-5)/panel["close"]-1  # 2026-08-28 修复: 未来0-5日
    panel["mom20"] = panel["close"].groupby(level=0).pct_change(20, fill_method=None)

    logger.info("计算因子...")
    for col in FACTOR_COLS:
        fn = {"cash_ratio": compute_cash_ratio, "fcf_yield": compute_fcf_yield,
              "real_dy": compute_real_dy, "cfp_ttm": compute_cfp_ttm,
              "illiq_20d": compute_illiq_20d}[col]
        panel[col] = fn(df).to_numpy()

    logger.info(f"逐日截面分解 ({panel.index.get_level_values(1).nunique()} 天)...")
    stats = {c: {"rho_fm": [], "rho_mr": [], "ic_raw": [], "ic_res": [],
                 "beta": []} for c in FACTOR_COLS}
    for _, g in panel.groupby(level=1):
        m = g["mom20"].dropna()
        r = g["fwd5"].dropna()
        if len(m) < 50:
            continue
        mm_r = m.loc[m.index.intersection(r.index)].rank().to_numpy()
        rr_r = r.loc[m.index.intersection(r.index)].rank().to_numpy()
        if len(mm_r) < 50:
            continue
        rho_mr = _sr(mm_r, rr_r)
        for col in FACTOR_COLS:
            f = g[col].dropna()
            common = f.index.intersection(m.index).intersection(r.index)
            if len(common) < 50:
                continue
            ff_r = f.loc[common].rank().to_numpy()
            m_r = m.loc[common].rank().to_numpy()
            r_r = r.loc[common].rank().to_numpy()
            ic_raw = _sr(ff_r, r_r)
            rho_fm = _sr(ff_r, m_r)
            beta = 0.0
            if m_r.var() > 1e-12:
                beta = np.cov(ff_r, m_r)[0, 1] / m_r.var()
                res = pd.Series(ff_r - beta * m_r).rank().to_numpy()
                ic_res = _sr(res, r_r)
            else:
                ic_res = ic_raw
            stats[col]["rho_fm"].append(rho_fm)
            stats[col]["rho_mr"].append(rho_mr)
            stats[col]["ic_raw"].append(ic_raw)
            stats[col]["ic_res"].append(ic_res)
            stats[col]["beta"].append(beta)

    print(f"\n{'='*104}")
    print("动量残差门机制分解 (逐日截面均值, 500只×1600d)")
    print(f"{'='*104}")
    print(f"{'因子':<14} {'rho(f,m)':>9} {'rho(m,r)':>9} {'IC_raw':>8} {'IC_res':>8} "
          f"{'Δ(IC_res-raw)':>13} {'beta':>7}  {'翻负日%':>7}")
    print("-" * 104)
    summary = {}
    for col in FACTOR_COLS:
        s = stats[col]
        fm, mr = float(np.mean(s["rho_fm"])), float(np.mean(s["rho_mr"]))
        raw, res = float(np.mean(s["ic_raw"])), float(np.mean(s["ic_res"]))
        beta = float(np.mean(s["beta"]))
        flip = 100.0 * np.mean([1 if a > 0 and b < 0 else 0 for a, b in zip(s["ic_raw"], s["ic_res"])])
        print(f"{col:<14} {fm:>+9.4f} {mr:>+9.4f} {raw:>+8.4f} {res:>+8.4f} "
              f"{res-raw:>+13.4f} {beta:>7.3f}  {flip:>6.1f}%")
        summary[col] = {"rho_fm": round(fm, 4), "rho_mr": round(mr, 4),
                        "ic_raw": round(raw, 4), "ic_res": round(res, 4),
                        "beta": round(beta, 3), "flip_pct": round(flip, 1)}

    print(f"\n{'='*104}")
    print("关键机制解读:")
    print("  rho(m,r) < 0 = A股动量反转结构 (涨多→未来跌, 跌多→未来涨)")
    print("  rho(f,m) 显著 = 因子与动量共线 → 原始 IC 的一部分是'借动量之力'")
    print("  IC_res ≈ IC_raw - rho(f,m)*rho(m,r) → 残差化剥离动量贡献")
    print("  翻负 = rho(f,m)*rho(m,r) 贡献 > 原始 IC (因子排序≈反转股排序)")
    out = Path(PROJECT_ROOT) / "results" / "factor_mining" / "diag_momentum_gate.json"
    out.write_text(json.dumps({"summary": summary, "n_symbols": int(df['code'].nunique()),
                               "elapsed_sec": round(time.time()-t0, 1)},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告 → {out}")


if __name__ == "__main__":
    main()
