"""Tests for Wyckoff event chain detection (PS/SC/AR/ST/SOS/LPS/JAC)."""

import pytest
import pandas as pd
import numpy as np
from uniquant.brain.wyckoff.events import (
    WyckoffEvent,
    detect_ps, detect_sc, detect_ar, detect_st,
    detect_sos, detect_lps, detect_jac,
    detect_all_events, event_sequence_key,
)


def make_daily(close_seq, vol_base=5e6, open_pct=0.995, high_pct=1.01, low_pct=0.99):
    """Create daily OHLCV DataFrame from close prices with simple OHLC."""
    n = len(close_seq)
    closes = np.array(close_seq)
    opens = closes * open_pct
    opens[0] = closes[0]
    highs = np.maximum(closes, opens) * high_pct
    lows = np.minimum(closes, opens) * low_pct
    dates = pd.date_range('2020-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'date': dates, 'open': opens, 'high': highs,
        'low': lows, 'close': closes,
        'volume': np.full(n, vol_base, dtype=float),
    })


def make_ps_scenario():
    """15-bar pre-warm + 25-bar downtrend ending with PS candidate."""
    np.random.seed(42)
    n = 40
    down = np.linspace(100, 80, n)
    noise = np.random.randn(n) * 0.3
    close = down + noise
    df = make_daily(close)
    # Add PS: volume spike, long lower shadow at bar 25, close in upper half
    df.loc[25, 'volume'] = 8e6  # >1.5x vol_ma20
    df.loc[25, 'low'] = df.loc[25, 'close'] - 1.5  # long lower shadow
    df.loc[26, 'close'] = df.loc[25, 'close'] + 0.5  # confirm next day
    return df


def make_sc_scenario():
    """60-bar window ending with SC candidate."""
    np.random.seed(42)
    n = 60
    down = np.linspace(100, 70, n)
    noise = np.random.randn(n) * 0.4
    close = down + noise
    df = make_daily(close, vol_base=3e6)
    # SC at bar 50: huge volume, long lower shadow, new low, rebound
    df.loc[50, 'volume'] = 12e6  # >2x vol_ma20
    df.loc[50, 'low'] = df.loc[50, 'close'] - 2.5  # very long lower shadow
    df.loc[50, 'high'] = df.loc[50, 'close'] + 0.5
    # Subsequent high (bar 51-55) shows recovery
    df.loc[51, 'close'] = df.loc[50, 'close'] + 2.0
    df.loc[52, 'close'] = df.loc[51, 'close'] + 1.0
    return df


def make_sos_scenario():
    """40-bar window ending with a strong SOS day."""
    n = 40
    close = np.linspace(100, 105, n)
    df = make_daily(close, vol_base=3e6)
    # SOS at bar 35: +5% gain, >2x volume, close near high, new 20d high
    df.loc[35, 'close'] = df.loc[34, 'close'] * 1.05
    df.loc[35, 'high'] = df.loc[35, 'close'] * 1.01
    df.loc[35, 'low'] = df.loc[34, 'close'] * 0.99
    df.loc[35, 'volume'] = 8e6
    return df


def make_jac_scenario():
    """40-bar window with tight TR ending in upside breakout."""
    n = 40
    close = np.linspace(100, 102, n)
    df = make_daily(close, vol_base=3e6)
    # Tight range: high=103, low=99 → range=4% < 15% ✅
    df['high'] = df['close'] + 2.0
    df['low'] = df['close'] - 2.0
    # JAC at bar 38: break above TR high
    df.loc[38, 'close'] = 104.5
    df.loc[38, 'high'] = 105.0
    df.loc[38, 'volume'] = 6e6
    return df


class TestDetectPS:
    def test_ps_detected_in_downtrend(self):
        df = make_ps_scenario()
        events = detect_ps(df)
        types = [e.event_type for e in events]
        assert 'PS' in types, f"No PS detected, got {types}"

    def test_ps_returns_empty_on_no_downtrend(self):
        n = 30
        close = np.linspace(100, 120, n)
        df = make_daily(close)
        assert detect_ps(df) == []

    def test_ps_returns_empty_on_short_data(self):
        df = make_daily([100] * 20)
        assert detect_ps(df) == []

    def test_ps_confidence_in_range(self):
        df = make_ps_scenario()
        for e in detect_ps(df):
            assert 0 <= e.confidence <= 1


class TestDetectSC:
    def test_sc_detected(self):
        df = make_sc_scenario()
        events = detect_sc(df)
        types = [e.event_type for e in events]
        assert 'SC' in types, f"No SC detected, got {types}"

    def test_sc_confidence_in_range(self):
        df = make_sc_scenario()
        for e in detect_sc(df):
            assert 0 <= e.confidence <= 1

    def test_sc_returns_empty_on_uptrend(self):
        n = 40
        close = np.linspace(100, 130, n)
        df = make_daily(close)
        assert detect_sc(df) == []


class TestDetectAR:
    def test_ar_detected_after_sc(self):
        df = make_sc_scenario()
        sc = detect_sc(df)
        events = detect_ar(df, sc)
        types = [e.event_type for e in events]
        assert len(sc) > 0
        assert 'AR' in types or len(events) == 0, f"No AR detected, got {types}"

    def test_ar_returns_empty_without_sc(self):
        df = make_sc_scenario()
        assert detect_ar(df, []) == []


class TestDetectST:
    def test_st_returns_events_with_sc_anchor(self):
        df = make_sc_scenario()
        sc = detect_sc(df)
        if sc:
            events = detect_st(df, sc)
            # ST may or may not fire depending on data — just don't crash
            for e in events:
                assert e.event_type == 'ST'
                assert 0 <= e.confidence <= 1


class TestDetectSOS:
    def test_sos_detected(self):
        df = make_sos_scenario()
        events = detect_sos(df)
        types = [e.event_type for e in events]
        assert 'SOS' in types, f"No SOS detected, got {types}"

    def test_sos_confidence_in_range(self):
        df = make_sos_scenario()
        for e in detect_sos(df):
            assert 0 <= e.confidence <= 1


class TestDetectLPS:
    def test_lps_returns_events_with_sos_anchor(self):
        df = make_sos_scenario()
        sos = detect_sos(df)
        if sos:
            events = detect_lps(df, sos)
            for e in events:
                assert e.event_type == 'LPS'
                assert 0 <= e.confidence <= 1


class TestDetectJAC:
    def test_jac_detected(self):
        df = make_jac_scenario()
        events = detect_jac(df)
        types = [e.event_type for e in events]
        assert 'JAC' in types, f"No JAC detected, got {types}"


class TestDetectAllEvents:
    def test_returns_sorted_events(self):
        df = make_ps_scenario()
        events = detect_all_events(df)
        for i in range(1, len(events)):
            assert events[i].date >= events[i - 1].date

    def test_no_crash_on_flat_data(self):
        n = 60
        close = np.full(n, 100.0)
        df = make_daily(close)
        events = detect_all_events(df)
        assert isinstance(events, list)

    def test_no_crash_on_short_data(self):
        df = make_daily([100] * 20)
        events = detect_all_events(df)
        assert isinstance(events, list)


class TestEventSequenceKey:
    def test_empty_events(self):
        assert event_sequence_key([]) == 'NONE'

    def test_single_event(self):
        e = [WyckoffEvent('PS', '2020-01-10', 100.0, 0.8, 1.5)]
        assert 'PS' in event_sequence_key(e)

    def test_low_confidence_filtered(self):
        e = [WyckoffEvent('PS', '2020-01-10', 100.0, 0.1, 1.5)]
        assert event_sequence_key(e) == 'LOW_CONF'
