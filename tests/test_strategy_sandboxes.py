# -*- coding: utf-8 -*-
"""
Tests for Strategy Sandboxes & Research OS Gate Integration
=============================================================
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.research.gates.alpha_tier_engine import AlphaTier, AlphaTierEngine
from uniquant.research.sandboxes import (
    BaseStrategySandbox,
    CANSLIMStrategySandbox,
    LPPLStrategySandbox,
    SandboxSignalEvaluation,
    WyckoffStrategySandbox,
)


@pytest.fixture
def mock_market_data():
    np.random.seed(42)
    n = 250
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    
    # 构造带有上涨趋势和震荡的合成价格
    ret = np.random.normal(0.001, 0.02, size=n)
    prices = 100.0 * np.exp(np.cumsum(ret))
    
    highs = prices * (1.0 + np.abs(np.random.normal(0, 0.01, size=n)))
    lows = prices * (1.0 - np.abs(np.random.normal(0, 0.01, size=n)))
    opens = (highs + lows) / 2.0
    volumes = np.random.uniform(100000, 5000000, size=n)
    
    df = pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes,
    })
    return df


class TestStrategySandboxes:
    def test_wyckoff_sandbox_simulation_and_gate(self, mock_market_data):
        sandbox = WyckoffStrategySandbox(box_size_pct=0.02, reversal_boxes=3, scaling_method="log")
        res = sandbox.run_sandbox_simulation(mock_market_data)
        
        assert res.strategy_name == "Wyckoff_Classic_Morphology"
        assert len(res.ic_series) > 0
        assert len(res.daily_returns) > 0
        assert len(res.turnover_series) > 0
        assert "pnf_box_count" in res.metadata

        # 通过 AlphaTierEngine 门禁：未提供真实残差 IC / PBO → 诚实判定 UNRATED（禁止捷径伪造）
        tier_engine = AlphaTierEngine()
        report = sandbox.evaluate_through_gates(mock_market_data, tier_engine=tier_engine)
        assert report.factor_name == "Wyckoff_Classic_Morphology"
        assert report.final_tier == AlphaTier.TIER_UNRATED
        assert report.rejection_reason is not None
        assert "捷径已禁用" in report.rejection_reason

    def test_lppl_sandbox_simulation_and_gate(self, mock_market_data):
        sandbox = LPPLStrategySandbox(lookback_window=60, bubble_threshold=0.50)
        res = sandbox.run_sandbox_simulation(mock_market_data)
        
        assert res.strategy_name == "LPPL_Critical_Bubble_Detector"
        assert len(res.ic_series) > 0
        assert len(res.daily_returns) > 0
        assert "mean_bubble_score" in res.metadata

        tier_engine = AlphaTierEngine()
        report = sandbox.evaluate_through_gates(mock_market_data, tier_engine=tier_engine)
        assert report.factor_name == "LPPL_Critical_Bubble_Detector"
        assert report.final_tier == AlphaTier.TIER_UNRATED

    def test_canslim_sandbox_simulation_and_gate(self, mock_market_data):
        sandbox = CANSLIMStrategySandbox(momentum_window=20, ha_smooth_window=5)
        res = sandbox.run_sandbox_simulation(mock_market_data)
        
        assert res.strategy_name == "CANSLIM_HA_Momentum_Rotation"
        assert len(res.ic_series) > 0
        assert len(res.daily_returns) > 0
        assert "ha_bullish_ratio" in res.metadata

        tier_engine = AlphaTierEngine()
        report = sandbox.evaluate_through_gates(mock_market_data, tier_engine=tier_engine)
        assert report.factor_name == "CANSLIM_HA_Momentum_Rotation"
        assert report.final_tier == AlphaTier.TIER_UNRATED


def _strong_gate_inputs():
    """构造四阶硬门禁**全部可达**的真实（非伪造）输入。

    返回 ``(ic_series, residual_ic_series, pbo_value, gate_inputs)``。
    """
    rng = np.random.default_rng(20261016)
    t_len = 250
    ic_series = (np.full(t_len, 0.05) + rng.normal(0, 0.004, t_len)).tolist()
    residual_ic_series = (np.full(t_len, 0.03) + rng.normal(0, 0.005, t_len)).tolist()
    gate_inputs = {
        "b": {
            "pure_ic_series": np.full(t_len, 0.04) + rng.normal(0, 0.005, t_len),
            "r2_series": np.full(20, 0.10),
            "size_corr_series": np.full(20, 0.05),
            # 故意以 Python list 传入 → 回归 `list ** 2` 崩溃缺陷
            "top_industry_weights": [0.08, 0.07, 0.05],
        },
        "c": {
            "net_cagr": 0.20,
            "net_sharpe": 1.50,
            "gross_sharpe": 1.80,
            "net_mdd": -0.12,
            "daily_turnover": 0.08,
            "regime_sharpes": {"bull": 1.5, "bear": 0.5},
            "portfolio_median_adv": 40_000_000.0,
            "calculated_capacity": 60_000_000.0,
        },
        "d": {
            "cleanroom_rank_corr": 0.9995,
            "is_sharpe": 1.50,
            "quarantine_oos_sharpe": 1.35,
            "adversarial_sharpe": 1.20,
            "sharpe_variance": 0.20,
            "sample_length_t": 252,
        },
    }
    return ic_series, residual_ic_series, 0.10, gate_inputs


class _StubSandbox(BaseStrategySandbox):
    """返回受控 IC 序列的测试沙盒（用于覆盖四阶全通过分支）。"""

    def __init__(self, ic_series):
        super().__init__(strategy_name="Stub_Strategy", description="stub")
        self._ic = ic_series

    def run_sandbox_simulation(self, df, **kwargs) -> SandboxSignalEvaluation:
        return SandboxSignalEvaluation(
            strategy_name=self.strategy_name,
            ic_series=self._ic,
            daily_returns=[0.0],
            turnover_series=[0.0],
        )


class TestAlphaTierHonestGate:
    """P0-1 回归：研究门禁捷径伪造与 `list ** 2` 崩溃修复守卫。"""

    def test_shortcut_path_disabled_without_real_inputs(self):
        """未提供真实动量残差 IC / PBO → 判 UNRATED，绝不伪造放行。"""
        engine = AlphaTierEngine()
        strong_ic = np.full(250, 0.06).tolist()  # 即便 IC 极强也不得走捷径晋升
        report = engine.evaluate_candidate("shortcut_candidate", strong_ic)

        assert report.final_tier == AlphaTier.TIER_UNRATED
        assert report.passed_class_a is False
        assert report.gate_results == []
        assert report.rejection_reason is not None
        assert "捷径已禁用" in report.rejection_reason

    def test_class_b_accepts_list_industry_weights_without_crash(self):
        """回归 `list ** 2`：top_industry_weights 传 Python list 不得崩溃。"""
        engine = AlphaTierEngine()
        ic_series, residual_ic_series, pbo_value, gate_inputs = _strong_gate_inputs()
        gate_inputs = {"b": gate_inputs["b"]}  # 仅到 Class B

        report = engine.evaluate_candidate(
            "list_weights_candidate",
            ic_series,
            residual_ic_series=residual_ic_series,
            pbo_value=pbo_value,
            gate_inputs=gate_inputs,
        )

        assert report.passed_class_a is True
        assert report.passed_class_b is True
        assert report.final_tier == AlphaTier.TIER_B
        assert "缺少 Class C" in report.rejection_reason

    def test_full_four_gate_pass_with_real_inputs(self):
        """真实达标输入应一路晋升至 TIER_D，覆盖四阶硬门禁完整通过分支。"""
        engine = AlphaTierEngine()
        ic_series, residual_ic_series, pbo_value, gate_inputs = _strong_gate_inputs()

        report = engine.evaluate_candidate(
            "replicated_alpha",
            ic_series,
            residual_ic_series=residual_ic_series,
            pbo_value=pbo_value,
            gate_inputs=gate_inputs,
        )

        assert report.passed_class_a is True
        assert report.passed_class_b is True
        assert report.passed_class_c is True
        assert report.passed_class_d is True
        assert report.final_tier == AlphaTier.TIER_D
        assert report.rejection_reason is None
        assert len(report.gate_results) == 4
        assert report.audit_metadata["evaluated_via"] == "evaluate_candidate"

    def test_sandbox_gate_forwards_real_inputs_to_tier_d(self):
        """沙盒经 evaluate_through_gates 转发真实输入后应可达 TIER_D。"""
        engine = AlphaTierEngine()
        ic_series, residual_ic_series, pbo_value, gate_inputs = _strong_gate_inputs()
        sandbox = _StubSandbox(ic_series)

        report = sandbox.evaluate_through_gates(
            df=pd.DataFrame({"close": [1.0, 2.0]}),
            tier_engine=engine,
            residual_ic_series=residual_ic_series,
            pbo_value=pbo_value,
            gate_inputs=gate_inputs,
        )

        assert report.final_tier == AlphaTier.TIER_D
        assert report.rejection_reason is None

    def test_sandbox_without_real_inputs_is_unrated(self):
        """沙盒缺少真实输入时必须诚实拒绝，而非走捷径。"""
        engine = AlphaTierEngine()
        ic_series, _, _, _ = _strong_gate_inputs()
        sandbox = _StubSandbox(ic_series)

        report = sandbox.evaluate_through_gates(
            df=pd.DataFrame({"close": [1.0, 2.0]}),
            tier_engine=engine,
        )

        assert report.final_tier == AlphaTier.TIER_UNRATED
        assert "捷径已禁用" in report.rejection_reason
