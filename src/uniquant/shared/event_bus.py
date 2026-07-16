from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List

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


class AsyncEventBus(EventBus):
    """异步 EventBus: 使用线程池执行 handler，不阻塞 publish()"""

    def __init__(self, max_workers: int = 4, isolate_errors: bool = True):
        super().__init__(isolate_errors)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="eventbus",
        )
        self._pending_futures: list[Any] = []

    def publish(self, event: Event) -> None:
        handlers = self._subscribers.get(event.topic, [])
        self._pending_futures = [f for f in self._pending_futures if not f.done()]
        for handler in handlers:
            fut = self._executor.submit(self._safe_dispatch, handler, event)
            self._pending_futures.append(fut)

    def shutdown(self, wait: bool = True) -> None:
        if wait:
            for fut in self._pending_futures:
                try:
                    fut.result()
                except Exception:
                    if not self._isolate_errors:
                        raise
        self._executor.shutdown(wait=wait)

    def _safe_dispatch(self, handler: EventHandler, event: Event) -> None:
        if self._isolate_errors:
            try:
                handler(event)
            except Exception as e:
                logger.error(
                    "Async event handler failed for %s: %s", event.topic, e,
                )
        else:
            handler(event)
