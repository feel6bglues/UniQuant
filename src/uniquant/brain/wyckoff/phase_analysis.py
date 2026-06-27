"""Multi-timeframe phase analysis — weekly, daily phase classifiers + resonance.

Extends MonthlyPhaseClassifier to provide complete Wyckoff phase detection
across three timeframes for the same observation point.

Usage:
    from uniquant.brain.wyckoff.phase_analysis import WeeklyPhaseClassifier, DailyPhaseClassifier, MultiTimeframeResonance
    wpc = WeeklyPhaseClassifier()
    dpc = DailyPhaseClassifier()
    w_phase = wpc.classify(weekly_12_bars)
    d_phase = dpc.classify(daily_60_bars)
    res = MultiTimeframeResonance.resonance(m_phase, w_phase, d_phase)
"""

import math

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional


class WeeklyPhaseClassifier:
    """Classifies Wyckoff phase from 12 weekly OHLCV bars.

    Thresholds are proportionally scaled from MonthlyPhaseClassifier's
    empirically-derived values (12 weekly bars ≈ 3 months vs 12 monthly bars = 12 months).
    """

    def __init__(self):
        self._last_features = {}

    def classify(self, df: pd.DataFrame) -> str:
        """Classify Wyckoff phase from weekly bars.

        Args:
            df: DataFrame with 12 rows, columns ['close','volume','high','low']

        Returns:
            Phase string: 'accumulation', 'markup', 'distribution', 'markdown', 'unknown'
        """
        if len(df) < 12:
            return 'unknown'

        c = df['close'].values
        v = df['volume'].values
        lo = float(df['low'].min())
        hi = float(df['high'].max())
        pp = (c[-1] - lo) / (hi - lo) if hi > lo else 0.5
        tr = (c[-1] / c[0] - 1) * 100 if c[0] > 0 else 0
        vt = (v[-1] / v[0] - 1) if v[0] > 0 else 0
        rp = (hi / lo - 1) * 100 if lo > 0 else 0
        vr = v[-3:].mean() / v.mean() if v.mean() > 0 else 1
        r6 = (c[-1] / c[-7] - 1) * 100 if len(c) >= 7 else 0
        vp_c = float(np.corrcoef(c, v)[0, 1]) if len(c) > 2 and np.std(v) > 0 else 0

        obv = 0
        for j in range(1, len(c)):
            obv += v[j] if c[j] > c[j-1] else -v[j] if c[j] < c[j-1] else 0
        obv_t = obv / v.mean() / len(c) if v.mean() > 0 else 0

        phase = self._rules(pp, tr, vt, rp, vr, r6, vp_c, obv_t)
        self._last_features = {
            'price_pos': pp, 'trend_pct': tr, 'vol_trend': vt,
            'range_pct': rp, 'vol_ratio': vr, 'ret_6w': r6,
            'vp_corr': vp_c, 'obv_trend': obv_t,
        }
        return phase

    def _rules(self, pp, tr, vt, rp, vr, r6, vp_c, obv_t) -> str:
        """Rule-based weekly phase classification with scaled thresholds.

        Scaling rationale (12 weekly bars ≈ 3 months vs 12 monthly bars = 12 months):
          - trend (tr): ~1/3 of monthly magnitude → threshold ±4%
          - range (rp): ~1/3 of monthly → threshold ~25%
          - volume decay (vt): slightly less extreme → -0.10
          - volume ratio (vr): same ratio scale → 0.85
          - OBV trend (obv_t): ~1/2 → ±3
        """
        if tr < -5 or (r6 < -3 and pp < 0.3):
            return 'markdown'

        if pp < 0.35 and vt < -0.10 and rp < 25 and vr < 0.85:
            return 'accumulation'

        if tr > 3 and pp > 0.5 and vt > 0:
            return 'markup'

        if pp > 0.6 and vp_c < -0.2 and rp > 25:
            return 'distribution'

        if pp > 0.6 and obv_t < -3 and r6 < 3:
            return 'distribution'

        if pp < 0.4 and obv_t > 3 and r6 > -3:
            return 'accumulation'

        return 'unknown'

    def get_features(self) -> dict:
        return dict(self._last_features)


class DailyPhaseClassifier:
    """Classifies short-term daily market phase from ~60 daily OHLCV bars.

    Uses price position, short-term trend (20d), volume patterns, and
    OBV divergence. Avoids MA60 which needs >60 bars to warm up.

    States:
      - markdown: price below MA20, 20-day trend negative, low range position
      - accumulation: price in lower range, tight range, volume declining
      - markup: price above MA20, positive 20-day trend, above mid-range
      - distribution: price at upper range, volume-price divergence
      - unknown: mixed or no clear pattern
    """

    def __init__(self):
        self._last_features = {}

    def classify(self, df: pd.DataFrame) -> str:
        """Classify daily short-term phase from ~60 daily bars.

        Args:
            df: DataFrame with 30-120 rows, columns ['close','volume','high','low']

        Returns:
            Phase string: 'markdown', 'accumulation', 'markup', 'distribution', 'unknown'
        """
        if len(df) < 30:
            return 'unknown'

        close = df['close'].values.astype(float)
        volume = df['volume'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        n = len(df)

        lo_60, hi_60 = float(low.min()), float(high.max())
        pp = (close[-1] - lo_60) / (hi_60 - lo_60) if hi_60 > lo_60 else 0.5
        rp = (hi_60 / lo_60 - 1) * 100 if lo_60 > 0 else 0

        tr_20 = (close[-1] / close[-20] - 1) * 100 if n >= 20 and close[-20] > 0 else 0

        ma20_s = pd.Series(close).rolling(20).mean().values
        ma20_v = ma20_s[-1] if not np.isnan(ma20_s[-1]) else close[-1]
        above_ma20 = close[-1] > ma20_v
        ma20_slope = (ma20_v / ma20_s[-10] - 1) if n >= 10 and ma20_s[-10] is not None and not np.isnan(ma20_s[-10]) and ma20_s[-10] > 0 else 0

        vol_ma20 = pd.Series(volume).rolling(20).mean().values
        vol_ma20_v = vol_ma20[-1] if not np.isnan(vol_ma20[-1]) else volume[-1]
        vol_ratio = volume[-5:].mean() / vol_ma20_v if vol_ma20_v > 0 else 1
        vol_trend = (volume[-1] / volume[0] - 1) if volume[0] > 0 else 0

        vp_c = 0.0
        if n >= 20 and np.std(volume[-20:]) > 0:
            vp_c = float(np.corrcoef(close[-20:], volume[-20:])[0, 1])

        obv = 0
        for j in range(1, n):
            obv += volume[j] if close[j] > close[j-1] else -volume[j] if close[j] < close[j-1] else 0
        obv_t = obv / volume.mean() / n if volume.mean() > 0 else 0

        phase = self._rules(pp, rp, above_ma20, tr_20, ma20_slope, vol_ratio, vol_trend, vp_c, obv_t)
        self._last_features = {
            'price_pos': pp, 'range_pct': rp,
            'above_ma20': above_ma20, 'trend_20d': tr_20,
            'ma20_slope': ma20_slope,
            'vol_ratio': vol_ratio, 'vol_trend': vol_trend,
            'vp_corr': vp_c, 'obv_trend': obv_t,
        }
        return phase

    def _rules(self, pp, rp, above_ma20, tr_20, ma20_slope, vol_ratio, vol_trend, vp_c, obv_t) -> str:
        """Daily phase decision rules using short-term indicators."""

        if not above_ma20 and tr_20 < -5 and pp < 0.4:
            return 'markdown'

        if above_ma20 and tr_20 > 5 and pp > 0.5 and ma20_slope > 0:
            return 'markup'

        if pp > 0.65 and vp_c < -0.3 and rp > 15 and (vol_ratio < 0.85 or tr_20 < 3):
            return 'distribution'

        if pp < 0.35 and rp < 20 and vol_trend < -0.15 and tr_20 > -10:
            return 'accumulation'

        if pp > 0.65 and obv_t < -3 and tr_20 < 5:
            return 'distribution'

        if pp < 0.40 and obv_t > 3 and rp < 18 and tr_20 > -8:
            return 'accumulation'

        return 'unknown'

    def get_features(self) -> dict:
        return dict(self._last_features)


class RegimeAwarePhaseClassifier:
    """
    Market-regime-adaptive phase classifier.

    Adjusts phase classification thresholds based on the overall market regime.
    In bull markets: accumulation is easier to identify (relax thresholds)
    In bear markets: distribution is easier to identify (relax thresholds)

    This directly addresses the session report finding that buy signals are
    regime-dependent but sell signals are regime-independent.
    """

    BULLISH = {'accumulation', 'markup'}
    BEARISH = {'distribution', 'markdown'}

    def __init__(self, market_regime_detector: Optional[object] = None):
        self.market_regime = market_regime_detector
        self._last_features: Dict = {}

    def classify(self, df: pd.DataFrame, date: pd.Timestamp,
                 period: str = "monthly") -> Tuple[str, float]:
        """Classify phase with regime-adaptive thresholds.

        Args:
            df: OHLCV DataFrame with columns ['close','volume','high','low']
            date: analysis date for regime look-up
            period: 'monthly' (12 bars) or 'daily' (30-120 bars)

        Returns:
            (phase, confidence)
            phase: 'accumulation' | 'markup' | 'distribution' | 'markdown' | 'unknown'
            confidence: 0.0 to 1.0
        """
        regime = self._get_regime(df, date)
        features = self._compute_features(df, period)
        thresholds = self._get_adaptive_thresholds(regime)
        phase = self._classify_with_thresholds(features, thresholds)
        confidence = self._compute_confidence(features, phase, thresholds)
        self._last_features = features
        return phase, confidence

    def _get_regime(self, df: pd.DataFrame, date: pd.Timestamp) -> str:
        """Get market regime: 'bull', 'bear', or 'neutral'."""
        if self.market_regime is not None:
            date_str = str(date.date()) if hasattr(date, 'date') else str(date)
            return self.market_regime.classify(date_str)
        c = df['close'].values
        if len(c) >= 2:
            total_ret = (c[-1] / c[0] - 1) * 100
            if total_ret > 8:
                return 'bull'
            elif total_ret < -8:
                return 'bear'
        return 'neutral'

    def _compute_features(self, df: pd.DataFrame, period: str) -> Dict:
        """Compute features matching MonthlyPhaseClassifier convention."""
        c = df['close'].values
        v = df['volume'].values
        lo = float(df['low'].min())
        hi = float(df['high'].max())
        pp = (c[-1] - lo) / (hi - lo) if hi > lo else 0.5
        tr = (c[-1] / c[0] - 1) * 100 if c[0] > 0 else 0
        vt = (v[-1] / v[0] - 1) if v[0] > 0 else 0
        rp = (hi / lo - 1) * 100 if lo > 0 else 0
        vr = v[-3:].mean() / v.mean() if v.mean() > 0 else 1
        n = len(c)
        r6 = (c[-1] / c[-7] - 1) * 100 if n >= 7 else 0
        vp_c = float(np.corrcoef(c, v)[0, 1]) if len(c) > 2 and np.std(v) > 0 else 0

        obv = 0
        for j in range(1, n):
            obv += v[j] if c[j] > c[j-1] else -v[j] if c[j] < c[j-1] else 0
        obv_t = obv / v.mean() / n if v.mean() > 0 else 0

        return {
            'price_pos': pp, 'trend_pct': tr, 'vol_trend': vt,
            'range_pct': rp, 'vol_ratio': vr, 'ret_6': r6,
            'vp_corr': vp_c, 'obv_trend': obv_t,
        }

    def _get_adaptive_thresholds(self, regime: str) -> Dict:
        """Get regime-specific thresholds.

        Base values match MonthlyPhaseClassifier empirically-derived defaults.
        Bull regime: relaxed accumulation, stricter distribution.
        Bear regime: stricter accumulation, relaxed distribution.
        """
        thresholds = {
            'accumulation_tr': -15,
            'markup_rp': 80,
            'distribution_tr': 15,
            'markdown_rp': -80,
            'accumulation_pp': 0.35,
            'accumulation_vt': -0.15,
            'accumulation_rp': 80,
            'accumulation_vr': 0.85,
            'markup_tr': 10,
            'markup_pp': 0.5,
            'distribution_pp': 0.6,
            'distribution_vp_c': -0.2,
            'distribution_rp': 80,
            'distribution_obv_t': -5,
            'distribution_r6': 5,
            'accumulation_obv_t': 5,
            'accumulation_r6': -5,
            'markdown_r6': -10,
            'markdown_pp': 0.3,
        }
        if regime == 'bull':
            thresholds['accumulation_tr'] = -10
            thresholds['distribution_tr'] = 20
            thresholds['accumulation_rp'] = 90
            thresholds['markup_tr'] = 8
        elif regime == 'bear':
            thresholds['accumulation_tr'] = -20
            thresholds['distribution_tr'] = 10
            thresholds['distribution_rp'] = 70
            thresholds['markdown_rp'] = -70
        return thresholds

    def _classify_with_thresholds(self, features: Dict, thresholds: Dict) -> str:
        """Classify phase using provided thresholds (same rule order as MonthlyPhaseClassifier)."""
        t = thresholds
        f = features

        if f.get('trend_pct', 0) < t['accumulation_tr'] or (
                f.get('ret_6', 0) < t['markdown_r6'] and f.get('price_pos', 0) < t['markdown_pp']):
            return 'markdown'

        if (f.get('price_pos', 0) < t['accumulation_pp'] and
                f.get('vol_trend', 0) < t['accumulation_vt'] and
                f.get('range_pct', 0) < t['accumulation_rp'] and
                f.get('vol_ratio', 0) < t['accumulation_vr']):
            return 'accumulation'

        if (f.get('trend_pct', 0) > t['markup_tr'] and
                f.get('price_pos', 0) > t['markup_pp'] and
                f.get('vol_trend', 0) > 0):
            return 'markup'

        if (f.get('price_pos', 0) > t['distribution_pp'] and
                f.get('vp_corr', 0) < t['distribution_vp_c'] and
                f.get('range_pct', 0) > t['distribution_rp']):
            return 'distribution'

        if (f.get('price_pos', 0) > t['distribution_pp'] and
                f.get('obv_trend', 0) < t['distribution_obv_t'] and
                f.get('ret_6', 0) < t['distribution_r6']):
            return 'distribution'

        if (f.get('price_pos', 0) < t['accumulation_pp'] + 0.05 and
                f.get('obv_trend', 0) > t['accumulation_obv_t'] and
                f.get('ret_6', 0) > t['accumulation_r6']):
            return 'accumulation'

        return 'unknown'

    def _compute_confidence(self, features: Dict, phase: str, thresholds: Dict) -> float:
        """Confidence proportional to sigmoid-of-distance from threshold boundary.

        Returns 0.0 for unknown, 0.3 for marginal classifications,
        approaching 1.0 as features move firmly past the boundary.
        """
        if phase == 'unknown':
            return 0.0

        f = features
        t = thresholds

        if phase == 'markdown':
            boundary = t['accumulation_tr']
            dist = boundary - f.get('trend_pct', 0)
        elif phase == 'accumulation':
            boundary = t['accumulation_tr']
            dist = boundary - f.get('trend_pct', 0)
        elif phase == 'markup':
            boundary = t['markup_tr']
            dist = f.get('trend_pct', 0) - boundary
        elif phase == 'distribution':
            boundary = t['distribution_tr']
            dist = f.get('trend_pct', 0) - boundary
        else:
            return 0.0

        if dist <= 0:
            return 0.3
        z = dist / max(abs(boundary), 5.0)
        return min(1.0, 0.3 + 0.7 * (1.0 - math.exp(-z)))

    def get_features(self) -> dict:
        return dict(self._last_features)


class MultiTimeframeResonance:
    """Analyses agreement across monthly, weekly, daily phases."""

    BULLISH = {'accumulation', 'markup'}
    BEARISH = {'distribution', 'markdown'}

    @classmethod
    def resonance(cls, monthly: str, weekly: str, daily: str) -> Dict:
        """Compute multi-timeframe resonance metrics.

        Args:
            monthly: monthly phase string
            weekly: weekly phase string
            daily: daily phase string

        Returns:
            dict with keys:
              - resonance_count: 0-3 (how many timeframes agree on direction)
              - resonance_dir: 'bullish', 'bearish', or 'conflicting'
              - phases: [monthly, weekly, daily]
        """
        phases = [monthly, weekly, daily]
        bullish_count = sum(1 for p in phases if p in cls.BULLISH)
        bearish_count = sum(1 for p in phases if p in cls.BEARISH)

        if bullish_count >= 2:
            return {
                'resonance_count': bullish_count,
                'resonance_dir': 'bullish',
                'phases': phases,
            }
        elif bearish_count >= 2:
            return {
                'resonance_count': bearish_count,
                'resonance_dir': 'bearish',
                'phases': phases,
            }
        else:
            return {
                'resonance_count': max(bullish_count, bearish_count),
                'resonance_dir': 'conflicting',
                'phases': phases,
            }

    @classmethod
    def resonance_strength(cls, monthly: str, weekly: str, daily: str) -> float:
        """Quantify multi-timeframe agreement strength.

        Returns 0.0 (total disagreement) to 1.0 (all timeframes fully agree).
        Weights: monthly=3, weekly=2, daily=1. Exact phase match across all
        three earns a small bonus.

        Compared to resonance() which returns 3-state direction + count,
        this provides a continuous measure suitable for signal ranking.
        """
        r = cls.resonance(monthly, weekly, daily)
        if r['resonance_dir'] == 'conflicting':
            return 0.0

        phases: Dict[str, str] = {'monthly': monthly, 'weekly': weekly, 'daily': daily}
        weights: Dict[str, int] = {'monthly': 3, 'weekly': 2, 'daily': 1}
        total_weight = sum(weights.values())

        weighted_agree = sum(
            weights[tf]
            for tf, p in phases.items()
            if (r['resonance_dir'] == 'bullish' and p in cls.BULLISH)
            or (r['resonance_dir'] == 'bearish' and p in cls.BEARISH)
        )

        strength = weighted_agree / total_weight

        if monthly == weekly == daily and monthly != 'unknown':
            strength = min(1.0, strength + 0.15)

        return strength

    @classmethod
    def is_bullish_confirmed(cls, monthly: str, weekly: str, daily: str) -> bool:
        """True if at least 2 of 3 timeframes are bullish."""
        return cls.resonance(monthly, weekly, daily)['resonance_dir'] == 'bullish'

    @classmethod
    def is_bearish_confirmed(cls, monthly: str, weekly: str, daily: str) -> bool:
        """True if at least 2 of 3 timeframes are bearish."""
        return cls.resonance(monthly, weekly, daily)['resonance_dir'] == 'bearish'

    @classmethod
    def is_strong_confirmed(cls, monthly: str, weekly: str, daily: str) -> bool:
        """True if all 3 timeframes agree on direction (strongest signal)."""
        r = cls.resonance(monthly, weekly, daily)
        return r['resonance_count'] == 3

    @classmethod
    def is_accum_confirmed(cls, monthly: str, weekly: str, daily: str) -> bool:
        """True if at least 2 of 3 timeframes are accumulation (strongest bullish)."""
        phases = [monthly, weekly, daily]
        return sum(1 for p in phases if p == 'accumulation') >= 2


__all__ = [
    'WeeklyPhaseClassifier',
    'DailyPhaseClassifier',
    'MultiTimeframeResonance',
    'RegimeAwarePhaseClassifier',
]
