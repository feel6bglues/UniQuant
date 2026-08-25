#!/usr/bin/env python3
"""D 组 — 三层验收门 (D1/D2/D3, P2-2)。

D1 确定性断言映射表 (100%): 五窗 T1 断言 + 运行时 adapter 矩阵。
  - 每窗 BUY>0, SELL==0, 无 做空/卖出 文本 → 恒 PASS ⇔ 全过
  - adapter 矩阵: direction×gate 的期望 action 断言
D2 预注册 MWU 门槛 (剔尾后 ≥2/3 窗同号 p<0.05): 无信号类达升级线。
D3 markup 置信存活表: P0-4 门槛 0.40 存活率 (每窗) + A/B/C/D×20d 超额表 (INFO)。

用法: python3 scripts/wyckoff_verify_20260812/deterministic_assertions.py
输出: results/wyckoff_verify_20260812/deterministic_assertions.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
    from scipy import stats
except ImportError as _ie:  # pragma: no cover
    sys.exit(f"numpy/pandas/scipy required: {_ie}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _common import BUY_DIRECTIONS, SIG_TYPES, load_window, sig_mask, write_out  # noqa: E402


# ─────────────────── D1: 确定性断言映射表 ───────────────────

def _t1_scsv(name: str) -> dict:
    df = load_window(name)
    direction = df["trading_plan_direction"].fillna("空仓观望")
    conf = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
    n_buy = int(direction.isin(BUY_DIRECTIONS).sum())
    n_sell_keyword = int(direction.isin({"做空", "卖出"}).sum())
    buy_gate = int((direction.isin(BUY_DIRECTIONS) & (conf >= 0.40)).sum())
    return {
        "n_buy": n_buy,
        "n_sell_keyword": n_sell_keyword,
        "buy_survive_040": buy_gate,
        "survival_rate_040": round(buy_gate / n_buy, 4) if n_buy else None,
        "a1_buy_gt_0": n_buy > 0,
        "a2_no_sell": n_sell_keyword == 0,
    }


def _adapter_matrix() -> dict:
    from uniquant.signal.adapters import WyckoffAdapter

    adapter = WyckoffAdapter()
    rows = {}
    for d in ("做多", "买入", "轻仓试探"):
        s = adapter.adapt({"wyckoff_direction": d, "wyckoff_confidence": 0.5,
                           "price": 10.0}, symbol="T")
        rows[f"{d}/0.5"] = s.action if s else None
    for d in ("做多", "轻仓试探"):
        s = adapter.adapt({"wyckoff_direction": d, "wyckoff_confidence": 0.35,
                           "price": 10.0}, symbol="T")
        rows[f"{d}/0.35_below_gate"] = s.action if s else None
    for d in ("做空", "卖出", "持有", "观察等待", "空仓观望"):
        s = adapter.adapt({"wyckoff_direction": d, "wyckoff_confidence": 0.9,
                           "price": 10.0}, symbol="T")
        rows[f"{d}/0.9"] = s.action if s else None
    return rows


def d1_run() -> dict:
    ok = True
    wrows = {}
    for name in ("W1", "W2", "W3", "X4", "X5"):
        w = _t1_scsv(name)
        w_ok = w["a1_buy_gt_0"] and w["a2_no_sell"]
        ok = ok and w_ok
        wrows[name] = w
    mat = _adapter_matrix()
    mat_expected = {
        "做多/0.5": "BUY", "买入/0.5": "BUY", "轻仓试探/0.5": "BUY",
        "做多/0.35_below_gate": None, "轻仓试探/0.35_below_gate": None,
        "做空/0.9": None, "卖出/0.9": None, "持有/0.9": None,
        "观察等待/0.9": None, "空仓观望/0.9": None,
    }
    mat_ok = all(mat.get(k) == v for k, v in mat_expected.items())
    ok = ok and mat_ok
    return {
        "windows": wrows,
        "adapter_matrix": mat,
        "adapter_matrix_expected": mat_expected,
        "adapter_matrix_ok": mat_ok,
        "all_pass": ok,
    }


# ─────────────────── D2: 预注册 MWU 门槛 ───────────────────

def d2_run() -> dict:
    per_type = {st: [] for st in SIG_TYPES}
    for name in ("W1", "W2", "W3", "X4", "X5"):
        df = load_window(name)
        trim = df[df["fwd_20d"].abs() <= 10.0]
        for st in SIG_TYPES:
            sig = trim[sig_mask(trim, st)]
            if len(sig) < 5:
                per_type[st].append({"mean": None, "p": None})
                continue
            other = trim[~sig_mask(trim, st)]
            p = np.nan
            if len(other) >= 5:
                _, p = stats.mannwhitneyu(sig["fwd_20d"], other["fwd_20d"])
            per_type[st].append({"mean": float(sig["fwd_20d"].mean()), "p": p})

    ok = True
    verdicts = {}
    for st in SIG_TYPES:
        recs = per_type[st]
        sig_w = [
            (name, rec["mean"])
            for name, rec in zip(("W1", "W2", "W3", "X4", "X5"), recs)
            if rec["mean"] is not None and rec["p"] is not None and rec["p"] < 0.05
        ]
        n_neg = sum(1 for _, m in sig_w if m < 0)
        n_pos = sum(1 for _, m in sig_w if m > 0)
        n_same = max(n_neg, n_pos)
        v_ok = n_same < 4  # ≥2/3 窗(5→4) 才达升级线
        ok = ok and v_ok
        verdicts[st] = {"same_sign_significant_n": n_same, "significant": sig_w,
                        "upgrade": not v_ok}
    return {"verdicts": verdicts, "all_pass": ok,
            "threshold": "无信号类达 2/3 多数同号 (≥4/5) 升级线 → 维持叙事/风控层"}


# ─────────────────── D3: markup 置信存活表 ───────────────────

def d3_run() -> dict:
    rows = {}
    for name in ("W1", "W2", "W3", "X4", "X5"):
        w = _t1_scsv(name)
        rows[name] = {
            "n_buy": w["n_buy"],
            "survive_040": w["buy_survive_040"],
            "survival_rate_040": w["survival_rate_040"],
        }
    # 定稿 T1b 参考 (INFO)
    ref = {"W1": 0.920, "W2": 0.900, "W3": 0.909, "X4": 0.928, "X5": 0.625}
    match = all(abs(rows[k]["survival_rate_040"] - v) < 0.005 for k, v in ref.items())
    return {"survival_table": rows, "reference": ref, "matches_reference": match}


def main() -> int:
    d1 = d1_run()
    d2 = d2_run()
    d3 = d3_run()
    overall = d1["all_pass"] and d2["all_pass"]
    results = {
        "pre_registered": True,
        "D1_deterministic_assertion_map": d1,
        "D2_preregistered_mwu_gate": d2,
        "D3_markup_survival_table": d3,
        "overall": "PASS" if overall else "FAIL",
    }
    path = write_out("deterministic_assertions", results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n→ {path}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())