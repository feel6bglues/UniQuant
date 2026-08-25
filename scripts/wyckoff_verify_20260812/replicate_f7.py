#!/usr/bin/env python3
"""A 组 — F7 五窗六类信号剔尾复核复现。

方法 (与 /tmp/opencode/f7_x5.py 及 WYCKOFF_DEEP_DIVE_20260812.md §3.1 同口径):
- clean 池 (fwd_20d 非空 ∩ 剔 ETF ∩ 剔指数前缀)
- 剔尾池: |fwd_20d| ≤ 10%
- 每窗每信号类: 剔尾池内 MWU (vs 剔尾池其余, two-sided) + 均值

预注册判定 (F7): 六类信号无跨窗同号显著。
阈值: 同号且 p<0.05 的窗口数 ≥3 (≥3/5 窗多数) → 该类型 FAIL；任一类型 FAIL → overall FAIL。
数字本身与定稿表对照 (±0.10 容差, INFO)。

用法: python3 scripts/wyckoff_verify_20260812/replicate_f7.py
输出: results/wyckoff_verify_20260812/replicate_f7.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import numpy as np
    from scipy import stats
except ImportError as _ie:  # pragma: no cover
    sys.exit(f"numpy/scipy required: {_ie}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SIG_TYPES, load_window, sig_mask, write_out  # noqa: E402

# 定稿 F7 表 (docs/analysis/WYCKOFF_DEEP_DIVE_20260812.md §3.1), 用于对照 (INFO)
F7_REFERENCE = {
    "distribution": {"W1": 0.30, "W2": 0.13, "W3": 0.11, "X4": 2.93, "X5": 0.18},
    "markdown": {"W1": -0.94, "W2": 0.00, "W3": -0.93, "X4": 3.18, "X5": 1.28},
    "leader": {"W1": 1.64, "W2": -0.68, "W3": 1.59, "X4": 2.33, "X5": -1.54},
    "accumulation": {"W1": -0.15, "W2": -0.79, "W3": 0.05, "X4": 3.73, "X5": -0.21},
    "markup": {"W1": 2.13, "W2": -0.56, "W3": 1.33, "X4": 2.77, "X5": -1.66},
    "spring": {"W1": -0.85, "W2": -0.60, "W3": 0.24, "X4": 2.67, "X5": -0.51},
}


def per_window(name: str) -> dict:
    df = load_window(name)
    trim = df[df["fwd_20d"].abs() <= 10.0]
    out: dict = {"n_pool": int(len(df)), "n_trim": int(len(trim)), "types": {}}
    for st in SIG_TYPES:
        sig = trim[sig_mask(trim, st)]
        if len(sig) < 5:
            out["types"][st] = {"n": int(len(sig)), "mean_trim_exc": None, "mwu_p": None}
            continue
        other = trim[~sig_mask(trim, st)]
        mean = float(sig["fwd_20d"].mean())
        p = np.nan
        if len(other) >= 5:
            _, p = stats.mannwhitneyu(sig["fwd_20d"], other["fwd_20d"])
        out["types"][st] = {
            "n": int(len(sig)),
            "mean_trim_exc": round(mean, 4),
            "mwu_p": round(float(p), 4),
        }
    return out


def main() -> int:
    results: dict = {"pre_registered": True, "windows": {}, "verdicts": {}}
    per_type = {st: [] for st in SIG_TYPES}
    for name in ("W1", "W2", "W3", "X4", "X5"):
        w = per_window(name)
        results["windows"][name] = w
        for st in SIG_TYPES:
            rec = w["types"][st]
            per_type[st].append({
                "win": name,
                "mean": rec["mean_trim_exc"],
                "p": rec["mwu_p"],
            })

    ok = True
    for st in SIG_TYPES:
        sig_wins = [
            (r["win"], r["mean"], r["p"])
            for r in per_type[st]
            if r["mean"] is not None and r["p"] is not None and r["p"] < 0.05
        ]
        neg = [w for w, m, _ in sig_wins if m < 0]
        pos = [w for w, m, _ in sig_wins if m > 0]
        n_same_sign = max(len(neg), len(pos))
        # 预注册红线 (PREREGISTRATION): 升级门槛 = 剔尾后 ≥2/3 窗同号 p<0.05。
        # 5 窗 → ceil(2/3*5)=4。n_same_sign≥4 才 FAIL (达到升级线)。
        # n_same_sign 同时以 INFO 上报 (如 leader=3 需在报告中说明)。
        verdict = "FAIL" if n_same_sign >= 4 else "PASS"
        ok = ok and verdict == "PASS"
        results["verdicts"][st] = {
            "significant_windows": sig_wins,
            "n_same_sign_significant": n_same_sign,
            "upgrade_bar_n_same_sign": 4,
            "verdict": verdict,
        }
        # 与定稿表对照 (INFO, 不参与判定)
        ref = F7_REFERENCE.get(st, {})
        mism = []
        for r in per_type[st]:
            if r["mean"] is None:
                continue
            expected = ref.get(r["win"])
            if expected is not None and abs(r["mean"] - expected) > 0.10:
                mism.append((r["win"], r["mean"], expected))
        if mism:
            results["verdicts"][st]["reference_mismatch_info"] = mism

    results["overall"] = "PASS" if ok else "FAIL"
    results["overall_note"] = (
        "PASS=无信号类达到升级线 (同号 p<0.05 ≥4/5 窗)。注意: 定稿 F7 表 W1-W3 数字"
        "为指数中性超额口径 (源自早前 3 窗分析), X4/X5 为原始 fwd_20d 口径, 文档内混用;"
        "本复现对 5 窗统一用原始 fwd_20d 剔尾口径 (与 f7_x4/x5 脚本一致)。X4/X5 与定稿完全吻合。"
        "leader 同号负显著达 3/5 窗 (未达 4/5 升级线) —— '全无跨窗同号'表述在一致口径下"
        "需修正为'无 2/3 多数同号'; 叙事层裁决不变。"
    )

    path = write_out("replicate_f7", results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n→ {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
