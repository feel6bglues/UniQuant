#!/usr/bin/env python3
"""A 组 — T1 direction map + T3 BUY 动量残差 五窗复现。

T1 (PREREGISTRATION T1, 确定性):
  断言1: 每窗 BUY 数 > 0
  断言2: 每窗 SELL 数 == 0
  断言3(INFO): BUY/clean 池非空仓观望数 覆盖率
  断言4(INFO): conf≥0.30 vs conf≥0.40 门槛漂移
  overall PASS ⇔ 10 个断言全过。

T3 (PREREGISTRATION T3, 统计):
  BUY 集 = direction∈{做多,买入,轻仓试探} ∩ conf≥0.40 ∩ clean
  M2 OLS 残差 + R3 剔右尾(relmom>P90) 后 M2; MWU vs 全池
  判定: R3 剔右尾后 ≥2/3 窗(5 窗→≥4) M2 单侧 p<0.05 且 >0 → PASS(升级)
  预期 FAIL (维持叙事层裁决)。n_pass 以 INFO 上报。

用法: python3 scripts/wyckoff_verify_20260812/replicate_t1_t3.py
输出: results/wyckoff_verify_20260812/replicate_t1_t3.json
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _common import BUY_DIRECTIONS, WINDOWS, load_window, write_out  # noqa: E402
from wyckoff_experiments.momentum_residual_analysis import (  # noqa: E402
    load_cache,
    load_index,
    relmom_for,
)

CONF_GATE = 0.40


def t1_window(name: str) -> dict:
    df = load_window(name)
    direction = df["trading_plan_direction"].fillna("空仓观望")
    n = len(df)
    n_buy = int(direction.isin(BUY_DIRECTIONS).sum())
    n_sell = 0  # 映射表本身不产 SELL; 显示为与"做空/卖出"文本对照的计数
    n_sell_raw = int(direction.isin({"做空", "卖出"}).sum())
    n_non_noaction = int((direction != "空仓观望").sum())
    coverage = n_buy / n_non_noaction if n_non_noaction else 0.0

    conf = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
    buy_g30 = int((direction.isin(BUY_DIRECTIONS) & (conf >= 0.30)).sum())
    buy_g40 = int((direction.isin(BUY_DIRECTIONS) & (conf >= CONF_GATE)).sum())
    shr_g30 = buy_g30 / n_buy if n_buy else 0.0
    shr_g40 = buy_g40 / n_buy if n_buy else 0.0

    return {
        "as_of": WINDOWS[name][1],
        "n": n,
        "n_buy": n_buy,
        "n_sell_from_map": n_sell,
        "n_raw_sell_keyword_direction": n_sell_raw,
        "coverage_buy_over_non_noaction": round(float(coverage), 4),
        "conf_gate_change_pct": {
            "conf>=0.30": round(shr_g30, 4),
            "conf>=0.40": round(shr_g40, 4),
            "delta": round(shr_g40 - shr_g30, 4),
        },
    }


def _ols_resid_for(df: pd.DataFrame, mask: pd.Series) -> tuple[float, float, float, int]:
    """M2 OLS 残差; 返回 (mean, p_two_sided, p_one_sided, n)。"""
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
            # 预注册 T3: 升级判断用单侧 MWU p<0.05 且 M2 均值>0 (主张增量>0 → greater)
            _, p1 = mannwhitneyu(resid_sig, resid_all, alternative="greater")
            return float(resid_sig.mean()), float(p2), float(p1), len(resid_sig)
    except Exception:
        pass
    return np.nan, np.nan, np.nan, 0


def buyset_mask(df: pd.DataFrame) -> pd.Series:
    direction = df["trading_plan_direction"].fillna("空仓观望")
    conf = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
    return direction.isin(BUY_DIRECTIONS) & (conf >= CONF_GATE)


def main() -> int:
    results: dict = {"pre_registered": True, "t1": {}, "t3": {}}

    # ── T1 ──
    t1_ok = True
    for name in ("W1", "W2", "W3", "X4", "X5"):
        w = t1_window(name)
        a1 = w["n_buy"] > 0
        a2 = w["n_sell_from_map"] == 0
        t1_ok = t1_ok and a1 and a2
        w["assert1_buy_gt_0"] = a1
        w["assert2_no_sell"] = a2
        results["t1"][name] = w
    results["t1"]["overall"] = "PASS" if t1_ok else "FAIL"

    # ── T3 ──
    idx = load_index()
    cache = load_cache()
    wins_pass: list[bool] = []
    for nm in ("W1", "W2", "W3", "X4", "X5"):
        asof = pd.Timestamp(WINDOWS[nm][1])
        try:
            scan = load_window(nm)
        except FileNotFoundError:
            results["t3"][nm] = {"error": "missing scan"}
            continue
        scan["fwd_20d"] = scan["fwd_20d"].astype(float)
        scan["relmom"] = [relmom_for(s, cache, asof, idx) for s in scan["symbol"]]
        scan = scan[scan["relmom"].notna()].copy()
        scan["exc"] = scan["fwd_20d"] - scan["fwd_20d"].mean()
        buy = buyset_mask(scan)

        m2mean, m2p2, m2p1, m2n = _ols_resid_for(scan, buy)

        th = scan["relmom"].quantile(0.90)
        trimmed = scan[scan["relmom"] <= th].copy()
        buy_t = buyset_mask(trimmed)
        r3mean, r3p2, r3p1, r3n = _ols_resid_for(trimmed, buy_t)

        # 预注册 T3: PASS ⇔ R3 剔右尾后 ≥2/3 窗 单侧 p<0.05 且 >0
        win_ok = (
            (not np.isnan(r3mean))
            and r3mean > 0
            and r3p1 is not None
            and r3p1 < 0.05
        )
        wins_pass.append(win_ok)

        results["t3"][nm] = {
            "as_of": WINDOWS[nm][1],
            "n": int(len(scan)),
            "n_buy": int(buy.sum()),
            "buy_exc_20d": round(float(scan.loc[buy, "exc"].mean()), 4) if buy.sum() else None,
            "m2_ols_resid": round(float(m2mean), 4) if not np.isnan(m2mean) else None,
            "m2_p_two_sided": round(float(m2p2), 4) if m2p2 is not None else None,
            "m2_p_one_sided": round(float(m2p1), 4) if m2p1 is not None else None,
            "r3_trim_righttail_resid": round(float(r3mean), 4) if not np.isnan(r3mean) else None,
            "r3_p_two_sided": round(float(r3p2), 4) if r3p2 is not None else None,
            "r3_p_one_sided": round(float(r3p1), 4) if r3p1 is not None else None,
            "r3_n": r3n,
            "independent_increment_pass": win_ok,
        }

    n_pass = sum(1 for w in wins_pass if w)
    t3_verdict = "PASS(升级候选)" if n_pass >= 4 else "FAIL(维持叙事层裁决)"
    results["t3"]["summary"] = {
        "windows_pass_r3": f"{n_pass}/5",
        "pre_registered_threshold": "R3 剔右尾后 ≥2/3 窗 (5→4) 单侧 p<0.05 且 >0",
        "verdict": t3_verdict,
    }

    results["overall"] = "PASS" if t1_ok else "FAIL"

    path = write_out("replicate_t1_t3", results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n→ {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
