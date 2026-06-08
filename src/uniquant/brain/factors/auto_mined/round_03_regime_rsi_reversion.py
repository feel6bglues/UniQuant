"""
Round 3: Regime-Conditioned RSI Mean-Reversion Factor
Hypothesis: in NORMAL liquidity regime, oversold stocks (low RSI) revert upward.
In STRESSED/FROZEN regimes, RSI signals are unreliable — dampen them.
"""
from __future__ import annotations
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[5]))

import numpy as np
import pandas as pd

from ....shared.logger_factory import get_logger

logger = get_logger(__name__)


def _live_guard(mode: str = "backtest"):
    if mode == "live":
        raise NotImplementedError("Round 3 factor is backtest-only")


_REGIME_WEIGHT = {"NORMAL": 1.0, "STRESSED": 0.3, "FROZEN": 0.0, "UNKNOWN": 0.5}


def compute_regime_rsi_reversion(df: pd.DataFrame, mode: str = "backtest") -> pd.Series:
    """RSI mean-reversion signal dampened by liquidity regime."""
    _live_guard(mode)
    from uniquant.brain.indicators.indicators import Indicators
    from uniquant.brain.regime.regime_detector import RegimeDetector

    rsi = Indicators.calc_rsi(df, window=14)
    # Mean-reversion: oversold = positive score, overbought = negative
    # Data shows RSI is a MOMENTUM signal in this market (not mean-reversion)
    # High RSI → strong trend → positive forward return
    rsi_signal = (rsi - 50.0) / 50.0     # range ~[-1, +1], attempt 2: momentum

    detector = RegimeDetector()
    regime_weights = pd.Series(np.nan, index=df.index)

    # compute regime every 5 bars (it's cheap but we still sample to save time)
    for i in range(29, len(df), 5):
        window = df.iloc[max(0, i - 29): i + 1]
        try:
            regime = detector.detect(window)
            regime_name = regime.value if hasattr(regime, "value") else str(regime)
            regime_weights.iloc[i] = _REGIME_WEIGHT.get(regime_name.upper(), 0.5)
        except Exception:
            logger.warning("Regime detection failed at index %d", i, exc_info=True)
            regime_weights.iloc[i] = 0.5

    regime_weights = regime_weights.ffill().fillna(0.5)
    return (rsi_signal * regime_weights).rename("regime_rsi_reversion")
