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
            l = o * 0.98
        else:
            h = c * 1.02
            l = o * 0.98
        v = int(1e7 * (1 + rng.uniform(-0.1, 0.1)))
        rows.append({"date": d, "open": o, "high": h, "low": l, "close": c, "volume": v})
    return pd.DataFrame(rows)


def synthetic_spring(seed: int = 42) -> pd.DataFrame:
    """Generate OHLCV with a classic Spring event.

    TR = [10, 12]; bar 80 breaks below TR low to 9.90, bar 81 recovers to 11.50.
    """
    rng = np.random.default_rng(seed)
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


def synthetic_false_breakout(seed: int = 42) -> pd.DataFrame:
    """Generate OHLCV with a false breakout above TR then fallback.

    TR = [10, 12]; bar 85 breaks above 12.50, bar 87 falls back into TR.
    """
    rng = np.random.default_rng(seed)
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


__all__ = [
    "synthetic_sine_wave",
    "synthetic_accumulation",
    "synthetic_distribution",
    "synthetic_trading_range",
    "synthetic_limit_up",
    "synthetic_spring",
    "synthetic_false_breakout",
]
