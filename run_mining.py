#!/usr/bin/env python3
"""
Alpha Mining Runner — Session 2 (2026-06-01)
Executes 10 rounds using existing system algorithms.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import warnings
warnings.filterwarnings("ignore")

import logging
logging.getLogger("uniquant").setLevel(logging.WARNING)
logging.getLogger("TdxSource").setLevel(logging.WARNING)
logging.getLogger("mootdx").setLevel(logging.WARNING)

from uniquant.brain.factors.auto_mined.mining_harness import run_round, PASS_ICIR_THRESHOLD

# -------------------------------------------------------
# Import all factor functions
# -------------------------------------------------------
from uniquant.brain.factors.auto_mined.round_01_wyckoff_confidence import (
    compute_wyckoff_phase_confidence,
)
from uniquant.brain.factors.auto_mined.round_02_lppl_bubble_risk import (
    compute_lppl_bubble_risk,
)
from uniquant.brain.factors.auto_mined.round_03_regime_rsi_reversion import (
    compute_regime_rsi_reversion,
)
from uniquant.brain.factors.auto_mined.round_04_entropy_shock_reversion import (
    compute_entropy_shock_reversion,
)
from uniquant.brain.factors.auto_mined.round_05_vol_price_exhaustion import (
    compute_vol_price_exhaustion,
)
from uniquant.brain.factors.auto_mined.round_06_czsc_signal_score import (
    compute_czsc_signal_score,
)
from uniquant.brain.factors.auto_mined.round_07_ma_dispersion_regime import (
    compute_ma_dispersion_regime,
)
from uniquant.brain.factors.auto_mined.round_08_wyckoff_persistence import (
    compute_wyckoff_persistence,
)
from uniquant.brain.factors.auto_mined.round_09_lppl_oscillation import (
    compute_lppl_oscillation_amplitude,
)
from uniquant.brain.factors.auto_mined.round_10_multi_engine_ensemble import (
    compute_multi_engine_ensemble,
)

ROUNDS = [
    (1,  "wyckoff_phase_confidence",    "Wyckoff",     compute_wyckoff_phase_confidence),
    (2,  "lppl_bubble_risk",            "LPPL",        compute_lppl_bubble_risk),
    (3,  "regime_rsi_reversion",        "Regime+RSI",  compute_regime_rsi_reversion),
    (4,  "entropy_shock_reversion",     "Entropy",     compute_entropy_shock_reversion),
    (5,  "vol_price_exhaustion",        "Volume-Price",compute_vol_price_exhaustion),
    (6,  "czsc_signal_score",           "CZSC",        compute_czsc_signal_score),
    (7,  "ma_dispersion_regime",        "MA+Regime",   compute_ma_dispersion_regime),
    (8,  "wyckoff_persistence",         "Wyckoff",     compute_wyckoff_persistence),
    (9,  "lppl_oscillation_amplitude",  "LPPL",        compute_lppl_oscillation_amplitude),
    (10, "multi_engine_ensemble",       "Composite",   compute_multi_engine_ensemble),
]

if __name__ == "__main__":
    results = {}
    for round_num, name, category, func in ROUNDS:
        passed = run_round(round_num, name, category, func, holding_period=5)
        results[name] = passed

    print("\n" + "="*60)
    print("MINING SESSION SUMMARY")
    print("="*60)
    passed = sum(v for v in results.values())
    print(f"Passed: {passed}/{len(ROUNDS)}")
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
