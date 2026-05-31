"""
Task-1.2: 压力测试逻辑错误修复测试
验证压力测试使用历史崩盘场景进行真正的压力测试
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.risk.evt_risk import HistoricalSimulationRisk as EVTRisk
from uniquant.shared.constants import RiskCalculationConstants


class TestEVTRiskStressTest:
    """测试压力测试修复"""

    @pytest.fixture
    def evt_risk(self):
        return EVTRisk()

    @pytest.fixture
    def normal_returns(self):
        """正常收益率序列"""
        np.random.seed(42)
        return pd.Series(np.random.normal(0.001, 0.02, 252))

    @pytest.fixture
    def volatile_returns(self):
        """高波动收益率序列"""
        np.random.seed(42)
        return pd.Series(np.random.normal(0.001, 0.05, 252))

    def test_stress_test_crash_scenarios(self, evt_risk, normal_returns):
        """测试崩盘场景"""
        scenarios = ["market_crash_2015", "circuit_breaker_2020", "financial_crisis_2008"]
        result = evt_risk.calculate_stress_test(normal_returns, scenarios)
        
        assert isinstance(result, dict)
        assert len(result) == 3
        
        # 验证结果在合理范围内（负值，表示亏损）
        for scenario, value in result.items():
            assert isinstance(value, float)
            assert value < 0, f"Crash scenario {scenario} should result in loss"

    def test_stress_test_rate_hike_scenarios(self, evt_risk, normal_returns):
        """测试加息场景"""
        scenarios = ["rate_hike_25bp", "rate_hike_50bp", "rate_hike_100bp"]
        result = evt_risk.calculate_stress_test(normal_returns, scenarios)
        
        assert isinstance(result, dict)
        assert len(result) == 3

    def test_stress_test_recession_scenarios(self, evt_risk, normal_returns):
        """测试衰退场景"""
        scenarios = ["mild_recession", "moderate_recession", "severe_recession"]
        result = evt_risk.calculate_stress_test(normal_returns, scenarios)
        
        assert isinstance(result, dict)
        assert len(result) == 3
        
        # 验证严重程度递增
        assert result["mild_recession"] > result["moderate_recession"]
        assert result["moderate_recession"] > result["severe_recession"]

    def test_stress_test_legacy_scenarios(self, evt_risk, normal_returns):
        """测试旧版场景名称兼容性"""
        scenarios = ["market_crash", "interest_rate_hike", "recession"]
        result = evt_risk.calculate_stress_test(normal_returns, scenarios)
        
        assert isinstance(result, dict)
        assert len(result) == 3

    def test_stress_test_volatile_returns(self, evt_risk, volatile_returns):
        """测试高波动场景下的压力测试"""
        scenarios = ["market_crash_2015"]
        result = evt_risk.calculate_stress_test(volatile_returns, scenarios)
        
        # 高波动应该导致更大的损失
        assert result["market_crash_2015"] < -0.30

    def test_stress_test_empty_returns(self, evt_risk):
        """测试空收益率序列"""
        empty_returns = pd.Series([], dtype=float)
        result = evt_risk.calculate_stress_test(empty_returns, ["market_crash_2015"])
        
        assert result == {}

    def test_stress_test_unknown_scenario(self, evt_risk, normal_returns):
        """测试未知场景"""
        scenarios = ["unknown_scenario"]
        result = evt_risk.calculate_stress_test(normal_returns, scenarios)
        
        # 未知场景应该被忽略
        assert result == {}

    def test_stress_test_mixed_scenarios(self, evt_risk, normal_returns):
        """测试混合场景"""
        scenarios = [
            "market_crash_2015",
            "rate_hike_50bp",
            "unknown_scenario",
            "severe_recession",
        ]
        result = evt_risk.calculate_stress_test(normal_returns, scenarios)
        
        # 只有已知场景应该有结果
        assert len(result) == 3
        assert "market_crash_2015" in result
        assert "rate_hike_50bp" in result
        assert "severe_recession" in result


class TestEVTRiskMetrics:
    """测试风险指标计算"""

    @pytest.fixture
    def evt_risk(self):
        return EVTRisk()

    @pytest.fixture
    def normal_returns(self):
        np.random.seed(42)
        return pd.Series(np.random.normal(0.001, 0.02, 252))

    def test_calculate_var(self, evt_risk, normal_returns):
        """测试VaR计算"""
        var_95 = evt_risk.calculate_var(normal_returns, 0.95)
        var_99 = evt_risk.calculate_var(normal_returns, 0.99)
        
        assert isinstance(var_95, float)
        assert isinstance(var_99, float)
        assert var_99 >= var_95  # 99% VaR应该大于等于95% VaR

    def test_calculate_cvar(self, evt_risk, normal_returns):
        """测试CVaR计算"""
        cvar_95 = evt_risk.calculate_cvar(normal_returns, 0.95)
        
        assert isinstance(cvar_95, float)
        assert cvar_95 >= 0

    def test_detect_regime(self, evt_risk, normal_returns):
        """测试市场状态检测"""
        regime = evt_risk.detect_regime(normal_returns)
        
        assert regime in ["CRISIS", "HIGH_VOL", "BULL", "BEAR", "NORMAL"]

    def test_calculate_max_drawdown(self, evt_risk, normal_returns):
        """测试最大回撤计算"""
        max_dd = evt_risk.calculate_max_drawdown(normal_returns)
        
        assert isinstance(max_dd, float)
        assert 0 <= max_dd <= 1

    def test_calculate_metrics(self, evt_risk, normal_returns):
        """测试综合指标计算"""
        metrics = evt_risk.calculate_metrics(normal_returns)
        
        assert isinstance(metrics, dict)
        assert "var_95" in metrics
        assert "var_99" in metrics
        assert "cvar_95" in metrics
        assert "cvar_99" in metrics
        assert "max_drawdown" in metrics
        assert "regime" in metrics
        assert "ntf_signal" in metrics
        assert "summary" in metrics


class TestCrashScenariosConstants:
    """测试崩盘场景常量"""

    def test_crash_scenarios_exist(self):
        """测试崩盘场景常量存在"""
        assert hasattr(RiskCalculationConstants, "CRASH_SCENARIOS")
        assert len(RiskCalculationConstants.CRASH_SCENARIOS) > 0

    def test_crash_scenarios_values(self):
        """测试崩盘场景值为负数"""
        for name, value in RiskCalculationConstants.CRASH_SCENARIOS.items():
            assert value < 0, f"Crash scenario {name} should be negative"
            assert value >= -0.5, f"Crash scenario {name} should be reasonable"

    def test_rate_hike_scenarios_exist(self):
        """测试加息场景常量存在"""
        assert hasattr(RiskCalculationConstants, "RATE_HIKE_SCENARIOS")
        assert len(RiskCalculationConstants.RATE_HIKE_SCENARIOS) > 0

    def test_recession_scenarios_exist(self):
        """测试衰退场景常量存在"""
        assert hasattr(RiskCalculationConstants, "RECESSION_SCENARIOS")
        assert len(RiskCalculationConstants.RECESSION_SCENARIOS) > 0
