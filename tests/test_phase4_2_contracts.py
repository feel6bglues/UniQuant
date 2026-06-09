from __future__ import annotations

import importlib
from unittest.mock import Mock

import pandas as pd
import pytest

from uniquant.hands.backtest.unified_engine import BacktestResult
from uniquant.services.analysis.engine_factory import AnalysisEngineFactory
from uniquant.services.analysis_service_v2 import AnalysisService, TickerAnalysisResult
from uniquant.services.research_pipeline import UnifiedResearchPipeline
from uniquant.shared.interfaces import TradingSignal


class _FakeBacktestEngine:
    def __init__(self) -> None:
        self.signals = []

    def run(self, df, signals, symbol, name=None):
        self.signals = signals
        return BacktestResult(
            trades=[],
            equity_curve=[100_000],
            initial_capital=100_000,
            final_cash=100_000,
        )


class _FakeAnalysisService:
    def __init__(self) -> None:
        self.trace_id = None

    def run_ticker_analysis(self, symbol: str, trace_id=None) -> TickerAnalysisResult:
        self.trace_id = trace_id
        stock = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
                "open": [10.0, 10.2],
                "high": [10.3, 10.5],
                "low": [9.9, 10.1],
                "close": [10.2, 10.4],
                "volume": [10000, 12000],
            }
        )
        return TickerAnalysisResult(
            symbol=symbol,
            data_pack={"stock": stock, "symbol": symbol, "price": 10.4, "trace_id": trace_id},
            decision={
                "final_decision": "EXECUTE_BUY",
                "final_score": 87,
                "reason": "fsm-only decision",
                "price": 10.4,
            },
            signals=[],
            success=True,
        )


def test_engine_factory_initialization_failure_is_fail_fast(monkeypatch):
    factory = AnalysisEngineFactory(orchestrator=Mock())

    def broken_import(*args, **kwargs):
        raise ImportError("missing engine module")

    monkeypatch.setattr(importlib, "import_module", broken_import)

    with pytest.raises(RuntimeError, match="Failed to initialize analysis engine fsm"):
        _ = factory.fsm


def test_analysis_service_rebinds_factory_orchestrator_contract():
    data_service = Mock()
    factory = AnalysisEngineFactory(orchestrator=data_service)

    analysis = AnalysisService(data_service=data_service, engine_factory=factory)

    assert factory._orchestrator is analysis
    for method_name in [
        "_generate_cache_key",
        "_get_cached_result",
        "_set_cached_result",
        "_optimize_dataframe",
        "_sample_data",
        "ensure_precision_consistency",
    ]:
        assert hasattr(analysis, method_name)

    fsm_engine = factory.fsm
    assert fsm_engine is not None
    assert fsm_engine.orchestrator is analysis


def test_pipeline_collects_fsm_decision_as_standard_trading_signal():
    backtest = _FakeBacktestEngine()
    analysis = _FakeAnalysisService()
    pipeline = UnifiedResearchPipeline(
        analysis_service=analysis,
        backtest_engine=backtest,
    )

    result = pipeline.run("000001.SZ", default_shares=100, trace_id="trace-p2")

    assert result.success is True
    assert result.trace_id == "trace-p2"
    assert result.data_pack["trace_id"] == "trace-p2"
    assert analysis.trace_id == "trace-p2"
    assert len(result.signals) == 1
    signal = result.signals[0]
    assert isinstance(signal, TradingSignal)
    assert signal.action == "BUY"
    assert signal.confidence == pytest.approx(0.87)
    assert signal.shares == 100
    assert signal.symbol == "000001.SZ"
    assert signal.reason == "fsm-only decision"
    assert backtest.signals == result.signals


def test_analysis_service_run_ticker_analysis_populates_trace_id():
    data_service = Mock()
    factory = Mock()
    analysis = AnalysisService(data_service=data_service, engine_factory=factory)
    stock = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "open": [10.0, 10.2],
            "high": [10.3, 10.5],
            "low": [9.9, 10.1],
            "close": [10.2, 10.4],
            "volume": [10000, 12000],
        }
    )

    analysis._prepare_data = Mock(return_value={"stock": stock})
    analysis._run_engines = Mock(return_value=True)
    analysis._make_decision = Mock(return_value={"final_decision": "HOLD"})

    result = analysis.run_ticker_analysis("000001.SZ", trace_id="trace-analysis")

    assert result.trace_id == "trace-analysis"
    assert result.data_pack["trace_id"] == "trace-analysis"
    assert result.data_pack["engine_status_meta"]["trace_id"] == "trace-analysis"
