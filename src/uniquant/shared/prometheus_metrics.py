from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

from .logger_factory import get_logger

logger = get_logger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server

    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False


_PROMETHEUS_PORT = 9100
_PROMETHEUS_STARTED = False


def ensure_prometheus_server(port: int = 9100) -> None:
    global _PROMETHEUS_PORT, _PROMETHEUS_STARTED
    _PROMETHEUS_PORT = port
    if HAS_PROMETHEUS and not _PROMETHEUS_STARTED:
        try:
            start_http_server(port)
            _PROMETHEUS_STARTED = True
            logger.info("Prometheus metrics server started on port %d", port)
        except Exception as e:
            logger.warning("Failed to start Prometheus server: %s", e)


class MetricsRegistry:
    _instance: Optional["MetricsRegistry"] = None

    def __new__(cls) -> "MetricsRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return
        self._counters: Dict[str, Any] = {}
        self._histograms: Dict[str, Any] = {}
        self._gauges: Dict[str, Any] = {}
        self._initialized = True

    def _get_counter(self, name: str, description: str = "") -> Any:
        if name not in self._counters:
            if HAS_PROMETHEUS:
                self._counters[name] = Counter(name, description or name)
            else:
                self._counters[name] = {"_val": 0}
        return self._counters[name]

    def _get_histogram(self, name: str, description: str = "") -> Any:
        if name not in self._histograms:
            if HAS_PROMETHEUS:
                self._histograms[name] = Histogram(name, description or name)
            else:
                self._histograms[name] = {"_vals": []}
        return self._histograms[name]

    def _get_gauge(self, name: str, description: str = "") -> Any:
        if name not in self._gauges:
            if HAS_PROMETHEUS:
                self._gauges[name] = Gauge(name, description or name)
            else:
                self._gauges[name] = {"_val": 0.0}
        return self._gauges[name]

    def increment(self, name: str, value: int = 1, description: str = "") -> None:
        c = self._get_counter(name, description)
        if HAS_PROMETHEUS:
            c.inc(value)
        else:
            c["_val"] += value

    def record(self, name: str, value: float, description: str = "") -> None:
        h = self._get_histogram(name, description)
        if HAS_PROMETHEUS:
            h.observe(value)
        else:
            h["_vals"].append(value)

    def set_gauge(self, name: str, value: float, description: str = "") -> None:
        g = self._get_gauge(name, description)
        if HAS_PROMETHEUS:
            g.set(value)
        else:
            g["_val"] = value

    def snapshot(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for name, c in self._counters.items():
            if HAS_PROMETHEUS:
                result[f"counter:{name}"] = c._value.get()
            else:
                result[f"counter:{name}"] = c["_val"]
        for name, h in self._histograms.items():
            if HAS_PROMETHEUS:
                result[f"histogram:{name}_count"] = h._count.get()
            else:
                vals = h["_vals"]
                result[f"histogram:{name}"] = {
                    "count": len(vals),
                    "avg": sum(vals) / len(vals) if vals else 0.0,
                }
        for name, g in self._gauges.items():
            if HAS_PROMETHEUS:
                result[f"gauge:{name}"] = g._value.get()
            else:
                result[f"gauge:{name}"] = g["_val"]
        return result


_metrics = MetricsRegistry()


def get_metrics() -> MetricsRegistry:
    return _metrics


@contextmanager
def measure(name: str, description: str = ""):
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        _metrics.record(f"{name}_seconds", elapsed, description)
