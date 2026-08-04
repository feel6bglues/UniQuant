#!/usr/bin/env python3
"""Phase E: WSS retrain on full universe data.

Runs Phase II event detection on all stocks in v4_results.json (if not
already done for the full universe), then retrains the WSS lookup table
with the expanded sample.

Usage:
    python3 scripts/wyckoff_multitf/phase_e_wss_retrain.py [--force]
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from scipy import stats

from src.uniquant.brain.wyckoff.events import detect_all_events, event_sequence_key

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(__file__).parent / "output_v4"
DATA_LAKE = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
N_JOBS = max(1, len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1)

import pandas as pd


def load_daily(symbol: str):
    fp = DATA_LAKE / f"{symbol}.parquet"
    if not fp.exists():
        return None
    try:
        df = pd.read_parquet(fp)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        if len(df) < 200:
            return None
        return df
    except Exception:
        return None


def window_before(daily: pd.DataFrame, cutoff_ts, lookback=120):
    import numpy as np
    date_arr = daily["date"].values
    pos = int(np.searchsorted(date_arr, np.datetime64(cutoff_ts), side="right")) - 1
    if pos < lookback:
        return None
    return daily.iloc[pos - lookback + 1: pos + 1].reset_index(drop=True)


def compute_events_for_obs(daily: pd.DataFrame, obs: dict) -> dict | None:
    try:
        cutoff = pd.Timestamp(obs["c"])
        w = window_before(daily, cutoff, lookback=120)
        if w is None or len(w) < 60:
            return None
        events = detect_all_events(w)
        seq_key = event_sequence_key(events)
        event_types = [e.event_type for e in events if e.confidence > 0.3]
        # Compute WSO score inline
        from src.uniquant.brain.wyckoff.sequence import WSOScorer
        wso_score = WSOScorer.score_events(event_types)
        has_spring = any(e.event_type == "Spring" for e in events)
        spring_count = sum(1 for e in events if e.event_type == "Spring")
        return {
            "s": obs.get("s", ""),
            "c": obs.get("c", ""),
            "f6": obs.get("f6", 0),
            "events": event_types,
            "seq": seq_key,
            "n_events": len(event_types),
            "wso_score": wso_score,
            "has_spring": has_spring,
            "spring_count": spring_count,
        }
    except Exception:
        return None


def load_base_results() -> list[dict]:
    src = OUTPUT_DIR / "v4_results.json"
    if not src.exists():
        print(f"ERROR: {src} not found. Run runner_v4.py first.")
        sys.exit(1)
    with open(src) as f:
        data = json.load(f)
    return data["data"]


def detect_events_for_universe(observations: list[dict]) -> list[dict]:
    from concurrent.futures import ProcessPoolExecutor, as_completed
    import time

    # Group observations by symbol
    sym_obs: dict[str, list[dict]] = defaultdict(list)
    for o in observations:
        sym_obs[o["s"]].append(o)

    results = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=N_JOBS) as pool:
        def process_one(symbol: str):
            daily = load_daily(symbol)
            if daily is None:
                return []
            return [r for o in sym_obs[symbol] if (r := compute_events_for_obs(daily, o)) is not None]

        fut = {pool.submit(process_one, s): s for s in sym_obs}
        done = 0
        total = len(sym_obs)
        for f in as_completed(fut):
            done += 1
            try:
                batch = f.result()
                results.extend(batch)
            except Exception:
                pass
            if done % 200 == 0 or done == total:
                print(f"  {done}/{total} stocks, {len(results)} obs, {time.time()-t0:.0f}s")

    print(f"Event detection complete: {len(results)} obs in {time.time()-t0:.0f}s")
    return results


def build_wss_lookup(event_data: list[dict], min_obs: int = 15) -> dict:
    seq_returns: dict[str, list[float]] = defaultdict(list)
    for obs in event_data:
        seq = obs.get("seq", "NONE")
        if seq in ("NONE", "LOW_CONF"):
            continue
        seq_returns[seq].append(obs.get("f6", 0))

    lookup = {}
    max_abs_t = 0.0
    for seq, rets in seq_returns.items():
        if len(rets) < min_obs:
            continue
        arr = np.array(rets)
        t_s, _ = stats.ttest_1samp(arr, 0)
        max_abs_t = max(max_abs_t, abs(t_s))
        lookup[seq] = {
            "n": len(rets),
            "mean": float(np.mean(arr)),
            "t": float(t_s),
            "win_rate": float(np.mean(arr > 0)),
            "std": float(np.std(arr)),
        }

    max_t = max_abs_t if max_abs_t > 0 else 1.0
    for seq in lookup:
        info = lookup[seq]
        t_norm = abs(info["t"]) / max_t
        mean_norm = info["mean"] / 100.0
        wr_bonus = (info["win_rate"] - 0.5) * 2
        info["wss"] = round(t_norm * mean_norm + 0.3 * wr_bonus * t_norm, 6)

    return lookup


def main():
    event_src = OUTPUT_DIR / "phase2_event_results.json"
    if not event_src.exists():
        print(f"ERROR: {event_src} not found. Run phase2_event_analysis.py first.")
        sys.exit(1)

    with open(event_src) as f:
        event_data = json.load(f)["data"]
    print(f"Loaded {len(event_data)} observations from Phase II output")

    print(f"\nBuilding WSS lookup from {len(event_data)} observations...")
    lookup = build_wss_lookup(event_data, min_obs=15)
    print(f"  {len(lookup)} qualifying sequences")

    # Compare with old lookup if it exists
    old_path = OUTPUT_DIR / "wss_lookup.json"
    if old_path.exists():
        with open(old_path) as f:
            old_lookup = json.load(f)
        print(f"  Old lookup: {len(old_lookup)} sequences")
        shared = set(old_lookup.keys()) & set(lookup.keys())
        print(f"  Shared sequences: {len(shared)}")
        if shared:
            old_wss = np.array([old_lookup[s].get("wss", old_lookup[s]) if isinstance(old_lookup[s], dict) else old_lookup[s] for s in shared])
            new_wss = np.array([lookup[s]["wss"] for s in shared])
            corr = np.corrcoef(old_wss, new_wss)[0, 1]
            print(f"  WSS correlation (shared sequences): {corr:.4f}")

    out_path = OUTPUT_DIR / "wss_lookup_v2.json"
    with open(out_path, "w") as f:
        json.dump(lookup, f, indent=2)
    print(f"WSS lookup v2 saved to {out_path} ({len(lookup)} sequences)")


if __name__ == "__main__":
    main()
