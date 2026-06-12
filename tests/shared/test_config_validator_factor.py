"""Tests for ConfigValidator factor registry validation"""
from unittest.mock import MagicMock, patch
from uniquant.shared.config_validator import ConfigValidator


class TestConfigValidatorFactor:
    def test_missing_factor_registry_skips(self):
        """FactorRegistry不可用时静默跳过"""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "base": {"data_lake": {"path": "data/lake"}},
            "cache": {"global": {"path": "data/cache"}},
            "data_sources": {"sources": []},
            "refactoring": {"feature_flags": {"factor_gate": "off"}},
            "factors": {"enabled": ["alpha_001"]},
        }.get(key, default) if isinstance(key, str) else default
        validator = ConfigValidator(config)
        errors = validator._validate_factor_registry()
        assert isinstance(errors, list)

    def test_enabled_factor_not_registered_produces_error(self):
        """配置中启用的因子未在 registry 注册时，_validate_factor_registry 返回 error"""
        config = MagicMock()

        def config_get(key, default=None):
            if key == "factors":
                return {"enabled": ["alpha_001", "fake_factor_xyz"]}
            if key == "base":
                return {"data_lake": {"path": "data/lake"}}
            if key == "cache":
                return {"global": {"path": "data/cache"}}
            if key == "data_sources":
                return {"sources": []}
            return default

        config.get.side_effect = config_get

        with patch("uniquant.brain.factors.registry.FactorRegistry") as MockReg:
            mock_reg = MagicMock()
            mock_reg.has.side_effect = lambda name: name == "alpha_001"
            MockReg.return_value = mock_reg

            validator = ConfigValidator(config)
            errors = validator._validate_factor_registry()

        assert len(errors) > 0, f"Expected errors for unregistered factor, got: {errors}"
        assert any("fake_factor_xyz" in e for e in errors), (
            f"Expected error about 'fake_factor_xyz', got: {errors}"
        )
