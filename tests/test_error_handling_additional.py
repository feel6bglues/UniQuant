import logging

import pytest

from uniquant.shared.error_handling import (
    _emit_log,
    _resolve_log_level,
    get_error_stats,
    handle_errors,
    reset_error_stats,
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
        @handle_errors(ValueError, default_return="fallback", error_type="value", reraise=False)
        def expected():
            raise ValueError("bad value")

        @handle_errors(ValueError, default_return="fallback", reraise=False)
        def alpha():
            raise AlphaTacticianError("alpha")

        @handle_errors(ValueError, default_return="fallback", reraise=False)
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

    def test_validate_inputs_and_with_context(self):
        @validate_inputs(count=lambda value: value > 0)
        def validated(count=1):
            return count

        @with_context({"phase": "unit"})
        def contextual():
            raise RuntimeError("boom")

        assert validated(2) == 2
        with pytest.raises(ValueError):
            validated(0)
        with pytest.raises(RuntimeError):
            contextual()

    def test_deprecated_wrappers_pruned(self):
        """第十七轮死代码清理：已弃用的5个包装器已被物理移除。"""
        import uniquant.shared.error_handling as eh

        pruned_names = [
            "retry_on_exception",
            "handle_network_errors",
            "handle_file_errors",
            "handle_data_errors",
            "handle_api_errors",
        ]
        for name in pruned_names:
            assert not hasattr(eh, name), f"{name} should have been pruned from error_handling"
