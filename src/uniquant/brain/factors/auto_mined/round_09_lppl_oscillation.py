"""
Round 9: LPPL Log-Periodic Oscillation Intensity Factor
Hypothesis: the amplitude coefficient |c| × angular frequency w from LPPL fitting
measures the intensity of log-periodic oscillations. High intensity near the critical
time (tc) indicates that the stock is in a late-stage bubble or crash.
Inverted: post-peak stocks with declining oscillation may be safe to enter long.
"""
from __future__ import annotations
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[5]))

import numpy as np
import pandas as pd


def _live_guard(mode: str = "backtest"):
    if mode == "live":
        raise NotImplementedError("Round 9 factor is backtest-only")


def compute_lppl_oscillation_amplitude(df: pd.DataFrame, mode: str = "backtest") -> pd.Series:
    """LPPL oscillation intensity |c|*w/2π, sign-flipped when is_bubble=True."""
    _live_guard(mode)
    from uniquant.brain.lppl.calculator import LPPLCalculator

    calc = LPPLCalculator()
    n = len(df)
    scores = np.full(n, np.nan)
    window_size = 100

    for i in range(window_size - 1, n, 20):
        window = df.iloc[max(0, i - window_size + 1): i + 1].copy()
        try:
            result = calc.fit(window)
            if result is None or "model_params" not in result:
                scores[i] = 0.0
                continue
            params = result["model_params"]
            c = abs(float(params.get("c", 0.0)))
            w = float(params.get("w", 6.0))
            oscillation = c * w / (2 * np.pi)
            is_bubble = bool(result.get("is_bubble", False))
            # Attempt 2: flip sign — high oscillation predicts DOWN moves (mean reversion)
            # Stronger oscillation = more extreme → negative signal
            scores[i] = -oscillation   # always negative (short signal)
        except Exception:
            scores[i] = 0.0

    result_series = pd.Series(scores, index=df.index)
    return result_series.ffill().fillna(0.0)
