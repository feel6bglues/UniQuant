"""
Round 7: MA Dispersion with Regime Filter Factor
Hypothesis: the spread between short-term and long-term moving averages (normalised
by ATR) measures trend quality. In NORMAL regime this signal is directional;
in STRESSED regime the trend often reverses, so we flip or dampen the signal.
Builds on registered factors ma_ratio_5_20 and ma_ratio_10_60.
"""
from __future__ import annotations
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[5]))

import numpy as np
import pandas as pd


def _live_guard(mode: str = "backtest"):
    if mode == "live":
        raise NotImplementedError("Round 7 factor is backtest-only")


_REGIME_FLIP = {"NORMAL": 1.0, "STRESSED": -0.5, "FROZEN": 0.0, "UNKNOWN": 0.3}


def compute_ma_dispersion_regime(df: pd.DataFrame, mode: str = "backtest") -> pd.Series:
    """MA dispersion (5/20/60) normalised by ATR, conditioned on regime."""
    _live_guard(mode)
    from uniquant.brain.indicators.indicators import Indicators
    from uniquant.brain.regime.regime_detector import RegimeDetector

    ma5 = Indicators.calc_ma(df, window=5)
    ma20 = Indicators.calc_ma(df, window=20)
    ma60 = Indicators.calc_ma(df, window=60)
    atr = Indicators.calc_atr(df, window=14)

    # composite dispersion: (ma5 - ma20)/ATR + 0.5*(ma20 - ma60)/ATR
    dispersion = ((ma5 - ma20) / (atr + 1e-8)
                  + 0.5 * (ma20 - ma60) / (atr + 1e-8))

    detector = RegimeDetector()
    regime_flip = pd.Series(np.nan, index=df.index)
    for i in range(29, len(df), 5):
        window = df.iloc[max(0, i - 29): i + 1]
        try:
            regime = detector.detect(window)
            name = regime.value if hasattr(regime, "value") else str(regime)
            regime_flip.iloc[i] = _REGIME_FLIP.get(name.upper(), 0.3)
        except Exception:
            regime_flip.iloc[i] = 0.3

    regime_flip = regime_flip.ffill().fillna(0.3)
    return (dispersion * regime_flip).rename("ma_dispersion_regime")
