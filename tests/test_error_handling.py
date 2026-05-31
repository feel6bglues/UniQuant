"""
Task-1.3: 线程安全漏洞修复测试
验证错误统计在多线程环境下的安全性
"""

import threading
import time
import pytest

from uniquant.shared.error_handling import (
    _update_error_stats,
    get_error_stats,
    reset_error_stats,
    handle_errors,
)


class TestThreadSafety:
    """测试线程安全性"""

    def setup_method(self):
        """每个测试前重置错误统计"""
        reset_error_stats()

    def test_single_thread_update(self):
        """测试单线程更新"""
        _update_error_stats("test_func", "test_error")
        stats = get_error_stats()
        
        assert "test_func" in stats
        assert stats["test_func"]["test_error"] == 1

    def test_multiple_updates_same_key(self):
        """测试同一键多次更新"""
        for _ in range(10):
            _update_error_stats("test_func", "test_error")
        
        stats = get_error_stats()
        assert stats["test_func"]["test_error"] == 10

    def test_concurrent_updates(self):
        """测试并发更新 - 线程安全验证"""
        num_threads = 10
        updates_per_thread = 100
        threads = []
        
        def update_stats():
            for _ in range(updates_per_thread):
                _update_error_stats("concurrent_func", "concurrent_error")
        
        for _ in range(num_threads):
            t = threading.Thread(target=update_stats)
            threads.append(t)
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        stats = get_error_stats()
        expected_count = num_threads * updates_per_thread
        assert stats["concurrent_func"]["concurrent_error"] == expected_count

    def test_concurrent_different_keys(self):
        """测试并发更新不同键"""
        num_threads = 5
        threads = []
        
        def update_stats(thread_id):
            for _ in range(50):
                _update_error_stats(f"func_{thread_id}", f"error_{thread_id}")
        
        for i in range(num_threads):
            t = threading.Thread(target=update_stats, args=(i,))
            threads.append(t)
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        stats = get_error_stats()
        for i in range(num_threads):
            assert f"func_{i}" in stats
            assert stats[f"func_{i}"][f"error_{i}"] == 50

    def test_reset_during_concurrent_access(self):
        """测试并发访问期间重置"""
        barrier = threading.Barrier(3)
        results = {"update": None, "reset": None, "get": None}
        
        def update_stats():
            barrier.wait()
            for _ in range(100):
                _update_error_stats("test", "error")
            results["update"] = True
        
        def reset_stats():
            barrier.wait()
            time.sleep(0.01)  # 稍微延迟
            reset_error_stats()
            results["reset"] = True
        
        def get_stats():
            barrier.wait()
            time.sleep(0.02)  # 稍微延迟
            stats = get_error_stats()
            results["get"] = True
        
        threads = [
            threading.Thread(target=update_stats),
            threading.Thread(target=reset_stats),
            threading.Thread(target=get_stats),
        ]
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        # 所有操作都应该完成，不应有死锁或异常
        assert results["update"] is True
        assert results["reset"] is True
        assert results["get"] is True

    def test_get_stats_returns_copy(self):
        """测试获取统计返回副本"""
        _update_error_stats("test_func", "test_error")
        stats1 = get_error_stats()
        stats1["test_func"]["test_error"] = 999  # 修改副本
        
        stats2 = get_error_stats()
        # 原始数据不应被修改
        assert stats2["test_func"]["test_error"] == 1


class TestHandleErrorsDecorator:
    """测试错误处理装饰器"""

    def setup_method(self):
        reset_error_stats()

    def test_handle_errors_catches_exception(self):
        """测试装饰器捕获异常"""
        @handle_errors(ValueError, default_return="default")
        def raise_value_error():
            raise ValueError("test error")
        
        result = raise_value_error()
        assert result == "default"

    def test_handle_errors_updates_stats(self):
        """测试装饰器更新统计"""
        @handle_errors(ValueError, error_type="value_error")
        def raise_value_error():
            raise ValueError("test error")
        
        raise_value_error()
        
        stats = get_error_stats()
        assert "raise_value_error" in stats
        assert stats["raise_value_error"]["value_error"] == 1

    def test_handle_errors_no_exception(self):
        """测试装饰器不捕获正常返回"""
        @handle_errors(ValueError, default_return="default")
        def normal_return():
            return "success"
        
        result = normal_return()
        assert result == "success"

    def test_concurrent_decorated_calls(self):
        """测试并发调用装饰函数"""
        @handle_errors(ValueError, error_type="concurrent_error")
        def may_raise(should_raise):
            if should_raise:
                raise ValueError("test")
            return "ok"
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=may_raise, args=(i % 2 == 0,))
            threads.append(t)
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        stats = get_error_stats()
        # 应该有5次错误（i % 2 == 0 的情况）
        assert stats["may_raise"]["concurrent_error"] == 5


class TestErrorStatsIsolation:
    """测试错误统计隔离"""

    def setup_method(self):
        reset_error_stats()

    def test_different_functions_isolated(self):
        """测试不同函数的统计隔离"""
        _update_error_stats("func_a", "error_1")
        _update_error_stats("func_b", "error_1")
        _update_error_stats("func_a", "error_2")
        
        stats = get_error_stats()
        assert stats["func_a"]["error_1"] == 1
        assert stats["func_a"]["error_2"] == 1
        assert stats["func_b"]["error_1"] == 1
        assert "error_2" not in stats["func_b"]

    def test_reset_clears_all(self):
        """测试重置清除所有统计"""
        _update_error_stats("func_a", "error_1")
        _update_error_stats("func_b", "error_2")
        
        reset_error_stats()
        
        stats = get_error_stats()
        assert len(stats) == 0
