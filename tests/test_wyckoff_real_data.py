"""Wyckoff real-data regression tests (skip if data lake unavailable)"""

import os

import pandas as pd
import pytest

from uniquant.brain.wyckoff.engine import WyckoffEngine

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_LAKE = os.path.join(PROJECT_ROOT, "data/lake/quotes/daily")

REAL_SYMBOLS = ["600519.SH", "300750.SZ"]

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
    return df


@pytest.mark.skipif(not _has_data, reason="Real data lake not available")
class TestWyckoffRealData:
    """Real A-share data regression tests for Wyckoff"""

    @pytest.mark.parametrize("symbol", REAL_SYMBOLS)
    def test_analyze_does_not_crash(self, symbol):
        df = make_real_data_df(symbol)
        engine = WyckoffEngine()
        result = engine.analyze(df, symbol=symbol)
        assert result is not None
        assert result.structure is not None

    @pytest.mark.parametrize("symbol", REAL_SYMBOLS)
    def test_analyze_returns_signal(self, symbol):
        df = make_real_data_df(symbol)
        engine = WyckoffEngine()
        result = engine.analyze(df, symbol=symbol)
        assert result.signal is not None
        assert result.signal.signal_type is not None
