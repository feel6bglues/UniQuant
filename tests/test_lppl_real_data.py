"""LPPL real-data regression tests (skip if data lake unavailable)"""

import os

import pandas as pd
import pytest

from uniquant.brain.lppl.calculator import LPPLCalculator
from uniquant.brain.lppl.engine import LPPLEngine, fit_single_window_lbfgsb, LPPLConfig

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_LAKE = os.path.join(PROJECT_ROOT, "data/lake/quotes/daily")

REAL_SYMBOLS = ["600519.SH", "000300.SH"]

_has_data = any(
    os.path.isfile(os.path.join(DATA_LAKE, f"{sym}.parquet"))
    for sym in REAL_SYMBOLS
)


def load_stock(symbol: str) -> pd.DataFrame:
    df = pd.read_parquet(os.path.join(DATA_LAKE, f"{symbol}.parquet"))
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def make_real_data_df(symbol: str) -> pd.DataFrame:
    df = load_stock(symbol)
    df = df[df["date"] >= "2022-01-01"].copy().reset_index(drop=True)
    df["high"] = df.get("high", df["close"])
    df["low"] = df.get("low", df["close"])
    df["volume"] = df.get("volume", 0)
    return df


@pytest.mark.skipif(not _has_data, reason="Real data lake not available")
class TestLpplRealData:
    """Real A-share data regression tests for LPPL"""

    @pytest.mark.parametrize("symbol", REAL_SYMBOLS)
    def test_lbfgsb_fit_succeeds(self, symbol):
        df = make_real_data_df(symbol)
        assert len(df) >= 120, f"{symbol}: insufficient data ({len(df)})"
        config = LPPLConfig(window_range=[120])
        result = fit_single_window_lbfgsb(
            df["close"].values, min(120, len(df)), config
        )
        assert result is not None, f"{symbol}: L-BFGS-B fit failed"
        assert "r_squared" in result
        assert result["r_squared"] >= -1.0
        assert "rmse" in result

    @pytest.mark.parametrize("symbol", REAL_SYMBOLS)
    def test_calculator_fit_returns_r_squared(self, symbol):
        df = make_real_data_df(symbol)
        calculator = LPPLCalculator()
        result = calculator.fit(df)
        if result:
            assert "r_squared" in result
            assert isinstance(result["r_squared"], float)

    @pytest.mark.parametrize("symbol", REAL_SYMBOLS)
    def test_engine_detect_bubble_no_crash(self, symbol):
        df = make_real_data_df(symbol)
        engine = LPPLEngine()
        result = engine.detect_bubble(df)
        assert isinstance(result, dict)
        if result:
            assert "risk_level" in result

    @pytest.mark.parametrize("symbol", REAL_SYMBOLS)
    def test_engine_bubble_confidence_no_crash(self, symbol):
        df = make_real_data_df(symbol)
        engine = LPPLEngine()
        result = engine.detect_bubble_confidence(df)
        assert isinstance(result, dict)
        if result:
            assert "risk_level" in result or "aggregate" in result
