import time

import pandas as pd

from uniquant.shared.retry_decorator import RetryConfig, retry, retry_with_fallback
from uniquant.shared.utils import (
    fetch_with_timeout,
    normalize_dataframe,
    retry_on_failure,
    safe_execute,
    with_timeout,
)


class _Source:
    def __init__(self):
        self.calls = 0

    def fetch(self, value, suffix=""):
        self.calls += 1
        return f"{value}{suffix}"

    def fail(self):
        self.calls += 1
        raise ValueError("boom")

    def slow(self):
        time.sleep(0.05)
        return "late"


class TestRetryDecorator:
    def test_retry_retries_then_succeeds(self, monkeypatch):
        attempts = {"count": 0}
        retries = []
        failures = []

        monkeypatch.setattr("uniquant.shared.retry_decorator.time.sleep", lambda *_: None)

        @retry(
            max_retries=2,
            delay=0.01,
            backoff=3.0,
            max_delay=0.02,
            exceptions=(ValueError,),
            on_retry=lambda exc, attempt: retries.append((str(exc), attempt)),
            on_failure=lambda exc: failures.append(str(exc)),
        )
        def flaky():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ValueError("temporary")
            return "ok"

        assert flaky() == "ok"
        assert attempts["count"] == 3
        assert retries == [("temporary", 1), ("temporary", 2)]
        assert failures == []

    def test_retry_calls_failure_hook_and_raises(self, monkeypatch):
        failure_messages = []
        monkeypatch.setattr("uniquant.shared.retry_decorator.time.sleep", lambda *_: None)

        @retry(
            max_retries=1,
            exceptions=(ValueError,),
            on_failure=lambda exc: failure_messages.append(str(exc)),
        )
        def always_fail():
            raise ValueError("fatal")

        try:
            always_fail()
        except ValueError as exc:
            assert str(exc) == "fatal"
        else:
            raise AssertionError("expected ValueError")

        assert failure_messages == ["fatal"]

    def test_retry_with_fallback_returns_value_after_retries(self, monkeypatch):
        monkeypatch.setattr("uniquant.shared.retry_decorator.time.sleep", lambda *_: None)
        attempts = {"count": 0}

        @retry_with_fallback(fallback_value=["fallback"], max_retries=2, exceptions=(ValueError,))
        def always_fail():
            attempts["count"] += 1
            raise ValueError("fatal")

        assert always_fail() == ["fallback"]
        assert attempts["count"] == 3

    def test_retry_config_returns_default_for_unknown_source(self):
        assert RetryConfig.get_config("sina")["delay"] == 0.5
        assert RetryConfig.get_config("unknown") == {
            "max_retries": RetryConfig.DEFAULT_MAX_RETRIES,
            "delay": RetryConfig.DEFAULT_DELAY,
            "backoff": RetryConfig.DEFAULT_BACKOFF,
        }


class TestSharedUtils:
    def test_with_timeout_success_and_error_default(self):
        assert with_timeout(lambda: "done", timeout=0.01) == "done"
        assert with_timeout(lambda: (_ for _ in ()).throw(ValueError("x")), default="fallback") == "fallback"

    def test_with_timeout_returns_default_on_timeout(self):
        assert with_timeout(lambda: time.sleep(0.05), timeout=0.001, default="late") == "late"

    def test_safe_execute_and_fetch_with_timeout(self):
        source = _Source()

        assert safe_execute(lambda: 3 + 4) == 7
        assert safe_execute(lambda: (_ for _ in ()).throw(RuntimeError("bad")), default=9) == 9
        assert fetch_with_timeout(source, "fetch", "A", suffix="B", timeout=0.02) == "AB"
        assert fetch_with_timeout(source, "fail", timeout=0.02, default="fallback") == "fallback"
        assert fetch_with_timeout(source, "slow", timeout=0.001, default="timeout") == "timeout"

    def test_normalize_dataframe_and_retry_on_failure(self, monkeypatch):
        raw = pd.DataFrame(
            {
                "日期": ["2026-04-01"],
                "开盘": [10.0],
                "成交量": [100],
            }
        )

        normalized = normalize_dataframe(raw)
        assert list(normalized.columns) == ["date", "open", "volume"]
        assert str(normalized["date"].dtype).startswith("datetime64")

        monkeypatch.setattr("uniquant.shared.utils.time.sleep", lambda *_: None)
        attempts = {"count": 0}

        def flaky():
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise ValueError("retry")
            return "ok"

        def broken():
            raise ValueError("fail")

        assert retry_on_failure(flaky, max_retries=3, delay=0.01) == "ok"
        assert retry_on_failure(broken, max_retries=2, delay=0.01, default="fallback") == "fallback"

    def test_normalize_dataframe_returns_empty_frame_unchanged(self):
        empty = pd.DataFrame()
        assert normalize_dataframe(empty).empty is True
