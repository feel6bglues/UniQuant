#!/usr/bin/env python3
"""V2: P0 实施后方向映射实证验证。

对 5 窗口 × trading_plan_direction 调用 WyckoffAdapter 做方向映射，
验证 P0 实施后 BUY>0 且 SELL==0。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import BUY_DIRECTIONS, WINDOWS, load_window, write_out

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from uniquant.signal.adapters import WyckoffAdapter

ADAPTER = WyckoffAdapter()
CONFIDENCE_GATE = 0.40


def _direction_lookup(dfs: dict[str, pd.DataFrame]) -> dict[str, str | None]:
    all_texts: set[str] = set()
    for df in dfs.values():
        col = df["trading_plan_direction"].fillna("空仓观望")
        all_texts.update(col.unique())
    lookup = {}
    for txt in sorted(all_texts):
        sig = ADAPTER.adapt(
            {"wyckoff_direction": txt, "wyckoff_confidence": 0.99, "price": 10.0},
            symbol="LOOKUP",
        )
        lookup[txt] = sig.action if sig else None
    return lookup


def _analyze_window(df: pd.DataFrame, name: str) -> dict:
    directions = df["trading_plan_direction"].fillna("空仓观望")
    confidences = df["confidence"].fillna(0.0)
    last_close = df.get("last_close", pd.Series([10.0] * len(df))).fillna(10.0)

    n_buy = 0
    n_none = 0
    n_sell = 0
    n_buy_gate40 = 0
    n_direction_only = 0
    n_non_neutral = 0

    for i in range(len(df)):
        d = str(directions.iloc[i])
        c = float(confidences.iloc[i])
        price = float(last_close.iloc[i])

        if d != "空仓观望":
            n_non_neutral += 1

        if d in BUY_DIRECTIONS:
            n_direction_only += 1
            if c >= CONFIDENCE_GATE:
                n_buy_gate40 += 1

        sig = ADAPTER.adapt(
            {"wyckoff_direction": d, "wyckoff_confidence": c, "price": price},
            symbol=str(df["symbol"].iloc[i]),
        )
        if sig is None:
            n_none += 1
        elif sig.action == "BUY":
            n_buy += 1
        else:
            n_sell += 1

    coverage = round(n_buy / n_non_neutral, 4) if n_non_neutral > 0 else 0.0

    return {
        "window": name,
        "as_of_date": WINDOWS[name][1],
        "n_total": len(df),
        "n_non_neutral": n_non_neutral,
        "n_buy": n_buy,
        "n_none": n_none,
        "n_sell": n_sell,
        "n_direction_only": n_direction_only,
        "n_buy_gate40": n_buy_gate40,
        "coverage": coverage,
        "buy_gt_0": n_buy > 0,
        "sell_eq_0": n_sell == 0,
    }


def main():
    dfs = {}
    results = []
    all_pass = True

    for name in WINDOWS:
        df = load_window(name)
        dfs[name] = df
        r = _analyze_window(df, name)
        results.append(r)
        if not (r["buy_gt_0"] and r["sell_eq_0"]):
            all_pass = False

    lookup = _direction_lookup(dfs)

    payload = {
        "meta": {
            "script": "v2_post_p0_direction_map.py",
            "description": "P0 实施后方向映射实证验证 — adapter direction gate 分布",
            "windows": list(WINDOWS.keys()),
            "entry_directions": sorted(BUY_DIRECTIONS),
            "confidence_gate": CONFIDENCE_GATE,
        },
        "verdict": {
            "overall_pass": all_pass,
            "rule": "V2 PASS ⇔ 5/5 窗 BUY>0 且 SELL==0",
            "all_buy_gt_0": all(r["buy_gt_0"] for r in results),
            "all_sell_eq_0": all(r["sell_eq_0"] for r in results),
            "details": {r["window"]: {"buy_gt_0": r["buy_gt_0"], "sell_eq_0": r["sell_eq_0"]} for r in results},
        },
        "per_window": results,
        "direction_lookup": lookup,
    }

    path = write_out("v2_post_p0_direction_map", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nWritten to {path}", file=sys.stderr)

    if not all_pass:
        print("FAIL: Not all windows satisfy BUY>0 and SELL==0", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()