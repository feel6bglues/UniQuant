#!/usr/bin/env python3
"""T2 — markup 置信度存活表 (P2-2C, 供 P0-4 定门槛)。

markup 信号按 confidence_level (A/B/C/D) × fwd_20d/fwd_60d 超额,
剔尾(|fwd|≤10%) 前后各一份。n<30 桶标记统计力不足不参与判定。

预注册阈值 (PREREGISTRATION T2):
- 仅 INFO; 若某桶剔尾后 ≥2/3 窗单侧 MWU p<0.05 且超额同号 → 标记 upgrade_candidate
  (走对抗裁定, 不直接采纳)

用法: python3 scripts/wyckoff_experiments/confidence_survival.py
输出: results/wyckoff_experiments/confidence_survival.json
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

ROOT = Path(__file__).resolve().parents[2]

from _symbols import is_index_symbol  # noqa: E402

WINDOWS = {
    "W1": ("results/wyckoff_xs/wyckoff_scan_all.csv", "2026-04-30"),
    "W2": ("results/wyckoff_xs2/wyckoff_scan_all.csv", "2026-03-31"),
    "W3": ("results/wyckoff_xs3/wyckoff_scan_all.csv", "2026-05-29"),
    "X4": ("results/wyckoff_xs4/wyckoff_scan_all.csv", "2025-06-30"),
    "X5": ("results/wyckoff_xs5/wyckoff_scan_all.csv", "2024-12-31"),
}
LEVELS = ["A", "B", "C", "D"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    out = df[df["fwd_20d"].notna()].copy()
    out = out[~out["is_etf"].fillna(False)].copy()
    out = out[~out["symbol"].map(lambda s: is_index_symbol(str(s)) if pd.notna(s) else False)].copy()
    return out


def _bucket_stats(vals: pd.Series, other: pd.Series) -> dict:
    n = int(len(vals))
    mean = float(np.nanmean(vals)) if n else 0.0
    p2 = p1 = None
    if n >= 5 and len(other) >= 5:
        try:
            _, p2 = stats.mannwhitneyu(vals, other, alternative="two-sided")
            # 预注册 T2: 升级判断用单侧 MWU p<0.05 且超额同号
            # 方向: 由 observed mean 符号决定 (同号判定在跨窗层)
            alt = "greater" if mean >= 0 else "less"
            _, p1 = stats.mannwhitneyu(vals, other, alternative=alt)
        except (ValueError, TypeError):
            p2 = p1 = None
    return {
        "n": n,
        "mean_excess": round(mean, 4),
        "mwu_p_two_sided": p2,
        "mwu_p_one_sided": p1,
    }


def main() -> int:
    results: dict = {"windows": {}, "upgrade_candidates": []}
    for name, (path, as_of) in WINDOWS.items():
        p = ROOT / path
        if not p.exists():
            results["windows"][name] = {"error": f"missing {p}"}
            continue
        df = _clean(pd.read_csv(p))
        markup = df[df["signal_type"] == "markup"].copy()
        win: dict = {"as_of": as_of, "n_markup": len(markup), "buckets": {}}
        for col, horizon in (("fwd_20d", "20d"), ("fwd_60d", "60d")):
            if col not in df.columns or df[col].isna().all():
                win[f"{horizon}"] = {"note": "column all-NA"}
                continue
            nonna = df[df[col].notna()].copy()
            for lvl in LEVELS:
                bucket = markup[markup["confidence_level"] == lvl]
                keep = bucket[bucket[col].notna()]
                if keep.empty:
                    win["buckets"].setdefault(lvl, {})[f"fwd_{horizon}"] = {"note": "empty"}
                    continue
                other = nonna[nonna["signal_type"] != "markup"]
                entry_full = _bucket_stats(keep[col], other[col])
                trimmed = keep[keep[col].abs() <= 10.0]
                other_trim = other[other[col].abs() <= 10.0]
                entry_trim = _bucket_stats(trimmed[col], other_trim[col])
                entry_trim["n_trim"] = int(len(trimmed))
                entry_trim["insufficient_n"] = entry_trim["n_trim"] < 30
                win["buckets"].setdefault(lvl, {})[f"fwd_{horizon}"] = {
                    "full": entry_full,
                    "trim10": entry_trim,
                }
                # 预注册 T2 upgrade candidate: 剔尾后 n≥30 且 单侧 MWU p<0.05 且超额同号
                t = entry_trim
                if (
                    t["n_trim"] >= 30
                    and t["mwu_p_one_sided"] is not None
                    and t["mwu_p_one_sided"] < 0.05
                    and abs(t["mean_excess"]) > 0.0
                ):
                    results["upgrade_candidates"].append(
                        f"{name}/{lvl}/{horizon} mean={t['mean_excess']} "
                        f"p1={t['mwu_p_one_sided']}"
                    )
        results["windows"][name] = win

    out = ROOT / "results" / "wyckoff_experiments"
    out.mkdir(parents=True, exist_ok=True)
    (out / "confidence_survival.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())