from __future__ import annotations


from uniquant.shared.config_schema import AppConfig, ExecutionConfig, RiskConfig, LoggingConfig


class TestAppConfig:
    def test_default_config(self):
        cfg = AppConfig.from_dict({})
        assert cfg.execution.trading_enabled is True
        assert cfg.risk.default_risk_pct == 0.1
        assert cfg.base.logging.level == "INFO"
        assert cfg.base.data_lake.path == "data/lake"

    def test_full_config(self):
        data = {
            "execution": {"trading_enabled": False, "kill_switch_reason": "test"},
            "risk": {"default_risk_pct": 0.2, "circuit_break_pct": 0.25},
            "base": {
                "data_lake": {"path": "custom/lake", "engine": "parquet"},
                "logging": {"level": "DEBUG", "json_format": True},
            },
            "refactoring": {
                "enabled": True,
                "feature_flags": {"event_bus": False, "factor_gate": "warn"},
            },
        }
        cfg = AppConfig.from_dict(data)
        assert cfg.execution.trading_enabled is False
        assert cfg.execution.kill_switch_reason == "test"
        assert cfg.risk.default_risk_pct == 0.2
        assert cfg.base.logging.level == "DEBUG"
        assert cfg.base.logging.json_format is True
        assert cfg.base.data_lake.path == "custom/lake"
        assert cfg.refactoring.enabled is True
        assert cfg.refactoring.feature_flags.event_bus is False
        assert cfg.refactoring.feature_flags.factor_gate == "warn"

    def test_validation_passes(self):
        cfg = AppConfig.from_dict({"risk": {"default_risk_pct": 0.15}})
        errors = cfg.validate()
        assert errors == []

    def test_validation_risk_range(self):
        cfg = AppConfig.from_dict({"risk": {"default_risk_pct": 0.0}})
        assert len(cfg.validate()) > 0

        cfg2 = AppConfig.from_dict({"risk": {"default_risk_pct": 1.5}})
        assert len(cfg2.validate()) > 0

    def test_validation_log_level(self):
        cfg = AppConfig.from_dict({"base": {"logging": {"level": "INVALID"}}})
        assert len(cfg.validate()) > 0

    def test_execution_config(self):
        ec = ExecutionConfig.from_dict({"trading_enabled": False})
        assert ec.trading_enabled is False
        ec2 = ExecutionConfig()
        assert ec2.trading_enabled is True

    def test_risk_config(self):
        rc = RiskConfig.from_dict({"default_risk_pct": 0.05})
        assert rc.default_risk_pct == 0.05
        assert rc.circuit_break_pct == 0.15

    def test_logging_config_json(self):
        lc = LoggingConfig.from_dict({"json_format": True, "level": "ERROR"})
        assert lc.json_format is True
        assert lc.level == "ERROR"
