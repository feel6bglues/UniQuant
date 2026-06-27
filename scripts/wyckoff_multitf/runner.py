#!/usr/bin/env python3
"""Wyckoff Multi-Timeframe Verification — Main Runner.

Usage:
    python -m scripts.wyckoff_multitf.runner --n-jobs 8
    python -m scripts.wyckoff_multitf.runner --quick  (50 stocks)
"""

import sys, time, json, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np

from scripts.wyckoff_multitf.config import VerifierConfig
from scripts.wyckoff_multitf.a_universe import build_universe
from scripts.wyckoff_multitf.b_multitf import analyze_batch
from scripts.wyckoff_multitf.c_hypotheses import run_all_hypotheses


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-jobs", type=int, default=6)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--max-stocks", type=int, default=0)
    args = parser.parse_args()

    config = VerifierConfig(n_jobs=args.n_jobs)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print(f"{'='*80}")
    print(f"Wyckoff Multi-Timeframe Verification v2")
    print(f"{'='*80}")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  N_jobs={config.n_jobs}, quick={args.quick}")

    # Module A: Universe
    records = build_universe(config)
    if args.quick:
        import random
        random.seed(42)
        records = random.sample(records, min(50, len(records)))
        print(f"  QUICK mode: {len(records)} stocks")
    elif args.max_stocks > 0:
        records = records[:args.max_stocks]
    print(f"  Final universe: {len(records)} stocks")

    # Module B: Multi-timeframe analysis (full data, for distribution report)
    results = analyze_batch(records, config)
    print(f"  Analyzed: {len(results)} stocks")

    # Module C: Hypothesis tests (using cutoff for forward returns)
    hypotheses = run_all_hypotheses(records, config)

    # Final report
    elapsed = time.time() - t0
    supported = sum(1 for h in hypotheses.values() if h.supported)
    total = len(hypotheses)

    print(f"\n{'='*80}")
    print(f"  VERIFICATION RESULTS")
    print(f"{'='*80}")
    for name, h in hypotheses.items():
        status = "✅" if h.supported else "❌"
        print(f"  {status} {name}: p={h.p_value:.4f}, effect={h.effect_size:+.2f}")

    print(f"\n  Supported: {supported}/{total}")
    print(f"  Elapsed: {elapsed:.0f}s")

    # Save
    output = {
        "meta": {
            "n_stocks": len(results),
            "n_jobs": config.n_jobs,
            "elapsed_seconds": elapsed,
            "quick": args.quick,
        },
        "hypotheses": {
            name: {
                "supported": h.supported,
                "p_value": h.p_value,
                "effect_size": h.effect_size,
                "details": h.details,
            }
            for name, h in hypotheses.items()
        },
    }

    out_path = config.output_dir / "verification_v2_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  Saved to: {out_path}")


if __name__ == "__main__":
    main()
