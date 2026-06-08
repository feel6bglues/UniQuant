"""
Round 8: Wyckoff Phase Persistence Factor
Hypothesis: stocks that have remained in the same Wyckoff bullish phase
(ACCUMULATION/MARKUP) for many consecutive bars are more likely to continue
that trend (institutional conviction).
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
        raise NotImplementedError("Round 8 factor is backtest-only")


_PHASE_BULLISH = {"ACCUMULATION": 1, "MARKUP": 1}
_PHASE_BEARISH = {"DISTRIBUTION": -1, "MARKDOWN": -1}


def compute_wyckoff_persistence(df: pd.DataFrame, mode: str = "backtest") -> pd.Series:
    """Consecutive bars in same Wyckoff direction × confidence, normalised."""
    _live_guard(mode)
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    engine = WyckoffEngine(lookback_days=120)
    n = len(df)
    phase_seq = []   # (direction, confidence) per sampled bar

    sample_indices = list(range(119, n, 5))
    raw_phases = []
    for i in sample_indices:
        # Wyckoff engine needs 'date' as a regular column, not as index
        window = df.iloc[max(0, i - 119): i + 1].copy().reset_index(drop=True)
        try:
            sig = engine.scan_signal(window, symbol="x")
            phase = str(sig.get("phase", "UNKNOWN")).upper()
            conf = float(sig.get("confidence", 0.2))  # confidence is a float, not a letter grade
            direction = _PHASE_BULLISH.get(phase, _PHASE_BEARISH.get(phase, 0))
            raw_phases.append((i, direction, conf))
        except Exception:
            logger.warning("Wyckoff persistence scan failed at window %d", i, exc_info=True)
            raw_phases.append((i, 0, np.nan))

    # compute persistence: count consecutive same-direction bars
    # Attempt 3: negate — persistent Wyckoff phase signals MEAN-REVERSION at 20d
    scores = np.full(n, np.nan)
    streak = 0
    prev_direction = None
    for idx, direction, conf in raw_phases:
        if direction == prev_direction and direction != 0:
            streak += 1
        else:
            streak = 1 if direction != 0 else 0
        prev_direction = direction
        # negate: persistent bullish Wyckoff → contrarian short signal
        scores[idx] = -direction * streak * conf / 10.0

    result = pd.Series(scores, index=df.index)
    return result.ffill()
