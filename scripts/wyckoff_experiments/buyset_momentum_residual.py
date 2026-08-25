#!/usr/bin/env python3
"""T3 — P0-2 新 BUY 集动量残差 (P2-3)。

BUY 集 = trading_plan_direction ∈ {做多,买入,轻仓试探} ∩ confidence≥0.40 ∩ clean 池。
检验该集合的 20d 超额是"Wyckoff 相位独立增量"还是"20d 相对动量 beta + 右尾运气"。

方法 (复用 momentum_residual_analysis.py 机制):
  M1 分位残差: relmom 10 分位桶内 BUY vs 桶内其他, 跨桶加权
  M2 OLS 残差: fwd_20d ~ relmom + relmom^2, BUY 残差均值 vs 全池 (MWU)
  R3 剔右尾: 剔除 relmom>P90 后重算 M2
  R4 分位内相位增量符号: 报告跨窗一致性

预注册阈值 (PREREGISTRATION T3):
  PASS(有独立增量) ⇔ 剔右尾后 ≥2/3 窗 M2 单侧 MWU p<0.05 且 M2 均值>0
  FAIL ⇔ 否则; 预期 FAIL: BUY=追涨动量+右尾 → 维持"引擎=叙事+风控层"裁决

用法: python3 scripts/wyckoff_experiments/buyset_momentum_residual.py
输出: results/wyckoff_experiments/buyset_momentum_residual.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
    from scipy.stats import mannwhitneyu
except ImportError as _ie:  # pragma: no cover
    sys.exit(f"numpy/pandas/scipy required: {_ie}")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from wyckoff_experiments.momentum_residual_analysis import (  # noqa: E402
    load_cache,
    load_index,
    relmom_for,
)
from wyckoff_experiments._symbols import is_index_symbol  # noqa: E402

DAILY = "data/lake/quotes/daily"
BUY_DIRECTIONS = {"做多", "买入", "轻仓试探"}
CONF_GATE = 0.40
ASOFS = {
    "W1": "2026-04-30",
    "W2": "2026-03-31",
    "W3": "2026-05-29",
    "X4": "2025-06-30",
    "X5": "2024-12-31",
}
SCANS = {
    "W1": "results/wyckoff_xs/wyckoff_scan_all.csv",
    "W2": "results/wyckoff_xs2/wyckoff_scan_all.csv",
    "W3": "results/wyckoff_xs3/wyckoff_scan_all.csv",
    "X4": "results/wyckoff_xs4/wyckoff_scan_all.csv",
    "X5": "results/wyckoff_xs5/wyckoff_scan_all.csv",
}


def buyset_mask(df: pd.DataFrame) -> pd.Series:
    direction = df["trading_plan_direction"].fillna("空仓观望")
    conf = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
    return direction.isin(BUY_DIRECTIONS) & (conf >= CONF_GATE)


def _ols_resid_for(df: pd.DataFrame, mask: pd.Series) -> tuple[float, float, float, int]:
    """M2 OLS 残差; 返回 (mean, mwu_p_two_sided, mwu_p_one_sided, n)。"""
    d = df[["fwd_20d", "relmom"]].dropna().copy()
    if len(d) < 30:
        return np.nan, np.nan, np.nan, 0
    x = np.column_stack([np.ones(len(d)), d["relmom"], d["relmom"] ** 2]).astype(float)
    y = d["fwd_20d"].astype(float).to_numpy()
    try:
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        resid = y - x @ beta
        resid_by_sym = dict(zip(d.index.tolist(), resid))
        sig_idx = [i for i in df.index[mask] if i in resid_by_sym]
        resid_sig = np.array([resid_by_sym[i] for i in sig_idx])
        resid_all = np.array([r for r in resid_by_sym.values()])
        if len(resid_sig) > 5:
            _, p2 = mannwhitneyu(resid_sig, resid_all, alternative="two-sided")
            # 预注册 T3: 升级判断用单侧 MWU p<0.05 且 M2 均值>0
            # 方向: 主张为"独立增量 > 0" → alternative="greater"
            _, p1 = mannwhitneyu(resid_sig, resid_all, alternative="greater")
            return float(resid_sig.mean()), float(p2), float(p1), len(resid_sig)
    except Exception:
        pass
    return np.nan, np.nan, np.nan, 0


def main() -> int:
    idx = load_index()
    cache = load_cache()
    results: dict = {"pre_registered": True, "windows": {}}
    wins_pass: list[bool] = []
    for nm, asof_s in ASOFS.items():
        scan_path = ROOT / SCANS[nm]
        if not scan_path.exists():
            results["windows"][nm] = {"error": f"missing {scan_path}"}
            continue
        asof = pd.Timestamp(asof_s)
        scan = pd.read_csv(scan_path)
        scan = scan[
            scan["fwd_20d"].notna()
            & ~scan["is_etf"].fillna(False)
            & ~scan["symbol"].map(lambda s: is_index_symbol(str(s)) if pd.notna(s) else False)
        ].copy()
        scan["fwd_20d"] = scan["fwd_20d"].astype(float)
        scan["relmom"] = [relmom_for(s, cache, asof, idx) for s in scan["symbol"]]
        scan = scan[scan["relmom"].notna()].copy()
        scan["exc"] = scan["fwd_20d"] - scan["fwd_20d"].mean()
        buy = buyset_mask(scan)

        # M1 分位残差
        qdf = scan.copy()
        qdf["q"] = pd.qcut(qdf["relmom"], 10, labels=False, duplicates="drop")
        m1 = np.nan
        for q, g in qdf.groupby("q"):
            s = g[buy.loc[g.index]]
            if len(s) < 5 or len(g) - len(s) < 5:
                continue
            other = g[~buy.loc[g.index]]
            effect = s["fwd_20d"].mean() - other["fwd_20d"].mean()
            w = len(s)
            m1 = (effect * w) if np.isnan(m1) else m1
        # 简化: 加权聚合
        m1_acc, m1_n = 0.0, 0
        for q, g in qdf.groupby("q"):
            s = g[buy.loc[g.index]]
            if len(s) < 5 or len(g) - len(s) < 5:
                continue
            other = g[~buy.loc[g.index]]
            m1_acc += (s["fwd_20d"].mean() - other["fwd_20d"].mean()) * len(s)
            m1_n += len(s)
        m1 = m1_acc / m1_n if m1_n else np.nan

        # M2 OLS 残差
        m2mean, m2p2, m2p1, m2n = _ols_resid_for(scan, buy)

        # R3 剔右尾 (relmom>P90) 后 M2
        th = scan["relmom"].quantile(0.90)
        trimmed = scan[scan["relmom"] <= th].copy()
        buy_t = buyset_mask(trimmed)
        r3mean, r3p2, r3p1, r3n = _ols_resid_for(trimmed, buy_t)

        # R4 分位内符号一致性
        signs = []
        for q, g in qdf.groupby("q"):
            s = g[buy.loc[g.index]]
            if len(s) < 5:
                continue
            signs.append(1 if (s["fwd_20d"].mean() - g["fwd_20d"].mean()) > 0 else -1)
        neg_frac = signs.count(-1) / len(signs) if signs else np.nan

        # 预注册 T3: PASS ⇔ R3 剔右尾后 ≥2/3 窗 单侧 MWU p<0.05 且 M2 均值>0
        win_ok = (
            (not np.isnan(r3mean))
            and r3mean > 0
            and r3p1 is not None
            and r3p1 < 0.05
        )
        wins_pass.append(win_ok)

        results["windows"][nm] = {
            "as_of": asof_s,
            "n": len(scan),
            "n_buy": int(buy.sum()),
            "buy_exc_20d": round(float(scan.loc[buy, "exc"].mean()), 4),
            "relmom_ic": round(float(np.corrcoef(scan["relmom"], scan["fwd_20d"])[0, 1]), 4),
            "m1_quantile_resid": round(float(m1), 4) if not np.isnan(m1) else None,
            "m2_ols_resid": round(float(m2mean), 4) if not np.isnan(m2mean) else None,
            "m2_p_two_sided": round(float(m2p2), 4) if m2p2 is not None else None,
            "m2_p_one_sided": round(float(m2p1), 4) if m2p1 is not None else None,
            "m2_n": m2n,
            "r3_trim_righttail_resid": round(float(r3mean), 4) if not np.isnan(r3mean) else None,
            "r3_p_two_sided": round(float(r3p2), 4) if r3p2 is not None else None,
            "r3_p_one_sided": round(float(r3p1), 4) if r3p1 is not None else None,
            "r3_n": r3n,
            "r4_neg_frac": round(float(neg_frac), 4) if not np.isnan(neg_frac) else None,
            "independent_increment_pass": win_ok,
        }
    n_windows = len(wins_pass)
    upgrade_bar = (2 * n_windows + 2) // 3  # ceil(2/3 * n_windows); 5 窗→4
    n_pass = sum(1 for w in wins_pass if w)
    verdict = "FAIL (维持叙事层裁决)" if n_pass < upgrade_bar else "PASS (升级候选)"
    results["summary"] = {
        "windows_pass_r3": f"{n_pass}/{n_windows}",
        "pre_registered_threshold": f"R3 剔右尾后 ≥2/3 窗 ({n_windows}→{upgrade_bar}) 单侧 p<0.05 且 >0",
        "verdict": verdict,
    }
    out = ROOT / "results" / "wyckoff_experiments"
    out.mkdir(parents=True, exist_ok=True)
    (out / "buyset_momentum_residual.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())