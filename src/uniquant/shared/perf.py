from __future__ import annotations

import os
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Any

_ENABLED = os.environ.get("UNIQUANT_PERF", "0") == "1"

_COUNTERS: defaultdict[str, int] = defaultdict(int)
_TIMERS: defaultdict[str, int] = defaultdict(int)


@contextmanager
def perf_section(name: str):
    if not _ENABLED:
        yield
        return
    t0 = time.perf_counter_ns()
    yield
    elapsed = time.perf_counter_ns() - t0
    _TIMERS[name] += elapsed
    _COUNTERS[name] += 1


def perf_report() -> dict[str, dict[str, Any]]:
    return {
        k: {
            "calls": _COUNTERS[k],
            "total_ms": round(_TIMERS[k] / 1e6, 2),
            "avg_us": round(_TIMERS[k] / _COUNTERS[k] / 1e3, 2) if _COUNTERS[k] else 0,
        }
        for k in sorted(_TIMERS)
    }


def perf_reset() -> None:
    _COUNTERS.clear()
    _TIMERS.clear()
