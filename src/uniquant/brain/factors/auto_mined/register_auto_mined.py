"""
Registration of auto-mined factors from Session 5 (2026-06-02).
9 factors passed ICIR >= 0.4 threshold.
Call register_all() once at startup to add them to FactorRegistry.
"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..'))


def register_all() -> None:
    """Register all passing auto-mined factors into FactorRegistry."""
    from uniquant.brain.factors.registry import FactorRegistry

    # lazy imports to avoid heavy deps at module load time
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

    _FACTORS = [
        # (registry_name, func, category, weight, description, icir)
        (
            "am_wyckoff_action",
            compute_wyckoff_phase_confidence,
            "alternative",
            0.85,
            "Wyckoff BUY/SELL action × confidence. ICIR=0.64@5d.",
        ),
        (
            "am_lppl_days_to_tc",
            compute_lppl_bubble_risk,
            "alternative",
            0.75,
            "LPPL tanh(days_to_tc/60) safety buffer. ICIR=0.58@20d.",
        ),
        (
            "am_regime_rsi_momentum",
            compute_regime_rsi_reversion,
            "technical",
            0.70,
            "Regime-conditioned RSI momentum. ICIR=0.47@5d.",
        ),
        (
            "am_entropy_shock",
            compute_entropy_shock_reversion,
            "alternative",
            0.90,
            "Market-entropy shock mean-reversion. ICIR=0.74@5d.",
        ),
        (
            "am_stealth_accumulation",
            compute_vol_price_exhaustion,
            "technical",
            0.85,
            "Stealth accumulation: low-vol up-days. ICIR=0.68@5d.",
        ),
        (
            "am_ma_dispersion_regime",
            compute_ma_dispersion_regime,
            "technical",
            0.85,
            "MA5/20/60 dispersion normalised by ATR, regime-filtered. ICIR=0.69@5d.",
        ),
        (
            "am_wyckoff_contrarian",
            compute_wyckoff_persistence,
            "alternative",
            0.75,
            "Wyckoff phase-persistence contrarian (negate). ICIR=0.61@20d.",
        ),
        (
            "am_lppl_oscillation",
            compute_lppl_oscillation_amplitude,
            "alternative",
            0.90,
            "LPPL |c|×w oscillation intensity (short signal). ICIR=1.03@5d.",
        ),
        (
            "am_multi_engine_ensemble",
            compute_multi_engine_ensemble,
            "alternative",
            1.00,
            "Rank-normalised ensemble of entropy/MA/vol/regime signals. ICIR=1.58@5d.",
        ),
    ]

    for name, func, cat, weight, desc in _FACTORS:
        FactorRegistry.register(
            name=name,
            compute_func=func,
            category=cat,
            default_weight=weight,
            description=desc,
        )
