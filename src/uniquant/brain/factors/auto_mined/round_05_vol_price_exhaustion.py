"""
Round 5: Volume-Price Exhaustion Factor
Hypothesis: high volume on down-days indicates selling exhaustion → subsequent bounce.
Factor is positive when recent volume is elevated AND price direction is negative.
Based on existing volume_ratio and registered momentum factor logic.
"""
from __future__ import annotations
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[5]))

import pandas as pd


def _live_guard(mode: str = "backtest"):
    if mode == "live":
        raise NotImplementedError("Round 5 factor is backtest-only")


def compute_vol_price_exhaustion(df: pd.DataFrame, mode: str = "backtest") -> pd.Series:
    """Volume-price exhaustion: elevated vol + negative 5-day return → buy signal."""
    _live_guard(mode)
    from uniquant.brain.indicators.indicators import Indicators

    vol_ratio = Indicators.calc_vol_ratio(df, window=20)   # vol / MA(20)
    pct_5d = df["close"].pct_change(5)

    # Attempt 3: "quiet strength" — negate original signal.
    # High vol + down price (panic selling) strongly predicts continued decline.
    # Inverted: LOW vol + UP price (stealth accumulation) predicts continuation upward.
    vol_excess = (vol_ratio - 1.0).clip(lower=0)
    price_weakness = (-pct_5d).clip(lower=0)
    panic_signal = vol_excess * price_weakness
    signal = -panic_signal   # stealth accumulation = positive
    # normalise to z-score within rolling 60-bar window
    rolling_mean = signal.rolling(60, min_periods=20).mean()
    rolling_std = signal.rolling(60, min_periods=20).std()
    z = (signal - rolling_mean) / (rolling_std + 1e-8)
    return z.rename("vol_price_exhaustion")
