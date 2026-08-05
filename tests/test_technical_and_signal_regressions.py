import pandas as pd
import pytest

pytest.importorskip("czsc")

from uniquant.services.analysis.signal_service import SignalAnalysisService
from uniquant.services.analysis.technical_service import TechnicalAnalysisService


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


def test_run_czsc_analysis_falls_back_on_runtime_error(monkeypatch):
    service = TechnicalAnalysisService()

    def raise_runtime_error(self, df):
        raise RuntimeError("czsc failed")

    monkeypatch.setattr(
        "uniquant.brain.czsc.czsc_engine.CZSCEngine.get_czsc_signals",
        raise_runtime_error,
    )

    result = service.run_czsc_analysis("000001.SZ", _sample_ohlc_df())

    assert result["status"] == "success"
    assert result["summary"] == "使用基本技术分析方法进行判断"
    assert result["current_state"] in {"BUY", "SELL", "STRONG_BUY", "STRONG_SELL", "NEUTRAL"}


def test_detect_czsc_signals_degrades_on_attribute_error(monkeypatch):
    service = TechnicalAnalysisService()
    data_pack = {}

    def raise_attribute_error(self, ticker):
        raise AttributeError("bad czsc dependency")

    monkeypatch.setattr(
        "uniquant.brain.czsc.czsc_engine.CZSCEngine.update_and_get_signals",
        raise_attribute_error,
    )

    service.detect_czsc_signals("000001.SZ", data_pack)

    assert data_pack["is_3rd_buy"] is False
    assert data_pack["bi_count"] == 0


def test_run_fsm_analysis_falls_back_on_runtime_error(monkeypatch):
    service = SignalAnalysisService()

    def raise_runtime_error(self):
        raise RuntimeError("fsm failed")

    monkeypatch.setattr(
        SignalAnalysisService,
        "_get_fsm_engine",
        raise_runtime_error,
    )

    result = service.run_fsm_analysis("000001.SZ", _sample_ohlc_df())

    assert result["status"] == "success"
    assert result["summary"] == "使用基本交易逻辑进行判断"
    assert result["recommendation"] in {"买入", "卖出", "持有", "等待", "未知"}


def test_analyze_alpha_sets_default_score_on_value_error(monkeypatch):
    service = SignalAnalysisService()
    data_pack = {"stock": _sample_ohlc_df()}

    def raise_value_error(stock_df, bench_df, sector_df=None):
        raise ValueError("alpha failed")

    monkeypatch.setattr(
        "uniquant.brain.alpha_decoupler.AlphaDecoupler.get_alpha_score",
        raise_value_error,
    )

    class DummyFetcher:
        def fetch_index_daily(self, symbol, start_date, end_date):
            return _sample_ohlc_df()

    monkeypatch.setattr("uniquant.data.data_fetcher.DataFetcher", DummyFetcher)

    service.analyze_alpha(data_pack)

    assert data_pack["alpha_score"] == 0.0
