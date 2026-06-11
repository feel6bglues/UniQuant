from __future__ import annotations

import time
from typing import List

import pytest

from uniquant.shared.event_bus import AsyncEventBus
from uniquant.shared.event_types import Event


class _TestEvent(Event):
    def __init__(self, value: str = ""):
        super().__init__(topic="test", payload={"value": value})
        self.processed_by: List[str] = []
        self.processing_time: float = 0.0


@pytest.fixture
def bus():
    eb = AsyncEventBus(max_workers=2)
    yield eb
    eb.shutdown(wait=True)


def slow_handler(event: _TestEvent) -> None:
    event.processing_time = 0.1
    time.sleep(event.processing_time)
    event.processed_by.append("slow")


def fast_handler(event: _TestEvent) -> None:
    event.processed_by.append("fast")


def test_publish_non_blocking(bus):
    event = _TestEvent()
    bus.subscribe("test", slow_handler)
    start = time.monotonic()
    bus.publish(event)
    elapsed = time.monotonic() - start
    assert elapsed < 0.05, f"publish() should not block, took {elapsed:.3f}s"


def test_multiple_subscribers_parallel(bus):
    event = _TestEvent()
    bus.subscribe("test", slow_handler)
    bus.subscribe("test", fast_handler)
    bus.publish(event)
    bus.shutdown(wait=True)
    assert "slow" in event.processed_by
    assert "fast" in event.processed_by


def test_error_isolation(bus):
    event = _TestEvent()

    def failing_handler(e: _TestEvent) -> None:
        raise ValueError("handler failed")

    def ok_handler(e: _TestEvent) -> None:
        e.processed_by.append("ok")

    bus.subscribe("test", failing_handler)
    bus.subscribe("test", ok_handler)
    bus.publish(event)
    bus.shutdown(wait=True)
    assert "ok" in event.processed_by


def test_error_propagation_when_disabled():
    bus = AsyncEventBus(max_workers=2, isolate_errors=False)
    event = _TestEvent()

    def failing_handler(e: _TestEvent) -> None:
        raise ValueError("handler failed")

    bus.subscribe("test", failing_handler)
    bus.publish(event)
    with pytest.raises(ValueError, match="handler failed"):
        bus.shutdown(wait=True)


def test_subscribe_unsubscribe(bus):
    event = _TestEvent()
    bus.subscribe("test", fast_handler)
    assert bus.has_subscribers("test")
    bus.unsubscribe("test", fast_handler)
    assert not bus.has_subscribers("test")


def test_shutdown_waits(bus):
    event = _TestEvent()
    bus.subscribe("test", slow_handler)
    bus.publish(event)
    bus.shutdown(wait=True)
    assert "slow" in event.processed_by


def test_clear(bus):
    event = _TestEvent()
    bus.subscribe("test", fast_handler)
    bus.clear()
    bus.publish(event)
    bus.shutdown(wait=True)
    assert not event.processed_by


def test_subscriber_count(bus):
    bus.subscribe("test", fast_handler)
    bus.subscribe("test", slow_handler)
    assert bus.subscriber_count("test") == 2


def test_different_topics_independent(bus):
    results: List[str] = []

    def handler_a(e: Event) -> None:
        results.append("a")

    def handler_b(e: Event) -> None:
        results.append("b")

    bus.subscribe("topic_a", handler_a)
    bus.subscribe("topic_b", handler_b)

    bus.publish(Event(topic="topic_a"))
    bus.publish(Event(topic="topic_b"))
    bus.shutdown(wait=True)

    assert "a" in results
    assert "b" in results
