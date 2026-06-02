"""
Round 10: Multi-Engine Composite Alpha
Combines signals from the cheapest/most robust sub-factors:
  - Regime-RSI reversion (Round 3)
  - Entropy shock reversion (Round 4)
  - Volume-price exhaustion (Round 5)
  - MA dispersion + regime (Round 7)
Weights are equal; each sub-signal is rank-normalised before combination.
"""
from __future__ import annotations
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[5]))

import numpy as np
import pandas as pd


def _live_guard(mode: str = "backtest"):
    if mode == "live":
        raise NotImplementedError("Round 10 factor is backtest-only")


def _rank_norm(s: pd.Series) -> pd.Series:
    """Rolling 60-bar rank normalisation to [-1, 1]."""
    def _rank(window):
        if len(window) < 5:
            return np.nan
        return 2 * (window.rank().iloc[-1] / len(window)) - 1
    return s.rolling(60, min_periods=20).apply(_rank, raw=False)


def compute_multi_engine_ensemble(df: pd.DataFrame, mode: str = "backtest") -> pd.Series:
    """Equal-weighted ensemble of 4 sub-signals, each rank-normalised."""
    _live_guard(mode)

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

    s3 = _rank_norm(compute_regime_rsi_reversion(df, mode=mode))
    s4 = _rank_norm(compute_entropy_shock_reversion(df, mode=mode))
    s5 = _rank_norm(compute_vol_price_exhaustion(df, mode=mode))
    s7 = _rank_norm(compute_ma_dispersion_regime(df, mode=mode))

    ensemble = pd.concat([s3, s4, s5, s7], axis=1).mean(axis=1)
    return ensemble.rename("multi_engine_ensemble")
