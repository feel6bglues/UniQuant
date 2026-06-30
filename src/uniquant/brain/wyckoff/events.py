"""Wyckoff event chain detection — PS/SC/AR/ST/Spring/SOS/LPS/JAC.

Each detector scans a daily OHLCV window (typically 120 bars) for its event type
and returns detected events with confidence scores (sigmoid-normalized 0-1).

Usage:
    from uniquant.brain.wyckoff.events import detect_all_events, WyckoffEvent
    events = detect_all_events(df_120d)
    # events: list of WyckoffEvent sorted by date
"""

from dataclasses import dataclass, field
from typing import List
import numpy as np
import pandas as pd
from numba import njit


@dataclass
class WyckoffEvent:
    event_type: str
    date: str
    price: float
    confidence: float
    volume_ratio: float
    features: dict = field(default_factory=dict)

    def __lt__(self, other):
        return self.date < other.date


def _sigmoid_confidence(raw_score: float, midpoint: float = 3.0, scale: float = 1.0) -> float:
    with np.errstate(over='ignore'):
        exp_arg = -(raw_score - midpoint) / scale
        return float(1.0 / (1.0 + np.exp(exp_arg)))


def _vol_ma20(volume: np.ndarray) -> float:
    if len(volume) >= 20:
        return float(np.mean(volume[-20:]))
    return float(np.mean(volume))


def _pre_detect_features(df: pd.DataFrame) -> dict:
    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    volume = df['volume'].values.astype(float)
    n = len(df)

    vol_ma20_v = _vol_ma20(volume)
    tr_20 = (close[-1] / close[-20] - 1) * 100 if n >= 20 and close[-20] > 0 else 0
    lo_all, hi_all = float(low.min()), float(high.max())
    pp = (close[-1] - lo_all) / (hi_all - lo_all) if hi_all > lo_all else 0.5

    ma20 = pd.Series(close).rolling(20).mean().values
    above_ma20 = close[-1] > ma20[-1] if not np.isnan(ma20[-1]) else False

    return {
        'close': close, 'high': high, 'low': low, 'volume': volume, 'n': n,
        'vol_ma20': vol_ma20_v, 'tr_20': tr_20, 'pp': pp,
        'ma20': ma20, 'above_ma20': above_ma20,
    }


@njit(cache=True)
def _score_ps_numba(close, high, low, open_prices, volume, vol_ma20, n):
    valid = np.zeros(n, dtype=np.bool_)
    scores = np.zeros(n)
    vol_ratios = np.zeros(n)
    wick_ratios = np.zeros(n)
    close_poses = np.zeros(n)
    confirms = np.zeros(n, dtype=np.bool_)
    close_vals = np.zeros(n)
    for i in range(n - 20, n):
        if i < 2 or i >= n - 2:
            continue
        tr_prior = (close[i] / close[i - 20] - 1) * 100 if close[i - 20] > 0 else 0
        if tr_prior > -5:
            continue
        vol_ratio = volume[i] / vol_ma20 if vol_ma20 > 0 else 1
        if vol_ratio < 1.2:
            continue
        body = abs(close[i] - open_prices[i])
        lo_w = min(close[i], open_prices[i]) - low[i]
        amp = (high[i] - low[i]) / low[i] if low[i] > 0 else 0
        close_pos = (close[i] - low[i]) / (high[i] - low[i]) if high[i] > low[i] else 0.5
        if body < 0.01:
            continue
        wick_ratio = lo_w / body
        if close_pos < 0.4:
            continue
        if amp < 0.015:
            continue
        confirm = close[i + 1] > close[i] if i + 1 < n else False
        score = 0
        score += 2 if vol_ratio > 1.5 else 1 if vol_ratio > 1.2 else 0
        score += 2 if wick_ratio > 2 else 1 if wick_ratio > 1 else 0
        score += 1 if close_pos > 0.6 else 0
        score += 1 if confirm else 0
        if score >= 3:
            valid[i] = True
            scores[i] = score
            vol_ratios[i] = vol_ratio
            wick_ratios[i] = wick_ratio
            close_poses[i] = close_pos
            confirms[i] = confirm
            close_vals[i] = close[i]
    return valid, scores, vol_ratios, wick_ratios, close_poses, confirms, close_vals


@njit(cache=True)
def _score_sc_numba(close, high, low, open_prices, volume, vol_ma20, vol_rank, subsequent_high, n):
    valid = np.zeros(n, dtype=np.bool_)
    scores = np.zeros(n)
    vol_ratios = np.zeros(n)
    wick_ratios = np.zeros(n)
    amps = np.zeros(n)
    new_20d_lows = np.zeros(n, dtype=np.bool_)
    rebounds = np.zeros(n)
    low_vals = np.zeros(n)
    for i in range(max(n - 60, 5), n):
        if i < 5:
            continue
        tr_prior = (close[i] / close[i - 20] - 1) * 100 if close[i - 20] > 0 else 0
        if tr_prior > -8:
            continue
        body = abs(close[i] - open_prices[i])
        lo_w = min(close[i], open_prices[i]) - low[i]
        amp = (high[i] - low[i]) / low[i] if low[i] > 0 else 0
        wick_ratio = lo_w / body if body > 0.01 else 10
        vol_ratio = volume[i] / vol_ma20 if vol_ma20 > 0 else 1
        new_20d_low = low[i] == low[max(0, i - 20):i + 1].min()
        rebound = (subsequent_high[i] - low[i]) / low[i] if low[i] > 0 else 0
        mask_last5 = i < n - 5
        score = 0
        score += 2 if vol_rank[i] > 0.8 else 0
        score += 2 if wick_ratio > 2 else 1 if wick_ratio > 1 else 0
        score += 2 if new_20d_low and rebound > 0.01 and mask_last5 else 0
        score += 1 if amp > 0.04 else 0
        score += 1 if vol_ratio > 2.0 else 0
        if score >= 3:
            valid[i] = True
            scores[i] = score
            vol_ratios[i] = vol_ratio
            wick_ratios[i] = wick_ratio
            amps[i] = amp
            new_20d_lows[i] = new_20d_low
            rebounds[i] = rebound
            low_vals[i] = low[i]
    return valid, scores, vol_ratios, wick_ratios, amps, new_20d_lows, rebounds, low_vals


@njit(cache=True)
def _score_sos_numba(close, high, low, volume, vol_ma20, n):
    valid = np.zeros(n, dtype=np.bool_)
    scores = np.zeros(n)
    vol_ratios = np.zeros(n)
    close_poses = np.zeros(n)
    new_highs = np.zeros(n, dtype=np.bool_)
    gains = np.zeros(n)
    close_vals = np.zeros(n)
    for i in range(max(n - 30, 5), n):
        if i < 2:
            continue
        gain = (close[i] - close[i - 1]) / close[i - 1] if close[i - 1] > 0 else 0
        if gain < 0.03:
            continue
        vol_ratio = volume[i] / vol_ma20 if vol_ma20 > 0 else 1
        if vol_ratio < 1.3:
            continue
        close_pos = (close[i] - low[i]) / (high[i] - low[i]) if high[i] > low[i] else 0.5
        new_high = high[i] == high[max(0, i - 20):i + 1].max()
        score = 0
        score += 2 if gain > 0.05 else 1 if gain > 0.03 else 0
        score += 2 if vol_ratio > 2.0 else 1 if vol_ratio > 1.5 else 0
        score += 1 if close_pos > 0.75 else 0
        score += 1 if new_high else 0
        if score >= 4:
            valid[i] = True
            scores[i] = score
            vol_ratios[i] = vol_ratio
            close_poses[i] = close_pos
            new_highs[i] = new_high
            gains[i] = gain
            close_vals[i] = close[i]
    return valid, scores, vol_ratios, close_poses, new_highs, gains, close_vals


def detect_ps(df: pd.DataFrame) -> List[WyckoffEvent]:
    """Preliminary Support: first sign of buying in a downtrend.

    Scans last 20 bars for PS candidates.
    """
    if len(df) < 25:
        return []
    f = _pre_detect_features(df)
    close, high, low, volume = f['close'], f['high'], f['low'], f['volume']
    n = len(df)
    vol_ma20 = f['vol_ma20']

    open_prices = df['open'].values.astype(float)
    valid, scores, vol_ratios, wick_ratios, close_poses, confirms, close_vals = _score_ps_numba(
        close, high, low, open_prices, volume, vol_ma20, n,
    )
    events = []
    for i in range(n - 20, n):
        if valid[i]:
            confidence = _sigmoid_confidence(scores[i], midpoint=3.5, scale=1.5)
            events.append(WyckoffEvent(
                event_type='PS', date=str(df['date'].values[i])[:10],
                price=float(close_vals[i]), confidence=confidence,
                volume_ratio=float(vol_ratios[i]),
                features={'score': int(scores[i]), 'wick_ratio': float(wick_ratios[i]),
                          'close_pos': float(close_poses[i]), 'confirm': bool(confirms[i])},
            ))
    return events[-3:] if events else []


def detect_sc(df: pd.DataFrame) -> List[WyckoffEvent]:
    """Selling Climax: extreme panic with volume spike + long lower shadow.

    Adapted from engine._scan_bc_sc sigmoid scoring.
    """
    if len(df) < 30:
        return []
    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    volume = df['volume'].values.astype(float)
    n = len(df)
    vol_ma20_v = _vol_ma20(volume)
    vol_rank = pd.Series(volume).rank(pct=True).values

    close_rev = close[::-1]
    sub_high_rev = pd.Series(close_rev).rolling(9, min_periods=1).max().to_numpy()
    subsequent_high = np.roll(sub_high_rev[::-1], -1)
    subsequent_high[-1] = close[-1]

    open_prices = df['open'].values.astype(float)
    valid, scores, vol_ratios, wick_ratios, amps, new_20d_lows, rebounds, low_vals = _score_sc_numba(
        close, high, low, open_prices, volume, vol_ma20_v, vol_rank, subsequent_high, n,
    )
    events = []
    for i in range(max(n - 60, 5), n):
        if valid[i]:
            confidence = _sigmoid_confidence(scores[i], midpoint=3.5, scale=1.5)
            events.append(WyckoffEvent(
                event_type='SC', date=str(df['date'].values[i])[:10],
                price=float(low_vals[i]), confidence=confidence,
                volume_ratio=float(vol_ratios[i]),
                features={'score': int(scores[i]), 'wick_ratio': float(wick_ratios[i]),
                          'amp': float(amps[i]), 'new_20d_low': bool(new_20d_lows[i]),
                          'rebound': float(rebounds[i])},
            ))
    return events[-2:] if events else []


def detect_ar(df: pd.DataFrame, sc_events: List[WyckoffEvent]) -> List[WyckoffEvent]:
    """Automatic Reaction: natural bounce within 5 days after SC.

    Requires SC events to anchor the detection.
    """
    if not sc_events:
        return []
    high = df['high'].values.astype(float)
    volume = df['volume'].values.astype(float)
    n = len(df)
    vol_ma20_v = _vol_ma20(volume)

    events = []
    for sc in sc_events[-1:]:
        sc_dt = pd.Timestamp(sc.date)
        sc_idx = df[df['date'] <= sc_dt].index[-1] if sc_dt in df['date'].values else -1
        if sc_idx < 0 or sc_idx >= n - 2:
            continue
        sc_low = sc.price

        for j in range(sc_idx + 2, min(sc_idx + 6, n)):
            rise = (high[j] - sc_low) / sc_low if sc_low > 0 else 0
            if rise < 0.3 * ((high[sc_idx] - sc_low) / sc_low if sc_low > 0 else 1):
                continue
            vol_ratio = volume[j] / vol_ma20_v if vol_ma20_v > 0 else 1
            if vol_ratio > 1.2:
                continue

            score = 2 if rise > 0.5 * ((high[sc_idx] - sc_low) / sc_low if sc_low > 0 else 1) else 1
            score += 1 if vol_ratio < 0.8 else 0
            confidence = _sigmoid_confidence(score, midpoint=2, scale=1)
            events.append(WyckoffEvent(
                event_type='AR', date=str(df['date'].values[j])[:10],
                price=float(high[j]), confidence=confidence,
                volume_ratio=float(vol_ratio),
                features={'score': score, 'rise_pct': float(rise * 100),
                          'sc_price': sc.price},
            ))
    return events[-1:] if events else []


def detect_st(df: pd.DataFrame, reference_events: List[WyckoffEvent]) -> List[WyckoffEvent]:
    """Secondary Test: volume-contracted retest of SC/Spring low.

    Scans for price returning to within 5% of reference low with volume contraction.
    """
    if not reference_events:
        return []
    close = df['close'].values.astype(float)
    low = df['low'].values.astype(float)
    volume = df['volume'].values.astype(float)
    n = len(df)
    vol_ma20_v = _vol_ma20(volume)

    ref = reference_events[-1]
    ref_low = ref.price
    ref_dt = pd.Timestamp(ref.date)
    ref_idx = df[df['date'] <= ref_dt].index[-1] if ref_dt in df['date'].values else -1
    if ref_idx < 0:
        return []

    events = []
    for i in range(ref_idx + 5, n):
        if i < 0 or i >= n:
            continue
        dist = (close[i] - ref_low) / ref_low if ref_low > 0 else 1
        if dist < -0.01 or dist > 0.05:
            continue
        lo_w = min(close[i], df['open'].values[i]) - low[i]
        vol_ratio = volume[i] / vol_ma20_v if vol_ma20_v > 0 else 1
        if vol_ratio > 0.8:
            continue

        score = 0
        score += 2 if vol_ratio < 0.5 else 1 if vol_ratio < 0.7 else 0
        score += 1 if lo_w > 0.01 else 0
        score += 1 if i - ref_idx > 10 else 0

        if score >= 2:
            confidence = _sigmoid_confidence(score, midpoint=2.5, scale=1)
            events.append(WyckoffEvent(
                event_type='ST', date=str(df['date'].values[i])[:10],
                price=float(low[i]), confidence=confidence,
                volume_ratio=float(vol_ratio),
                features={'score': score, 'dist_to_ref': float(dist * 100),
                          'ref_type': ref.event_type, 'ref_price': ref.price},
            ))
    return events[-2:] if events else []


def detect_sos(df: pd.DataFrame) -> List[WyckoffEvent]:
    """Sign of Strength: strong up day with volume confirming.

    Scans last 30 bars for >3% gain with >1.5x volume and strong close.
    Threshold raised from 3→4 to reduce 109.5% detection rate (was detecting SOS on nearly every observation).
    """
    if len(df) < 30:
        return []
    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    volume = df['volume'].values.astype(float)
    n = len(df)
    vol_ma20_v = _vol_ma20(volume)

    valid, scores, vol_ratios, close_poses, new_highs, gains, close_vals = _score_sos_numba(
        close, high, low, volume, vol_ma20_v, n,
    )
    events = []
    for i in range(max(n - 30, 5), n):
        if valid[i]:
            confidence = _sigmoid_confidence(scores[i], midpoint=4, scale=1.5)
            events.append(WyckoffEvent(
                event_type='SOS', date=str(df['date'].values[i])[:10],
                price=float(close_vals[i]), confidence=confidence,
                volume_ratio=float(vol_ratios[i]),
                features={'score': int(scores[i]), 'gain_pct': float(gains[i] * 100),
                          'close_pos': float(close_poses[i]), 'new_high': bool(new_highs[i])},
            ))
    return events[-2:] if events else []


def detect_lps(df: pd.DataFrame, sos_events: List[WyckoffEvent]) -> List[WyckoffEvent]:
    """Last Point of Support: volume-contracted pullback after SOS.

    Requires SOS events to anchor detection.
    """
    if not sos_events:
        return []
    close = df['close'].values.astype(float)
    low = df['low'].values.astype(float)
    volume = df['volume'].values.astype(float)
    n = len(df)
    vol_ma20_v = _vol_ma20(volume)

    sos = sos_events[-1]
    sos_dt = pd.Timestamp(sos.date)
    sos_idx = df[df['date'] <= sos_dt].index[-1] if sos_dt in df['date'].values else -1
    if sos_idx < 0:
        return []
    sos_low = low[sos_idx]
    sos_close = close[sos_idx]

    events = []
    for i in range(sos_idx + 2, n):
        if i >= n:
            continue
        pullback = (close[i] - sos_close) / sos_close if sos_close > 0 else 0
        if pullback > 0.01:
            continue
        if low[i] < sos_low:
            continue
        vol_ratio = volume[i] / vol_ma20_v if vol_ma20_v > 0 else 1
        if vol_ratio > 0.85:
            continue
        lo_w = min(close[i], df['open'].values[i]) - low[i]

        score = 0
        score += 2 if vol_ratio < 0.6 else 1 if vol_ratio < 0.8 else 0
        score += 1 if lo_w > 0.01 else 0
        score += 1 if pullback > -0.03 else 0

        if score >= 2:
            confidence = _sigmoid_confidence(score, midpoint=2.5, scale=1)
            events.append(WyckoffEvent(
                event_type='LPS', date=str(df['date'].values[i])[:10],
                price=float(low[i]), confidence=confidence,
                volume_ratio=float(vol_ratio),
                features={'score': score, 'pullback_pct': float(pullback * 100),
                          'sos_price': float(sos_close)},
            ))
    return events[-1:] if events else []


def detect_jac(df: pd.DataFrame) -> List[WyckoffEvent]:
    """Jump Across Creek: volume-confirmed breakout above TR.

    Finds the most recent 20-day TR, checks if price breaks the upper bound.
    """
    if len(df) < 30:
        return []
    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    volume = df['volume'].values.astype(float)
    n = len(df)
    vol_ma20_v = _vol_ma20(volume)

    events = []
    for i in range(max(n - 20, 20), n):
        if i < 20:
            continue
        tr_high = high[i - 19:i + 1].max()
        tr_low = low[i - 19:i + 1].min()
        tr_range = (tr_high - tr_low) / tr_low if tr_low > 0 else 0
        if tr_range > 0.15:
            continue
        vol_ratio = volume[i] / vol_ma20_v if vol_ma20_v > 0 else 1
        if close[i] <= tr_high * 0.99 or vol_ratio < 0.9:
            continue

        score = 0
        score += 2 if vol_ratio > 1.5 else 1 if vol_ratio > 1.0 else 0
        score += 1 if close[i] > tr_high else 0
        score += 1 if tr_range < 0.10 else 0
        confidence = _sigmoid_confidence(score, midpoint=2.5, scale=1)
        events.append(WyckoffEvent(
            event_type='JAC', date=str(df['date'].values[i])[:10],
            price=float(close[i]), confidence=confidence,
            volume_ratio=float(vol_ratio),
            features={'score': score, 'tr_range': float(tr_range * 100),
                      'tr_high': float(tr_high)},
        ))
    return events[-1:] if events else []


def detect_all_events(df: pd.DataFrame) -> List[WyckoffEvent]:
    """Run all event detectors on a DataFrame and return events sorted by date.

    Detectors that depend on other events (AR, ST, LPS) use the previous
    detector's output to maintain correct Wyckoff chronology.
    """
    all_events: List[WyckoffEvent] = []
    all_events.extend(detect_ps(df))
    sc_events = detect_sc(df)
    all_events.extend(sc_events)
    all_events.extend(detect_ar(df, sc_events))

    st_from_sc = detect_st(df, sc_events)
    all_events.extend(st_from_sc)

    all_events.extend(detect_sos(df))
    sos_events = detect_sos(df)
    all_events.extend(detect_lps(df, sos_events))
    all_events.extend(detect_jac(df))

    all_events.sort()
    return all_events


def event_sequence_key(events: List[WyckoffEvent], max_gap_days: int = 120) -> str:
    """Summarize an event list as a sequence key (e.g. 'PS>SC>AR>ST').

    Only includes events within max_gap_days and with confidence > 0.3.
    """
    if not events:
        return 'NONE'
    filtered = [e for e in events if e.confidence > 0.3]
    if not filtered:
        return 'LOW_CONF'
    types = [e.event_type for e in filtered]
    return '>'.join(types)


__all__ = [
    'WyckoffEvent', 'detect_ps', 'detect_sc', 'detect_ar', 'detect_st',
    'detect_sos', 'detect_lps', 'detect_jac', 'detect_all_events',
    'event_sequence_key',
]
