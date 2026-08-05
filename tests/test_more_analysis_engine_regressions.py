import pandas as pd
import pytest

pytest.importorskip("czsc")

from uniquant.services.analysis.czsc_analysis_engine import CzscAnalysisEngine
from uniquant.services.analysis.lppl_analysis_engine import LpplAnalysisEngine
from uniquant.shared.interfaces import CZSCOutput
from uniquant.services.analysis.regime_analysis_engine import RegimeAnalysisEngine


def _sample_ohlc_df(rows: int = 80) -> pd.DataFrame:
    base = list(range(100, 100 + rows))
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "open": base,
            "high": [x + 1 for x in base],
            "low": [x - 1 for x in base],
            "close": [x + 0.5 for x in base],
            "volume": [1000 + i for i in range(rows)],
        }
    )


class _DummyLake:
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def read_data(self, symbol: str, data_type: str = "stock", market: str = "cn") -> pd.DataFrame:
        return self._df.copy()


class _DummyDataService:
    def __init__(self, df: pd.DataFrame):
        self.lake = _DummyLake(df)


class _DummyOrchestrator:
    def __init__(self, df: pd.DataFrame):
        self.data_service = _DummyDataService(df)
        self._market_cache = {}
        self._market_cache_date = "2026-04-04"

    def _generate_cache_key(self, prefix: str, **kwargs) -> str:
        return f"{prefix}:{kwargs}"

    def _get_cached_result(self, cache_key: str, use_disk: bool = False):
        return None

    def _set_cached_result(self, cache_key: str, result, use_disk: bool = False, ttl=None):
        return True

    def _optimize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _sample_data(self, df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
        return df

    def ensure_precision_consistency(self, result):
        return result


def test_regime_engine_returns_failed_result_on_attribute_error(monkeypatch):
    engine = RegimeAnalysisEngine(_DummyOrchestrator(_sample_ohlc_df()))

    def raise_attribute_error(self, symbol):
        raise AttributeError("bad regime engine")

    monkeypatch.setattr(
        "uniquant.brain.regime.regime_detector.RegimeDetector.detect",
        raise_attribute_error,
    )

    result = engine.run_regime_detection("000300.SH")

    assert result["status"] == "failed"
    assert result["regime"] == "NORMAL"
    assert "bad regime engine" in result["error"]


def test_lppl_engine_falls_back_on_runtime_error(monkeypatch):
    engine = LpplAnalysisEngine(_DummyOrchestrator(_sample_ohlc_df()))

    def raise_runtime_error(self, df):
        raise RuntimeError("lppl failed")

    monkeypatch.setattr(
        "uniquant.brain.lppl.engine.LPPLEngine.detect_bubble",
        raise_runtime_error,
    )

    result = engine.run_lppl_analysis("000001.SZ", _sample_ohlc_df())

    assert result.risk_level in ("Safe", "Warning")
    assert isinstance(result.confidence, float)


def test_czsc_engine_falls_back_on_runtime_error(monkeypatch):
    engine = CzscAnalysisEngine(_DummyOrchestrator(_sample_ohlc_df()))

    def raise_runtime_error(self, df):
        raise RuntimeError("czsc failed")

    monkeypatch.setattr(
        "uniquant.brain.czsc.czsc_engine.CZSCEngine.get_czsc_signals",
        raise_runtime_error,
    )

    result = engine.run_czsc_analysis("000001.SZ", _sample_ohlc_df())

    assert isinstance(result, CZSCOutput)
    assert isinstance(result.price, float)
