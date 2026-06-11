"""
Tests for EventBus — synchronous in-memory event pub/sub with error isolation.
"""

from __future__ import annotations

import pytest

from uniquant.shared.event_bus import EventBus
from uniquant.shared.event_types import Event, Priority


def test_publish_subscribe():
    bus = EventBus()
    received: list[Event] = []

    bus.subscribe("test.topic", lambda e: received.append(e))
    event = Event(topic="test.topic", payload={"key": "value"})
    bus.publish(event)

    assert len(received) == 1
    assert received[0].topic == "test.topic"
    assert received[0].payload["key"] == "value"


def test_unsubscribe():
    bus = EventBus()
    received: list[Event] = []

    def handler(e: Event) -> None:
        received.append(e)

    bus.subscribe("test.topic", handler)
    bus.unsubscribe("test.topic", handler)
    bus.publish(Event(topic="test.topic"))

    assert len(received) == 0


def test_multiple_subscribers():
    bus = EventBus()
    results: list[int] = []

    bus.subscribe("test.topic", lambda e: results.append(1))
    bus.subscribe("test.topic", lambda e: results.append(2))
    bus.publish(Event(topic="test.topic"))

    assert sorted(results) == [1, 2]


def test_error_isolation_default():
    bus = EventBus(isolate_errors=True)
    results: list[int] = []

    def failing(_: Event) -> None:
        raise ValueError("handler error")

    def passing(_: Event) -> None:
        results.append(42)

    bus.subscribe("test.topic", failing)
    bus.subscribe("test.topic", passing)

    bus.publish(Event(topic="test.topic"))
    assert results == [42]


def test_error_propagation_when_disabled():
    bus = EventBus(isolate_errors=False)
    bus.subscribe("test.topic", lambda e: (_ for _ in ()).throw(ValueError("fail")))

    with pytest.raises(ValueError, match="fail"):
        bus.publish(Event(topic="test.topic"))


def test_different_topics():
    bus = EventBus()
    results: dict[str, int] = {}

    bus.subscribe("topic.a", lambda e: results.update({"a": results.get("a", 0) + 1}))
    bus.subscribe("topic.b", lambda e: results.update({"b": results.get("b", 0) + 1}))

    bus.publish(Event(topic="topic.a"))
    bus.publish(Event(topic="topic.b"))
    bus.publish(Event(topic="topic.a"))

    assert results == {"a": 2, "b": 1}


def test_has_subscribers():
    bus = EventBus()
    assert not bus.has_subscribers("nonexistent")

    bus.subscribe("exists", lambda e: None)
    assert bus.has_subscribers("exists")
    assert bus.subscriber_count("exists") == 1


def test_subscriber_count():
    bus = EventBus()
    assert bus.subscriber_count("test") == 0
    bus.subscribe("test", lambda e: None)
    bus.subscribe("test", lambda e: None)
    assert bus.subscriber_count("test") == 2


def test_clear():
    bus = EventBus()
    bus.subscribe("a", lambda e: None)
    bus.subscribe("b", lambda e: None)
    assert bus.subscriber_count("a") == 1
    assert bus.subscriber_count("b") == 1

    bus.clear()
    assert bus.subscriber_count("a") == 0
    assert bus.subscriber_count("b") == 0


def test_publish_event_id_and_timestamp():
    bus = EventBus()
    received: list[Event] = []

    bus.subscribe("test", lambda e: received.append(e))
    event = Event(topic="test", source="test_source", priority=Priority.HIGH)
    bus.publish(event)

    assert received[0].event_id == event.event_id
    assert received[0].source == "test_source"
    assert received[0].priority == Priority.HIGH
