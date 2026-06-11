"""
Integration tests for EventBus integration in the research pipeline.
Verifies that events are published in the correct order with proper payloads.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
from uniquant.shared.event_bus import EventBus
from uniquant.shared.event_types import DataLoaded
from uniquant.services.research_pipeline import PipelineResult, UnifiedResearchPipeline


def _make_mock_data_pack() -> dict:
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=5, freq="D"),
        "open": [10.0] * 5,
        "high": [11.0] * 5,
        "low": [9.0] * 5,
        "close": [10.5] * 5,
        "volume": [10000] * 5,
        "pre_close": [10.0] * 5,
        "avg_daily_volume": [10000] * 5,
    })
    return {
        "stock": df,
        "symbol": "000001.SZ",
        "regime": "NORMAL",
        "action": "HOLD",
        "confidence": 0.5,
    }


def _make_mock_analysis_service(success: bool = True):
    svc = MagicMock()
    svc.run_ticker_analysis.return_value = MagicMock(
        success=success,
        data_pack=_make_mock_data_pack() if success else {},
        decision={"action": "HOLD", "confidence": 0.0} if success else {},
        error=None if success else "mock error",
        symbol="000001.SZ",
    )
    return svc


def test_event_bus_publishes_all_events_in_order():
    bus = EventBus()
    events: list[str] = []

    bus.subscribe("pipeline.run.started", lambda e: events.append("started"))
    bus.subscribe("pipeline.data.loaded", lambda e: events.append("data_loaded"))
    bus.subscribe("pipeline.decision.produced", lambda e: events.append("decision"))
    bus.subscribe("pipeline.signals.collected", lambda e: events.append("signals"))
    bus.subscribe("pipeline.run.completed", lambda e: events.append("completed"))

    mock_engine = MagicMock(spec=UnifiedBacktestEngine)
    mock_engine.run.return_value = MagicMock(
        trades=[],
        equity_curve=[100000.0],
        daily_returns=[0.0],
        initial_capital=100000.0,
        final_cash=100000.0,
        total_trades=0,
        total_return=0.0,
    )

    pipeline = UnifiedResearchPipeline(
        analysis_service=_make_mock_analysis_service(),
        backtest_engine=mock_engine,
        event_bus=bus,
    )
    result = pipeline.run("000001.SZ")

    assert result.success
    assert events == ["started", "data_loaded", "decision", "signals", "completed"]


def test_event_bus_run_started_payload():
    bus = EventBus()
    payloads: list[dict] = []

    bus.subscribe("pipeline.run.started", lambda e: payloads.append(e.payload))
    bus.subscribe("pipeline.run.completed", lambda e: payloads.append(e.payload))

    mock_engine = MagicMock(spec=UnifiedBacktestEngine)
    mock_engine.run.return_value = MagicMock(
        trades=[],
        equity_curve=[100000.0],
        daily_returns=[0.0],
        initial_capital=100000.0,
        final_cash=100000.0,
        total_trades=0,
        total_return=0.0,
    )

    pipeline = UnifiedResearchPipeline(
        analysis_service=_make_mock_analysis_service(),
        backtest_engine=mock_engine,
        event_bus=bus,
    )
    pipeline.run("000001.SZ")

    assert len(payloads) >= 2
    assert payloads[0]["symbol"] == "000001.SZ"
    assert "trace_id" in payloads[0]


def test_event_bus_data_loaded_event():
    bus = EventBus()
    data_events: list[DataLoaded] = []

    bus.subscribe("pipeline.data.loaded", lambda e: data_events.append(e))

    mock_engine = MagicMock(spec=UnifiedBacktestEngine)
    mock_engine.run.return_value = MagicMock(
        trades=[],
        equity_curve=[100000.0],
        daily_returns=[0.0],
        initial_capital=100000.0,
        final_cash=100000.0,
        total_trades=0,
        total_return=0.0,
    )

    pipeline = UnifiedResearchPipeline(
        analysis_service=_make_mock_analysis_service(),
        backtest_engine=mock_engine,
        event_bus=bus,
    )
    pipeline.run("000001.SZ")

    assert len(data_events) == 1
    assert data_events[0].payload["success"] is True
    assert data_events[0].payload["rows"] == 5


def test_event_bus_failure_path():
    bus = EventBus()
    events: list[str] = []

    bus.subscribe("pipeline.run.started", lambda e: events.append("started"))
    bus.subscribe("pipeline.run.completed", lambda e: events.append("completed"))

    pipeline = UnifiedResearchPipeline(
        analysis_service=_make_mock_analysis_service(success=False),
        backtest_engine=MagicMock(),
        event_bus=bus,
    )
    result = pipeline.run("000001.SZ")

    assert not result.success
    assert events == ["started", "completed"]


def test_event_bus_disabled_by_default():
    pipeline = UnifiedResearchPipeline(
        analysis_service=_make_mock_analysis_service(),
        backtest_engine=MagicMock(),
    )
    assert pipeline._event_bus is None


def test_metrics_recorder_attached_to_result():
    mock_engine = MagicMock(spec=UnifiedBacktestEngine)
    mock_engine.run.return_value = MagicMock(
        trades=[],
        equity_curve=[100000.0],
        daily_returns=[0.0],
        initial_capital=100000.0,
        final_cash=100000.0,
        total_trades=0,
        total_return=0.0,
    )

    pipeline = UnifiedResearchPipeline(
        analysis_service=_make_mock_analysis_service(),
        backtest_engine=mock_engine,
    )
    result = pipeline.run("000001.SZ")

    assert result.metrics is not None
    snap = result.metrics.snapshot()
    assert any(k.startswith("histogram:perf:") for k in snap)
