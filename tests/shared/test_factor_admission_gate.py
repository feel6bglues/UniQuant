from __future__ import annotations

import pytest

from uniquant.shared.archive.factor_governance import (
    FactorAdmissionGate, FactorManifest, AdmissionResult, CheckResult,
)


def test_create_gate_default_mode():
    gate = FactorAdmissionGate()
    assert gate.mode == "warn"


def test_create_gate_off_mode():
    gate = FactorAdmissionGate(mode="off")
    assert gate.mode == "off"


def test_create_gate_block_mode():
    gate = FactorAdmissionGate(mode="block")
    assert gate.mode == "block"


def test_invalid_mode():
    with pytest.raises(ValueError, match="无效"):
        FactorAdmissionGate(mode="invalid")


def test_set_mode():
    gate = FactorAdmissionGate()
    gate.set_mode("block")
    assert gate.mode == "block"


def test_check_admission_passes():
    gate = FactorAdmissionGate()
    manifest = FactorManifest(
        name="my_test_factor",
        description="A valid test factor for admission checks",
        category="technical",
    )
    result = gate.check_admission(manifest)
    assert result.passed is True
    assert "naming" in result.checks
    assert "documentation" in result.checks
    assert "parameters" in result.checks


def test_check_admission_empty_name():
    gate = FactorAdmissionGate()
    manifest = FactorManifest(name="")
    result = gate.check_admission(manifest)
    assert result.passed is False
    assert not result.checks["naming"].passed


def test_check_admission_no_description():
    gate = FactorAdmissionGate()
    manifest = FactorManifest(name="valid_name", description="short")
    result = gate.check_admission(manifest)
    assert result.passed is False
    assert not result.checks["documentation"].passed


def test_check_admission_invalid_category():
    gate = FactorAdmissionGate()
    manifest = FactorManifest(
        name="factor_x",
        description="Valid description for testing purposes",
        category="invalid_cat",
    )
    result = gate.check_admission(manifest)
    assert result.passed is False
    assert not result.checks["parameters"].passed


def test_check_admission_invalid_naming():
    gate = FactorAdmissionGate()
    manifest = FactorManifest(
        name="Invalid-Name",
        description="A factor with bad naming convention",
        category="technical",
    )
    result = gate.check_admission(manifest)
    assert result.passed is False
    assert not result.checks["naming"].passed


def test_check_admission_long_name():
    gate = FactorAdmissionGate()
    manifest = FactorManifest(
        name="a" * 200,
        description="Factor with an excessively long name for testing",
        category="technical",
    )
    result = gate.check_admission(manifest)
    assert result.passed is False
    assert not result.checks["naming"].passed


def test_admission_result_defaults():
    r = AdmissionResult(passed=True)
    assert r.passed is True
    assert r.checks == {}
    assert r.summary == ""


def test_check_result_defaults():
    c = CheckResult(check_name="naming", passed=True)
    assert c.check_name == "naming"
    assert c.passed is True
    assert c.message == ""
