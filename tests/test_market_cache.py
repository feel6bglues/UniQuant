import threading
from unittest.mock import patch

from uniquant.services.market_cache import MarketLevelCache


class TestMarketLevelCacheTOCTOU:
    """TOCTOU 竞态测试：批量计算时 compute 只执行一次"""

    def test_get_or_compute_regime_called_once(self):
        cache = MarketLevelCache()
        call_count = 0
        lock = threading.Lock()

        def compute_fn():
            nonlocal call_count
            with lock:
                call_count += 1
            return "NORMAL", {"entropy": 0.5, "turnover_z": 0.3}

        n_threads = 8
        barrier = threading.Barrier(n_threads)
        results = []

        def worker():
            barrier.wait()
            result = cache.get_or_compute_regime(compute_fn)
            results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert call_count == 1, f"compute_fn 被调用了 {call_count} 次（期望 1 次）"
        assert len(results) == n_threads
        for regime, details in results:
            assert regime == "NORMAL"
            assert details["entropy"] == 0.5

    def test_get_or_compute_returns_cached_on_subsequent_calls(self):
        cache = MarketLevelCache()
        call_count = 0

        def compute_fn():
            nonlocal call_count
            call_count += 1
            return "FROZEN", {"entropy": 0.05}

        r1 = cache.get_or_compute_regime(compute_fn)
        assert call_count == 1
        assert r1 == ("FROZEN", {"entropy": 0.05})

        r2 = cache.get_or_compute_regime(compute_fn)
        assert call_count == 1, "compute_fn 不应被再次调用"
        assert r2 == ("FROZEN", {"entropy": 0.05})

    def test_get_or_compute_stale_date_recomputes(self):
        cache = MarketLevelCache()
        call_count = 0

        def compute_fn():
            nonlocal call_count
            call_count += 1
            return "NORMAL", {}

        with patch.object(cache, "_today", return_value="2026-01-01"):
            cache.get_or_compute_regime(compute_fn)
        assert call_count == 1

        with patch.object(cache, "_today", return_value="2026-01-02"):
            r = cache.get_or_compute_regime(compute_fn)
        assert call_count == 2, "跨日应重新计算"
        assert r == ("NORMAL", {})


class TestMarketLevelCacheBasic:
    """基本功能测试（回归）"""

    def test_set_and_get(self):
        cache = MarketLevelCache()
        cache.set_regime("NORMAL", {"entropy": 0.5})
        assert cache.get_regime() == "NORMAL"
        details = cache.get_regime_details()
        assert details["entropy"] == 0.5

    def test_clear(self):
        cache = MarketLevelCache()
        cache.set_regime("STRESSED", {})
        cache.clear()
        assert cache.get_regime() is None

    def test_status(self):
        cache = MarketLevelCache()
        cache.set_regime("NORMAL", {})
        cache.set_ntf({"side": "SUPPORT"})
        status = cache.status()
        assert status["has_regime"] is True
        assert status["has_ntf"] is True
        assert status["has_benchmark"] is False

    def test_today_date_boundary(self):
        cache = MarketLevelCache()
        with patch.object(cache, "_today", return_value="2026-06-01"):
            cache.set_regime("FROZEN", {"entropy": 0.01})

        with patch.object(cache, "_today", return_value="2026-06-02"):
            result = cache.get_regime()
        assert result is None, "隔天应返回 None"
