"""
Tests for ConfigValidator and env-var override support.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from uniquant.shared.config_validator import ConfigValidator, ConfigValidationError


class FakeConfig:
    """Minimal config mock for validator tests."""

    def __init__(self, data: dict):
        self._data = data
        self.ROOT_DIR = MagicMock()

    def get(self, key_path: str, default=None):
        keys = key_path.split(".")
        value = self._data
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default


def test_validate_all_passes_with_valid_config():
    config = FakeConfig({
        "base": {"data_lake": {"path": "data/lake"}, "tdx": {"path": "/tmp"}},
        "cache": {"global": {"path": "data/cache", "enabled": True}},
        "data_sources": {"sources": []},
        "brain": {},
        "risk": {},
        "refactoring": {"feature_flags": {"factor_gate": "warn"}},
    })
    validator = ConfigValidator(config)
    errors = validator.validate_all()
    assert errors == []


def test_missing_required_sections():
    config = FakeConfig({})
    validator = ConfigValidator(config)
    errors = validator.validate_all()
    assert any("Missing required config section: base" in e for e in errors)
    assert any("Missing config section: brain" in e for e in errors)
    assert any("Missing config section: risk" in e for e in errors)


def test_assert_valid_raises_on_errors():
    config = FakeConfig({})
    validator = ConfigValidator(config)
    with pytest.raises(ConfigValidationError):
        validator.assert_valid()


def test_invalid_factor_gate():
    config = FakeConfig({
        "base": {"data_lake": {"path": "data/lake"}},
        "cache": {"global": {"path": "data/cache"}},
        "data_sources": {"sources": []},
        "brain": {},
        "risk": {},
        "refactoring": {"feature_flags": {"factor_gate": "invalid_mode"}},
    })
    validator = ConfigValidator(config)
    errors = validator.validate_all()
    assert any("Invalid factor_gate" in e for e in errors)


def test_data_source_class_import_error():
    config = FakeConfig({
        "base": {"data_lake": {"path": "data/lake"}},
        "cache": {"global": {"path": "data/cache"}},
        "data_sources": {"sources": [{"class": "nonexistent.module.FakeSource"}]},
        "brain": {},
        "risk": {},
    })
    validator = ConfigValidator(config)
    errors = validator.validate_all()
    assert any("cannot be imported" in e for e in errors)


# ── ConfigLoader env override tests ──

def test_parse_env_key_alias():
    from uniquant.shared.config_loader import _parse_env_key
    assert _parse_env_key("UNIQUANT_TDX_PATH") == "base.tdx.path"
    assert _parse_env_key("UNIQUANT_LOG_LEVEL") == "base.logging.level"


def test_parse_env_key_double_underscore():
    from uniquant.shared.config_loader import _parse_env_key
    assert _parse_env_key("UNIQUANT_BASE__TDX__PATH") == "base.tdx.path"
    assert _parse_env_key("UNIQUANT_CACHE__GLOBAL__ENABLED") == "cache.global.enabled"


def test_parse_env_key_no_prefix():
    from uniquant.shared.config_loader import _parse_env_key
    assert _parse_env_key("OTHER_VAR") is None


def test_cast_env_value():
    from uniquant.shared.config_loader import _cast_env_value
    assert _cast_env_value("true") is True
    assert _cast_env_value("false") is False
    assert _cast_env_value("42") == 42
    assert _cast_env_value("3.14") == 3.14
    assert _cast_env_value("hello") == "hello"


def test_parse_env_key_unknown_suffix():
    from uniquant.shared.config_loader import _parse_env_key
    result = _parse_env_key("UNIQUANT_SOME_RANDOM_KEY")
    assert result == "some_random_key"


def test_apply_env_overrides(monkeypatch):
    from uniquant.shared.config_loader import _apply_env_overrides
    monkeypatch.setenv("UNIQUANT_TDX_PATH", "/custom/tdx")
    monkeypatch.setenv("UNIQUANT_CACHE__GLOBAL__ENABLED", "false")
    config = {
        "base": {"tdx": {"path": "/default/tdx"}, "data_lake": {"path": "data/lake"}},
        "cache": {"global": {"enabled": True, "path": "data/cache"}},
    }
    result = _apply_env_overrides(config)
    assert result["base"]["tdx"]["path"] == "/custom/tdx"
    assert result["cache"]["global"]["enabled"] is False


# ── Secrets overlay tests (P1-8) ──


def test_secret_env_overrides_string_value(monkeypatch):
    """Simulate injecting a token via env var - string values preserved."""
    from uniquant.shared.config_loader import _apply_env_overrides
    monkeypatch.setenv("UNIQUANT_DATA_SOURCES__EASTMONEY__TOKEN", "sk-abc123")
    config = {"data_sources": {"eastmoney": {}}}
    result = _apply_env_overrides(config)
    assert result["data_sources"]["eastmoney"]["token"] == "sk-abc123"


def test_secret_env_overrides_deep_nested_path(monkeypatch):
    """Override a 4-level deep config path (simulating nested secrets)."""
    from uniquant.shared.config_loader import _apply_env_overrides
    monkeypatch.setenv("UNIQUANT_BRAIN__LLM__API__KEY", "sk-llm-secret")
    config = {"brain": {"llm": {}}}
    result = _apply_env_overrides(config)
    assert result["brain"]["llm"]["api"]["key"] == "sk-llm-secret"


def test_secret_env_does_not_leak_to_sibling_keys(monkeypatch):
    """Verify env override only touches the target key, not siblings."""
    from uniquant.shared.config_loader import _apply_env_overrides
    monkeypatch.setenv("UNIQUANT_CACHE__GLOBAL__ENABLED", "false")
    config = {"cache": {"global": {"enabled": True, "path": "data/cache"}}}
    result = _apply_env_overrides(config)
    assert result["cache"]["global"]["enabled"] is False
    assert result["cache"]["global"]["path"] == "data/cache"


def test_no_static_secrets_in_committed_config():
    """Verify committed config.yaml contains no hardcoded tokens or passwords."""
    import os
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "config", "config.yaml"
    )
    if not os.path.exists(config_path):
        pytest.skip("config.yaml not found")
    with open(config_path) as f:
        content = f.read()
    secrets = ["api_key", "token", "password", "secret"]
    for s in secrets:
        lines = [line for line in content.splitlines() if s in line.lower()]
        assert not lines, f"Static secret '{s}' found in config.yaml: {lines}"
