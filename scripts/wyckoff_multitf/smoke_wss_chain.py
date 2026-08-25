#!/usr/bin/env python3
"""Smoke test: run the full WSS training chain on a small stock subset.

Stage 1: runner_v4 panel (v4_results.json)
Stage 2: phase2_event_analysis (phase2_event_results.json)
Stage 3: phase_e_wss_retrain (wss_lookup_v2.json)

Usage:
    python3 scripts/wyckoff_multitf/smoke_wss_chain.py --stocks 000001.SZ,600000.SH
    python3 scripts/wyckoff_multitf/smoke_wss_chain.py --count 20
"""

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

OUTPUT_DIR = Path(__file__).resolve().parent / "output_v4"


def stage1_v4(stocks: list) -> int:
    from scripts.wyckoff_multitf.runner_v4 import run_panel

    obs = run_panel(stocks)
    out = {
        "meta": {"n_stocks": len(stocks), "n_obs": len(obs)},
        "data": [
            {"s": o.symbol, "c": o.cutoff, "p": o.month_phase,
             "ds": o.day_spring, "f1": o.fwd_1m, "f3": o.fwd_3m, "f6": o.fwd_6m}
            for o in obs
        ],
    }
    with open(OUTPUT_DIR / "v4_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"Smoke stage1: {len(obs)} obs -> {OUTPUT_DIR / 'v4_results.json'}")
    return len(obs)


def stage2_phase2() -> int:
    mod = importlib.import_module("scripts.wyckoff_multitf.phase2_event_analysis")
    mod.OUTPUT_DIR = OUTPUT_DIR
    mod.run()
    with open(OUTPUT_DIR / "phase2_event_results.json") as f:
        return len(json.load(f)["data"])


def stage3_phase_e() -> int:
    mod = importlib.import_module("scripts.wyckoff_multitf.phase_e_wss_retrain")
    mod.OUTPUT_DIR = OUTPUT_DIR
    mod.main()
    with open(OUTPUT_DIR / "wss_lookup_v2.json") as f:
        return len(json.load(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stocks", default="")
    ap.add_argument("--count", type=int, default=20)
    args = ap.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.stocks:
        stocks = [s for s in args.stocks.split(",") if s]
    else:
        from scripts.wyckoff_multitf.a_universe import scan_universe
        from scripts.wyckoff_multitf.config import VerifierConfig
        cfg = VerifierConfig()
        records = scan_universe(cfg)
        stocks = [r.symbol for r in records[: args.count]]

    t0 = time.time()

    n1 = stage1_v4(stocks)
    n2 = stage2_phase2()
    n3 = stage3_phase_e()
    print(f"\nSmoke chain complete in {time.time() - t0:.0f}s over {len(stocks)} stocks")
    print(f"  v4 obs: {n1} | phase2 obs: {n2} | wss sequences: {n3}")


if __name__ == "__main__":
    main()