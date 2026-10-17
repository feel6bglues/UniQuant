"""Coverage-focused unit tests for uniquant.services.validation_service.

Exercises the failure/edge branches that the existing smoke test does not:
invalid metric values, exception handlers, empty/short series and report
error paths. Pure in-memory; no network or ``data/`` access.
"""

import math

import pandas as pd
import pytest

from uniquant.services.validation_service import ValidationService


@pytest.fixture
def service():
    return ValidationService()


# --------------------------------------------------------------------------
# validate_risk_metrics
# --------------------------------------------------------------------------

def test_validate_risk_metrics_flags_invalid_cvar(service):
    result = service.validate_risk_metrics({"cvar_95": 0.5}, {"cvar_95": 0.07})

    assert result["all_valid"] is False
    assert result["results"]["cvar_95"]["valid"] is False
    assert result["results"]["cvar_95"]["difference"] == pytest.approx(0.43)


def test_validate_risk_metrics_flags_invalid_max_drawdown(service):
    result = service.validate_risk_metrics({"max_drawdown": 0.9}, {"max_drawdown": 0.1})

    assert result["all_valid"] is False
    assert result["results"]["max_drawdown"]["valid"] is False


def test_validate_risk_metrics_regime_match(service):
    result = service.validate_risk_metrics({"regime": "bull"}, {"regime": "bull"})

    assert result["all_valid"] is True
    assert result["results"]["regime"] == {
        "calculated": "bull",
        "expected": "bull",
        "valid": True,
    }


def test_validate_risk_metrics_regime_mismatch(service):
    result = service.validate_risk_metrics({"regime": "bull"}, {"regime": "bear"})

    assert result["all_valid"] is False
    assert result["results"]["regime"]["valid"] is False


def test_validate_risk_metrics_recovers_from_type_error(service):
    result = service.validate_risk_metrics({"var_95": "abc"}, {"var_95": 0.05})

    assert result["all_valid"] is False
    assert result["results"] == {}
    assert "error" in result


# --------------------------------------------------------------------------
# calculate_standard_var / cvar / max_drawdown
# --------------------------------------------------------------------------

def test_calculate_standard_var_empty_returns_zero(service):
    assert service.calculate_standard_var(pd.Series(dtype=float), 0.95) == 0.0


def test_calculate_standard_var_non_numeric_returns_zero(service):
    assert service.calculate_standard_var(pd.Series(["a", "b"]), 0.95) == 0.0


def test_calculate_standard_cvar_empty_returns_zero(service):
    assert service.calculate_standard_cvar(pd.Series(dtype=float), 0.95) == 0.0


def test_calculate_standard_cvar_non_numeric_returns_zero(service):
    assert service.calculate_standard_cvar(pd.Series(["a", "b"]), 0.95) == 0.0


def test_calculate_standard_cvar_matches_tail_mean(service):
    returns = pd.Series([-0.10, -0.05, 0.01, 0.02, 0.03])
    var = service.calculate_standard_var(returns, 0.8)
    cvar = service.calculate_standard_cvar(returns, 0.8)

    assert cvar == pytest.approx(-returns[returns <= -var].mean())
    assert cvar >= var


def test_calculate_standard_max_drawdown_empty_returns_zero(service):
    assert service.calculate_standard_max_drawdown(pd.Series(dtype=float)) == 0.0


def test_calculate_standard_max_drawdown_non_numeric_returns_zero(service):
    assert service.calculate_standard_max_drawdown(pd.Series(["a", "b"])) == 0.0


# --------------------------------------------------------------------------
# validate_technical_indicators
# --------------------------------------------------------------------------

def test_validate_technical_indicators_flags_invalid_signal(service):
    result = service.validate_technical_indicators(
        {"signal_strength": 0.1}, {"signal_strength": 0.8}
    )

    assert result["all_valid"] is False
    assert result["results"]["signal_strength"]["valid"] is False


def test_validate_technical_indicators_flags_invalid_price(service):
    result = service.validate_technical_indicators(
        {"stop_loss": 50.0, "take_profit": 110.0},
        {"stop_loss": 95.0, "take_profit": 110.0},
    )

    assert result["all_valid"] is False
    assert result["results"]["stop_loss"]["valid"] is False
    assert result["results"]["take_profit"]["valid"] is True


def test_validate_technical_indicators_recovers_from_type_error(service):
    result = service.validate_technical_indicators(
        {"signal_strength": "x"}, {"signal_strength": 0.8}
    )

    assert result["all_valid"] is False
    assert result["results"] == {}
    assert "error" in result


# --------------------------------------------------------------------------
# compare_calculation_methods
# --------------------------------------------------------------------------

def test_compare_calculation_methods_produces_both_methods(service):
    returns = pd.Series([-0.10, -0.05, 0.01, 0.02, 0.03, 0.0, -0.02])
    result = service.compare_calculation_methods(returns)

    assert set(result["standard_method"]) == {
        "var_95",
        "var_99",
        "cvar_95",
        "cvar_99",
        "max_drawdown",
    }
    assert set(result["alternative_method"]) == set(result["standard_method"])
    assert "validation" in result


def test_compare_calculation_methods_recovers_from_error(service, monkeypatch):
    def boom(*_args, **_kwargs):
        raise TypeError("kaboom")

    monkeypatch.setattr(service, "_calculate_alternative_var", boom)
    result = service.compare_calculation_methods(pd.Series([0.01, -0.02, 0.03]))

    assert result == {"error": "kaboom"}


# --------------------------------------------------------------------------
# alternative-method helpers
# --------------------------------------------------------------------------

def test_alternative_var_empty_returns_zero(service):
    assert service._calculate_alternative_var(pd.Series(dtype=float), 0.95) == 0.0


def test_alternative_var_non_numeric_returns_zero(service):
    assert service._calculate_alternative_var(pd.Series(["a", "b"]), 0.95) == 0.0


def test_alternative_cvar_empty_returns_zero(service):
    assert service._calculate_alternative_cvar(pd.Series(dtype=float), 0.95) == 0.0


def test_alternative_cvar_empty_tail_returns_var(service):
    # All-NaN series -> percentile var is NaN -> tail mask is empty -> return var.
    result = service._calculate_alternative_cvar(pd.Series([float("nan"), float("nan")]), 0.95)
    assert math.isnan(result)


def test_alternative_cvar_non_numeric_returns_zero(service):
    assert service._calculate_alternative_cvar(pd.Series(["a", "b"]), 0.95) == 0.0


def test_alternative_max_drawdown_empty_returns_zero(service):
    assert service._calculate_alternative_max_drawdown(pd.Series(dtype=float)) == 0.0


def test_alternative_max_drawdown_non_numeric_returns_zero(service):
    assert service._calculate_alternative_max_drawdown(pd.Series(["a", "b"])) == 0.0


# --------------------------------------------------------------------------
# generate_validation_report
# --------------------------------------------------------------------------

def test_generate_report_includes_error_message(service):
    report = service.generate_validation_report(
        {"all_valid": False, "results": {}, "error": "boom"}
    )

    assert "失败" in report
    assert "错误信息: boom" in report


def test_generate_report_recovers_from_internal_error(service):
    class ExplodingDict(dict):
        def get(self, *_args, **_kwargs):
            raise TypeError("explode")

    report = service.generate_validation_report(ExplodingDict())
    assert report.startswith("生成验证报告时出错")


def test_generate_report_lists_each_metric(service):
    report = service.generate_validation_report(
        {
            "all_valid": True,
            "results": {
                "var_95": {
                    "calculated": 0.05,
                    "expected": 0.05,
                    "difference": 0.0,
                    "valid": True,
                },
                "regime": {"calculated": "bull", "expected": "bull", "valid": True},
            },
        }
    )

    assert "指标: var_95" in report
    assert "指标: regime" in report
    # regime has no "difference" key -> that line is skipped.
    assert "regime\n  计算值" in report
    assert report.rstrip().endswith("=== 报告结束 ===")
