"""条件信号定向验证 — 执行预注册假设 H-A / H-BL / H-BS / H-C。

预注册: docs/analysis/CONDITIONAL_VALIDATION_PREREGISTRATION.md (冻结)
门限: G1 NW-t>=3 | G2 块自助CI方向一致 | G3 动量残差NW-t>=2同号 | G4 前后半符号一致
关键升级: 主判定用 PIT 状态 (滚动750日波动分位), 全样本状态仅作对照报告。
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

from scripts.factor_mining.conditional_stats import (  # noqa: E402
    block_bootstrap_ci,
    newey_west_t,
    pit_vol_states,
)
from scripts.factor_mining.data_loader import load_universe  # noqa: E402
from scripts.factor_mining.run_logic_factor_test import (  # noqa: E402
    _daily_ic_series_for_window,
)

OUT_PATH = PROJECT_ROOT / "results" / "factor_mining" / "conditional_validation.json"

CANDIDATES = [
    {"id": "H-A", "factor": "illiq_20d", "trend": "trend_on", "vol": "vol_high",
     "direction": +1, "h": 5},
    {"id": "H-BL", "factor": "roe", "trend": "trend_on", "vol": "vol_low",
     "direction": +1, "h": 21},
    {"id": "H-BS", "factor": "roe", "trend": "trend_on", "vol": "vol_high",
     "direction": -1, "h": 21},
    {"id": "H-C", "factor": "c_single_yoy", "trend": "trend_on", "vol": "vol_low",
     "direction": +1, "h": 21},
]
G1_NWT, G3_NWT = 3.0, 2.0


def build_states(index_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (pit_states, full_states): 各含 date/trend/vol_state。"""
    from scripts.factor_mining.run_regime_conditional_ic import index_states

    idx = index_df.sort_values("date").copy()
    idx["date"] = pd.to_datetime(idx["date"])
    full = index_states(idx)
    pit_vol = pit_vol_states(idx)
    trend_map = idx[["date"]].copy()
    trend_map["trend"] = np.where(
        idx["close"] > idx["close"].rolling(200).mean(), "trend_on", "trend_off"
    )
    pit = pit_vol.merge(trend_map, on="date", how="left").dropna(subset=["trend"])
    return pit, full


def evaluate_candidate(panel_mi: pd.DataFrame, cand: dict, states: pd.DataFrame) -> dict:
    """单候选在给定状态表下的四门评估。"""
    h = cand["h"]
    sel = states[(states["trend"] == cand["trend"]) & (states["vol_state"] == cand["vol"])]
    days = pd.DatetimeIndex(sel["date"])
    sub = panel_mi[panel_mi.index.get_level_values(1).isin(days)]
    if len(sub) < 30 * 20:
        return {"error": f"状态内样本不足 (days={len(days)})"}

    daily = _daily_ic_series_for_window(sub, cand["factor"], f"fwd{h}", "mom20")
    raw = np.asarray(daily["raw"], dtype=float)
    res = np.asarray(daily["res"], dtype=float)
    if len(raw) < 60 or len(res) < 60:
        return {"error": f"有效日不足 raw={len(raw)} res={len(res)}"}

    t_raw = newey_west_t(raw, lag=h)
    t_res = newey_west_t(res, lag=h)
    point, lo, hi = block_bootstrap_ci(raw, block=10, n_boot=2000)
    direction = cand["direction"]

    half = len(raw) // 2
    m1, m2 = float(np.nanmean(raw[:half])), float(np.nanmean(raw[half:]))

    g1 = bool(direction * t_raw >= G1_NWT)
    ci_ok = (lo > 0) if direction > 0 else (hi < 0)
    g2 = bool(ci_ok)
    g3 = bool(direction * t_res >= G3_NWT)
    g4 = bool(direction * m1 > 0 and direction * m2 > 0)

    return {
        "state_days": int(len(days)), "ic_days_used": int(len(raw)),
        "mean_ic": round(point, 4),
        "nw_t_raw": round(float(t_raw), 2),
        "nw_t_resid": round(float(t_res), 2),
        "boot_ci": [round(lo, 4), round(hi, 4)],
        "half_means": [round(m1, 4), round(m2, 4)],
        "gates": {"G1_nwt": g1, "G2_ci": g2, "G3_resid": g3, "G4_halves": g4},
        "passed_all": bool(g1 and g2 and g3 and g4),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="条件信号定向验证 (预注册)")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args(argv)
    n_sample = 100 if args.smoke else 500

    t0 = time.time()

    df = load_universe(as_of="2026-05-29", max_workers=16)
    codes_all = sorted(df["code"].unique())
    rng = np.random.RandomState(42)
    selected = rng.choice(codes_all, size=min(n_sample, len(codes_all)), replace=False)
    df = df[df["code"].isin(selected)].reset_index(drop=True)
    cutoff = df["date"].sort_values().unique()[-1600]
    df = df[df["date"] >= cutoff].reset_index(drop=True)

    # 因子: 价量 composer 集 + 成长族 (与 P6 完全一致)
    from uniquant.brain.factors.composer import FactorComposer
    from scripts.canslim.growth_factors import (
        build_universe_metrics, merge_factors_to_daily,
    )

    comp = FactorComposer()
    fac = comp.compute_all_factors(df, mode="backtest")
    for c in fac.columns:
        if c not in df.columns:
            df[c] = fac[c].to_numpy()
    qm = build_universe_metrics(sorted(df["code"].unique()))
    if not qm.empty:
        df = merge_factors_to_daily(df, qm)

    need_h = {c["h"] for c in CANDIDATES}
    for h in sorted(need_h):
        df[f"fwd{h}"] = df.groupby("code")["close"].shift(-h) / df["close"] - 1
    df["mom20"] = df.groupby("code")["close"].pct_change(20, fill_method=None)
    df["date"] = pd.to_datetime(df["date"])
    print(f"[1/3] 面板 {df['code'].nunique()} 只 × {df['date'].nunique()} 天")

    idx_path = PROJECT_ROOT / "data/lake/quotes/daily/000300.SH.parquet"
    pit_states, full_states = build_states(pd.read_parquet(idx_path))
    print(f"[2/3] PIT 状态天数={len(pit_states)} 全样本状态天数={len(full_states)}")

    panel = df.set_index(["code", "date"], drop=False)
    panel.index = panel.index.set_names(["code_idx", "date_idx"])

    report = {"_meta": {"n_symbols": int(df["code"].nunique()),
                        "elapsed_sec": None,
                        "gates": "G1 nwt>=3; G2 blockCI(10,2000,seed42); "
                                 "G3 resid_nwt>=2; G4 halves"},
              "candidates": {}}

    for cand in CANDIDATES:
        entry = {"pre_registered": {k: v for k, v in cand.items()}}
        r_pit = evaluate_candidate(panel, cand, pit_states)
        entry["pit_primary"] = r_pit
        r_full = evaluate_candidate(panel, cand, full_states)
        entry["full_sample_reference"] = r_full
        passed = bool(isinstance(r_pit, dict) and r_pit.get("passed_all"))
        entry["verdict"] = "PASS" if passed else "FAIL"
        report["candidates"][cand["id"]] = entry

        def fmt(r):
            if not isinstance(r, dict) or "error" in r:
                return str(r.get("error") if isinstance(r, dict) else r)
            return (f"IC={r['mean_ic']:+.4f} NWt={r['nw_t_raw']:+.1f} "
                    f"resNWt={r['nw_t_resid']:+.1f} CI=[{r['boot_ci'][0]:+.4f},{r['boot_ci'][1]:+.4f}] "
                    f"halves={r['half_means']} gates={''.join('✓' if v else '✗' for v in r['gates'].values())}")

        print(f"  {cand['id']:<5} {cand['factor']:<14} @{cand['trend']}∧{cand['vol']} dir={cand['direction']:+d} h={cand['h']}")
        print(f"        PIT : {fmt(r_pit)} → {'PASS' if passed else 'FAIL'}")
        print(f"        FULL: {fmt(r_full)}")

    bl = report["candidates"]["H-BL"]["pit_primary"]
    bs = report["candidates"]["H-BS"]["pit_primary"]
    flip_pass = bool(
        isinstance(bl, dict) and isinstance(bs, dict)
        and bl.get("passed_all") and bs.get("passed_all")
    )
    report["verdict"] = {
        "H_A": report["candidates"]["H-A"]["pit_primary"].get("passed_all", False),
        "H_B_flip": flip_pass,
        "H_C": report["candidates"]["H-C"]["pit_primary"].get("passed_all", False),
        "any_survivor": None,
    }
    report["verdict"]["any_survivor"] = bool(
        report["verdict"]["H_A"] or report["verdict"]["H_B_flip"] or report["verdict"]["H_C"]
    )
    report["_meta"]["elapsed_sec"] = round(time.time() - t0, 1)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    v = report["verdict"]
    print(f"[3/3] 裁决: H-A={v['H_A']} H-B翻转={v['H_B_flip']} H-C={v['H_C']} "
          f"→ 幸存者存在={v['any_survivor']}")
    print(f"报告 → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())