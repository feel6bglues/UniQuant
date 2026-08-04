#!/usr/bin/env python3
"""Phase 8b Multi-Regime OOS: 6-regime-window cross-validation.

Reads phase2_event_results.json, splits into 6 independent train/test
regime windows (2015 crash, 2018 trade war, 2020 COVID, 2021 recovery,
2022 tightening, 2023 bear), reports signal decay metrics per window
and aggregated cross-regime stability.

Usage:
    python3 scripts/wyckoff_multitf/phase8_multi_regime_oos.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.uniquant.brain.wyckoff.sequence import WSOScorer
from src.uniquant.shared.cost_model import calculate_sharpe_ratio
from scripts.wyckoff_multitf.regime_detector import MarketRegimeDetector

OUTPUT_DIR = Path(__file__).parent / "output_v4"

# 6 independent regime windows with explicit date ranges
# Each window: train = pre-regime data, test = regime period
REGIME_WINDOWS = [
    {
        "name": "2015_crash",
        "train": ("2012-01-01", "2015-05-31"),
        "test": ("2015-06-01", "2016-02-29"),
        "expected": "bear",
    },
    {
        "name": "2018_trade_war",
        "train": ("2015-07-01", "2017-12-31"),
        "test": ("2018-01-01", "2018-12-31"),
        "expected": "bear",
    },
    {
        "name": "2020_covid",
        "train": ("2017-01-01", "2019-12-31"),
        "test": ("2020-01-01", "2020-06-30"),
        "expected": "bear",
    },
    {
        "name": "2021_recovery",
        "train": ("2018-01-01", "2020-12-31"),
        "test": ("2021-01-01", "2021-12-31"),
        "expected": "bull",
    },
    {
        "name": "2022_tightening",
        "train": ("2019-01-01", "2021-12-31"),
        "test": ("2022-01-01", "2022-12-31"),
        "expected": "bear",
    },
    {
        "name": "2023_bear",
        "train": ("2020-01-01", "2022-12-31"),
        "test": ("2023-01-01", "2024-06-30"),
        "expected": "bear",
    },
]

BOOTSTRAP_N = 2000


def winsorized_stats(arr: np.ndarray) -> dict:
    if len(arr) < 3:
        return {"n": 0, "mean": 0.0, "t": 0.0, "median": 0.0, "sharpe": 0.0, "win_rate": 0.0}
    lo, hi = np.percentile(arr, [1, 99])
    w = np.clip(arr, lo, hi)
    n = len(arr)
    mean = float(np.mean(arr))
    med = float(np.median(arr))
    wmean = float(np.mean(w))
    wstd = float(np.std(w, ddof=1))
    wse = wstd / math.sqrt(n)
    t = wmean / wse if wse > 0 else 0.0
    wr = float(np.mean(arr > 0))
    sharpe = calculate_sharpe_ratio(arr / 100.0, period_days=126)
    return {"n": n, "mean": mean, "median": med, "t": t, "sharpe": sharpe, "win_rate": wr}


def bootstrap_mean(arr: np.ndarray, n_boot: int = BOOTSTRAP_N) -> tuple[float, float]:
    if len(arr) < 3:
        return (0.0, 0.0)
    means = np.array([np.mean(np.random.choice(arr, len(arr), replace=True)) for _ in range(n_boot)])
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def load_data() -> list[dict]:
    src = OUTPUT_DIR / "phase2_event_results.json"
    if not src.exists():
        print(f"ERROR: {src} not found. Run phase2_event_analysis.py first.")
        sys.exit(1)
    with open(src) as f:
        data = json.load(f)["data"]
    print(f"Loaded {len(data)} observations from {src}")
    return data


def filter_window(data: list[dict], start: str, end: str) -> list[dict]:
    return [o for o in data if start <= o.get("c", "") <= end]


def signal_stats(obs: list[dict]) -> dict:
    buy_f6 = np.array([o["f6"] for o in obs if o.get("wso_signal") == "buy" and o.get("f6") is not None])
    sell_f6 = np.array([-o["f6"] for o in obs if o.get("wso_signal") == "sell" and o.get("f6") is not None])
    all_f6 = np.array([o["f6"] for o in obs if o.get("f6") is not None])
    mkt_ret = float(np.median(all_f6)) if len(all_f6) > 0 else 0.0
    result = {"market_return": mkt_ret}
    for label, arr in [("buy", buy_f6), ("sell", sell_f6)]:
        s = winsorized_stats(arr)
        result[label] = s
        if s["n"] > 0:
            result[f"{label}_relative_alpha"] = s["mean"] - mkt_ret
        else:
            result[f"{label}_relative_alpha"] = 0.0
    if result.get("buy", {}).get("n", 0) > 0 and result.get("sell", {}).get("n", 0) > 0:
        result["long_short_spread"] = result["buy"]["mean"] - result["sell"]["mean"]
    else:
        result["long_short_spread"] = 0.0
    return result


def run_window_oos(data: list[dict], window: dict) -> dict:
    train_raw = filter_window(data, window["train"][0], window["train"][1])
    test_raw = filter_window(data, window["test"][0], window["test"][1])
    if len(train_raw) < 100 or len(test_raw) < 50:
        return {"name": window["name"], "error": f"insufficient_data: train={len(train_raw)} test={len(test_raw)}"}
    scorer = WSOScorer()
    for obs in train_raw:
        events = obs.get("events", [])
        obs["wso_score"], obs["wso_signal"] = scorer.score_events(events), scorer.signal(
            scorer.score_events(events)
        )
    for obs in test_raw:
        events = obs.get("events", [])
        obs["wso_score"], obs["wso_signal"] = scorer.score_events(events), scorer.signal(
            scorer.score_events(events)
        )
    train_stats = signal_stats(train_raw)
    test_stats = signal_stats(test_raw)
    result = {"name": window["name"], "expected_regime": window["expected"]}
    for label in ["buy", "sell"]:
        if train_stats[label]["n"] > 0 and test_stats[label]["n"] > 0:
            train_ci = bootstrap_mean(np.array([o["f6"] for o in train_raw if o.get("wso_signal") == label]))
            test_ci = bootstrap_mean(np.array([o["f6"] for o in test_raw if o.get("wso_signal") == label]))
            decay = test_stats[label]["mean"] - train_stats[label]["mean"]
            result[f"{label}_train"] = {**train_stats[label], "ci_95": train_ci}
            result[f"{label}_test"] = {**test_stats[label], "ci_95": test_ci}
            result[f"{label}_decay"] = round(decay, 4)
            rel_alpha_decay = (test_stats.get(f"{label}_relative_alpha", 0)
                               - train_stats.get(f"{label}_relative_alpha", 0))
            result[f"{label}_relative_alpha_decay"] = round(rel_alpha_decay, 4)
    result["train_n"] = len(train_raw)
    result["test_n"] = len(test_raw)
    return result


def main():
    data = load_data()
    detector = MarketRegimeDetector()
    try:
        detector.load_index_data()
    except FileNotFoundError:
        print("WARNING: CSI 300 index data not found, regime labels will not be verified")

    all_results = []
    for window in REGIME_WINDOWS:
        print(f"\n── {window['name']} ({window['test'][0]} to {window['test'][1]}) ──")
        result = run_window_oos(data, window)
        all_results.append(result)
        if "error" in result:
            print(f"  SKIPPED: {result['error']}")
            continue
        print(f"  Train N={result['train_n']}, Test N={result['test_n']}")
        for label in ["buy", "sell"]:
            if label in result:
                tr = result[f"{label}_train"]
                te = result[f"{label}_test"]
                decay = result[f"{label}_decay"]
                ra_decay = result.get(f"{label}_relative_alpha_decay", 0)
                print(f"  {label:5s}: train f6={tr['mean']:+7.2f}% t={tr['t']:+7.2f}  "
                      f"test f6={te['mean']:+7.2f}% t={te['t']:+7.2f}  "
                      f"decay={decay:+7.2f}  α_decay={ra_decay:+7.2f}")

    # Cross-regime stability summary
    print(f"\n{'=' * 70}")
    print("CROSS-REGIME STABILITY SUMMARY")
    print(f"{'=' * 70}")
    print(f"  {'Window':<20} {'Regime':<10} {'Buy_f6':>9} {'Buy_t':>8} {'Sell_f6':>9} {'Sell_t':>8}")
    decay_buys = []
    decay_sells = []
    for r in all_results:
        if "error" in r:
            continue
        bt = r.get("buy_test", {})
        st = r.get("sell_test", {})
        print(f"  {r['name']:<20} {r['expected_regime']:<10} "
              f"{bt.get('mean', 0):>+9.2f} {bt.get('t', 0):>+8.2f} "
              f"{st.get('mean', 0):>+9.2f} {st.get('t', 0):>+8.2f}")
        decay_buys.append(r.get("buy_decay", 0))
        decay_sells.append(r.get("sell_decay", 0))

    if decay_buys:
        b_arr = np.array(decay_buys)
        s_arr = np.array(decay_sells)
        print(f"\n  Cross-regime buy α-decay:  mean={np.mean(b_arr):+7.2f}  std={np.std(b_arr):.2f}")
        print(f"  Cross-regime sell α-decay: mean={np.mean(s_arr):+7.2f}  std={np.std(s_arr):.2f}")

    out_path = OUTPUT_DIR / "phase8_multi_regime_oos.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
