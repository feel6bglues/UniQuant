"""
Round 1: Wyckoff Phase-Confidence Score Factor
Hypothesis: stocks in Wyckoff accumulation/markup phase with high engine confidence
tend to outperform over the next 1-4 weeks.
"""
from __future__ import annotations
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[5]))

import numpy as np
import pandas as pd

from ....shared.logger_factory import get_logger

logger = get_logger(__name__)

if True:  # mode guard
    def _live_guard(mode: str = "backtest"):
        if mode == "live":
            raise NotImplementedError("Round 1 factor is backtest-only — live mode not supported")

_PHASE_SCORE = {
    "ACCUMULATION": 2.0,
    "MARKUP": 1.0,
    "UNKNOWN": 0.0,
    "MARKDOWN": -1.0,
    "DISTRIBUTION": -2.0,
}
_CONF_MULT = {"A": 1.0, "B": 0.70, "C": 0.40, "D": 0.20}


def compute_wyckoff_phase_confidence(df: pd.DataFrame, mode: str = "backtest") -> pd.Series:
    """Wyckoff phase × confidence score, computed on rolling 120-day windows (weekly sampling)."""
    _live_guard(mode)
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    engine = WyckoffEngine(lookback_days=120)
    n = len(df)
    scores = np.full(n, np.nan)

    # sample every 5 bars to limit cost; forward-fill the rest
    for i in range(119, n, 5):
        # Wyckoff engine needs 'date' as a regular column, not as index
        window = df.iloc[max(0, i - 119): i + 1].copy().reset_index(drop=True)
        try:
            sig = engine.scan_signal(window, symbol="factor_calc")
            # Attempt 2: use action directly rather than phase × confidence
            action = str(sig.get("action", "HOLD")).upper()
            conf = float(sig.get("confidence", 0.0))
            if action == "BUY":
                scores[i] = conf
            elif action == "SELL":
                scores[i] = -conf
            else:
                scores[i] = 0.0
            if sig.get("spring_detected", False):
                scores[i] += 0.3
            if sig.get("utad_detected", False):
                scores[i] -= 0.3
        except Exception:
            logger.warning("Wyckoff confidence scan failed at window %d", i, exc_info=True)

    result = pd.Series(scores, index=df.index)
    return result.ffill()
