#!/usr/bin/env python3
"""Wyckoff Verification Framework — Main Runner.

Usage:
    python -m scripts.wyckoff_verification.runner [--n-jobs 6] [--quick]
"""

import sys
import time
import json
import argparse
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.wyckoff_verification.config import VerifierConfig
from scripts.wyckoff_verification.a_universe import build_universe
from scripts.wyckoff_verification.b_pattern_tests import run_pattern_tests
from scripts.wyckoff_verification.c_factor_model import run_factor_decomposition
from scripts.wyckoff_verification.d_strategy import run_strategy
from scripts.wyckoff_verification.e_regime import run_regime_analysis


def main():
    parser = argparse.ArgumentParser(description="Wyckoff Verification Framework")
    parser.add_argument("--n-jobs", type=int, default=6)
    parser.add_argument("--quick", action="store_true", help="Use subset of stocks for fast iteration")
    parser.add_argument("--max-stocks", type=int, default=0, help="Max stocks to process")
    args = parser.parse_args()

    config = VerifierConfig(n_jobs=args.n_jobs)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print("Wyckoff Verification Framework")
    print(f"{'='*80}")
    print(f"Runner started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"N_jobs={config.n_jobs}, quick={args.quick}")
    print()

    # ── Module A: Universe ──
    records = build_universe(config)
    if args.max_stocks > 0:
        records = records[:args.max_stocks]
    elif args.quick:
        import random
        random.seed(config.seed)
        records = random.sample(records, min(200, len(records)))
    print(f"Final universe: {len(records)} stocks")

    # Save universe list
    univ_path = config.output_dir / "universe.txt"
    univ_path.write_text("\n".join(r.symbol for r in records))
    print(f"Saved to {univ_path}")

    results = {}

    # ── Module B: Pattern Tests ──
    pattern_results = run_pattern_tests(records, config)
    results["pattern_tests"] = [
        {"hypothesis": r.hypothesis, "n_events": r.n_events,
         "mean_return": r.mean_excess_return, "ci_lower": r.ci_lower,
         "ci_upper": r.ci_upper, "hit_rate": r.hit_rate,
         "t_stat": r.t_stat, "p_value": r.p_value,
         "bh_significant": r.bh_significant}
        for r in pattern_results
    ]
    summary_path = config.output_dir / "pattern_tests.json"
    with open(summary_path, "w") as f:
        json.dump(results["pattern_tests"], f, indent=2)
    print(f"Saved to {summary_path}")

    # ── Module C: Factor Decomposition ──
    factor_result = run_factor_decomposition(records, config)
    results["factor_decomposition"] = {
        "n_events": factor_result.n_events,
        "alpha_pct": factor_result.alpha_pct,
        "alpha_t_stat": factor_result.alpha_t_stat,
        "alpha_p_value": factor_result.alpha_p_value,
    }
    factor_path = config.output_dir / "factor_decomposition.json"
    with open(factor_path, "w") as f:
        json.dump(results["factor_decomposition"], f, indent=2)

    # ── Module D: Strategy ──
    strategy_results = run_strategy(records, config)
    rets = [r.total_return_pct for r in strategy_results]
    anns = [r.annualized_return_pct for r in strategy_results]
    sharpes = [r.sharpe for r in strategy_results]
    results["strategy"] = {
        "n_stocks": len(strategy_results),
        "mean_return_pct": float(np.mean(rets)),
        "median_return_pct": float(np.median(rets)),
        "mean_annualized_pct": float(np.mean(anns)),
        "median_annualized_pct": float(np.median(anns)),
        "mean_sharpe": float(np.mean(sharpes)),
        "profitable_stocks_pct": float(sum(1 for r in rets if r > 0) / len(rets) * 100) if rets else 0,
        "total_trades": sum(r.n_trades for r in strategy_results),
    }
    strategy_path = config.output_dir / "strategy.json"
    with open(strategy_path, "w") as f:
        json.dump(results["strategy"], f, indent=2)

    # ── Module E: Regime ──
    regime_results = run_regime_analysis(strategy_results, config)
    results["regime_analysis"] = {
        k: {"n_stocks": v.n_stocks_active, "mean_return_pct": v.mean_return_pct}
        for k, v in regime_results.items()
    }

    # ── Final Summary ──
    elapsed = time.time() - t0
    results["elapsed_seconds"] = elapsed

    final_path = config.output_dir / "wyckoff_verification_results.json"
    with open(final_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n{'='*80}")
    print(f"Verification complete. {elapsed:.0f}s elapsed.")
    print(f"Results saved to: {final_path}")
    print(f"{'='*80}")

    # Print final verdict
    print("\n═══ FINAL VERDICT ═══")
    print()
    # Pattern test summary
    sig_count = sum(1 for r in pattern_results if r.bh_significant)
    print(f"Pattern Tests: {sig_count}/{len(pattern_results)} hypotheses significant (BH FDR < 0.05)")
    for r in pattern_results:
        if r.bh_significant:
            print(f"  ✅ {r.hypothesis}: mean={r.mean_excess_return:+.3f}% [{r.ci_lower:+.3f}, {r.ci_upper:+.3f}]")
    for r in pattern_results:
        if not r.bh_significant and r.n_events >= 10:
            print(f"  ❌ {r.hypothesis}: mean={r.mean_excess_return:+.3f}% (NOT significant)")

    alpha = results["factor_decomposition"].get("alpha_p_value", 1)
    print(f"\nFactor Model: alpha p-value = {alpha:.4f} {'✅' if alpha < 0.05 else '❌'}")

    strat = results["strategy"]
    print(f"\nWyckoff Strategy: ann={strat['mean_annualized_pct']:+.2f}%, "
          f"sharpe={strat['mean_sharpe']:+.3f}, "
          f"profitable={strat['profitable_stocks_pct']:.1f}%")

    print("\nRegime Decomposition:")
    for regime, data in results.get("regime_analysis", {}).items():
        print(f"  {regime}: {data['mean_return_pct']:+.2f}% avg PnL ({data['n_stocks']} stocks)")


if __name__ == "__main__":
    main()
