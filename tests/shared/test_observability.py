"""
Tests for InMemoryMetricsRecorder and perf_section.
"""

from __future__ import annotations

import time


from uniquant.shared.observability import (
    InMemoryMetricsRecorder,
    disable_perf_logging,
    enable_perf_logging,
    is_perf_enabled,
    perf_section,
)


class TestInMemoryMetricsRecorder:
    def test_increment_counter(self):
        m = InMemoryMetricsRecorder()
        m.increment("signals_collected")
        m.increment("signals_collected")
        m.increment("errors", 3)
        snap = m.snapshot()
        assert snap["counter:signals_collected"] == 2
        assert snap["counter:errors"] == 3

    def test_record_histogram(self):
        m = InMemoryMetricsRecorder()
        m.record("latency_ms", 10.0)
        m.record("latency_ms", 20.0)
        m.record("latency_ms", 30.0)
        snap = m.snapshot()
        h = snap["histogram:latency_ms"]
        assert h["count"] == 3
        assert h["min"] == 10.0
        assert h["max"] == 30.0
        assert h["avg"] == 20.0

    def test_set_gauge(self):
        m = InMemoryMetricsRecorder()
        m.set_gauge("cash", 100000.0)
        m.set_gauge("positions", 5)
        snap = m.snapshot()
        assert snap["gauge:cash"] == 100000.0
        assert snap["gauge:positions"] == 5

    def test_clear(self):
        m = InMemoryMetricsRecorder()
        m.increment("a")
        m.record("b", 1.0)
        m.set_gauge("c", 2.0)
        m.clear()
        snap = m.snapshot()
        assert len(snap) == 0

    def test_report_format(self):
        m = InMemoryMetricsRecorder()
        m.increment("test_count", 5)
        report = m.report()
        assert "=== Metrics Report ===" in report
        assert "counter:test_count: 5" in report

    def test_empty_recorder_snapshot(self):
        m = InMemoryMetricsRecorder()
        assert m.snapshot() == {}

    def test_snapshot_immutable(self):
        m = InMemoryMetricsRecorder()
        m.increment("x", 1)
        snap = m.snapshot()
        assert snap["counter:x"] == 1

    def test_histogram_single_value(self):
        m = InMemoryMetricsRecorder()
        m.record("single", 42.0)
        snap = m.snapshot()
        h = snap["histogram:single"]
        assert h["count"] == 1
        assert h["min"] == 42.0
        assert h["max"] == 42.0
        assert h["avg"] == 42.0


class TestPerfSection:
    def test_perf_section_records_timing(self):
        m = InMemoryMetricsRecorder()
        with perf_section("test_op", recorder=m):
            time.sleep(0.001)
        snap = m.snapshot()
        assert "histogram:perf:test_op" in snap
        h = snap["histogram:perf:test_op"]
        assert h["count"] == 1
        assert h["min"] > 0

    def test_perf_section_without_recorder(self):
        section_name = "noop"
        with perf_section(section_name):
            pass
        assert section_name == "noop"

    def test_perf_section_records_on_exception(self):
        m = InMemoryMetricsRecorder()
        try:
            with perf_section("failing_op", recorder=m):
                raise ValueError("boom")
        except ValueError:
            pass
        snap = m.snapshot()
        assert "histogram:perf:failing_op" in snap

    def test_enable_disable_perf_logging(self):
        enable_perf_logging()
        assert is_perf_enabled()
        disable_perf_logging()
        assert not is_perf_enabled()
