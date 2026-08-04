#!/usr/bin/env python3
"""Synthetic OHLCV fixtures for Classic Wyckoff TDD tests.

All generators accept a ``seed`` parameter for reproducible output.

Usage:
    from scripts.wyckoff_fixtures import synthetic_accumulation

    df = synthetic_accumulation(seed=42)
    engine.analyze(df)
"""

from __future__ import annotations


import numpy as np
import pandas as pd

from uniquant.brain.wyckoff.pnf import PointAndFigure


def synthetic_sine_wave(
    length: int = 120,
    freq: float = 0.05,
    amp: float = 0.02,
    vol_base: float = 1e7,
    vol_noise: float = 0.3,
    seed: int = 42,
) -> pd.DataFrame:
    """Produce sine-wave OHLCV as a random data baseline."""
    rng = np.random.default_rng(seed)
    t = np.arange(length)
    price = 10.0 * (1 + amp * np.sin(2 * np.pi * freq * t))
    price += rng.normal(0, 0.01, length).cumsum()
    close = price
    high = close * (1 + rng.uniform(0, 0.01, length))
    low = close * (1 - rng.uniform(0, 0.01, length))
    open_ = (high + low) / 2
    volume = (vol_base * (1 + rng.normal(0, vol_noise, length))).astype(int)
    return pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=length, freq="D"),
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


def synthetic_accumulation(length: int = 120, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV with a complete Accumulation event sequence.

    Sequence: PS -> BC -> AR -> SC -> ST1 -> ST2 -> Spring -> SOS -> LPS
    """
    rng = np.random.default_rng(seed)
    df = synthetic_sine_wave(length, seed=seed)
    close = df["close"].values
    n = len(close)
    vol_med = float(df["volume"].median())

    # Phase A: downtrend -> PS
    phase_a_end = n // 4
    close[:phase_a_end] = close[0] * (1 - 0.15 * np.linspace(0, 1, phase_a_end))
    ps_idx = phase_a_end - 1
    df.loc[ps_idx, "low"] = close[ps_idx] * 0.95
    df.loc[ps_idx, "volume"] = int(2.0 * vol_med)

    # Phase B: BC -> AR -> SC -> ST x 2
    bc_idx = ps_idx + 2
    close[bc_idx] = close[ps_idx] * 1.08
    df.loc[bc_idx, "volume"] = int(1.8 * vol_med)
    df.loc[bc_idx, "high"] = close[bc_idx] * 1.03
    df.loc[bc_idx, "low"] = close[bc_idx] * 0.97

    sc_idx = bc_idx + 5
    close[sc_idx] = close[sc_idx - 1] * 0.92
    df.loc[sc_idx, "volume"] = int(3.0 * vol_med)
    df.loc[sc_idx, "low"] = close[sc_idx] * 0.96

    for i, st_idx in enumerate([sc_idx + 5, sc_idx + 12]):
        close[st_idx] = close[sc_idx] * 1.02
        df.loc[st_idx, "volume"] = int(vol_med * (0.6 - i * 0.1))
        df.loc[st_idx, "close"] = close[st_idx]

    # Phase C: Spring + recovery
    spring_idx = sc_idx + 18
    close[spring_idx] = close[sc_idx] * 0.97
    df.loc[spring_idx, "low"] = close[spring_idx] * 0.98
    df.loc[spring_idx, "volume"] = int(0.5 * vol_med)
    close[spring_idx + 1] = close[spring_idx] * 1.06
    df.loc[spring_idx + 1, "volume"] = int(1.5 * vol_med)

    # SOS + LPS
    sos_idx = spring_idx + 5
    close[sos_idx] = close[spring_idx + 1] * 1.08
    df.loc[sos_idx, "volume"] = int(2.0 * vol_med)

    df["close"] = close
    df["open"] = df["close"] * (1 + rng.uniform(-0.005, 0.005, n))
    return df


def synthetic_distribution(length: int = 120, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV with a Distribution event sequence.

    Sequence: uptrend -> PSY -> UTAD -> LPSY -> breakdown
    """
    rng = np.random.default_rng(seed)
    df = synthetic_sine_wave(length, seed=seed * 2 + 1)
    close = df["close"].values
    n = len(close)
    vol_med = float(df["volume"].median())

    # Uptrend
    uptrend_end = n // 3
    close[:uptrend_end] = close[0] * (1 + 0.20 * np.linspace(0, 1, uptrend_end))

    # PSY: high-volume upper shadow
    psy_idx = uptrend_end - 1
    high_psy = close[psy_idx] * 1.05
    df.loc[psy_idx, "high"] = high_psy
    df.loc[psy_idx, "close"] = close[psy_idx] * 1.01
    df.loc[psy_idx, "low"] = close[psy_idx] * 0.99
    df.loc[psy_idx, "volume"] = int(2.5 * vol_med)

    # UTAD: false breakout above TR then fallback
    utad_idx = psy_idx + 3
    close[utad_idx] = high_psy * 1.03
    df.loc[utad_idx, "high"] = close[utad_idx] * 1.02
    df.loc[utad_idx, "close"] = close[psy_idx]  # fall back
    df.loc[utad_idx, "volume"] = int(2.0 * vol_med)

    # LPSY: lower volume test of high
    lpsy_idx = utad_idx + 4
    close[lpsy_idx] = close[psy_idx] * 0.98
    df.loc[lpsy_idx, "volume"] = int(0.7 * vol_med)

    # Breakdown
    bd_idx = lpsy_idx + 3
    close[bd_idx:] = close[bd_idx - 1] * (1 - 0.08 * np.linspace(0, 1, n - bd_idx))
    df.loc[bd_idx, "volume"] = int(2.0 * vol_med)
    df.loc[bd_idx, "low"] = close[bd_idx] * 0.97

    df["close"] = close
    df["open"] = df["close"] * (1 + rng.uniform(-0.005, 0.005, n))
    return df


def synthetic_trading_range(
    length: int = 120,
    low_bound: float = 10.0,
    high_bound: float = 12.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLCV confined to a horizontal trading range."""
    rng = np.random.default_rng(seed)
    mid = (low_bound + high_bound) / 2
    half_range = (high_bound - low_bound) / 2
    close = mid + rng.uniform(-half_range, half_range, length) * 0.8
    high = close + rng.uniform(0, half_range * 0.3, length)
    low = close - rng.uniform(0, half_range * 0.3, length)
    volume = (1e7 * (1 + rng.normal(0, 0.3, length))).astype(int)
    return pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=length, freq="D"),
        "open": close * (1 + rng.uniform(-0.005, 0.005, length)),
        "high": np.clip(high, low_bound * 0.98, high_bound * 1.02),
        "low": np.clip(low, low_bound * 0.98, high_bound * 1.02),
        "close": close,
        "volume": volume,
    })


def synthetic_limit_up(seed: int = 42) -> pd.DataFrame:
    """Generate OHLCV with 3 consecutive limit-up days.

    All three days have close == high (limit price) and no upper shadow.
    """
    rng = np.random.default_rng(seed)
    base = 10.0
    dates = pd.date_range("2020-01-01", periods=5, freq="D")
    prices = [base, base * 1.1, base * 1.21, base * 1.331, base * 1.331 * 0.97]
    rows = []
    for i, d in enumerate(dates):
        c = prices[i]
        o = c * (1 - rng.uniform(0.005, 0.02))
        if i in (1, 2, 3):
            h = c
            lo = o * 0.98
        else:
            h = c * 1.02
            lo = o * 0.98
        v = int(1e7 * (1 + rng.uniform(-0.1, 0.1)))
        rows.append({"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": v})
    return pd.DataFrame(rows)


def synthetic_spring(seed: int = 42) -> pd.DataFrame:
    """Generate OHLCV with a classic Spring event.

    TR = [10, 12]; bar 80 breaks below TR low to 9.90, bar 81 recovers to 11.50.
    """
    np.random.default_rng(seed)
    df = synthetic_trading_range(length=100, low_bound=10.0, high_bound=12.0, seed=seed)
    close = df["close"].values

    close[79] = 9.90  # spring low
    df.loc[79, "low"] = 9.85
    df.loc[79, "high"] = 10.50
    df.loc[79, "volume"] = int(0.5 * df["volume"].median())

    close[80] = 11.50  # recovery
    df.loc[80, "low"] = 10.80
    df.loc[80, "high"] = 11.80
    df.loc[80, "volume"] = int(1.5 * df["volume"].median())

    df["close"] = close
    return df


def synthetic_spring_late_recovery(seed: int = 42) -> pd.DataFrame:
    """Counter-example for ES-C1: price breaks below TR lower but recovers
    only 3+ columns later (not a classic Spring).

    TR = [10, 12]; bar 80 low=9.90 (break 1% below), recovery only at bar 85
    (5 bars later). 1-2 column recovery rule must reject this.
    """
    df = synthetic_trading_range(length=100, low_bound=10.0, high_bound=12.0, seed=seed * 7)
    close = df["close"].values

    close[79] = 9.90  # spring-like dip
    df.loc[79, "low"] = 9.85
    df.loc[79, "high"] = 10.50
    df.loc[79, "volume"] = int(0.5 * df["volume"].median())

    for idx in range(80, 85):  # stays below TR for 5 bars
        close[idx] = 9.95
        df.loc[idx, "low"] = 9.80
        df.loc[idx, "high"] = 10.20
        df.loc[idx, "volume"] = int(0.6 * df["volume"].median())

    close[84] = 11.50  # recovery only at bar 85 (5 bars later)
    df.loc[84, "volume"] = int(1.5 * df["volume"].median())

    df["close"] = close
    return df


def synthetic_spring_aligned(seed: int = 3) -> pd.DataFrame:
    """Generate OHLCV with a classic Spring aligned to the engine's P&F TR.

    Base range [10.4, 11.4]; spring dip 1% below the detected congestion-zone
    lower, recovered next bar back into the zone with volume contraction.  The
    phase resolves to ACCUMULATION so the full analyze() path emits "spring".
    """
    rng = np.random.default_rng(seed)
    low, high = 10.4, 11.4
    mid = (low + high) / 2
    half = (high - low) / 2
    close = mid + rng.uniform(-half, half, 100) * 0.5
    high_ = close + rng.uniform(0, 0.15, 100)
    low_ = close - rng.uniform(0, 0.15, 100)
    vol = (1e7 * (1 + rng.normal(0, 0.3, 100))).astype(int)
    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=100, freq="D"),
        "open": close * (1 + rng.uniform(-0.005, 0.005, 100)),
        "high": high_,
        "low": low_,
        "close": close,
        "volume": vol,
    })

    pnf = PointAndFigure(box_size=0.02, reversal=2)
    pnf.build(df)
    zone_lower = pnf.congestion_zone()[0]

    dip = zone_lower * 0.99  # 1% below detected TR lower
    df.loc[79, "low"] = dip - 0.02
    df.loc[79, "close"] = dip + 0.03
    df.loc[79, "volume"] = int(0.5 * df["volume"].median())

    df.loc[80, "close"] = zone_lower + 0.15
    df.loc[80, "low"] = dip + 0.05
    df.loc[80, "high"] = zone_lower + 0.25
    df.loc[80, "volume"] = int(1.2 * df["volume"].median())
    return df


def synthetic_accumulation_event_sequence(seed: int = 42) -> pd.DataFrame:
    """Generate OHLCV driven purely by the accumulation event sequence.

    Price position stays in the middle band (relative_position 0.4-0.6) so no
    price_position heuristic fires; only the event sequence PS->SC->AR->ST->ST
    can drive ACCUMULATION.  Detected events: PS (0.58), SC (0.91), AR (0.73),
    ST (0.62) x2.  P&F phase_hint is "unknown" so the detector chain runs.
    """
    rng = np.random.default_rng(seed)
    n = 130
    amp = 0.6
    osc_early = 15
    down_start = 90
    down_len = 16
    down_end = down_start + down_len
    sc_low = 8.3
    end_close = 9.4

    close = np.zeros(n)
    t = np.arange(down_start)
    close[:down_start] = (
        10.25 + amp * np.sin(2 * np.pi * t / osc_early)
        + amp * 0.17 * np.sin(2 * np.pi * t / 7)
    )
    close[down_start:down_end] = np.linspace(10.5, 9.6, down_len)

    ps_i, sc_i = down_end, down_end + 6
    st1, st2 = sc_i + 5, sc_i + 8
    spr = sc_i + 11
    sos = spr + 3
    close[ps_i] = 9.6
    close[ps_i + 1] = 9.8
    close[sc_i] = sc_low
    close[sc_i + 1] = sc_low * 1.03
    close[st1] = sc_low * 1.005
    close[st2] = sc_low * 1.015
    close[spr] = sc_low * 0.99
    close[spr + 1] = 9.4
    close[sos] = 9.8
    close[sos + 1] = end_close
    close[sos + 2] = end_close * 0.99
    close[sos + 3] = end_close * 0.995
    for i in range(n):
        if close[i] == 0:
            close[i] = close[i - 1]

    opn = close * (1 + rng.uniform(-0.005, 0.005, n))
    hi = np.maximum(opn, close) * (1 + rng.uniform(0.002, 0.02, n))
    lo = np.minimum(opn, close) * (1 - rng.uniform(0.002, 0.02, n))
    vol = np.full(n, int(1e7))
    vol[ps_i] = int(2.2e7)
    vol[sc_i] = int(3.2e7)
    vol[st1] = int(4e6)
    vol[st2] = int(4e6)
    vol[spr] = int(4e6)
    vol[sos] = int(1.8e7)

    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=n, freq="D"),
        "open": opn, "high": hi, "low": lo, "close": close, "volume": vol,
    })
    df.loc[ps_i, "low"] = 9.3
    df.loc[ps_i, "high"] = 9.9
    df.loc[ps_i, "close"] = 9.6
    df.loc[ps_i, "open"] = 9.7
    df.loc[sc_i, "low"] = sc_low * 0.98
    df.loc[sc_i, "high"] = sc_low * 1.03
    df.loc[sc_i, "close"] = sc_low
    df.loc[sc_i, "open"] = sc_low * 1.01
    df.loc[spr, "low"] = sc_low * 0.99
    df.loc[spr, "high"] = sc_low * 1.04
    df.loc[spr, "close"] = sc_low * 0.99
    df.loc[spr, "open"] = sc_low * 1.02
    df.loc[sos, "low"] = 9.5
    df.loc[sos, "high"] = 10.0
    df.loc[sos, "close"] = 9.8
    df.loc[sos, "open"] = 9.6
    return df


def synthetic_distribution_event_sequence(seed: int = 42) -> pd.DataFrame:
    """Generate OHLCV driven purely by the distribution event sequence.

    Sequence: 上涨 → PSY(放量上影线) → UTAD(放量假突破收回) → LPSY(缩量) → 跌破 TR。
    尾部跌破段故意不深（11.0→9.5），避免 markdown 启发式抢跑；仅 UTAD 事件
    (vol_ratio 2.0) 能驱动 DISTRIBUTION。P&F phase_hint="unknown" 确保走检测器链。
    """
    rng = np.random.default_rng(seed)
    n = 120
    close = np.zeros(n)
    t = np.arange(40)
    close[:40] = 8 + 4 * t / 40 + 0.1 * np.sin(2 * np.pi * t / 10)
    t2 = np.arange(40, 110)
    close[40:110] = (
        11.25 + 0.7 * np.sin(2 * np.pi * (t2 - 40) / 18)
        + 0.15 * np.sin(2 * np.pi * (t2 - 40) / 7)
    )
    psy = 95
    utad = 100
    lpsy = 105
    close[psy] = 11.8
    close[utad] = 11.5
    close[lpsy] = 11.3
    close[110:] = np.linspace(11.0, 9.5, 10)
    for i in range(n):
        if close[i] == 0:
            close[i] = close[i - 1]

    opn = close * (1 + rng.uniform(-0.008, 0.008, n))
    hi = np.maximum(opn, close) * (1 + rng.uniform(0.002, 0.02, n))
    lo = np.minimum(opn, close) * (1 - rng.uniform(0.002, 0.02, n))
    vol = np.full(n, int(1e7))
    vol[psy] = int(2.0e7)
    vol[utad] = int(2.5e7)
    vol[lpsy] = int(4e6)

    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=n, freq="D"),
        "open": opn, "high": hi, "low": lo, "close": close, "volume": vol,
    })
    df.loc[psy, "high"] = 13.2
    df.loc[psy, "low"] = 11.0
    df.loc[psy, "close"] = 11.8
    df.loc[psy, "open"] = 12.2
    df.loc[utad, "high"] = 13.5
    df.loc[utad, "low"] = 11.2
    df.loc[utad, "close"] = 11.5
    df.loc[utad, "open"] = 13.0
    df.loc[lpsy, "high"] = 11.6
    df.loc[lpsy, "low"] = 11.0
    df.loc[lpsy, "close"] = 11.3
    df.loc[lpsy, "open"] = 11.5
    return df


def synthetic_false_breakout(seed: int = 42) -> pd.DataFrame:
    """Generate OHLCV with a false breakout above TR then fallback.

    TR = [10, 12]; bar 85 breaks above 12.50, bar 87 falls back into TR.
    """
    np.random.default_rng(seed)
    df = synthetic_trading_range(length=100, low_bound=10.0, high_bound=12.0, seed=seed * 3)
    close = df["close"].values

    close[84] = 12.50  # breakout
    df.loc[84, "high"] = 12.80
    df.loc[84, "volume"] = int(2.5 * df["volume"].median())

    close[85] = 12.80  # extend
    df.loc[85, "high"] = 13.00
    df.loc[85, "volume"] = int(2.0 * df["volume"].median())

    close[86] = 11.50  # fall back into TR
    df.loc[86, "volume"] = int(1.2 * df["volume"].median())

    df["close"] = close
    return df


def synthetic_utad(length: int = 100, seed: int = 42) -> pd.DataFrame:
    """Generate OHLCV with a UTAD (Upthrust After Distribution) event.

    TR = [10, 12]; bar 90 high=12.50 (breakout 4% above TR upper), close=11.50
    (recovered back into range), volume ratio > 1.5x median. Preceded by a
    mild uptrend to set the distribution context.
    """
    rng = np.random.default_rng(seed)
    df = synthetic_trading_range(length=length, low_bound=10.0, high_bound=12.0, seed=seed * 11)
    close = df["close"].values

    # Prior uptrend (markup context before distribution)
    up_end = length // 3
    close[:up_end] = close[0] * (1 + 0.15 * np.linspace(0, 1, up_end))

    # UTAD bar: high above TR upper, close recovered back into range
    utad_idx = 89
    close[utad_idx] = 11.50
    df.loc[utad_idx, "high"] = 12.50
    df.loc[utad_idx, "low"] = min(11.30, close[utad_idx] * 0.98)
    df.loc[utad_idx, "volume"] = int(2.0 * df["volume"].median())

    df["close"] = close
    df["open"] = df["close"] * (1 + rng.uniform(-0.005, 0.005, length))
    return df


__all__ = [
    "synthetic_sine_wave",
    "synthetic_accumulation",
    "synthetic_distribution",
    "synthetic_trading_range",
    "synthetic_limit_up",
    "synthetic_spring",
    "synthetic_spring_late_recovery",
    "synthetic_spring_aligned",
    "synthetic_accumulation_event_sequence",
    "synthetic_distribution_event_sequence",
    "synthetic_false_breakout",
    "synthetic_utad",
]
