#!/usr/bin/env python3
"""V3: WSO EMA 信号压缩比验证

假设: EMA(span=5) 平滑降低 WSO 分值方差的同时保留预测信号，
      从而提高信噪比。

方法:
  1. 加载 phase6_combined_results.json (22K 观测 + 事件序列)
  2. 对每只股票按时序排列观测
  3. 分别用 WSOScorer (有 EMA) 和 raw score-only 模式评分
  4. 对比:  方差比(σ_raw/σ_smooth), 信号翻转率, f6 相关衰减
"""

import sys
import json
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.uniquant.brain.wyckoff.sequence import WSOScorer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = PROJECT_ROOT / "scripts" / "wyckoff_multitf" / "output_v4"
PHASE6 = OUTPUT / "phase6_combined_results.json"


def main():
    print("=" * 60)
    print("  V3: WSO EMA 信号压缩比验证")
    print("=" * 60)

    with open(PHASE6) as f:
        data = json.load(f)
    rows = data["data"]
    print(f"\nPhase6 观测数: {len(rows)}")

    df = pd.DataFrame(rows)

    # Track raw vs smoothed scores by stock
    stocks = defaultdict(list)
    exclude_stock = {"date": "date", "f6": 0.0, "events": []}
    for _, r in df.iterrows():
        s = r.get("s", "")
        events_raw = r.get("events", [])
        if isinstance(events_raw, list):
            events = events_raw
        else:
            events = []
        stocks[s].append({
            "date": r.get("c", ""),
            "f6": r.get("f6", 0.0),
            "f3": r.get("f3", 0.0),
            "events": events,
            "wso_sig": r.get("wso_sig", "hold"),
            "wso_score": r.get("wso_score", 0.0),
        })

    raw_scores = []
    smooth_scores = []
    raw_sigs = []
    smooth_sigs = []
    raw_f6 = []
    smooth_f6 = []
    flip_count = 0
    total_obs = 0
    total_stocks = 0

    for sym, obs_list in stocks.items():
        if len(obs_list) < 2:
            continue
        obs_list.sort(key=lambda x: x["date"])
        total_stocks += 1

        scorer_smooth = WSOScorer()

        prev_raw_sig = None
        prev_smooth_sig = None

        for ob in obs_list:
            events = ob["events"]
            if not events:
                continue
            total_obs += 1

            # Raw: fresh WSOScorer per call (first call returns raw since _is_warm=False)
            scorer_raw = WSOScorer()
            raw = scorer_raw.score_events(events,
                                          has_spring=False, spring_event_count=0)

            smooth = scorer_smooth.score_events(events)

            raw_sig = WSOScorer.signal(raw)
            smooth_sig = WSOScorer.signal(smooth)

            raw_scores.append(raw)
            smooth_scores.append(smooth)
            raw_f6.append(ob["f6"])
            smooth_f6.append(ob["f6"])

            if prev_raw_sig and prev_raw_sig != raw_sig:
                flip_count += 1
            prev_raw_sig = raw_sig
            prev_smooth_sig = smooth_sig

    raw_arr = np.array(raw_scores, dtype=np.float64)
    smooth_arr = np.array(smooth_scores, dtype=np.float64)

    print(f"  有效股票: {total_stocks}")
    print(f"  有效观测: {total_obs}")
    print(f"  信号翻转: {flip_count}\n")

    # ── 1. Variance comparison ──
    print("=" * 60)
    print("  1. 方差对比")
    print("=" * 60)
    raw_var = np.var(raw_arr)
    smooth_var = np.var(smooth_arr)
    raw_std = np.std(raw_arr)
    smooth_std = np.std(smooth_arr)
    ratio = raw_var / smooth_var if smooth_var > 0 else float("inf")
    print(f"  Raw score 方差: {raw_var:.6f}  (std={raw_std:.4f})")
    print(f"  Smoothed score 方差: {smooth_var:.6f}  (std={smooth_std:.4f})")
    print(f"  压缩比 (σ_raw/σ_smooth): {raw_std / smooth_std:.4f}")
    print(f"  压缩比 (Var_raw/Var_smooth): {ratio:.4f}")

    # ── 2. Signal distribution ──
    print("\n" + "=" * 60)
    print("  2. 信号分布")
    print("=" * 60)
    raw_sig_arr = np.array([WSOScorer.signal(s) for s in raw_scores])
    smooth_sig_arr = np.array([WSOScorer.signal(s) for s in smooth_scores])
    for name, arr in [("Raw", raw_sig_arr), ("Smooth", smooth_sig_arr)]:
        buy = (arr == "buy").sum()
        sell = (arr == "sell").sum()
        hold = (arr == "hold").sum()
        n = len(arr)
        print(f"  {name}: buy={buy} ({buy/n:.1%}), sell={sell} ({sell/n:.1%}), hold={hold} ({hold/n:.1%})")

    # ── 3. Signal stability: consecutive diff ──
    print("\n" + "=" * 60)
    print("  3. 信号稳定性 (一阶差分均方根)")
    print("=" * 60)
    raw_diff = np.diff(raw_arr)
    smooth_diff = np.diff(smooth_arr)
    raw_rms = np.sqrt(np.mean(raw_diff ** 2))
    smooth_rms = np.sqrt(np.mean(smooth_diff ** 2))
    print(f"  Raw score 一阶差分RMS: {raw_rms:.6f}")
    print(f"  Smoothed score 一阶差分RMS: {smooth_rms:.6f}")
    print(f"  稳定性提升比: {raw_rms / smooth_rms:.4f}x")

    # ── 4. f6 correlation ──
    print("\n" + "=" * 60)
    print("  4. f6 Pearson 相关")
    print("=" * 60)
    f6_arr = np.array(raw_f6, dtype=np.float64)
    from scipy.stats import pearsonr
    r_raw, p_raw = pearsonr(raw_arr, f6_arr)
    r_smooth, p_smooth = pearsonr(smooth_arr, f6_arr)
    print(f"  Raw vs f6:     r = {r_raw:+.4f}, p = {p_raw:.6f}")
    print(f"  Smooth vs f6:  r = {r_smooth:+.4f}, p = {p_smooth:.6f}")
    print(f"  信号保留率: {r_smooth / r_raw:.4f}" if r_raw != 0 else "  无法计算 (r_raw=0)")

    # ── 5. Signal consistency (flipping rate) ──
    print("\n" + "=" * 60)
    print("  5. 信号翻转率")
    print("=" * 60)
    raw_flips = sum(1 for i in range(1, len(raw_sig_arr))
                    if raw_sig_arr[i] != raw_sig_arr[i - 1])
    smooth_flips = sum(1 for i in range(1, len(smooth_sig_arr))
                       if smooth_sig_arr[i] != smooth_sig_arr[i - 1])
    print(f"  Raw signal flips:    {raw_flips} ({raw_flips/len(raw_sig_arr):.2%})")
    print(f"  Smooth signal flips: {smooth_flips} ({smooth_flips/len(smooth_sig_arr):.2%})")
    flip_reduction = 1 - smooth_flips / raw_flips if raw_flips > 0 else 0
    print(f"  翻转减少: {flip_reduction:.1%}")

    # ── 6. Histogram bins ──
    print("\n" + "=" * 60)
    print("  6. Score 分位统计")
    print("=" * 60)
    for pct in [5, 25, 50, 75, 95]:
        print(f"  P{pct:02d}:  raw={np.percentile(raw_arr, pct):+.6f}, "
              f"smooth={np.percentile(smooth_arr, pct):+.6f}")

    print("\n" + "=" * 60)
    print("  V3 验证结论")
    print("=" * 60)
    conclusion = f"""
  WSO EMA(span=5) 效果:
    方差压缩比: {raw_std / smooth_std:.4f}x
    稳定性提升: {raw_rms / smooth_rms:.4f}x
    信号翻转减少: {flip_reduction:.1%}
    f6 相关度: raw r={r_raw:+.4f} → smooth r={r_smooth:+.4f}

  结论:
  {'✅ EMA 在保留 f6 相关性的同时显著降低噪声' if r_smooth >= r_raw * 0.9 else '⚠️ EMA 过度衰减信号, 保留率不足 90%'}
  {'✅ 翻转率显著降低' if flip_reduction > 0.2 else '⚠️ 翻转减少幅度有限'}
"""
    print(conclusion)

    out_path = OUTPUT / "v3_wso_ema_results.json"
    summary = {
        "raw_var": float(raw_var), "smooth_var": float(smooth_var),
        "raw_std": float(raw_std), "smooth_std": float(smooth_std),
        "compression_ratio": float(raw_std / smooth_std),
        "raw_f6_r": float(r_raw), "smooth_f6_r": float(r_smooth),
        "raw_rms": float(raw_rms), "smooth_rms": float(smooth_rms),
        "raw_flips": int(raw_flips), "smooth_flips": int(smooth_flips),
        "flip_reduction": float(flip_reduction),
    }
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  结果已保存: {out_path}")


if __name__ == "__main__":
    main()
