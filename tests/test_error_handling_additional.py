import logging

import pandas as pd
import pytest

from uniquant.shared.error_handling import (
    _emit_log,
    _resolve_log_level,
    get_error_stats,
    handle_api_errors,
    handle_data_errors,
    handle_errors,
    handle_file_errors,
    handle_network_errors,
    reset_error_stats,
    retry_on_exception,
    validate_inputs,
    with_context,
)
from uniquant.shared.exceptions import AlphaTacticianError


class TestErrorHandlingHelpers:
    def setup_method(self):
        reset_error_stats()

    def test_resolve_log_level_and_emit_log(self):
        messages = []

        def recorder(message, **kwargs):
            messages.append((message, kwargs.get("exc_info", False)))

        assert _resolve_log_level(logging.WARNING) == logging.WARNING
        assert _resolve_log_level(logging.info) == logging.INFO
        assert _resolve_log_level("bad") == logging.ERROR

        _emit_log(recorder, "callable message", exc_info=True)
        _emit_log(logging.ERROR, "numeric message")

        assert messages == [("callable message", True)]

    def test_handle_errors_reraise_alpha_and_unexpected(self):
        @handle_errors(ValueError, default_return="fallback", error_type="value")
        def expected():
            raise ValueError("bad value")

        @handle_errors(ValueError, default_return="fallback")
        def alpha():
            raise AlphaTacticianError("alpha")

        @handle_errors(ValueError, default_return="fallback")
        def unexpected():
            raise RuntimeError("boom")

        @handle_errors(ValueError, reraise=True)
        def reraised():
            raise ValueError("again")

        assert expected() == "fallback"
        assert alpha() == "fallback"
        assert unexpected() == "fallback"
        with pytest.raises(ValueError):
            reraised()

        stats = get_error_stats()
        assert stats["expected"]["value"] == 1
        assert stats["alpha"]["alpha_tactician_error"] == 1
        assert stats["unexpected"]["unexpected"] == 1
        assert stats["reraised"]["unknown"] == 1

    def test_retry_on_exception_validate_inputs_and_with_context(self, monkeypatch):
        monkeypatch.setattr("uniquant.shared.error_handling.time.sleep", lambda *_: None)
        monkeypatch.setattr("uniquant.shared.error_handling.random.random", lambda: 0.0)
        attempts = {"count": 0}

        @retry_on_exception(max_retries=3, backoff=0.01, retry_exceptions=(ValueError,), jitter=False)
        def flaky():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ValueError("retry")
            return "ok"

        @validate_inputs(count=lambda value: value > 0)
        def validated(count=1):
            return count

        @with_context({"phase": "unit"})
        def contextual():
            raise RuntimeError("boom")

        assert flaky() == "ok"
        assert validated(2) == 2
        with pytest.raises(ValueError):
            validated(0)
        with pytest.raises(RuntimeError):
            contextual()

    def test_specialized_wrappers(self, monkeypatch):
        monkeypatch.setattr("uniquant.shared.error_handling.time.sleep", lambda *_: None)
        monkeypatch.setattr("uniquant.shared.error_handling.random.random", lambda: 0.0)

        import requests

        @handle_network_errors(default_return="network", max_retries=1)
        def network():
            raise requests.RequestException("down")

        @handle_file_errors(default_return="file")
        def file_op():
            raise FileNotFoundError("missing")

        @handle_data_errors(default_return="data")
        def data_op():
            raise pd.errors.ParserError("bad csv")

        @handle_api_errors(default_return="api", max_retries=1)
        def api_op():
            raise requests.RequestException("bad response")

        assert network() == "network"
        assert file_op() == "file"
        assert data_op() == "data"
        assert api_op() == "api"

        stats = get_error_stats()
        assert stats["wrapper"]["network"] >= 1
