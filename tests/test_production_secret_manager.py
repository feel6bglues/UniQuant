from __future__ import annotations

import os

import pytest

from uniquant.shared.secret_manager import SecretManager, get_secret_manager


class TestSecretManager:
    def test_singleton(self):
        sm1 = get_secret_manager()
        sm2 = get_secret_manager()
        assert sm1 is sm2

    def test_set_and_get(self):
        sm = SecretManager()
        sm.set("TEST_KEY", "test_value")
        assert sm.get("TEST_KEY") == "test_value"

    def test_get_default(self):
        sm = SecretManager()
        assert sm.get("NONEXISTENT") is None
        assert sm.get("NONEXISTENT", "default") == "default"

    def test_get_required(self):
        sm = SecretManager()
        sm.set("REQUIRED_KEY", "required_value")
        assert sm.get_required("REQUIRED_KEY") == "required_value"

    def test_get_required_raises(self):
        sm = SecretManager()
        with pytest.raises(ValueError, match="Required secret not found"):
            sm.get_required("MISSING_KEY")

    def test_llm_api_key(self):
        sm = SecretManager()
        sm.set("WYCKOFF_LLM_API_KEY", "llm-key-123")
        assert sm.get_llm_api_key() == "llm-key-123"

    def test_mask(self):
        sm = SecretManager()
        assert sm.mask("abc") == "***"
        assert sm.mask("very_long_secret_key_12345") != "very_long_secret_key_12345"
        assert "..." in sm.mask("very_long_secret_key_12345")

    def test_snapshot_metadata(self):
        sm = SecretManager()
        sm.set("API_KEY", "secret-api-value")
        meta = sm.snapshot_metadata()
        assert "API_KEY" in meta

    def test_os_env_fallback(self):
        sm = SecretManager()
        os.environ["UNIQUANT_TEST_SECRET"] = "env-value"
        assert sm.get("UNIQUANT_TEST_SECRET") == "env-value"
