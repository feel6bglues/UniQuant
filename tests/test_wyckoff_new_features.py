"""Tests for new Wyckoff features — pnf, bayesian_events, v_shape_detector,
ashare_constraints, sequence EMA smoothing."""

import numpy as np
import pandas as pd
import pytest


# ───────────────────────── pnf.py ─────────────────────────


class TestPnFBox:
    def test_default_values(self):
        from uniquant.brain.wyckoff.pnf import PnFBox
        box = PnFBox(price_level=10.5, column_index=0, is_x=True)
        assert box.price_level == 10.5
        assert box.column_index == 0
        assert box.is_x is True


class TestPointAndFigure:
    def test_default_init(self):
        from uniquant.brain.wyckoff.pnf import PointAndFigure
        pnf = PointAndFigure()
        assert pnf.box_size == 0.01
        assert pnf.reversal == 3

    def test_custom_init(self):
        from uniquant.brain.wyckoff.pnf import PointAndFigure
        pnf = PointAndFigure(box_size=0.02, reversal=5)
        assert pnf.box_size == 0.02
        assert pnf.reversal == 5

    def test_build_up_trend(self):
        from uniquant.brain.wyckoff.pnf import PointAndFigure
        df = pd.DataFrame({
            "high": [10.0, 10.2, 10.4, 10.6, 10.8],
            "low":  [9.8, 10.0, 10.2, 10.4, 10.6],
            "close": [10.1, 10.3, 10.5, 10.7, 10.9],
            "open":  [9.9, 10.1, 10.3, 10.5, 10.7],
        })
        pnf = PointAndFigure(box_size=0.1, reversal=3)
        boxes = pnf.build(df)
        assert len(boxes) > 0
        assert all(b.is_x for b in boxes)

    def test_build_down_trend(self):
        from uniquant.brain.wyckoff.pnf import PointAndFigure
        df = pd.DataFrame({
            "high": [10.8, 10.6, 10.4, 10.2, 10.0],
            "low":  [10.6, 10.4, 10.2, 10.0, 9.8],
            "close": [10.7, 10.5, 10.3, 10.1, 9.9],
            "open":  [10.9, 10.7, 10.5, 10.3, 10.1],
        })
        pnf = PointAndFigure(box_size=0.1, reversal=3)
        boxes = pnf.build(df)
        assert len(boxes) > 0
        assert all(not b.is_x for b in boxes)

    def test_build_empty_df(self):
        from uniquant.brain.wyckoff.pnf import PointAndFigure
        df = pd.DataFrame({"high": [], "low": []})
        pnf = PointAndFigure()
        boxes = pnf.build(df)
        assert boxes == []

    def test_breakout_detected_returns_tuple(self):
        from uniquant.brain.wyckoff.pnf import PointAndFigure
        rng = np.random.default_rng(42)
        price = 10.0
        rows = []
        for i in range(80):
            price += rng.normal(0.01, 0.05)
            rows.append({"high": price + 0.1, "low": price - 0.1})
        df = pd.DataFrame(rows)
        pnf = PointAndFigure(box_size=0.05, reversal=3)
        pnf.build(df)
        detected, direction = pnf.breakout_detected()
        assert isinstance(detected, bool)
        assert isinstance(direction, str)

    def test_wyckoff_phase_hint_returns_string(self):
        from uniquant.brain.wyckoff.pnf import PointAndFigure
        df = pd.DataFrame({
            "high": [10.0, 10.1, 10.2, 10.3, 10.4],
            "low":  [9.8, 9.9, 10.0, 10.1, 10.2],
            "close": [10.0, 10.1, 10.2, 10.3, 10.4],
            "open":  [9.9, 10.0, 10.1, 10.2, 10.3],
        })
        pnf = PointAndFigure(box_size=0.1, reversal=3)
        pnf.build(df)
        hint = pnf.wyckoff_phase_hint()
        assert isinstance(hint, str)
        assert hint in ("accumulation", "distribution", "unknown")

    def test_count_target_returns_float(self):
        from uniquant.brain.wyckoff.pnf import PointAndFigure
        rng = np.random.default_rng(99)
        price = 10.0
        rows = []
        for i in range(100):
            price += rng.normal(0.005, 0.03)
            rows.append({"high": price + 0.05, "low": price - 0.05})
        df = pd.DataFrame(rows)
        pnf = PointAndFigure(box_size=0.05, reversal=3)
        pnf.build(df)
        target = pnf.count_target()
        assert isinstance(target, float)


# ───────────────────────── bayesian_events.py ─────────────────────────


class TestBayesianEventState:
    def test_default_values(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventState
        s = BayesianEventState()
        assert s.alpha == 1.0
        assert s.beta == 1.0
        assert s.last_score == 0.0
        assert s.n_observations == 0


class TestBayesianEventDetector:
    def test_default_init(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        assert d._prior_alpha == 1.0
        assert d._prior_beta == 1.0

    def test_custom_priors(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector(prior_alpha=2.0, prior_beta=5.0)
        assert d._prior_alpha == 2.0
        assert d._prior_beta == 5.0

    def test_update_increases_posterior_mean(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        d.update("PS", score=0.8, confidence=0.9)
        mean = d.posterior_mean("PS")
        assert mean > 0.5

    def test_update_decreases_posterior_mean(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        d.update("PS", score=-0.5, confidence=0.8)
        mean = d.posterior_mean("PS")
        assert mean < 0.5

    def test_collapse_probability_true_when_exceeded(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        for _ in range(10):
            d.update("PS", score=0.9, confidence=0.9)
        collapsed, mean = d.collapse_probability("PS", threshold=0.8)
        assert collapsed is True
        assert mean > 0.8

    def test_collapse_probability_false_below_threshold(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        collapsed, mean = d.collapse_probability("PS", threshold=0.8)
        assert collapsed is False
        assert mean == 0.0

    def test_credible_interval_returns_tuple(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        for _ in range(5):
            d.update("PS", score=0.7, confidence=0.8)
        low, high = d.credible_interval("PS", alpha=0.05)
        assert low < high
        assert 0 < low < 1
        assert 0 < high < 1

    def test_credible_interval_unknown_event_returns_zeros(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        low, high = d.credible_interval("NONEXISTENT")
        assert low == 0.0
        assert high == 0.0

    def test_reset_clears_all(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        d.update("PS", score=0.8, confidence=0.9)
        assert d.posterior_mean("PS") > 0.5
        d.reset()
        assert d.posterior_mean("PS") == 0.0

    def test_reset_single_event(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        d.update("PS", score=0.8, confidence=0.9)
        d.update("SC", score=0.7, confidence=0.8)
        d.reset("PS")
        assert d.posterior_mean("PS") == 0.0
        assert d.posterior_mean("SC") > 0.5

    def test_update_from_events(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector

        class _MockWyckoffEvent:
            def __init__(self, event_type, score, confidence):
                self.event_type = event_type
                self.features = {"score": score}
                self.confidence = confidence

        events = [
            _MockWyckoffEvent("PS", 8.0, 0.9),
            _MockWyckoffEvent("SC", 7.0, 0.8),
            _MockWyckoffEvent("SOS", -2.0, 0.6),
        ]
        d = BayesianEventDetector()
        d.update_from_events(events)
        assert d.posterior_mean("PS") > 0.5
        assert d.posterior_mean("SC") > 0.5
        posteriors = d.get_all_posteriors()
        assert "PS" in posteriors
        assert "SC" in posteriors
        assert "SOS" in posteriors

    def test_get_all_posteriors(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        d.update("PS", score=0.8, confidence=0.9)
        posteriors = d.get_all_posteriors()
        assert "PS" in posteriors
        assert "alpha" in posteriors["PS"]
        assert "mean" in posteriors["PS"]

    def test_posterior_std(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        d.update("PS", score=0.8, confidence=0.9)
        std = d.posterior_std("PS")
        assert 0 < std < 0.5

    def test_evidence_ratio(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        d.update("PS", score=0.8, confidence=0.9)
        assert d.evidence_ratio("PS") == d.posterior_mean("PS")

    def test_update_batch(self):
        from uniquant.brain.wyckoff.bayesian_events import BayesianEventDetector
        d = BayesianEventDetector()
        obs = [("PS", 0.8, 0.9), ("SC", -0.3, 0.7), ("AR", 0.5, 0.6)]
        d.update_batch(obs)
        assert d.posterior_mean("PS") > 0.5
        posteriors = d.get_all_posteriors()
        assert posteriors["PS"]["n_obs"] == 1
        assert posteriors["SC"]["n_obs"] == 1
        assert posteriors["AR"]["n_obs"] == 1


# ───────────────────────── v_shape_detector.py ─────────────────────────


class TestVShapeResult:
    def test_default_values(self):
        from scripts.wyckoff_multitf.v_shape_detector import VShapeResult
        r = VShapeResult(
            date="2024-01-15",
            v_type="v_bottom",
            severity="high",
            decline_pct=25.0,
            recovery_pct=60.0,
            decline_days=5,
            recovery_days=3,
        )
        assert r.date == "2024-01-15"
        assert r.v_type == "v_bottom"
        assert r.in_progress is False

    def test_in_progress_flag(self):
        from scripts.wyckoff_multitf.v_shape_detector import VShapeResult
        r = VShapeResult(
            date="2024-01-15",
            v_type="v_top",
            severity="medium",
            decline_pct=20.0,
            recovery_pct=30.0,
            decline_days=4,
            recovery_days=0,
            in_progress=True,
        )
        assert r.in_progress is True


class TestVShapedReversalDetector:
    def _make_v_bottom_data(self, n_bars=130) -> pd.DataFrame:
        close = np.ones(n_bars) * 100.0
        decline_end = 60
        for i in range(1, decline_end):
            close[i] = close[i - 1] * (1 - 0.005)
        trough = close[decline_end - 1]
        for i in range(decline_end, n_bars):
            close[i] = close[i - 1] * (1 + 0.012)
        return pd.DataFrame({"close": close})

    def _make_v_top_data(self, n_bars=130) -> pd.DataFrame:
        close = np.ones(n_bars) * 100.0
        rally_end = 60
        for i in range(1, rally_end):
            close[i] = close[i - 1] * (1 + 0.005)
        peak = close[rally_end - 1]
        for i in range(rally_end, n_bars):
            close[i] = close[i - 1] * (1 - 0.012)
        return pd.DataFrame({"close": close})

    def _make_flat_data(self, n_bars=130) -> pd.DataFrame:
        return pd.DataFrame({"close": np.ones(n_bars) * 100.0})

    def test_detect_v_bottom(self):
        from scripts.wyckoff_multitf.v_shape_detector import VShapedReversalDetector
        df = self._make_v_bottom_data()
        detector = VShapedReversalDetector(decline_threshold=0.10, recovery_ratio=0.30)
        results = detector.detect(df)
        bottoms = [r for r in results if r.v_type == "v_bottom"]
        assert len(bottoms) > 0
        assert bottoms[0].decline_pct > 0

    def test_detect_v_top(self):
        from scripts.wyckoff_multitf.v_shape_detector import VShapedReversalDetector
        df = self._make_v_top_data()
        detector = VShapedReversalDetector(decline_threshold=0.10, recovery_ratio=0.30)
        results = detector.detect(df)
        tops = [r for r in results if r.v_type == "v_top"]
        assert len(tops) > 0

    def test_classify_date_detected(self):
        from scripts.wyckoff_multitf.v_shape_detector import VShapedReversalDetector
        df = self._make_v_bottom_data()
        detector = VShapedReversalDetector(decline_threshold=0.10, recovery_ratio=0.30)
        results = detector.detect(df)
        if results:
            first_date = results[0].date
            info = detector.classify_date(first_date, df)
            assert info["v_shape_detected"] is True
            assert info["v_type"] in ("v_bottom", "v_top")

    def test_classify_date_no_detection(self):
        from scripts.wyckoff_multitf.v_shape_detector import VShapedReversalDetector
        df = self._make_flat_data()
        detector = VShapedReversalDetector()
        info = detector.classify_date("9999-12-31", df)
        assert info["v_shape_detected"] is False
        assert info["v_type"] == "none"
        assert info["severity"] == "none"
        assert info["decline_pct"] == 0.0


# ───────────────────────── ashare_constraints.py ─────────────────────────


class TestAShareLimitPct:
    def test_star_market(self):
        from scripts.wyckoff_multitf.ashare_constraints import _get_limit_pct
        assert _get_limit_pct("688001.SH") == 0.20

    def test_chip_next(self):
        from scripts.wyckoff_multitf.ashare_constraints import _get_limit_pct
        assert _get_limit_pct("300001.SZ") == 0.20

    def test_bse(self):
        from scripts.wyckoff_multitf.ashare_constraints import _get_limit_pct
        assert _get_limit_pct("830001.BJ") == 0.30

    def test_main_board(self):
        from scripts.wyckoff_multitf.ashare_constraints import _get_limit_pct
        assert _get_limit_pct("600001.SH") == 0.10
        assert _get_limit_pct("000001.SZ") == 0.10

    def test_st_stock(self):
        from scripts.wyckoff_multitf.ashare_constraints import _get_limit_pct
        assert _get_limit_pct("ST600001.SH") == 0.05
        assert _get_limit_pct("*ST000001.SZ") == 0.05

    def test_static_method(self):
        from scripts.wyckoff_multitf.ashare_constraints import AShareConstraints
        assert AShareConstraints.get_limit_pct("688001.SH") == 0.20
        assert AShareConstraints.get_limit_pct("600001.SH") == 0.10


# ───────────────────────── sequence.py WSOScorer EMA ─────────────────────────


class TestWSOScorerEMA:
    def test_second_call_returns_smoothed_value(self):
        from uniquant.brain.wyckoff.sequence import WSOScorer
        scorer = WSOScorer()
        first = scorer.score_events(["SC"])
        second = scorer.score_events(["AR"])
        assert first == pytest.approx(0.0094, abs=1e-4)
        assert second != pytest.approx(0.0083, abs=1e-4)
        alpha = 2.0 / (WSOScorer.EMA_SPAN + 1)
        expected = 0.0083 * alpha + 0.0094 * (1 - alpha)
        assert second == pytest.approx(expected, abs=1e-6)
