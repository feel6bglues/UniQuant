"""
Round 4: Market Entropy Shock Mean-Reversion Factor
Hypothesis: when Shannon entropy of returns drops sharply (market becomes one-sided),
a mean-reversion follows as order flow normalises.
"""
from __future__ import annotations
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[5]))

import numpy as np
import pandas as pd


def _live_guard(mode: str = "backtest"):
    if mode == "live":
        raise NotImplementedError("Round 4 factor is backtest-only")


def compute_entropy_shock_reversion(df: pd.DataFrame, mode: str = "backtest") -> pd.Series:
    """Normalised entropy drop → positive = oversold via entropy."""
    _live_guard(mode)
    from uniquant.brain.indicators.indicators import Indicators

    entropy = Indicators.calc_market_entropy(df, window=20, bins=10)
    ma = entropy.rolling(40, min_periods=10).mean()
    std = entropy.rolling(40, min_periods=10).std()

    # negative z-score: entropy dropped → market one-sided → mean-reversion
    z = (entropy - ma) / (std + 1e-8)
    signal = -z   # lower entropy than norm → positive (expected bounce)
    return signal.rename("entropy_shock_reversion")
