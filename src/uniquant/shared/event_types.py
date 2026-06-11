from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class Priority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Event:
    """基础事件类型"""
    topic: str
    payload: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: Optional[datetime] = None
    priority: Priority = Priority.NORMAL


@dataclass
class Command:
    """基础命令类型"""
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    command_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    source: str = ""


# ── 领域事件 ──

@dataclass
class AnalysisCompleted(Event):
    def __init__(self, symbol: str, result: Dict[str, Any]):
        super().__init__(
            topic="analysis.completed",
            payload={"symbol": symbol, "result": result},
        )


@dataclass
class SignalGenerated(Event):
    def __init__(self, symbol: str, signal: Dict[str, Any]):
        super().__init__(
            topic="signal.generated",
            payload={"symbol": symbol, "signal": signal},
        )


@dataclass
class BacktestCompleted(Event):
    def __init__(self, symbol: str, trades: int, total_return: float):
        super().__init__(
            topic="backtest.completed",
            payload={
                "symbol": symbol,
                "trades": trades,
                "total_return": total_return,
            },
        )


@dataclass
class ErrorOccurred(Event):
    def __init__(self, source: str, error: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            topic="error.occurred",
            payload={"source": source, "error": error, "context": context or {}},
            priority=Priority.HIGH,
        )


# ── 流水线事件 (Phase 4 - EventBus) ──

@dataclass
class RunStarted(Event):
    def __init__(self, symbol: str, trace_id: str):
        super().__init__(
            topic="pipeline.run.started",
            payload={"symbol": symbol, "trace_id": trace_id},
        )


@dataclass
class DataLoaded(Event):
    def __init__(self, symbol: str, success: bool, rows: int = 0):
        super().__init__(
            topic="pipeline.data.loaded",
            payload={"symbol": symbol, "success": success, "rows": rows},
        )


@dataclass
class EngineCompleted(Event):
    def __init__(self, engine_name: str, symbol: str, status: str, elapsed_ms: float = 0.0):
        super().__init__(
            topic="pipeline.engine.completed",
            payload={
                "engine_name": engine_name,
                "symbol": symbol,
                "status": status,
                "elapsed_ms": elapsed_ms,
            },
        )


@dataclass
class DecisionProduced(Event):
    def __init__(self, symbol: str, action: str, confidence: float):
        super().__init__(
            topic="pipeline.decision.produced",
            payload={"symbol": symbol, "action": action, "confidence": confidence},
        )


@dataclass
class SignalsCollected(Event):
    def __init__(self, symbol: str, count: int):
        super().__init__(
            topic="pipeline.signals.collected",
            payload={"symbol": symbol, "count": count},
        )


@dataclass
class RunCompleted(Event):
    def __init__(self, symbol: str, success: bool, total_return: float = 0.0, total_trades: int = 0):
        super().__init__(
            topic="pipeline.run.completed",
            payload={
                "symbol": symbol,
                "success": success,
                "total_return": total_return,
                "total_trades": total_trades,
            },
        )
