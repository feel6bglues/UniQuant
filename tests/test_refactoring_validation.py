# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
import pytest

from uniquant.brain.lppl.numba_optimizer import (
    _de_solve_numba,
    _solve_linear_parameters_numba,
)
from uniquant.brain.factors.analyzer import (
    check_lookahead_leakage,
    LookaheadBiasError,
)


# ============================================================================
# 1. Test LPPL Numba Optimizers
# ============================================================================

def test_numba_linear_solver():
    """Verify that JIT OLS solver yields correct linear parameters."""
    t = np.arange(50, dtype=np.float64)
    # Generate mock LPPL curve with target params
    tc, m, w = 60.0, 0.5, 10.0
    a, b, c, phi = 2.0, -1.0, 0.2, 0.5
    
    tau = tc - t
    fitted = a + b * (tau**m) + c * (tau**m) * np.cos(w * np.log(tau) + phi)
    
    # Solve linear params
    a_fit, b_fit, c_fit, phi_fit = _solve_linear_parameters_numba(t, fitted, tc, m, w)
    
    assert np.allclose(a_fit, a, atol=1e-2)
    assert np.allclose(b_fit, b, atol=1e-2)
    assert np.allclose(c_fit, c, atol=1e-2)
    assert np.allclose(phi_fit, phi, atol=1e-2)


def test_de_numba_solver():
    """Verify convergence of Numba-compiled Differential Evolution solver."""
    t = np.arange(50, dtype=np.float64)
    tc, m, w = 60.0, 0.5, 10.0
    a, b, c, phi = 2.0, -1.0, 0.2, 0.5
    
    tau = tc - t
    prices = a + b * (tau**m) + c * (tau**m) * np.cos(w * np.log(tau) + phi)
    
    # Bounds for tc, m, w
    bounds = np.array([
        [51.0, 70.0],
        [0.1, 0.9],
        [6.0, 13.0]
    ], dtype=np.float64)
    
    sol, fit, success = _de_solve_numba(
        t, prices, bounds, popsize=15, maxiter=80, tol=0.01, seed=42
    )
    
    assert success
    assert 55.0 <= sol[0] <= 65.0
    assert 0.1 <= sol[1] <= 0.9
    assert 6.0 <= sol[2] <= 13.0


# ============================================================================
# 2. Test DataAligner removed (S4a: dead component deleted, fail-fast on misaligned data)
# ============================================================================

def test_data_aligner_removed():
    """Step4 S4a: DataAligner 随死源删除 — 数据不齐由 DataCleaner/DataValidator fail-fast 兜底,
    不再有日历对齐 + ffill 的停牌补行能力。"""
    import importlib.util

    assert importlib.util.find_spec("uniquant.data.pipeline.data_aligner") is None


# ============================================================================
# 3. Test Factor Pipeline Look-ahead Bias Assertion
# ============================================================================

def test_check_lookahead_leakage_clean():
    """Verify that a factor calculation with no lookahead bias passes check."""
    data = []
    for date in pd.date_range("2026-01-01", periods=30, freq="B"):
        data.append({
            "date": date,
            "code": "000001.SZ",
            "close": 10.0 + np.sin(date.day),
        })
    df = pd.DataFrame(data)
    
    # Lagged momentum: shift(1), no future leakage
    def clean_factor_func(x):
        x = x.copy()
        x["momentum"] = x["close"].shift(1)
        return x
        
    # Should pass without LookaheadBiasError
    assert check_lookahead_leakage(df, clean_factor_func, ["momentum"])


def test_check_lookahead_leakage_dirty():
    """Verify that check_lookahead_leakage successfully catches future leakage."""
    data = []
    for date in pd.date_range("2026-01-01", periods=30, freq="B"):
        data.append({
            "date": date,
            "code": "000001.SZ",
            "close": 10.0 + np.sin(date.day),
        })
    df = pd.DataFrame(data)
    
    # Future momentum: shift(-1), uses future data!
    def dirty_factor_func(x):
        x = x.copy()
        x["momentum"] = x["close"].shift(-1)
        return x
        
    with pytest.raises(LookaheadBiasError, match="Look-ahead bias detected in factor 'momentum'"):
        check_lookahead_leakage(df, dirty_factor_func, ["momentum"])
