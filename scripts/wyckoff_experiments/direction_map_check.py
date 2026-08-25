#!/usr/bin/env python3
"""T1 — P0-2 direction 映射表确定性断言 (P2-2A 验收门)。

对每个 as-of 窗口 CSV 断言 P0-2 adapter 语义:
    trading_plan_direction ∈ {做多, 买入, 轻仓试探} → BUY
    其余 → None (恒不产 SELL)
叠加 P0-4 置信门槛 0.30→0.40, 报告门槛漂移 (INFO)。

预注册阈值 (scripts/wyckoff_experiments/PREREGISTRATION_20260812.md T1):
- 断言1: 每窗 BUY 数 > 0, 否则 FAIL
- 断言2: 每窗 SELL 数 == 0, 否则 FAIL
- 覆盖率与门槛漂移仅 INFO

用法: python3 scripts/wyckoff_experiments/direction_map_check.py
输出: results/wyckoff_experiments/direction_map_check.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError as _ie:  # pragma: no cover
    sys.exit(f"pandas required: {_ie}")

from _symbols import is_index_symbol  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "wyckoff_experiments"))

BUY_DIRECTIONS = {"做多", "买入", "轻仓试探"}
WINDOWS = {
    "W1": ("results/wyckoff_xs/wyckoff_scan_all.csv", "2026-04-30"),
    "W2": ("results/wyckoff_xs2/wyckoff_scan_all.csv", "2026-03-31"),
    "W3": ("results/wyckoff_xs3/wyckoff_scan_all.csv", "2026-05-29"),
    "X4": ("results/wyckoff_xs4/wyckoff_scan_all.csv", "2025-06-30"),
    "X5": ("results/wyckoff_xs5/wyckoff_scan_all.csv", "2024-12-31"),
}


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """clean 池: fwd_20d 非空 ∩ 剔 ETF ∩ 剔指数 (符号级, 不误杀 SZ 主板股)。"""
    out = df[df["fwd_20d"].notna()].copy()
    out = out[~out["is_etf"].fillna(False)].copy()
    out = out[~out["symbol"].map(lambda s: is_index_symbol(str(s)) if pd.notna(s) else False)].copy()
    return out


def p0_2_map(direction: str) -> str:
    if direction in BUY_DIRECTIONS:
        return "BUY"
    return "None"


def main() -> int:
    results: dict = {
        "pre_registered": True,
        "windows": {},
        "summary": {},
    }
    ok = True
    for name, (path, as_of) in WINDOWS.items():
        p = ROOT / path
        if not p.exists():
            results["windows"][name] = {"error": f"missing {p}"}
            ok = False
            continue
        df = _clean(pd.read_csv(p))
        df["direction"] = df["trading_plan_direction"].fillna("空仓观望")
        mapped = df["direction"].apply(p0_2_map)

        n = len(df)
        n_buy = int((mapped == "BUY").sum())
        n_sell = int((mapped == "SELL").sum())
        n_none = n - n_buy
        # 预注册 T1 断言3: BUY 数 / clean 池非空仓观望数 (非除以全池)
        n_non_noaction = int((df["direction"] != "空仓观望").sum())
        coverage = n_buy / n_non_noaction if n_non_noaction > 0 else 0.0

        # P0-4 门槛漂移: conf>=0.30 vs conf>=0.40 的 BUY 集
        df["conf"] = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
        buy_g30 = int(((mapped == "BUY") & (df["conf"] >= 0.30)).sum())
        buy_g40 = int(((mapped == "BUY") & (df["conf"] >= 0.40)).sum())
        buy_all = int(((mapped == "BUY")).sum())
        shr_g30 = buy_g30 / buy_all if buy_all else 0.0
        shr_g40 = buy_g40 / buy_all if buy_all else 0.0

        assert1 = n_buy > 0
        assert2 = n_sell == 0
        w_ok = assert1 and assert2
        ok = ok and w_ok

        results["windows"][name] = {
            "as_of": as_of,
            "n": n,
            "n_buy": n_buy,
            "n_sell": n_sell,
            "n_none": n_none,
            "coverage_buy_over_non_noaction": round(coverage, 4),
            "assert1_buy_gt_0": assert1,
            "assert2_no_sell": assert2,
            "conf_gate_change_pct": {
                "conf>=0.30": round(shr_g30, 4),
                "conf>=0.40": round(shr_g40, 4),
                "delta": round(shr_g40 - shr_g30, 4),
            },
        }
        results["summary"][name] = "PASS" if w_ok else "FAIL"
    results["overall"] = "PASS" if ok else "FAIL"

    out = ROOT / "results" / "wyckoff_experiments"
    out.mkdir(parents=True, exist_ok=True)
    (out / "direction_map_check.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())