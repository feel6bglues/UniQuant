# -*- coding: utf-8 -*-
"""
Tests for uniquant.brain.lppl.fitting_optimizer

Validates the extracted fitting & optimization module and ensures
complete backward compatibility with uniquant.brain.lppl.engine.
"""

import pytest
import numpy as np

import uniquant.brain.lppl.engine as engine_mod
import uniquant.brain.lppl.fitting_optimizer as opt_mod
from uniquant.brain.lppl.fitting_optimizer import (
    LPPLConfig,
    _in_parallel,
    calculate_risk_level,
    classify_top_phase,
    cost_function,
    danger_r2_threshold,
    fit_single_window_lbfgsb,
    precheck_fit_input,
    scan_date_range,
    scan_single_date,
    track_fit_failure,
    validate_model,
    warning_r2_threshold,
    watch_r2_threshold,
)


def test_backward_compatibility_reexports():
    """All symbols in fitting_optimizer must be re-exported by engine."""
    symbols = [
        "DEFAULT_CONFIG",
        "LPPLConfig",
        "_config",
        "_in_parallel",
        "calculate_risk_level",
        "classify_top_phase",
        "cost_function",
        "danger_r2_threshold",
        "fit_single_window",
        "fit_single_window_lbfgsb",
        "get_default_config",
        "precheck_fit_input",
        "scan_date_range",
        "scan_single_date",
        "track_fit_failure",
        "validate_model",
        "warning_r2_threshold",
        "watch_r2_threshold",
    ]
    for sym in symbols:
        assert hasattr(engine_mod, sym), f"engine missing re-export of {sym}"
        assert getattr(engine_mod, sym) is getattr(opt_mod, sym), f"{sym} identity mismatch"


def test_precheck_fit_input():
    # None or insufficient data
    assert precheck_fit_input(None, 20) == "insufficient_data"
    assert precheck_fit_input(np.array([10.0] * 5), 20) == "insufficient_data"

    # Window too small
    assert precheck_fit_input(np.array([10.0] * 20), 5) == "window_too_small"

    # Constant price (no price variation in recent 5 bars)
    assert precheck_fit_input(np.array([10.0] * 20), 15) == "no_price_variation"

    # Valid varying prices
    valid_prices = np.linspace(10.0, 20.0, 30)
    assert precheck_fit_input(valid_prices, 20) is None


def test_threshold_helpers():
    config = LPPLConfig(window_range=[20, 40], r2_threshold=0.6, danger_r2_offset=0.1)
    assert warning_r2_threshold(config) == pytest.approx(0.55)
    assert watch_r2_threshold(config) == pytest.approx(0.45)
    assert danger_r2_threshold(config) == pytest.approx(0.70)


def test_classify_top_phase():
    config = LPPLConfig(
        window_range=[20],
        r2_threshold=0.5,
        danger_days=5,
        warning_days=12,
        watch_days=25,
    )
    # Passed crash time
    assert classify_top_phase(-1, 0.8, config) == "none"

    # Danger phase
    assert classify_top_phase(3, 0.8, config) == "danger"

    # Warning phase
    assert classify_top_phase(8, 0.8, config) == "warning"

    # Watch phase
    assert classify_top_phase(20, 0.8, config) == "watch"

    # Safe / low R2
    assert classify_top_phase(3, 0.2, config) == "none"

    # ATR adjustments
    assert classify_top_phase(3, 0.50, config, atr_pct=1.0) == "none"  # r2 adjusted to 0.30 < 0.35 (watch)
    assert classify_top_phase(3, 0.75, config, atr_pct=3.0) == "danger"  # r2 adjusted to 0.65 >= 0.50


def test_cost_function():
    t_data = np.arange(20, dtype=np.float64)
    log_price = np.linspace(2.0, 3.0, 20)
    params = (30.0, 0.5, 8.0, 2.0, -0.5, 0.1, 0.0)
    val = cost_function(params, t_data, log_price)
    assert isinstance(val, float)
    assert val >= 0.0


def test_track_fit_failure(caplog):
    track_fit_failure("insufficient_data", context="window=40")
    # Should not raise any exception


def test_calculate_risk_level_and_validate_model():
    config = LPPLConfig(window_range=[20, 40])
    # Invalid model (m out of bounds)
    status, is_danger, is_warning = calculate_risk_level(m=0.01, w=10.0, days_left=3, lppl_config=config)
    assert status == "无效模型"
    assert not is_danger and not is_warning

    # Valid model critical days (< critical_days = 2)
    status, is_danger, is_warning = calculate_risk_level(m=0.5, w=10.0, days_left=1, r2=0.9, lppl_config=config)
    assert status == "极高危"
    assert is_danger and is_warning

    # Valid model high danger
    status, is_danger, is_warning = calculate_risk_level(m=0.5, w=10.0, days_left=3, r2=0.9, lppl_config=config)
    assert status == "高危"

    # Valid model watch
    status, is_danger, is_warning = calculate_risk_level(m=0.5, w=10.0, days_left=15, r2=0.9, lppl_config=config)
    assert status == "观察"

    # Valid model safe
    status, is_danger, is_warning = calculate_risk_level(m=0.5, w=10.0, days_left=50, r2=0.9, lppl_config=config)
    assert status == "安全"

    # validate_model
    assert validate_model({"m": 0.5, "w": 10.0, "r_squared": 0.8}, config) is True
    assert validate_model({"m": 0.01, "w": 10.0, "r_squared": 0.8}, config) is False
    assert validate_model({"m": 0.5, "w": 10.0, "r_squared": 0.2}, config) is False


def test_fit_single_window_lbfgsb_success():
    prices = np.exp(np.linspace(2.0, 3.0, 60)) + np.random.normal(0, 0.01, 60)
    config = LPPLConfig(window_range=[40])
    res = fit_single_window_lbfgsb(prices, 40, config)
    assert res is not None
    assert "window_size" in res
    assert "rmse" in res
    assert "r_squared" in res
    assert "params" in res


def test_scan_single_date_and_date_range(monkeypatch):
    monkeypatch.setenv("LPPL_DISABLE_PARALLEL", "1")
    assert _in_parallel() is True

    prices = np.exp(np.linspace(1.0, 2.5, 80))
    config = LPPLConfig(window_range=[30])

    res = scan_single_date(prices, idx=50, window_range=[30], config=config)
    assert res is not None
    assert res["idx"] == 50

    range_results = scan_date_range(prices, start_idx=40, end_idx=60, window_range=[30], step=10, config=config)
    assert len(range_results) == 2
