from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from .event_types import Event

logger = logging.getLogger(__name__)

EventHandler = Callable[[Event], None]


class EventBus:
    def __init__(self, isolate_errors: bool = True):
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._isolate_errors = isolate_errors

    def subscribe(self, event_topic: str, handler: EventHandler) -> None:
        if event_topic not in self._subscribers:
            self._subscribers[event_topic] = []
        self._subscribers[event_topic].append(handler)

    def unsubscribe(self, event_topic: str, handler: EventHandler) -> None:
        if event_topic in self._subscribers:
            self._subscribers[event_topic] = [
                h for h in self._subscribers[event_topic] if h is not handler
            ]

    def publish(self, event: Event) -> None:
        handlers = self._subscribers.get(event.topic, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                if self._isolate_errors:
                    logger.error(
                        "Event handler failed for %s: %s", event.topic, e,
                    )
                else:
                    raise

    def has_subscribers(self, event_topic: str) -> bool:
        return len(self._subscribers.get(event_topic, [])) > 0

    def subscriber_count(self, event_topic: str) -> int:
        return len(self._subscribers.get(event_topic, []))

    def clear(self) -> None:
        self._subscribers.clear()
