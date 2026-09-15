"""五门验证共享统计 — 真实 OOS 测试窗逐日 IC (2026-08-28 修复 fwd5 错位 bug)。

背景 (D+15 验证 2026-08-28 重大修正):
1. 原 P11/P12/P14 脚本 `panel["fwd5"] = pct_change(-5).shift(-5)` 经 pandas 语义
   验证 = close[t+5]/close[t+10]-1, 即"未来5-10日"收益, 视野错位 5 天
   (正确应为 close[t+5]/close[t]-1 = 未来0-5日, 与 analyzer 官方一致)。
   → 动量残差门/逐日 IC 全部基于错位视野。
2. 原 `WalkForwardFactorPipeline.w.ic_mean` 是训练窗 IC 均值(且 1/5/20 期再平均),
   非 OOS → 不能用作 oos_ic_mean。

本模块统一修正:
- correct_fwd5: 未来 0-5 日收益 (shift(-5)/close - 1, groupby code)
- 全部五门统计基于 walk-forward 测试窗 panel 逐日 IC (真实 OOS)
- 与 analyzer.compute_ic_ir 官方实现逐位一致 (已验证 差=0.000000)

用法:
    from scripts.factor_mining.five_gate import factor_gates, correct_fwd5
    panel["fwd5"] = correct_fwd5(panel)      # 替代 pct_change(-5).shift(-5)
    gates = factor_gates(panel, windows, name, expected_dir)
"""

from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.research.gates.alpha_tier_engine import ClassAEvaluator


def correct_fwd5(panel: pd.DataFrame, price_col: str = "close") -> pd.Series:
    """未来 0-5 日收益 = close[t+5]/close[t]-1 (analyzer 官方同款, 逐位一致)。"""
    return panel[price_col].groupby(level=0).shift(-5) / panel[price_col] - 1


def _spearman_from_ranks(fr: pd.Series, rr: pd.Series) -> float | None:
    fv, rv = fr.to_numpy(), rr.to_numpy()
    n = len(fv)
    num = n * float(np.dot(fv, rv)) - float(fv.sum()) * float(rv.sum())
    den = np.sqrt(
        (n * float(np.dot(fv, fv)) - float(fv.sum()) ** 2)
        * (n * float(np.dot(rv, rv)) - float(rv.sum()) ** 2)
    )
    return num / den if den > 1e-12 else None


def daily_ic_series(panel: pd.DataFrame, factor_col: str) -> dict:
    """测试窗内逐日 IC: raw / momentum 残差化 / 剔右尾 (正确 fwd5)。"""
    raw_ics, res_ics, tail_ics = [], [], []
    for _, g in panel.groupby(level=1):
        f = g[factor_col].dropna()
        r = g["fwd5"].dropna()
        m = g["mom20"].dropna()
        common = f.index.intersection(r.index).intersection(m.index)
        if len(common) < 20:
            continue
        ff_r = f.loc[common].rank().to_numpy()
        rr_r = r.loc[common].rank().to_numpy()
        mm_r = m.loc[common].rank().to_numpy()
        raw = _spearman_from_ranks(pd.Series(ff_r), pd.Series(rr_r))
        if raw is None:
            continue
        raw_ics.append(raw)
        mv = mm_r
        mv_var = float(np.var(mv, ddof=1))
        if mv_var > 1e-12:
            beta = float(np.cov(ff_r, mv, ddof=1)[0, 1]) / mv_var
            res = pd.Series(ff_r - beta * mv).rank().to_numpy()
            n = len(res)
            num = n * float(np.dot(res, rr_r)) - float(res.sum()) * float(rr_r.sum())
            den = np.sqrt(
                (n * float(np.dot(res, res)) - float(res.sum()) ** 2)
                * (n * float(np.dot(rr_r, rr_r)) - float(rr_r.sum()) ** 2)
            )
            res_ics.append(num / den if den > 1e-12 else 0.0)
        th = np.quantile(mv, 0.9)
        keep = mv <= th
        if keep.sum() >= 20:
            kf, kr = ff_r[keep], rr_r[keep]
            nk = len(kf)
            num = nk * float(np.dot(kf, kr)) - float(kf.sum()) * float(kr.sum())
            den = np.sqrt(
                (nk * float(np.dot(kf, kf)) - float(kf.sum()) ** 2)
                * (nk * float(np.dot(kr, kr)) - float(kr.sum()) ** 2)
            )
            tail_ics.append(num / den if den > 1e-12 else 0.0)
    return {"raw": raw_ics, "res": res_ics, "tail": tail_ics}


def block_bootstrap_pbo(oos_ics: list, n_bootstrap: int = 2000) -> float:
    arr = np.array([x for x in oos_ics if np.isfinite(x)])
    n = len(arr)
    if n < 5:
        return 1.0
    rng = np.random.RandomState(42)
    best_idx = int(np.argmax(arr))
    block_size = max(1, int(n / 5))
    n_blocks = int(np.ceil(n / block_size))
    worse = 0
    for _ in range(n_bootstrap):
        blocks = rng.choice(n_blocks, size=n_blocks, replace=True)
        boot = np.concatenate(
            [arr[i * block_size: (i + 1) * block_size] for i in blocks]
        )[:n]
        cand = boot[: best_idx + 1] if best_idx < len(boot) else boot
        if len(cand) and np.max(cand) >= arr[best_idx]:
            worse += 1
    return worse / n_bootstrap


def block_bootstrap_ic_ci(
    oos_ics: list, n_bootstrap: int = 2000, ci_level: float = 0.95
) -> dict:
    """真实重叠块自助法计算 OOS IC 均值 95% 置信区间与零假设检验。"""
    arr = np.array([x for x in oos_ics if np.isfinite(x)], dtype=np.float64)
    n = len(arr)
    if n < 3:
        return {"ci_lower": 0.0, "ci_upper": 0.0, "bootstrap_p": 1.0, "is_significant": False}
    rng = np.random.RandomState(42)
    block_size = max(1, int(n / 4))
    n_blocks = int(np.ceil(n / block_size))
    boot_means = []
    for _ in range(n_bootstrap):
        blocks = rng.choice(n_blocks, size=n_blocks, replace=True)
        sample = np.concatenate([arr[i * block_size: (i + 1) * block_size] for i in blocks])[:n]
        boot_means.append(float(np.mean(sample)))
    boot_arr = np.array(boot_means)
    alpha = (1.0 - ci_level) / 2.0
    low = float(np.percentile(boot_arr, alpha * 100))
    high = float(np.percentile(boot_arr, (1.0 - alpha) * 100))
    m = float(np.mean(arr))
    p_zero = float(np.mean(boot_arr <= 0)) if m > 0 else float(np.mean(boot_arr >= 0))
    is_sig = bool((low > 0 and high > 0) or (low < 0 and high < 0))
    return {
        "ci_lower": round(low, 4),
        "ci_upper": round(high, 4),
        "bootstrap_p": round(min(1.0, p_zero * 2.0), 4),
        "is_significant": is_sig,
    }


def factor_gates(
    panel: pd.DataFrame,
    windows: list,
    name: str,
    expected_dir: int,
    n_bootstrap: int = 2000,
) -> dict:
    """基于真实 OOS 测试窗逐日 IC 计算五门 (替代 pipeline 训练窗 w.ic_mean)。

    每窗取测试段 panel → 逐日 raw/res/tail IC; oos_ic_mean = 各窗 raw IC 均值,
    ICIR = mean/std, PBO = 各窗 raw IC 块自助, 动量门 = res/tail/pos_frac。
    集成 QTR-OS 科研门禁: Newey-West t-stat、块自助置信区间与 Class A 裁决。
    """
    per_win_raw, per_win_res = [], []
    res_all, tail_all, pos_windows, n_win = [], [], 0, 0
    for w in windows:
        sub = panel[
            (panel.index.get_level_values(1) >= w.test_start)
            & (panel.index.get_level_values(1) <= w.test_end)
        ]
        if sub.empty or name not in sub.columns:
            continue
        daily = daily_ic_series(sub, name)
        n_win += 1
        if daily["raw"]:
            per_win_raw.append(float(np.mean(daily["raw"])))
        if daily["res"]:
            per_win_res.append(float(np.mean(daily["res"])))
            pos_windows += (float(np.mean(daily["res"])) > 0)
            res_all.extend(daily["res"])
        tail_all.extend(daily["tail"])

    if not per_win_raw:
        return {"n_windows": 0, "note": "no valid window IC"}

    oos_mean = float(np.mean(per_win_raw))
    oos_std = float(np.std(per_win_raw))
    icir = oos_mean / max(oos_std, 1e-10)
    pbo = block_bootstrap_pbo(per_win_raw, n_bootstrap)
    correct_sign = (oos_mean > 0 and expected_dir > 0) or (
        oos_mean < 0 and expected_dir < 0
    )

    res_m = float(np.mean(res_all)) if res_all else 0.0
    tail_m = float(np.mean(tail_all)) if tail_all else 0.0
    frac_pos = pos_windows / max(n_win, 1)
    if expected_dir < 0:
        res_m, tail_m = -res_m, -tail_m
        frac_pos = 1.0 - frac_pos

    # 科研控制平面门禁指标计算
    ci_res = block_bootstrap_ic_ci(per_win_raw, n_bootstrap)
    _, t_nw, p_nw = ClassAEvaluator.compute_newey_west_t(np.array(per_win_raw), forecast_horizon=5)

    d = {
        "oos_ic_mean": round(oos_mean, 4),
        "oos_ic_std": round(oos_std, 4),
        "oos_icir": round(icir, 4),
        "pbo": round(pbo, 4),
        "n_windows": len(per_win_raw),
        "expected_direction": expected_dir,
        "correct_sign": bool(correct_sign),
        "passed_ic": bool(abs(oos_mean) > 0.01),
        "passed_icir": bool(abs(icir) > 0.5),
        "passed_pbo": bool(pbo < 0.2),
        "mom_res_mean": round(res_m, 4),
        "mom_tail_mean": round(tail_m, 4),
        "mom_pos_frac": round(frac_pos, 3),
        "passed_mom": bool(res_m > 0 and tail_m > 0 and frac_pos >= 2.0 / 3.0),
        # Research OS 门禁增强指标
        "newey_west_t": round(t_nw, 3),
        "newey_west_p": round(p_nw, 5),
        "ic_ci_95": [ci_res["ci_lower"], ci_res["ci_upper"]],
        "bootstrap_sig": ci_res["is_significant"],
        "class_a_supported": bool(abs(t_nw) >= 3.0 and ci_res["is_significant"] and (res_m > 0 and frac_pos >= 2.0 / 3.0)),
    }
    d["passed_all_base"] = bool(
        d["passed_ic"] and d["passed_icir"] and d["passed_pbo"] and correct_sign
    )
    d["passed_all"] = bool(d["passed_all_base"] and d["passed_mom"])
    return d
