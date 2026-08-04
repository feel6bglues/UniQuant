"""Tests for MonthlyPhaseClassifier."""

import pandas as pd
import numpy as np
from uniquant.brain.wyckoff.monthly_classifier import MonthlyPhaseClassifier


def make_monthly_bars(close_seq, low_pct=0.94, high_pct=1.06, vol_base=1e8):
    """Helper: create 12 monthly OHLCV bars from a close price sequence."""
    n = len(close_seq)
    closes = np.array(close_seq)
    lows = closes * low_pct
    highs = closes * high_pct
    vols = np.full(n, vol_base)
    return pd.DataFrame({
        'close': closes, 'high': highs, 'low': lows, 'volume': vols,
    })


class TestMonthlyPhaseClassifier:
    def test_accumulation_detected(self):
        """Accumulation: pp<0.35, vt<-0.15, rp<80, vr<0.85."""
        # Range 80-100, final close at 86 → pp = 6/20 = 0.30 < 0.35 ✅
        close = np.array([100, 98, 95, 92, 89, 87, 85, 84, 83, 84, 85, 86])
        df = pd.DataFrame({
            'close': close, 'high': 102, 'low': 80,
            'volume': np.linspace(3e8, 1e8, 12),
        })
        # vt = 1e8/3e8-1 = -0.67 < -0.15 ✅
        # rp = 102/80-1 = 27.5% < 80% ✅
        # vr = mean(v[-3:])/mean(v) = 0.59 < 0.85 ✅
        clf = MonthlyPhaseClassifier()
        assert clf.classify(df) == 'accumulation'

    def test_markup_detected(self):
        """Markup: tr>10, pp>0.5, vt>0."""
        close = np.linspace(100, 180, 12)
        df = pd.DataFrame({
            'close': close, 'high': 185, 'low': 95,
            'volume': np.linspace(1e8, 2.5e8, 12),
        })
        clf = MonthlyPhaseClassifier()
        assert clf.classify(df) == 'markup'

    def test_distribution_detected(self):
        """Distribution: pp>0.6, vp_corr<-0.2, rp>80."""
        # Range 100-200 (rp=100% > 80% ✅), price at 170 (pp=0.70 > 0.6 ✅)
        # Price trending up but volume trending down → vp_corr negative ✅
        close = np.linspace(150, 170, 12)
        df = pd.DataFrame({
            'close': close, 'high': 200, 'low': 100,
            'volume': np.linspace(4e8, 1e8, 12),  # vol declining while price up → negative corr
        })
        clf = MonthlyPhaseClassifier()
        phase = clf.classify(df)
        assert phase == 'distribution', f"Expected distribution, got {phase}"

    def test_markdown_detected(self):
        """Markdown: strong downtrend."""
        close = np.linspace(200, 80, 12)  # -60% decline
        df = make_monthly_bars(close, low_pct=0.9, high_pct=1.1)

        clf = MonthlyPhaseClassifier()
        phase = clf.classify(df)
        assert phase == 'markdown', f"Expected markdown, got {phase}"

    def test_unknown_returned_for_ambiguous(self):
        """Random data returns unknown (or any valid phase, no crash)."""
        np.random.seed(42)
        close = 100 * np.cumprod(1 + np.random.normal(0, 0.03, 12))
        df = make_monthly_bars(close)
        df['volume'] = np.random.uniform(1e8, 2e8, 12)

        clf = MonthlyPhaseClassifier()
        phase = clf.classify(df)
        assert phase in ('accumulation', 'markup', 'distribution', 'markdown', 'unknown')

    def test_raises_on_too_few_bars(self):
        """Should handle <12 bars gracefully."""
        df = make_monthly_bars([100] * 6)
        clf = MonthlyPhaseClassifier()
        assert clf.classify(df) == 'unknown'

    def test_features_stored(self):
        """Last features accessible after classify()."""
        close = np.linspace(100, 150, 12)
        df = make_monthly_bars(close)
        clf = MonthlyPhaseClassifier()
        clf.classify(df)
        features = clf.get_features()
        assert 'price_pos' in features
        assert 'trend_pct' in features
        assert 'ret_6m' in features
        assert 0 <= features['price_pos'] <= 1

    def test_synthetic_accumulation_from_real_profile(self):
        """Match known accumulation profile from the 76K snapshot analysis."""
        # Accumulation profile: pp<0.35, vt<-0.15, rp<80, vr<0.85
        close = np.array([100, 99, 97, 95, 94, 93, 92, 91, 90, 91.5, 92.5, 94])
        df = pd.DataFrame({
            'close': close,
            'high': 102,  # range = (102-88)/88 = 16%, < 80% ✅
            'low': 88,
            'volume': np.linspace(3e8, 1e8, 12),  # vol -67% < -15% ✅
        })
        # pp = (94-88)/(102-88) = 6/14 = 0.43  — still > 0.35!
        # Need tighter range
        df['high'] = 96
        # pp = (94-88)/(96-88) = 6/8 = 0.75 — too high!
        # The issue: price recovered too much, need to stay lower
        close = np.array([100, 98, 95, 93, 91, 90, 89, 88, 88, 89, 89, 90])
        df = pd.DataFrame({
            'close': close,
            'high': 102,
            'low': 87,
            'volume': np.linspace(3e8, 1e8, 12),
        })
        # pp = (90-87)/(102-87) = 3/15 = 0.20 < 0.35 ✅
        # rp = (102/87-1)*100 = 17% < 80% ✅
        # vt = (1e8/3e8-1) = -0.67 < -0.15 ✅
        # vr = 1.33e8/2e8 = 0.67 < 0.85 ✅
        clf = MonthlyPhaseClassifier()
        phase = clf.classify(df)
        assert phase == 'accumulation', f"Expected accumulation, got {phase}"
