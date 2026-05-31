"""Tests for src.services.validation_service"""

import pandas as pd
import numpy as np
from uniquant.services.validation_service import ValidationService


class TestValidationService:
    """Test validation service functionality."""

    def test_validate_risk_metrics_matching(self):
        service = ValidationService()
        calculated = {"var_95": 0.05, "var_99": 0.08, "cvar_95": 0.07, "cvar_99": 0.10, "max_drawdown": 0.15}
        expected = {"var_95": 0.05, "var_99": 0.08, "cvar_5": 0.07, "cvar_99": 0.10, "max_drawdown": 0.15}
        result = service.validate_risk_metrics(calculated, expected)
        assert "all_valid" in result
        assert "results" in result

    def test_validate_risk_metrics_empty(self):
        service = ValidationService()
        result = service.validate_risk_metrics({}, {})
        assert result["all_valid"] is True

    def test_calculate_standard_var(self):
        service = ValidationService()
        returns = pd.Series(np.random.randn(252) * 0.02)
        var = service.calculate_standard_var(returns, 0.95)
        assert isinstance(var, float)
        assert var > 0

    def test_calculate_standard_var_empty(self):
        service = ValidationService()
        var = service.calculate_standard_var(pd.Series(dtype=float), 0.95)
        assert var == 0.0

    def test_calculate_standard_cvar(self):
        service = ValidationService()
        returns = pd.Series(np.random.randn(252) * 0.02)
        cvar = service.calculate_standard_cvar(returns, 0.95)
        assert isinstance(cvar, float)

    def test_calculate_standard_max_drawdown(self):
        service = ValidationService()
        returns = pd.Series(np.random.randn(252) * 0.02)
        mdd = service.calculate_standard_max_drawdown(returns)
        assert isinstance(mdd, float)
        assert mdd >= 0

    def test_calculate_standard_max_drawdown_empty(self):
        service = ValidationService()
        mdd = service.calculate_standard_max_drawdown(pd.Series(dtype=float))
        assert mdd == 0.0

    def test_validate_technical_indicators(self):
        service = ValidationService()
        calculated = {"signal_strength": 0.8, "stop_loss": 95.0, "take_profit": 110.0}
        expected = {"signal_strength": 0.8, "stop_loss": 95.0, "take_profit": 110.0}
        result = service.validate_technical_indicators(calculated, expected)
        assert result["all_valid"] is True

    def test_compare_calculation_methods(self):
        service = ValidationService()
        returns = pd.Series(np.random.randn(252) * 0.02)
        result = service.compare_calculation_methods(returns)
        assert "standard_method" in result
        assert "alternative_method" in result
        assert "validation" in result

    def test_generate_validation_report(self):
        service = ValidationService()
        validation_results = {
            "all_valid": True,
            "results": {
                "var_95": {"calculated": 0.05, "expected": 0.05, "difference": 0.0, "valid": True}
            }
        }
        report = service.generate_validation_report(validation_results)
        assert "验证报告" in report
        assert "通过" in report
