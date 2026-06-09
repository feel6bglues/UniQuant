from itertools import chain, repeat

import importlib
import sys
import time

import pandas as pd

from uniquant.shared.cache.backends import DiskCacheBackend, MemoryCacheBackend, _SENTINEL
from uniquant.shared.cache.cache_factory import CacheFactory
from uniquant.shared.di_container import DIContainer


class TestDIContainer:
    def test_import_does_not_initialize_service_container_singleton(self):
        from uniquant.services.service_container import ServiceContainer

        ServiceContainer._instance = None
        sys.modules.pop("uniquant.shared.di_container", None)

        module = importlib.import_module("uniquant.shared.di_container")

        assert ServiceContainer._instance is None
        assert module.container.get("missing") is None
        assert ServiceContainer._instance is not None
        ServiceContainer._instance = None

    def test_register_get_reset_and_clear(self):
        container = DIContainer()
        service = object()
        calls = {"count": 0}

        def factory(di):
            calls["count"] += 1
            return {"cached": di.has("service")}

        container.register("service", service)
        container.register_factory("factory", factory)

        assert container.has("service") is True
        assert container.get("service") is service
        assert container.get("factory") == {"cached": True}
        assert container.get("factory") == {"cached": True}
        assert calls["count"] == 1

        container.reset()
        assert container.get("factory") == {"cached": True}
        assert calls["count"] == 2

        container.clear()
        assert container.has("service") is False
        assert container.get("missing") is None


class TestMemoryCacheBackend:
    def test_memory_cache_set_get_evict_cleanup_and_stats(self, monkeypatch):
        backend = MemoryCacheBackend(max_size=1)
        timeline = chain(
            [100.0, 100.0, 101.0, 101.0, 102.0, 102.0, 103.0, 103.0, 104.0, 104.0],
            repeat(105.0),
        )
        monkeypatch.setattr("uniquant.shared.cache.backends.time.time", lambda: next(timeline))

        assert backend.set("k1", {"value": 1}, ttl=10) is True
        assert backend.get("k1") == {"value": 1}
        assert backend.get_stats()["hits"] == 1

        assert backend.set("k2", {"value": 2}, ttl=10) is True
        assert backend.get("k1") is _SENTINEL
        assert backend.get_stats()["misses"] >= 1

        assert backend.delete("missing") is False
        assert backend.clear(pattern="k2") == 1
        assert backend.set("k3", {"value": 3}, ttl=0) is True
        assert backend.cleanup() == 1
        backend.reset_stats()
        assert backend.get_stats()["hit_rate"] == 0.0

    def test_memory_cache_rejects_none_and_empty_dataframe(self):
        backend = MemoryCacheBackend(max_size=2)
        assert backend.set("none", None) is False
        assert backend.set("empty", pd.DataFrame()) is False


class TestDiskCacheBackend:
    def test_disk_cache_set_get_delete_clear_and_stats(self, tmp_path):
        backend = DiskCacheBackend(cache_dir=str(tmp_path), max_cache_age=7, max_cache_size=1024 * 1024)

        assert backend.set("price:000001", {"close": 12.3}, ttl=60) is True
        assert backend.get("price:000001") == {"close": 12.3}
        assert backend.get("missing") is _SENTINEL
        assert backend.get_stats()["files"] == 1
        assert backend.delete("price:000001") is True
        assert backend.delete("price:000001") is False

        backend.set("group:a", {"v": 1})
        backend.set("group:b", {"v": 2})
        backend.set("other", {"v": 3})
        assert backend.clear(pattern="group") == 2
        assert backend.get_stats()["files"] == 1
        backend.reset_stats()
        assert backend.get_stats()["hit_rate"] == 0.0

    def test_disk_cache_handles_corrupt_and_expired_files(self, tmp_path):
        backend = DiskCacheBackend(cache_dir=str(tmp_path), max_cache_age=0, max_cache_size=25)
        corrupt_path = backend._get_cache_path("corrupt")
        corrupt_path.write_text("bad", encoding="utf-8")

        assert backend.get("corrupt") is _SENTINEL
        assert not corrupt_path.exists()

        backend.set("old:key", {"v": 1})
        old_path = backend._get_cache_path("old:key")
        old_time = time.time() - 86400
        old_payload = {"data": {"v": 1}, "timestamp": old_time, "key": "old:key", "ttl": 60}
        import joblib
        joblib.dump(old_payload, old_path)

        assert backend.get("old:key") is _SENTINEL
        assert not old_path.exists()

    def test_disk_cache_cleanup_and_key_sanitizing(self, tmp_path):
        backend = DiskCacheBackend(cache_dir=str(tmp_path), max_cache_age=7, max_cache_size=40)

        long_key = "a" * 240 + ":bad/key"
        sanitized = backend._sanitize_cache_key(long_key)
        assert len(sanitized) <= 200
        assert ":" not in sanitized
        assert "/" not in sanitized

        backend.set("first", "x" * 100)
        backend.set("second", "y" * 100)
        cleaned = backend.cleanup()
        assert cleaned >= 0
        assert backend._get_total_size() <= backend.max_cache_size


class TestCacheFactory:
    def test_cache_factory_creates_expected_backends(self, tmp_path):
        memory = CacheFactory.create("memory", max_size=5)
        disk = CacheFactory.create("disk", cache_dir=str(tmp_path), max_cache_age=2, max_cache_size=64)
        default = CacheFactory.create_default()

        assert isinstance(memory, MemoryCacheBackend)
        assert memory.max_size == 5
        assert isinstance(disk, DiskCacheBackend)
        assert disk.cache_dir == tmp_path
        assert isinstance(default, DiskCacheBackend)

        try:
            CacheFactory.create("redis")
        except ValueError as exc:
            assert "Unsupported backend type" in str(exc)
        else:
            raise AssertionError("expected ValueError")
