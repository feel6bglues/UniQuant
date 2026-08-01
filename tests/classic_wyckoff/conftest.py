"""Classic Wyckoff TDD test fixtures.

Registers the synthetic OHLCV generators from scripts/wyckoff_fixtures.py
as pytest fixtures. All generators are seed-parameterized for reproducibility.
"""

from __future__ import annotations

import pytest

from scripts.wyckoff_fixtures import (
    synthetic_accumulation,
    synthetic_distribution,
    synthetic_false_breakout,
    synthetic_limit_up,
    synthetic_sine_wave,
    synthetic_spring,
    synthetic_trading_range,
)


@pytest.fixture
def sine_ohlcv():
    """Random sine-wave OHLCV baseline (no Wyckoff structure)."""
    return synthetic_sine_wave(seed=42)


@pytest.fixture
def accumulation_ohlcv():
    """Full Accumulation event sequence: PS->BC->AR->SC->ST1->ST2->Spring->SOS->LPS."""
    return synthetic_accumulation(seed=42)


@pytest.fixture
def distribution_ohlcv():
    """Distribution event sequence: uptrend->PSY->UTAD->LPSY->breakdown."""
    return synthetic_distribution(seed=42)


@pytest.fixture
def trading_range_ohlcv():
    """OHLCV confined to horizontal TR [10, 12]."""
    return synthetic_trading_range(seed=42)


@pytest.fixture
def limit_up_ohlcv():
    """3 consecutive limit-up days (close == high, no upper shadow)."""
    return synthetic_limit_up(seed=42)


@pytest.fixture
def spring_ohlcv():
    """Classic Spring: bar 80 breaks below TR low to 9.90, bar 81 recovers to 11.50."""
    return synthetic_spring(seed=42)


@pytest.fixture
def false_breakout_ohlcv():
    """False breakout above TR then fallback into range."""
    return synthetic_false_breakout(seed=42)
