"""
Round 6: CZSC Buy-Signal Recency Score Factor
Hypothesis: stocks that recently generated CZSC 1st/2nd buy signals (一买/二买)
tend to trend upward over the following 1-3 weeks.
Score decays exponentially with time since last signal.
"""
from __future__ import annotations
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[5]))

import numpy as np
import pandas as pd


def _live_guard(mode: str = "backtest"):
    if mode == "live":
        raise NotImplementedError("Round 6 factor is backtest-only")


_SIGNAL_SCORE = {
    "FIRST_BUY": 3.0,
    "SECOND_BUY": 2.0,
    "THIRD_BUY": 1.0,
    "FIRST_SELL": -3.0,
    "SECOND_SELL": -2.0,
    "THIRD_SELL": -1.0,
    "UNKNOWN": 0.0,
}
_DECAY_HALFLIFE = 10  # bars


def compute_czsc_signal_score(df: pd.DataFrame, mode: str = "backtest") -> pd.Series:
    """CZSC signal score with exponential time-decay."""
    _live_guard(mode)
    from uniquant.brain.czsc.czsc_engine import CZSCEngine

    engine = CZSCEngine()
    # reset engine state
    raw_scores = np.zeros(len(df))

    # CZSC engine is incremental — feed rows one at a time
    # df already has a 'date' column added by the harness, so no reset needed
    # Attempt 3: use bi_count (price structure complexity) as a factor.
    # High bi_count = complex zigzag structure → momentum tends to continue in direction of 5d return.
    bi_counts = np.zeros(len(df))
    is_3rd_buy = np.zeros(len(df))
    for pos, (_, row) in enumerate(df.iterrows()):
        try:
            sig = engine.update_and_get_signals(row)
            bi_counts[pos] = float(sig.get("bi_count", 0) or 0)
            is_3rd_buy[pos] = 1.0 if sig.get("is_3rd_buy", False) else 0.0
        except Exception:
            pass

    bi_series = pd.Series(bi_counts, index=df.index)
    buy_series = pd.Series(is_3rd_buy, index=df.index)

    # Normalise bi_count into a z-score over rolling 60-bar window
    bi_z = (bi_series - bi_series.rolling(60, min_periods=20).mean()) / (
        bi_series.rolling(60, min_periods=20).std() + 1e-8
    )

    # Third-buy event bonus (decayed)
    decay = np.exp(-np.log(2) / _DECAY_HALFLIFE)
    buy_smooth = np.zeros(len(bi_counts))
    for i in range(len(buy_smooth)):
        buy_smooth[i] = (buy_smooth[i - 1] * decay if i > 0 else 0) + is_3rd_buy[i]
    buy_smooth_series = pd.Series(buy_smooth, index=df.index)

    # Combine: bi_z captures trend quality; buy_smooth adds event-driven signal
    signal = bi_z + buy_smooth_series
    return signal.rename("czsc_bi_momentum")
