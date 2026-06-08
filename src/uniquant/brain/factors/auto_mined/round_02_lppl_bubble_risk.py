"""
Round 2: LPPL Bubble-Proximity Risk Factor
Hypothesis: when LPPL detects a bubble with high confidence and the critical time
is near (small days_to_tc), the stock is close to a crash → negative signal for long.
Inverse: post-crash (days_to_tc < 0) stocks may bounce.
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
        raise NotImplementedError("Round 2 factor is backtest-only")


def compute_lppl_bubble_risk(df: pd.DataFrame, mode: str = "backtest") -> pd.Series:
    """LPPL bubble-proximity score. High positive → near crash (short signal).
    Computed monthly (every 20 bars) and forward-filled.
    """
    _live_guard(mode)
    from uniquant.brain.lppl.calculator import LPPLCalculator

    calc = LPPLCalculator()
    n = len(df)
    scores = np.full(n, np.nan)
    window_size = 100

    for i in range(window_size - 1, n, 5):
        window = df.iloc[max(0, i - window_size + 1): i + 1].copy()
        try:
            result = calc.fit(window)
            if result is None:
                continue  # leave as NaN
            # Attempt 3: days_to_tc as a safety buffer signal.
            # More days to critical time → safer → positive factor for long.
            # Cap days_to_tc at 200 to avoid outliers from non-converged fits.
            days_to_tc = float(result.get("days_to_tc", 200))
            days_to_tc = np.clip(days_to_tc, -30, 200)
            # Positive = distant from crash; negative = past or near crash
            scores[i] = np.tanh(days_to_tc / 60.0)
        except Exception:
            logger.warning("LPPL bubble risk fit failed at window %d", i, exc_info=True)

    result_series = pd.Series(scores, index=df.index)
    return result_series.ffill()
