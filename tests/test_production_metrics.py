from __future__ import annotations

from uniquant.shared.prometheus_metrics import MetricsRegistry, get_metrics, measure


class TestMetricsRegistry:
    def test_singleton(self):
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2

    def test_increment(self):
        metrics = MetricsRegistry()
        metrics.increment("test_counter", 5)
        snap = metrics.snapshot()
        assert snap.get("counter:test_counter", 0) >= 5

    def test_record_histogram(self):
        metrics = MetricsRegistry()
        metrics.record("test_hist", 0.5)
        metrics.record("test_hist", 1.5)
        snap = metrics.snapshot()
        hist_key = "histogram:test_hist"
        assert hist_key in snap
        assert snap[hist_key]["count"] >= 2

    def test_set_gauge(self):
        metrics = MetricsRegistry()
        metrics.set_gauge("test_gauge", 99.9)
        snap = metrics.snapshot()
        assert snap.get("gauge:test_gauge", 0) == 99.9

    def test_snapshot_content(self):
        metrics = MetricsRegistry()
        metrics.increment("a", 1)
        metrics.record("b", 0.1)
        metrics.set_gauge("c", 1.0)
        snap = metrics.snapshot()
        assert "counter:a" in snap
        assert "histogram:b" in snap
        assert "gauge:c" in snap

    def test_measure_context_manager(self):
        metrics = MetricsRegistry()
        with measure("test_operation"):
            pass
        snap = metrics.snapshot()
        op_key = "histogram:test_operation_seconds"
        assert op_key in snap
        assert snap[op_key]["count"] == 1
