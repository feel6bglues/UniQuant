import pytest
import pandas as pd
import numpy as np

@pytest.fixture
def sample_ohlcv_data():
    dates = pd.date_range("2024-01-01", periods=252, freq="B")
    return pd.DataFrame({
        "date": dates,
        "open": np.random.randn(252).cumsum() + 100,
        "high": np.random.randn(252).cumsum() + 102,
        "low": np.random.randn(252).cumsum() + 98,
        "close": np.random.randn(252).cumsum() + 100,
        "volume": np.random.randint(100000, 10000000, 252),
    })

@pytest.fixture
def sample_wyckoff_data():
    dates = pd.date_range("2024-01-01", periods=400, freq="B")
    return pd.DataFrame({
        "date": dates,
        "open": np.random.randn(400).cumsum() + 100,
        "high": np.random.randn(400).cumsum() + 102,
        "low": np.random.randn(400).cumsum() + 98,
        "close": np.random.randn(400).cumsum() + 100,
        "volume": np.random.randint(100000, 10000000, 400),
    })
