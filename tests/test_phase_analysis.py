"""Tests for multi-timeframe phase analysis (WeeklyPhaseClassifier, DailyPhaseClassifier, MultiTimeframeResonance)."""

import pytest
import pandas as pd
import numpy as np
from uniquant.brain.wyckoff.phase_analysis import (
    WeeklyPhaseClassifier,
    DailyPhaseClassifier,
    MultiTimeframeResonance,
)


def make_weekly_bars(close_seq, low_pct=0.93, high_pct=1.07, vol_base=2e8):
    n = len(close_seq)
    closes = np.array(close_seq)
    lows = closes * low_pct
    highs = closes * high_pct
    vols = np.full(n, vol_base)
    return pd.DataFrame({
        'close': closes, 'high': highs, 'low': lows, 'volume': vols,
    })


def make_daily_bars(n_days, start_price=100, trend=0, volatility=2, vol_base=5e6):
    """Create synthetic daily bars with given trend and volatility."""
    np.random.seed(42)
    prices = start_price * np.cumprod(1 + np.random.randn(n_days) * volatility / 100 + trend / 100)
    return pd.DataFrame({
        'close': prices,
        'high': prices * 1.02,
        'low': prices * 0.98,
        'volume': np.random.uniform(0.5, 1.5, n_days) * vol_base,
    })


class TestWeeklyPhaseClassifier:
    def test_markup_detected(self):
        close = np.linspace(100, 130, 12)
        df = pd.DataFrame({
            'close': close, 'high': 135, 'low': 95,
            'volume': np.linspace(2e8, 3e8, 12),
        })
        clf = WeeklyPhaseClassifier()
        assert clf.classify(df) == 'markup'

    def test_markdown_detected(self):
        close = np.linspace(200, 80, 12)
        df = make_weekly_bars(close, low_pct=0.9, high_pct=1.1)
        clf = WeeklyPhaseClassifier()
        assert clf.classify(df) == 'markdown'

    def test_accumulation_detected(self):
        close = np.array([100, 97, 100, 96, 99, 95, 98, 94, 97, 94, 96, 96])
        df = pd.DataFrame({
            'close': close,
            'high': 110,
            'low': 90,
            'volume': np.linspace(4e8, 1.5e8, 12),
        })
        clf = WeeklyPhaseClassifier()
        phase = clf.classify(df)
        assert phase == 'accumulation', f"Expected accumulation, got {phase}"

    def test_distribution_detected_by_vp_divergence(self):
        close = np.linspace(150, 165, 12)
        df = pd.DataFrame({
            'close': close, 'high': 200, 'low': 100,
            'volume': np.linspace(4e8, 1e8, 12),
        })
        clf = WeeklyPhaseClassifier()
        phase = clf.classify(df)
        assert phase == 'distribution', f"Expected distribution, got {phase}"

    def test_returns_unknown_for_too_few_bars(self):
        df = make_weekly_bars([100] * 6)
        clf = WeeklyPhaseClassifier()
        assert clf.classify(df) == 'unknown'

    def test_no_crash_on_random_data(self):
        np.random.seed(42)
        close = 100 * np.cumprod(1 + np.random.normal(0, 0.02, 12))
        df = make_weekly_bars(close)
        df['volume'] = np.random.uniform(1e8, 3e8, 12)
        clf = WeeklyPhaseClassifier()
        phase = clf.classify(df)
        assert phase in ('accumulation', 'markup', 'distribution', 'markdown', 'unknown')

    def test_features_stored(self):
        close = np.linspace(100, 130, 12)
        df = make_weekly_bars(close)
        clf = WeeklyPhaseClassifier()
        clf.classify(df)
        features = clf.get_features()
        assert 'price_pos' in features
        assert 'trend_pct' in features
        assert 'range_pct' in features
        assert 0 <= features['price_pos'] <= 1


class TestDailyPhaseClassifier:
    def test_markdown_detected(self):
        df = make_daily_bars(60, start_price=100, trend=-0.35, volatility=1.5)
        clf = DailyPhaseClassifier()
        phase = clf.classify(df)
        assert phase == 'markdown', f"Expected markdown, got {phase}"

    def test_markup_detected(self):
        n = 60
        close = np.linspace(100, 140, n) + np.random.RandomState(42).randn(n) * 0.5
        volume = np.linspace(3e6, 6e6, n)
        df = pd.DataFrame({
            'close': close,
            'high': close * 1.02,
            'low': close * 0.98,
            'volume': volume,
        })
        clf = DailyPhaseClassifier()
        phase = clf.classify(df)
        assert phase == 'markup', f"Expected markup, got {phase}"

    def test_accumulation_detected(self):
        np.random.seed(42)
        n = 60
        close = np.linspace(100, 95, n) + np.random.randn(n) * 0.5
        volume = np.linspace(8e6, 2e6, n)
        df = pd.DataFrame({
            'close': close,
            'high': close * 1.03,
            'low': close * 0.97,
            'volume': volume,
        })
        clf = DailyPhaseClassifier()
        phase = clf.classify(df)
        assert phase == 'accumulation', f"Expected accumulation, got {phase}"

    def test_distribution_detected(self):
        n = 60
        np.random.seed(42)
        close = np.linspace(150, 158, n) + np.random.randn(n) * 0.3
        volume = np.linspace(8e6, 2e6, n)
        df = pd.DataFrame({
            'close': close,
            'high': close * 1.04,
            'low': close * 0.88,
            'volume': volume,
        })
        clf = DailyPhaseClassifier()
        phase = clf.classify(df)
        assert phase == 'distribution', f"Expected distribution, got {phase}"

    def test_returns_unknown_for_too_few_bars(self):
        df = make_daily_bars(15)
        clf = DailyPhaseClassifier()
        assert clf.classify(df) == 'unknown'

    def test_no_crash_on_random_data(self):
        np.random.seed(42)
        df = make_daily_bars(60, start_price=100, trend=0, volatility=3)
        clf = DailyPhaseClassifier()
        phase = clf.classify(df)
        assert phase in ('accumulation', 'markup', 'distribution', 'markdown', 'unknown')

    def test_features_stored(self):
        df = make_daily_bars(60, start_price=100, trend=0.15)
        clf = DailyPhaseClassifier()
        clf.classify(df)
        features = clf.get_features()
        assert 'price_pos' in features
        assert 'above_ma20' in features
        assert 'trend_20d' in features

    def test_no_crash_on_flat_data(self):
        df = pd.DataFrame({
            'close': np.full(60, 100.0),
            'high': np.full(60, 101.0),
            'low': np.full(60, 99.0),
            'volume': np.full(60, 5e6),
        })
        clf = DailyPhaseClassifier()
        phase = clf.classify(df)
        assert phase in ('accumulation', 'markup', 'distribution', 'markdown', 'unknown')

    def test_no_crash_on_zero_volume(self):
        df = make_daily_bars(60, start_price=100, trend=-0.15)
        df['volume'] = 0
        clf = DailyPhaseClassifier()
        assert clf.classify(df) == 'markdown'


class TestMultiTimeframeResonance:
    def test_three_bullish(self):
        r = MultiTimeframeResonance.resonance('accumulation', 'markup', 'accumulation')
        assert r['resonance_count'] == 3
        assert r['resonance_dir'] == 'bullish'

    def test_three_bearish(self):
        r = MultiTimeframeResonance.resonance('markdown', 'distribution', 'markdown')
        assert r['resonance_count'] == 3
        assert r['resonance_dir'] == 'bearish'

    def test_two_bullish(self):
        r = MultiTimeframeResonance.resonance('accumulation', 'unknown', 'markup')
        assert r['resonance_count'] == 2
        assert r['resonance_dir'] == 'bullish'

    def test_two_bearish(self):
        r = MultiTimeframeResonance.resonance('markdown', 'unknown', 'distribution')
        assert r['resonance_count'] == 2
        assert r['resonance_dir'] == 'bearish'

    def test_conflicting_one_each(self):
        r = MultiTimeframeResonance.resonance('accumulation', 'markdown', 'unknown')
        assert r['resonance_dir'] == 'conflicting'
        assert r['resonance_count'] == 1

    def test_conflicting_all_unknown(self):
        r = MultiTimeframeResonance.resonance('unknown', 'unknown', 'unknown')
        assert r['resonance_dir'] == 'conflicting'
        assert r['resonance_count'] == 0

    def test_is_bullish_confirmed(self):
        assert MultiTimeframeResonance.is_bullish_confirmed('markup', 'accumulation', 'unknown')
        assert not MultiTimeframeResonance.is_bullish_confirmed('markdown', 'markup', 'unknown')

    def test_is_bearish_confirmed(self):
        assert MultiTimeframeResonance.is_bearish_confirmed('distribution', 'markdown', 'unknown')
        assert not MultiTimeframeResonance.is_bearish_confirmed('markup', 'accumulation', 'unknown')

    def test_is_strong_confirmed_all_3(self):
        assert MultiTimeframeResonance.is_strong_confirmed('markup', 'markup', 'accumulation')
        assert not MultiTimeframeResonance.is_strong_confirmed('markup', 'accumulation', 'unknown')

    def test_is_accum_confirmed(self):
        assert MultiTimeframeResonance.is_accum_confirmed('accumulation', 'accumulation', 'markup')
        assert not MultiTimeframeResonance.is_accum_confirmed('accumulation', 'markup', 'markdown')
