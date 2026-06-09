"""
测试 HistoricalSimulationRisk.calculate_cvar 空尾部防御

核心目标：
1. 验证当 returns[returns <= -var] 为空时，CVaR 不返回 NaN
2. 数学保证：CVaR >= VaR（空尾部时 CVaR 至少等于 VaR）
"""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from uniquant.risk.evt_risk import HistoricalSimulationRisk as EVTRisk


class TestCVaREmptyTail:
    """CVaR 空尾部防御测试"""

    @pytest.fixture
    def evt_risk(self):
        return EVTRisk()

    # ------------------------------------------------------------------ #
    #  测试 1：模拟空尾部 — calculate_var 返回极大值使尾部为空
    # ------------------------------------------------------------------ #
    def test_cvar_empty_tail_returns_var(self, evt_risk):
        """
        当 calculate_var 返回极大值时，
        returns[returns <= -var] 为空，CVaR 不应返回 NaN。
        """
        returns = pd.Series([0.01, 0.02, 0.015, 0.03, 0.005])

        # Mock VaR to return a value that makes the tail empty
        with patch.object(evt_risk, 'calculate_var', return_value=1.0):
            cvar = evt_risk.calculate_cvar(returns, 0.95)

        assert isinstance(cvar, float)
        assert not np.isnan(cvar), "CVaR should not be NaN when tail is empty"

    # ------------------------------------------------------------------ #
    #  测试 2：CVaR >= VaR 数学保证
    # ------------------------------------------------------------------ #
    def test_cvar_gte_var(self, evt_risk):
        """
        数学上 CVaR >= VaR 必须成立。
        当尾部为空时，CVaR 应至少等于 VaR。
        """
        returns = pd.Series([0.01, 0.02, 0.015, 0.03, 0.005])

        var = evt_risk.calculate_var(returns, 0.95)
        cvar = evt_risk.calculate_cvar(returns, 0.95)

        assert cvar >= var, f"CVaR ({cvar}) must be >= VaR ({var})"

    # ------------------------------------------------------------------ #
    #  测试 3：正常数据 — CVaR 正常工作
    # ------------------------------------------------------------------ #
    def test_cvar_normal_data(self, evt_risk):
        """正常含亏损的数据，CVaR 应正常计算。"""
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.02, 252))

        cvar = evt_risk.calculate_cvar(returns, 0.95)

        assert isinstance(cvar, float)
        assert not np.isnan(cvar)

    # ------------------------------------------------------------------ #
    #  测试 4：极端牛市 — 所有收益率相同正值
    # ------------------------------------------------------------------ #
    def test_cvar_constant_positive_returns_empty_tail_variant(self, evt_risk):
        """所有收益率完全相同且为正，CVaR 应返回有效值。"""
        returns = pd.Series([0.01] * 50)

        cvar = evt_risk.calculate_cvar(returns, 0.95)

        assert isinstance(cvar, float)
        assert not np.isnan(cvar)

    # ------------------------------------------------------------------ #
    #  测试 5：99% 置信度 — 更极端的尾部
    # ------------------------------------------------------------------ #
    def test_cvar_99_confidence_no_nan_empty_tail_variant(self, evt_risk):
        """99% 置信度下尾部更极端，CVaR 仍应有效。"""
        returns = pd.Series([0.001, 0.002, 0.0015, 0.003, 0.0005, 0.0025])

        cvar = evt_risk.calculate_cvar(returns, 0.99)

        assert isinstance(cvar, float)
        assert not np.isnan(cvar)

    # ------------------------------------------------------------------ #
    #  测试 4：极端牛市 — 所有收益率相同正值
    # ------------------------------------------------------------------ #
    def test_cvar_constant_positive_returns(self, evt_risk):
        """所有收益率完全相同且为正，CVaR 应返回有效值。"""
        returns = pd.Series([0.01] * 50)

        cvar = evt_risk.calculate_cvar(returns, 0.95)

        assert isinstance(cvar, float)
        assert not np.isnan(cvar)

    # ------------------------------------------------------------------ #
    #  测试 5：空尾部 — 99% 置信度下更可能触发
    # ------------------------------------------------------------------ #
    def test_cvar_99_confidence_no_nan(self, evt_risk):
        """99% 置信度下尾部更极端，更可能为空。"""
        returns = pd.Series([0.001, 0.002, 0.0015, 0.003, 0.0005, 0.0025])

        cvar = evt_risk.calculate_cvar(returns, 0.99)

        assert isinstance(cvar, float)
        assert not np.isnan(cvar)
