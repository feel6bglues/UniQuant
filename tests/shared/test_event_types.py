from __future__ import annotations

from uuid import UUID

from uniquant.shared.event_types import (
    Event, Command, Priority,
    AnalysisCompleted, SignalGenerated, BacktestCompleted,
    ErrorOccurred, RunStarted, DataLoaded, EngineCompleted,
    DecisionProduced, SignalsCollected, RunCompleted,
)


def test_event_base():
    e = Event(topic="test.topic", payload={"key": "val"})
    assert e.topic == "test.topic"
    assert e.payload["key"] == "val"
    assert e.priority == Priority.NORMAL
    UUID(e.event_id)


def test_command_base():
    c = Command(action="do_something", params={"arg": 1})
    assert c.action == "do_something"
    assert c.params["arg"] == 1
    UUID(c.command_id)


def test_analysis_completed():
    e = AnalysisCompleted(symbol="000001.SZ", result={"status": "ok"})
    assert e.topic == "analysis.completed"
    assert e.payload["symbol"] == "000001.SZ"


def test_signal_generated():
    e = SignalGenerated(symbol="000001.SZ", signal={"action": "BUY"})
    assert e.topic == "signal.generated"
    assert e.payload["signal"]["action"] == "BUY"


def test_backtest_completed():
    e = BacktestCompleted(symbol="000001.SZ", trades=5, total_return=0.12)
    assert e.topic == "backtest.completed"
    assert e.payload["trades"] == 5
    assert e.payload["total_return"] == 0.12


def test_error_occurred():
    e = ErrorOccurred(source="test", error="something broke")
    assert e.topic == "error.occurred"
    assert e.priority == Priority.HIGH


def test_run_started():
    e = RunStarted(symbol="000001.SZ", trace_id="abc123")
    assert e.topic == "pipeline.run.started"


def test_data_loaded():
    e = DataLoaded(symbol="000001.SZ", success=True, rows=100)
    assert e.topic == "pipeline.data.loaded"
    assert e.payload["rows"] == 100


def test_engine_completed():
    e = EngineCompleted(engine_name="lppl", symbol="000001.SZ", status="OK", elapsed_ms=15.5)
    assert e.topic == "pipeline.engine.completed"
    assert e.payload["engine_name"] == "lppl"
    assert e.payload["elapsed_ms"] == 15.5


def test_decision_produced():
    e = DecisionProduced(symbol="000001.SZ", action="BUY", confidence=0.8)
    assert e.topic == "pipeline.decision.produced"


def test_signals_collected():
    e = SignalsCollected(symbol="000001.SZ", count=3)
    assert e.topic == "pipeline.signals.collected"


def test_run_completed():
    e = RunCompleted(symbol="000001.SZ", success=True, total_return=0.05, total_trades=2)
    assert e.topic == "pipeline.run.completed"


def test_all_topics_unique():
    events = [
        AnalysisCompleted("sym", {}),
        SignalGenerated("sym", {}),
        BacktestCompleted("sym", 1, 0.1),
        ErrorOccurred("src", "err"),
        RunStarted("sym", "tid"),
        DataLoaded("sym", True),
        EngineCompleted("eng", "sym", "OK"),
        DecisionProduced("sym", "BUY", 0.5),
        SignalsCollected("sym", 1),
        RunCompleted("sym", True),
    ]
    topics = [e.topic for e in events]
    assert len(topics) == len(set(topics)), "所有事件 topic 必须唯一"
