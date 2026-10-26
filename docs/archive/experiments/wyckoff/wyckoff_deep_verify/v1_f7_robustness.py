#!/usr/bin/env python3
"""V1: F7 口径统一与剔尾边界稳健性审计。

对 5 窗口 × 6 信号类型，在 4 种剔尾边界下做 MWU（双侧+单侧），
检验 leader 3/5 结论对剔尾边界和 MWU 替代假说的稳健性。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import WINDOWS, SIG_TYPES, load_window, sig_mask, write_out

TRIM_BOUNDS = [5.0, 10.0, 15.0, 20.0]
ALTERNATIVES = ["two-sided", "greater", "less"]
UPGRADE_LINE = 4  # ≥4 同号显著窗口 = 升级线


def _trim_pool(df: pd.DataFrame, bound: float) -> pd.DataFrame:
    """|fwd_20d| <= bound 的剔尾子集。"""
    return df[df["fwd_20d"].abs() <= bound].copy()


def _run_mwu(signal_vals: np.ndarray, rest_vals: np.ndarray, alt: str) -> float:
    try:
        _, p = mannwhitneyu(signal_vals, rest_vals, alternative=alt)
        return float(p)
    except ValueError:
        return 1.0


def analyze_window(df: pd.DataFrame, name: str) -> dict:
    """单窗口分析：返回每信号类型 × 剔尾边界 × 替代假说的结果。"""
    results = {}
    for sig_type in SIG_TYPES:
        for bound in TRIM_BOUNDS:
            trim = _trim_pool(df, bound)
            tmask = sig_mask(trim, sig_type)
            t_sig = trim[tmask]["fwd_20d"].values
            t_rest = trim[~tmask]["fwd_20d"].values
            mean_sig = float(np.mean(t_sig)) if len(t_sig) > 0 else None
            for alt in ALTERNATIVES:
                key = (sig_type, bound, alt)
                p = _run_mwu(t_sig, t_rest, alt) if len(t_sig) >= 2 and len(t_rest) >= 2 else 1.0
                results[key] = {
                    "window": name,
                    "signal_type": sig_type,
                    "trim_bound": bound,
                    "alternative": alt,
                    "signal_count": int(len(t_sig)),
                    "rest_count": int(len(t_rest)),
                    "signal_mean": mean_sig,
                    "p_value": p,
                    "significant": p < 0.05,
                }
    return results


def _same_sign_count(
    rows: list[dict], sig_type: str, bound: float, alt: str,
) -> int:
    relevant = [r for r in rows if r["signal_type"] == sig_type
                and r["trim_bound"] == bound and r["alternative"] == alt]
    if alt == "two-sided":
        pos = sum(1 for r in relevant if r["significant"] and r["signal_mean"] is not None and r["signal_mean"] > 0)
        neg = sum(1 for r in relevant if r["significant"] and r["signal_mean"] is not None and r["signal_mean"] < 0)
        return max(pos, neg)
    elif alt == "greater":
        return sum(1 for r in relevant if r["significant"] and r["signal_mean"] is not None and r["signal_mean"] > 0)
    elif alt == "less":
        return sum(1 for r in relevant if r["significant"] and r["signal_mean"] is not None and r["signal_mean"] < 0)
    return 0


def _fwd60d_analysis(dfs: dict[str, pd.DataFrame]) -> dict:
    """X4/X5 的 fwd_60d 额外分析。"""
    info = {}
    for name in ["X4", "X5"]:
        df = dfs[name]
        df60 = df[df["fwd_60d"].notna()].copy()
        rows = []
        for sig_type in SIG_TYPES:
            for bound in TRIM_BOUNDS:
                trim = df60[df60["fwd_60d"].abs() <= bound].copy()
                tmask = sig_mask(trim, sig_type)
                t_sig = trim[tmask]["fwd_60d"].values
                t_rest = trim[~tmask]["fwd_60d"].values
                mean_sig = float(np.mean(t_sig)) if len(t_sig) > 0 else None
                for alt in ALTERNATIVES:
                    p = _run_mwu(t_sig, t_rest, alt) if len(t_sig) >= 2 and len(t_rest) >= 2 else 1.0
                    rows.append({
                        "window": name,
                        "signal_type": sig_type,
                        "trim_bound": bound,
                        "alternative": alt,
                        "signal_count": int(len(t_sig)),
                        "rest_count": int(len(t_rest)),
                        "signal_mean": mean_sig,
                        "p_value": p,
                        "significant": p < 0.05,
                    })
        info[name] = rows
    return info


def main():
    # 加载五窗数据
    dfs = {}
    all_rows = []
    for name in WINDOWS:
        df = load_window(name)
        dfs[name] = df
        for _, row in analyze_window(df, name).items():
            all_rows.append(row)

    # 汇总表：每(信号类型, 剔尾边界, 替代假说)的同号显著窗口数
    summary = {}
    for sig_type in SIG_TYPES:
        for bound in TRIM_BOUNDS:
            for alt in ALTERNATIVES:
                cnt = _same_sign_count(all_rows, sig_type, bound, alt)
                summary[(sig_type, bound, alt)] = cnt

    verdicts = {}
    overall_pass = True
    for sig_type in SIG_TYPES:
        sig_verdicts = {}
        for bound in TRIM_BOUNDS:
            for alt in ALTERNATIVES:
                cnt = summary[(sig_type, bound, alt)]
                fail = cnt >= UPGRADE_LINE
                if fail:
                    overall_pass = False
                sig_verdicts[f"bound={bound}_alt={alt}"] = {
                    "same_sign_count": cnt,
                    "fail": fail,
                }
        verdicts[sig_type] = sig_verdicts

    # 升级线同号数变化表
    upgrade_table = {}
    for bound in TRIM_BOUNDS:
        row = {}
        for sig_type in SIG_TYPES:
            for alt in ALTERNATIVES:
                row[f"{sig_type}_{alt}"] = summary[(sig_type, bound, alt)]
        upgrade_table[f"bound={bound}"] = row

    # fwd_60d INFO
    fwd60 = _fwd60d_analysis(dfs)

    # 找出最高同号数
    max_count = max(summary.values())

    payload = {
        "meta": {
            "script": "v1_f7_robustness.py",
            "description": "F7 口径统一与剔尾边界稳健性审计",
            "trim_bounds": TRIM_BOUNDS,
            "alternatives": ALTERNATIVES,
            "signal_types": SIG_TYPES,
            "upgrade_line": UPGRADE_LINE,
            "windows": list(WINDOWS.keys()),
        },
        "verdict": {
            "overall_pass": overall_pass,
            "rule": "V1 PASS ⇔ 所有边界×方向×信号类同号显著窗口数均 < 4（无信号类达升级线）",
            "max_same_sign_count_across_all": max_count,
            "leader_3_5_robust": overall_pass,
            "details": verdicts,
        },
        "same_sign_count_table": upgrade_table,
        "all_results": all_rows,
        "fwd60d_info": {
            "note": "X4/X5 额外 fwd_60d 分析（仅 INFO，不参与判定）",
            "results": fwd60,
        },
    }

    path = write_out("v1_f7_robustness", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nWritten to {path}", file=sys.stderr)


if __name__ == "__main__":
    main()