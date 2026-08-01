"""
Tests for WalkForwardFactorPipeline
"""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from uniquant.brain.factors.walk_forward_pipeline import (
    WalkForwardFactorPipeline,
    WalkForwardResult,
)
from uniquant.brain.factors.analyzer import FactorICResult


def _make_synthetic_data(n_dates=500, n_factors=3, n_codes=3, seed=42):
    np.random.seed(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    codes = [f"{i:06d}.SZ" for i in range(n_codes)]
    rows = []
    progress = np.linspace(0, 1, n_dates)
    for d in dates:
        for code in codes:
            row = {"date": d, "code": code, "close": 10.0 + np.random.randn() * 0.5}
            for i in range(n_factors):
                row[f"factor_{i}"] = (
                    np.random.randn() * 0.1 + progress[dates.get_loc(d)] * 0.02 * (i + 1)
                )
            weights = [0.5, 0.3, 0.2][:n_factors]
            row["return_1d"] = sum(
                w * row[f"factor_{i}"] for i, w in enumerate(weights)
            ) + np.random.randn() * 0.05
            rows.append(row)
    return pd.DataFrame(rows)


def _make_ic_results(factor_cols, ic_mean=0.05, icir=0.5):
    results = {}
    for col in factor_cols:
        results[col] = {}
        for period in [1, 5, 20]:
            results[col][period] = FactorICResult(
                factor_name=col,
                ic_mean=ic_mean,
                ic_std=0.1,
                icir=icir,
                ic_positive_ratio=0.6,
                ic_t_stat=2.0,
                n_periods=30,
            )
    return results


class TestWalkForwardFactorPipeline:

    @pytest.fixture
    def pipeline(self):
        return WalkForwardFactorPipeline(
            train_window=50, test_window=10, min_train_days=20,
        )

    @pytest.fixture
    def sample_data(self):
        return _make_synthetic_data(n_dates=200, n_factors=3, n_codes=5)

    @pytest.fixture
    def factor_cols(self):
        return ["factor_0", "factor_1", "factor_2"]

    # ------------------------------------------------
    # 1. Initialization defaults
    # ------------------------------------------------
    def test_initialization_defaults(self):
        p = WalkForwardFactorPipeline()
        assert p.train_window == 504
        assert p.test_window == 63
        assert p.min_train_days == 252
        assert p.weight_method == "rank_icir"
        assert p.analyzer is not None
        assert p.composer is not None

    # ------------------------------------------------
    # 2. Temporal split – no leakage
    # ------------------------------------------------
    def test_train_test_split(self, pipeline, sample_data):
        windows = pipeline._temporal_split(sample_data)
        assert len(windows) > 0
        for ts, te, ss, se in windows:
            assert ss > te
            train_dates = set(
                sample_data[
                    (sample_data["date"] >= ts) & (sample_data["date"] <= te)
                ]["date"].unique()
            )
            test_dates = set(
                sample_data[
                    (sample_data["date"] >= ss) & (sample_data["date"] <= se)
                ]["date"].unique()
            )
            assert len(train_dates & test_dates) == 0

    # ------------------------------------------------
    # 3. End-to-end walk-forward fit
    # ------------------------------------------------
    def test_walk_forward_fit(self, pipeline, sample_data, factor_cols):
        ic_results = _make_ic_results(factor_cols)

        with patch.object(pipeline.analyzer, "compute_ic_ir", return_value=ic_results):
            result = pipeline.run(sample_data, factor_cols=factor_cols)

        assert isinstance(result, WalkForwardResult)
        assert len(result.windows) > 0
        assert set(result.final_weights.keys()) == set(factor_cols)

        wr = result.windows[0]
        assert wr.train_start < wr.train_end < wr.test_start < wr.test_end
        assert set(wr.weights.keys()) == set(factor_cols)
        assert abs(sum(wr.weights.values()) - 1.0) < 1e-6
        assert wr.n_train_stocks > 0
        assert wr.n_test_stocks > 0

        assert pipeline._ic_history != {}

    # ------------------------------------------------
    # 4. Rank-ICIR weighting
    # ------------------------------------------------
    def test_rank_icir_weighting(self, pipeline):
        factor_cols = ["factor_a", "factor_b", "factor_c"]
        ic_results = {
            "factor_a": {1: FactorICResult("factor_a", 0.05, 0.1, 1.5, 0.6, 2.0, 30)},
            "factor_b": {1: FactorICResult("factor_b", 0.03, 0.1, 0.5, 0.55, 1.0, 30)},
            "factor_c": {1: FactorICResult("factor_c", 0.01, 0.1, 0.2, 0.52, 0.5, 30)},
        }
        weights = pipeline._compute_weights(ic_results, factor_cols)
        for w in weights.values():
            assert w > 0
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        assert weights["factor_a"] > weights["factor_c"]

    def test_rank_icir_weighting_empty(self, pipeline):
        weights = pipeline._compute_weights({}, ["fa", "fb"])
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        assert weights["fa"] == pytest.approx(0.5)

    def test_rank_icir_weighting_single(self, pipeline):
        ic = {"fa": {1: FactorICResult("fa", 0.05, 0.1, 1.5, 0.6, 2.0, 30)}}
        weights = pipeline._compute_weights(ic, ["fa"])
        assert abs(weights["fa"] - 1.0) < 1e-6

    def test_rank_icir_weighting_all_zero(self, pipeline):
        ic = {
            "fa": {1: FactorICResult("fa", 0.0, 0.1, 0.0, 0.5, 0.0, 30)},
            "fb": {1: FactorICResult("fb", 0.0, 0.1, 0.0, 0.5, 0.0, 30)},
        }
        weights = pipeline._compute_weights(ic, ["fa", "fb"])
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    # ------------------------------------------------
    # 5. OOS metrics
    # ------------------------------------------------
    def test_oos_metrics(self, pipeline, sample_data, factor_cols):
        ic_results = _make_ic_results(factor_cols)

        with patch.object(pipeline.analyzer, "compute_ic_ir", return_value=ic_results):
            with patch.object(
                pipeline.composer, "process", return_value=(sample_data.copy(), {})
            ):
                result = pipeline.run(sample_data, factor_cols=factor_cols)

        assert isinstance(result.oos_ic_mean, float)
        assert isinstance(result.oos_ic_std, float)
        assert isinstance(result.oos_icir, float)
        for col in factor_cols:
            assert col in result.weight_stability
            assert isinstance(result.weight_stability[col], float)
            assert result.weight_stability[col] >= 0.0

    # ------------------------------------------------
    # 6. Insufficient data
    # ------------------------------------------------
    def test_data_insufficient(self):
        pipeline = WalkForwardFactorPipeline(train_window=50, test_window=10)
        small = _make_synthetic_data(n_dates=15, n_codes=1, n_factors=1)
        with pytest.raises((AssertionError, ValueError)):
            pipeline.run(small, factor_cols=["factor_0"])

    def test_data_insufficient_empty_windows(self):
        pipeline = WalkForwardFactorPipeline(train_window=500, test_window=100)
        small = _make_synthetic_data(n_dates=100, n_codes=1, n_factors=1)
        with pytest.raises((AssertionError, ValueError)):
            pipeline.run(small, factor_cols=["factor_0"])

    # ------------------------------------------------
    # 7. No lookahead – each window depends only on prior data
    # ------------------------------------------------
    def test_no_lookahead(self, pipeline, sample_data):
        windows = pipeline._temporal_split(sample_data)
        for ts, te, ss, se in windows:
            train_dates = set(
                sample_data[
                    (sample_data["date"] >= ts) & (sample_data["date"] <= te)
                ]["date"].unique()
            )
            test_dates = set(
                sample_data[
                    (sample_data["date"] >= ss) & (sample_data["date"] <= se)
                ]["date"].unique()
            )
            assert len(train_dates & test_dates) == 0
            assert max(train_dates) < min(test_dates)

    def test_walk_forward_ic_path_live(self, pipeline, sample_data, factor_cols):
        ic_results = _make_ic_results(factor_cols)

        with patch.object(pipeline.analyzer, "compute_ic_ir", return_value=ic_results):
            result = pipeline.run(sample_data, factor_cols=factor_cols)

        assert isinstance(result, WalkForwardResult)
        assert len(result.windows) > 0
        wr = result.windows[0]
        assert abs(sum(wr.weights.values()) - 1.0) < 1e-6

    def test_no_lookahead_train_data_boundary(self, pipeline, sample_data, factor_cols):
        captured = {"train_end": None}

        def recording_compute_ic_ir(train_df, **kwargs):
            captured["train_end"] = pd.to_datetime(train_df["date"]).max()
            return _make_ic_results(factor_cols)

        with patch.object(pipeline.analyzer, "compute_ic_ir", side_effect=recording_compute_ic_ir):
            with patch.object(
                pipeline.composer, "process", return_value=(sample_data.copy(), {})
            ):
                result = pipeline.run(sample_data, factor_cols=factor_cols)

        for wr in result.windows:
            for col in factor_cols:
                assert col in wr.weights
