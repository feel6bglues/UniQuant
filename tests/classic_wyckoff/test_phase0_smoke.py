"""Smoke test: fixtures load and engine accepts them.

Verifies the synthetic OHLCV generators produce data the WyckoffEngine
can analyze without crashing. This is the Phase 0 integration gate.
"""

from __future__ import annotations

from uniquant.brain.wyckoff.engine import WyckoffEngine


def _run_engine(df):
    engine = WyckoffEngine()
    return engine.analyze(df, symbol="TEST.SH")


def test_fixtures_load(sine_ohlcv, accumulation_ohlcv, distribution_ohlcv):
    """All synthetic generators return valid OHLCV frames."""
    for df in (sine_ohlcv, accumulation_ohlcv, distribution_ohlcv):
        assert {"date", "open", "high", "low", "close", "volume"}.issubset(df.columns)
        assert len(df) >= 100  # engine minimum for daily


def test_engine_accepts_accumulation_fixture(accumulation_ohlcv):
    """Engine runs without error on the synthetic accumulation sequence."""
    report = _run_engine(accumulation_ohlcv)
    assert report is not None


def test_engine_accepts_distribution_fixture(distribution_ohlcv):
    """Engine runs without error on the synthetic distribution sequence."""
    report = _run_engine(distribution_ohlcv)
    assert report is not None


def test_engine_accepts_spring_fixture(spring_ohlcv):
    """Engine runs without error on the synthetic Spring fixture."""
    report = _run_engine(spring_ohlcv)
    assert report is not None
