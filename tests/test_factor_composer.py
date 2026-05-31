import pytest
import pandas as pd
import numpy as np
from uniquant.brain.factors.registry import FactorRegistry
from uniquant.brain.factors.composer import FactorComposer

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
    assert weights["a"] == pytest.approx(0.5)
    assert weights["b"] == pytest.approx(1.5)
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
