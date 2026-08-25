"""CANSLIM 因子轨四重门测试 — D+4 生死判定 (红蓝对抗 MVP 流程)。

对财务成长因子 (C/A/ROE/营收) 在净化真实数据上执行与 P3 同款四重门:
  IC 方向 / |ICIR|>0.5 / PBO<0.2 / 动量残差门,
并按 §7.5 输出季频事件法并行判据。

判定规则 (预注册 §7.1 冻结):
  - 面板: 500 只 seed=42 × 1600 交易日 × 17 窗 (504/63), as-of 2026-05-29
  - 金融股剔除 (R-FIN); 年轻股因子已置 NaN (R-YOUNG)
  - 早出口: C 族(c_single_yoy/c_ttm_yoy) 与 A 族(a_cagr3) 双败 → 路线终止

用法:
    python3 scripts/canslim/run_factor_gate.py            # 500 只全量
    python3 scripts/canslim/run_factor_gate.py --smoke    # 100 只冒烟
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

from scripts.canslim.growth_factors import (  # noqa: E402
    build_universe_metrics,
    merge_factors_to_daily,
)
from scripts.factor_mining.data_loader import load_universe  # noqa: E402
from scripts.factor_mining.run_logic_factor_test import (  # noqa: E402
    _daily_ic_series_for_window,
    block_bootstrap_pbo,
)

FACTOR_COLS = ["c_single_yoy", "c_ttm_yoy", "rev_ttm_yoy", "roe", "a_cagr3"]
FACTOR_FAMILY = {
    "c_single_yoy": "C", "c_ttm_yoy": "C",
    "rev_ttm_yoy": "REV", "roe": "ROE", "a_cagr3": "A",
}
GATES = {"ic": 0.01, "icir": 0.5, "pbo": 0.2}

OUT_PATH = PROJECT_ROOT / "results" / "canslim" / "factor_gate.json"


def temporal_split(dates: pd.DatetimeIndex, train: int = 504, test: int = 63, min_train: int = 252):
    ds = np.sort(pd.unique(dates))
    windows = []
    i = min_train
    while i + test <= len(ds):
        ws, we = ds[max(0, i - train)], ds[i - 1]
        ss, se = ds[i], ds[min(i + test, len(ds)) - 1]
        windows.append((ws, we, ss, se))
        i += test
    return windows


def evaluate_factor(panel_mi: pd.DataFrame, name: str, windows, fwd_col: str) -> dict | None:
    ic_by_win, res_all, tail_all, ctl_pos, n_used = [], [], [], 0, 0
    for ws, we, ss, se in windows:
        sub = panel_mi[(panel_mi.index.get_level_values(1) >= ss) &
                       (panel_mi.index.get_level_values(1) <= se)]
        if sub.empty or name not in sub.columns:
            continue
        daily = _daily_ic_series_for_window(sub, name, fwd_col, "mom20")
        n_used += 1
        if daily["raw"]:
            ic_by_win.append(float(np.mean(daily["raw"])))
        if daily["res"]:
            res_all.extend(daily["res"])
            ctl_pos += int(np.mean(daily["res"]) > 0)
        if daily["tail"]:
            tail_all.extend(daily["tail"])
    if len(ic_by_win) < 5 or not res_all:
        return None
    arr = np.array(ic_by_win)
    ic_mean, ic_std = float(arr.mean()), float(arr.std())
    icir = ic_mean / max(ic_std, 1e-10)
    res_m = float(np.mean(res_all))
    tail_m = float(np.mean(tail_all)) if tail_all else 0.0
    frac_pos = ctl_pos / max(n_used, 1)
    passed = {
        "ic": bool(abs(ic_mean) > GATES["ic"]),
        "icir": bool(abs(icir) > GATES["icir"]),
        "pbo": bool(block_bootstrap_pbo(list(arr)) < GATES["pbo"]),
        "momentum": bool(res_m > 0 and tail_m > 0 and frac_pos >= 2 / 3),
    }
    return {
        "fwd_col": fwd_col,
        "oos_ic_mean": round(ic_mean, 4),
        "oos_icir": round(icir, 4),
        "pbo": round(block_bootstrap_pbo(list(arr)), 4),
        "mom_res_ic": round(res_m, 4),
        "mom_tail_ic": round(tail_m, 4),
        "mom_pos_frac": round(frac_pos, 3),
        "n_windows": len(ic_by_win),
        "passed": passed,
        "passed_all": bool(all(passed.values()) and ic_mean > 0),
    }


def event_study(panel_flat: pd.DataFrame, qm: pd.DataFrame, windows,
                factor: str, horizon: int = 63) -> dict | None:
    """季频事件法 (§7.5): 公告日为事件, 按因子分位分层的 FwdRet 多空差。"""
    spreads = []
    ev = qm.dropna(subset=[factor]).copy()
    ev = ev[~ev.get("is_fin", pd.Series(False, index=ev.index)).astype(bool)]
    for ws, we, ss, se in windows:
        w_ev = ev[(ev["effective_date"] >= ss) & (ev["effective_date"] <= se)]
        if w_ev.empty:
            continue
        # 事件日横截面: 同一公告日 ≥10 只才分层
        for eff_dt, grp in w_ev.groupby("effective_date"):
            if len(grp) < 10:
                continue
            codes = grp["code"].tolist()
            day_rows = panel_flat[(panel_flat["code"].isin(codes)) &
                                  (panel_flat["date"] == eff_dt)]
            if len(day_rows) < 10:
                continue
            merged = day_rows[["code", f"fwd{horizon}"]].merge(
                grp[["code", factor]], on="code", how="inner"
            ).dropna()
            if len(merged) < 10:
                continue
            q_hi = merged[factor].quantile(0.8)
            q_lo = merged[factor].quantile(0.2)
            hi = merged.loc[merged[factor] >= q_hi, f"fwd{horizon}"]
            lo = merged.loc[merged[factor] <= q_lo, f"fwd{horizon}"]
            if len(hi) >= 3 and len(lo) >= 3:
                spreads.append(float(hi.median() - lo.median()))
    if len(spreads) < 8:
        return None
    arr = np.array(spreads)
    return {
        "n_events": len(spreads),
        "median_spread": round(float(np.median(arr)), 4),
        "mean_spread": round(float(arr.mean()), 4),
        "pos_frac": round(float((arr > 0).mean()), 3),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="CANSLIM 因子轨四重门 (D+4)")
    ap.add_argument("--smoke", action="store_true", help="100 只冒烟")
    ap.add_argument("--sample", type=int, default=None)
    args = ap.parse_args(argv)
    n_sample = args.sample or (100 if args.smoke else 500)

    t0 = time.time()

    # 1. 行情面板 (与 P1/P3 完全同参)
    df = load_universe(as_of="2026-05-29", max_workers=16)
    codes_all = sorted(df["code"].unique())
    rng = np.random.RandomState(42)
    selected = rng.choice(codes_all, size=min(n_sample, len(codes_all)), replace=False)
    df = df[df["code"].isin(selected)].reset_index(drop=True)
    cutoff = df["date"].sort_values().unique()[-1600]
    df = df[df["date"] >= cutoff].reset_index(drop=True)
    print(f"[1/5] 行情: {df['code'].nunique()} 只 × {df['date'].nunique()} 天")

    # 2. 季度成长指标 + 日频合并
    qm = build_universe_metrics(sorted(df["code"].unique()))
    print(f"[2/5] 财务指标: {qm['code'].nunique() if not qm.empty else 0} 只, {len(qm)} 季行")
    if qm.empty:
        print("TERMINATE: 无可用财务数据")
        return 2
    df = merge_factors_to_daily(df, qm)

    # 3. 前向收益与动量; MultiIndex 面板
    df["fwd5"] = df.groupby("code")["close"].shift(-5) / df["close"] - 1
    df["fwd63"] = df.groupby("code")["close"].shift(-63) / df["close"] - 1
    df["mom20"] = df.groupby("code")["close"].pct_change(20, fill_method=None)
    df = df[~df["is_fin"].fillna(False).astype(bool)]          # R-FIN
    panel = df.set_index(["code", "date"], drop=False)
    panel.index = panel.index.set_names(["code_idx", "date_idx"])
    windows = temporal_split(df["date"])
    print(f"[3/5] 净化后 {panel.index.get_level_values(0).nunique()} 只; 窗口数 {len(windows)}")

    # 4. 四重门 × {fwd5, fwd63} + 事件法
    report = {"_meta": {"n_symbols": int(df["code"].nunique()),
                        "as_of": "2026-05-29", "windows": len(windows),
                        "elapsed_sec": None},
              "factors": {}, "event_study": {}}
    for name in FACTOR_COLS:
        entry = {}
        for fwd in ("fwd5", "fwd63"):
            r = evaluate_factor(panel, name, windows, fwd)
            if r:
                entry[fwd] = r
        es = event_study(df, qm, windows, name, horizon=63)
        if es:
            report["event_study"][name] = es
        fam = FACTOR_FAMILY[name]
        verdict = bool(entry and any(e["passed_all"] for e in entry.values()))
        entry["family"] = fam
        entry["passed_all_any_horizon"] = verdict
        report["factors"][name] = entry
        ic5 = entry.get("fwd5", {}).get("oos_ic_mean", "—")
        print(f"  {name:<14} [{fam}] fwd5 IC={ic5} 判定={'PASS' if verdict else 'FAIL'}"
              + (f" 事件法={es['median_spread']:+.4f}(n={es['n_events']})" if es else ""))

    # 5. 早出口裁决
    fam_pass = {report["factors"][k]["family"]: report["factors"][k]["passed_all_any_horizon"]
                for k in report["factors"]}
    c_pass = fam_pass.get("C", False)
    a_pass = fam_pass.get("A", False)
    report["verdict"] = {
        "H1_C_pass": bool(c_pass), "H2_A_pass": bool(a_pass),
        "early_exit_terminate": bool(not c_pass and not a_pass),
    }
    report["_meta"]["elapsed_sec"] = round(time.time() - t0, 1)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"[5/5] H1(C)={'PASS' if c_pass else 'FAIL'} H2(A)={'PASS' if a_pass else 'FAIL'}"
          f" → {'✅ 继续 D+9 组合轨' if (c_pass or a_pass) else '⛔ 早出口: 路线终止'}")
    print(f"报告 → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())