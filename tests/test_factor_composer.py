import pytest
import pandas as pd
import numpy as np
from uniquant.brain.factors.custom_factors import register_all
from uniquant.brain.factors.registry import FactorRegistry
from uniquant.brain.factors.composer import FactorComposer
from uniquant.brain.factors.analyzer import FactorICResult

def factor_a(df):
    return df['close']

def factor_b(df):
    return df['close'] * 2

def factor_group_id(df):
    return pd.Series(np.arange(len(df)), index=df.index, dtype=float)

@pytest.fixture(autouse=True)
def setup_registry():
    FactorRegistry._factors.clear()
    FactorRegistry.register("a", factor_a, default_weight=0.5)
    FactorRegistry.register("b", factor_b, default_weight=1.5)
    yield
    # 恢复生产注册, 防止单例污染下游测试 (P11 修复)
    FactorRegistry._factors.clear()
    register_all()

@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "close": [10.0, 11.0, 12.0, 13.0, 14.0]
    })

def test_compute_all_factors(sample_df):
    composer = FactorComposer()
    result = composer.compute_all_factors(sample_df)
    
    assert "a" in result.columns
    assert "b" in result.columns
    assert len(result) == 5
    assert list(result["a"]) == [10.0, 11.0, 12.0, 13.0, 14.0]
    assert list(result["b"]) == [20.0, 22.0, 24.0, 26.0, 28.0]

def test_compute_all_factors_respects_code_groups():
    FactorRegistry._factors.clear()
    FactorRegistry.register("group_id", factor_group_id)
    composer = FactorComposer()
    df = pd.DataFrame({
        "code": ["AAA", "AAA", "AAA", "BBB", "BBB", "BBB"],
        "date": pd.to_datetime([
            "2024-01-03",
            "2024-01-01",
            "2024-01-02",
            "2024-01-02",
            "2024-01-01",
            "2024-01-03",
        ]),
        "close": [1, 2, 3, 10, 20, 30],
    })

    result = composer.compute_all_factors(df)

    assert result["group_id"].tolist() == [2.0, 0.0, 1.0, 1.0, 0.0, 2.0]

def test_process_returns_composite_score(sample_df):
    composer = FactorComposer()
    scored_df, weights = composer.process(sample_df, factor_cols=["a", "b"])

    assert "composite_score" in scored_df.columns
    assert "a" in scored_df.columns
    assert "b" in scored_df.columns
    assert abs(weights["a"] + weights["b"] - 1.0) < 1e-6
    assert weights["b"] > weights["a"]
    assert not scored_df["composite_score"].isna().any()

def test_compose_scores(sample_df):
    composer = FactorComposer()
    result = composer.compose_scores(sample_df, ic_weights={"a": 1.0, "b": 2.0})
    
    assert "composite_score" in result.columns
    assert "a" in result.columns
    assert "b" in result.columns
    
    assert not result["composite_score"].isna().any()
    assert isinstance(result["composite_score"].iloc[0], (float, np.floating))

def test_compose_scores_default_weights(sample_df):
    composer = FactorComposer()
    result = composer.compose_scores(sample_df)
    
    assert "composite_score" in result.columns
    assert not result["composite_score"].isna().any()
    assert isinstance(result["composite_score"].iloc[0], (float, np.floating))

def test_compose_scores_returns_valid_result(sample_df):
    composer = FactorComposer()
    result = composer.compose_scores(sample_df)
    
    assert "composite_score" in result.columns
    assert "a" in result.columns
    assert "b" in result.columns
    assert len(result) == 5


def test_process_reports_failed_factor_diagnostics(sample_df):
    def bad_factor(df):
        raise ValueError("factor exploded")

    FactorRegistry.register("bad", bad_factor, default_weight=2.0)
    composer = FactorComposer()

    scored_df, weights, diagnostics = composer.process(
        sample_df,
        factor_cols=["a", "bad"],
        return_diagnostics=True,
    )

    assert "composite_score" in scored_df.columns
    assert "a" in scored_df.columns
    assert "bad" not in scored_df.columns
    assert abs(weights["a"] - 1.0) < 1e-6
    assert diagnostics["composite_usable"] is True
    assert diagnostics["composite_status"] == "DEGRADED"
    assert "bad" in diagnostics["failed_factors"]
    assert "factor exploded" in diagnostics["failed_factors"]["bad"]


def test_compose_scores_reports_orthogonalization_failure(sample_df, monkeypatch):
    def raise_linalg_error(*args, **kwargs):
        raise np.linalg.LinAlgError("singular covariance")

    monkeypatch.setattr("uniquant.brain.factors.composer.linalg.eigh", raise_linalg_error)
    composer = FactorComposer(orthogonalize=True)

    result, diagnostics = composer.compose_scores(
        sample_df,
        factor_cols=["a", "b"],
        return_diagnostics=True,
    )

    assert "composite_score" in result.columns
    assert diagnostics["orthogonalization_attempted"] is True
    assert diagnostics["orthogonalization_failed"] is True
    assert "singular covariance" in diagnostics["orthogonalization_error"]
    assert diagnostics["composite_status"] == "DEGRADED"


def test_compute_all_factors_can_return_diagnostics(sample_df):
    def bad_factor(df):
        raise RuntimeError("bad factor")

    FactorRegistry.register("bad", bad_factor)
    composer = FactorComposer()

    factor_df, diagnostics = composer.compute_all_factors(
        sample_df,
        return_diagnostics=True,
    )

    assert "a" in factor_df.columns
    assert "bad" not in factor_df.columns
    assert diagnostics["computed_factors"] == ["a", "b"]
    assert "bad" in diagnostics["failed_factors"]
    assert composer.get_last_diagnostics() == diagnostics


def test_ic_decay_basic():
    composer = FactorComposer()
    result = composer._apply_cross_window_decay(history=[0.1, 0.2], current_icir=0.3, half_life=60)
    assert abs(result - 0.3) < abs(result - 0.1), "should be biased toward recent (current)"


def test_ic_decay_single():
    composer = FactorComposer()
    result = composer._apply_cross_window_decay(history=[], current_icir=0.3, half_life=60)
    assert result == pytest.approx(0.3)


def test_ic_decay_equal():
    composer = FactorComposer()
    result = composer._apply_cross_window_decay(history=[0.5, 0.3], current_icir=0.4, half_life=1_000_000)
    assert result == pytest.approx(0.4, abs=0.01)


def test_ic_decay_short():
    composer = FactorComposer()
    result = composer._apply_cross_window_decay(history=[0.2], current_icir=0.1, half_life=2)
    assert 0.1 < result < 0.2, "decay-weighted average should lie between history and current"
    assert result < 0.15, "recent (current) weight exceeds historical weight, pulling below simple avg"


def test_weight_normalization():
    FactorRegistry._factors.clear()
    FactorRegistry.register("x", factor_a, default_weight=1.0)
    FactorRegistry.register("y", factor_b, default_weight=1.0)
    FactorRegistry.register("z", factor_group_id, default_weight=1.0)

    ic_results = {
        "x": {1: FactorICResult("x", 0.05, 0.1, 0.1, 0.6, 2.0, 30)},
        "y": {1: FactorICResult("y", 0.05, 0.1, 0.4, 0.6, 2.0, 30)},
        "z": {1: FactorICResult("z", 0.05, 0.1, 0.5, 0.6, 2.0, 30)},
    }
    composer = FactorComposer()
    weights = composer._resolve_weights(["x", "y", "z"], ic_results=ic_results)
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert weights["z"] > weights["x"]


def test_resolve_ic_result_list_defense(caplog):
    from unittest.mock import Mock
    from uniquant.brain.factors.composer import FactorComposer
    composer = FactorComposer()
    result = composer._resolve_ic_result([Mock()])
    assert result is None
