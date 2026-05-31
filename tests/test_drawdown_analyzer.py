"""
DrawdownAnalyzer 测试：
- 单调上涨 → 零回撤
- 经典峰谷 → 精确 MDD
- 滚动 MDD 窗口正确性
- 尾部风险度量单调性
- 压力场景合理性
"""

import numpy as np
import pytest

from src.uniquant.risk.drawdown_analyzer import DrawdownAnalyzer, DrawdownMetrics, TailRiskMetrics


def test_monotonic_up():
    eq = np.linspace(100, 200, 252)
    m = DrawdownAnalyzer.analyze_drawdown(eq)
    assert m.max_drawdown == pytest.approx(0.0, abs=1e-12), "Monotonic up should have zero drawdown"
    assert m.max_drawdown_duration == 0
    assert m.ulcer_index == pytest.approx(0.0, abs=1e-12)


def test_classic_peak_trough():
    eq = np.array([100.0, 110.0, 120.0, 90.0, 100.0, 130.0])
    m = DrawdownAnalyzer.analyze_drawdown(eq)
    expected_mdd = (120.0 - 90.0) / 120.0
    assert m.max_drawdown == pytest.approx(expected_mdd, abs=1e-10), "MDD should be exact"
    assert m.max_drawdown_duration >= 2


def test_monotonic_down():
    eq = np.linspace(100, 50, 252)
    m = DrawdownAnalyzer.analyze_drawdown(eq)
    assert m.max_drawdown > 0
    assert m.max_drawdown_duration >= 251


def test_tail_risk_symmetric():
    np.random.seed(42)
    r = np.random.normal(0, 0.02, 1000)
    t = DrawdownAnalyzer.analyze_tail_risk(r)
    assert t.var_95 > 0, "VaR should be positive"
    assert t.var_99 > t.var_95, "VaR 99 > VaR 95"
    assert t.cvar_95 >= t.var_95, "CVaR >= VaR"
    assert t.cvar_99 >= t.var_99, "CVaR 99 >= VaR 99"
    assert t.cvar_99 >= t.cvar_95, "CVaR 99 >= CVaR 95"
    assert abs(t.skewness) < 1.0, "Gaussian skew near zero"
    assert 2.5 < t.kurtosis < 4.0, "Gaussian kurtosis near 3"


def test_tail_risk_heavy_tail():
    np.random.seed(42)
    r = np.random.standard_t(df=3, size=2000) * 0.02
    t = DrawdownAnalyzer.analyze_tail_risk(r)
    assert t.kurtosis > 5, "t(3) should have heavy tails"
    assert t.cvar_99 > t.cvar_95, "CVaR 99 > CVaR 95"
    assert t.var_99 > t.var_95, "VaR 99 > VaR 95"


def test_rolling_mdd():
    eq = np.array([100.0, 110.0, 105.0, 95.0, 100.0, 120.0, 115.0, 110.0, 130.0])
    m = DrawdownAnalyzer.analyze_drawdown(eq)
    assert m.rolling_mdd_60d == 0.0, "Window > len → no data"
    assert m.rolling_mdd_252d == 0.0


def test_stress_scenario():
    eq = np.linspace(100, 200, 252)
    s = DrawdownAnalyzer.stress_scenario(eq, "2015_crash")
    assert s.loss_pct == pytest.approx(-0.40, abs=1e-4), "2015 crash = -40%"
    assert s.loss_value < 0, "Loss should be negative"


def test_calmar_ratio():
    eq = np.array([100.0, 120.0, 80.0, 110.0, 140.0])
    mdd = (120 - 80) / 120
    ann_ret = 0.15
    m = DrawdownAnalyzer.analyze_drawdown(eq, annual_return=ann_ret)
    expected_calmar = abs(ann_ret / mdd)
    assert m.calmar_ratio == pytest.approx(expected_calmar, abs=1e-10)
