from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PERF_ENABLED = os.environ.get("UNIQUANT_PERF", "0") == "1"


def enable_perf_logging() -> None:
    global _PERF_ENABLED
    _PERF_ENABLED = True


def disable_perf_logging() -> None:
    global _PERF_ENABLED
    _PERF_ENABLED = False


def is_perf_enabled() -> bool:
    return _PERF_ENABLED


@contextmanager
def perf_section(name: str, recorder: Optional[InMemoryMetricsRecorder] = None):
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        if recorder is not None:
            recorder.record(f"perf:{name}", elapsed)
        if _PERF_ENABLED:
            logger.debug("[perf] %s: %.1fms", name, elapsed * 1000)


class InMemoryMetricsRecorder:
    def __init__(self) -> None:
        self._counters: Dict[str, int] = defaultdict(int)
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._gauges: Dict[str, float] = {}

    def increment(self, name: str, value: int = 1) -> None:
        self._counters[name] += value

    def record(self, name: str, value: float) -> None:
        self._histograms[name].append(value)

    def set_gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    def snapshot(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for k, v in self._counters.items():
            result[f"counter:{k}"] = v
        for k, vals in self._histograms.items():
            if vals:
                result[f"histogram:{k}"] = {
                    "count": len(vals),
                    "min": float(min(vals)),
                    "max": float(max(vals)),
                    "avg": float(sum(vals) / len(vals)),
                    "sum": float(sum(vals)),
                }
        for k, v in self._gauges.items():
            result[f"gauge:{k}"] = v
        return dict(result)

    def report(self) -> str:
        lines = ["=== Metrics Report ==="]
        for k, v in self.snapshot().items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    def clear(self) -> None:
        self._counters.clear()
        self._histograms.clear()
        self._gauges.clear()
