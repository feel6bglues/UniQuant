from unittest.mock import Mock

import pandas as pd

from uniquant.services.analysis.fsm_analysis_engine import FsmAnalysisEngine
from uniquant.services.analysis.macro_analysis_engine import MacroAnalysisEngine


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


class _DummyFetcher:
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def fetch_index_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._df.copy()


class _DummyValidationService:
    def calculate_standard_var(self, returns, confidence):
        return 0.01

    def calculate_standard_cvar(self, returns, confidence):
        return 0.02

    def calculate_standard_max_drawdown(self, returns):
        return 0.03

    def validate_risk_metrics(self, metrics, standard_results):
        raise ValueError("validation failed")

    def generate_validation_report(self, validation_result):
        return "report"


class _DummyOrchestrator:
    def __init__(self, df: pd.DataFrame):
        self.data_service = Mock()
        self.data_service.lake = _DummyLake(df)
        self.data_service.fetcher = _DummyFetcher(df)
        self.evt_risk = Mock()
        self.evt_risk.calculate_metrics = Mock(
            return_value={
                "var_95": 0.01,
                "var_99": 0.02,
                "cvar_95": 0.03,
                "cvar_99": 0.04,
                "max_drawdown": 0.05,
            }
        )
        self.validation_service = _DummyValidationService()
        self._market_cache = {}
        self._market_cache_date = "2026-04-04"
        self.brain = None
        self.sizer = None

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

    def validate_risk_metrics(self, metrics):
        return True


def test_fsm_engine_falls_back_on_runtime_error(monkeypatch):
    engine = FsmAnalysisEngine(_DummyOrchestrator(_sample_ohlc_df()))

    def raise_runtime_error(*args, **kwargs):
        raise RuntimeError("fsm failed")

    monkeypatch.setattr(
        "uniquant.brain.fsm.DecisionBrain.make_decision",
        raise_runtime_error,
    )

    result = engine.run_fsm_analysis("000001.SZ", _sample_ohlc_df())

    assert result["status"] == "success"
    assert result["summary"] == "使用基本交易逻辑进行判断"
    assert result["recommendation"] in {"买入", "卖出", "持有", "等待", "未知"}


def test_macro_engine_keeps_metrics_when_validation_service_fails():
    engine = MacroAnalysisEngine(_DummyOrchestrator(_sample_ohlc_df()))

    result = engine.analyze_macro_health()

    assert result["var_95"] == 0.01
    assert result["max_drawdown"] == 0.05
