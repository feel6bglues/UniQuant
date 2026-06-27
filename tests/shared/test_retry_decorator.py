"""Tests for uniquant.shared.retry_decorator — retry, retry_with_fallback, RetryConfig."""

import pytest

from uniquant.shared.retry_decorator import retry, retry_with_fallback, RetryConfig


class TestRetry:
    def test_success_on_first_attempt(self):
        call_count = 0

        @retry(max_retries=3, delay=0.01)
        def ok():
            nonlocal call_count
            call_count += 1
            return 42

        assert ok() == 42
        assert call_count == 1

    def test_retry_then_success(self):
        call_count = 0

        @retry(max_retries=3, delay=0.01)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("not yet")
            return "success"

        assert flaky() == "success"
        assert call_count == 2

    def test_all_retries_exhausted(self):
        @retry(max_retries=2, delay=0.01)
        def always_fail():
            raise ValueError("always fail")

        with pytest.raises(ValueError, match="always fail"):
            always_fail()

    def test_custom_exception_types(self):
        @retry(max_retries=2, delay=0.01, exceptions=(KeyError,))
        def raises_type_error():
            raise TypeError("wrong type")

        with pytest.raises(TypeError, match="wrong type"):
            raises_type_error()

    def test_on_retry_callback(self):
        callback_log = []

        @retry(max_retries=2, delay=0.01, on_retry=lambda e, a: callback_log.append((str(e), a)))
        def flaky():
            nonlocal callback_log
            if len(callback_log) < 1:
                raise ValueError("retry me")
            return "done"

        assert flaky() == "done"
        assert len(callback_log) == 1
        assert "retry me" in callback_log[0][0]
        assert callback_log[0][1] == 1

    def test_on_failure_callback(self):
        callback_log = []

        @retry(max_retries=1, delay=0.01, on_failure=lambda e: callback_log.append(str(e)))
        def always_fail():
            raise ValueError("dead")

        with pytest.raises(ValueError):
            always_fail()
        assert len(callback_log) == 1
        assert "dead" in callback_log[0]

    def test_max_delay_caps_backoff(self):
        @retry(max_retries=2, delay=0.1, backoff=10.0, max_delay=0.15)
        def flaky():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            flaky()

    def test_zero_retries(self):
        call_count = 0

        @retry(max_retries=0, delay=0.01)
        def flaky():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        with pytest.raises(ValueError):
            flaky()
        assert call_count == 1


class TestRetryWithFallback:
    def test_returns_fallback_after_exhaustion(self):
        @retry_with_fallback(fallback_value="default", max_retries=2, delay=0.01)
        def always_fail():
            raise ValueError("fail")

        assert always_fail() == "default"

    def test_success_no_fallback_needed(self):
        @retry_with_fallback(fallback_value="default", max_retries=2, delay=0.01)
        def ok():
            return 99

        assert ok() == 99

    def test_custom_fallback_value(self):
        @retry_with_fallback(fallback_value=[], max_retries=2, delay=0.01)
        def fail():
            raise RuntimeError("boom")

        assert fail() == []


class TestRetryConfig:
    def test_default_config(self):
        cfg = RetryConfig.get_config("unknown_source")
        assert cfg["max_retries"] == RetryConfig.DEFAULT_MAX_RETRIES
        assert cfg["delay"] == RetryConfig.DEFAULT_DELAY
        assert cfg["backoff"] == RetryConfig.DEFAULT_BACKOFF

    def test_eastmoney_config(self):
        cfg = RetryConfig.get_config("eastmoney")
        assert cfg["max_retries"] == 3
        assert cfg["delay"] == 1.0

    def test_sina_config(self):
        cfg = RetryConfig.get_config("sina")
        assert cfg["delay"] == 0.5
        assert cfg["backoff"] == 1.5

    def test_tencent_config(self):
        cfg = RetryConfig.get_config("tencent")
        assert cfg["max_retries"] == 3
        assert cfg["backoff"] == 1.5
