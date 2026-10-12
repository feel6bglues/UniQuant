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
    CANSLIMStrategySandbox,
    LPPLStrategySandbox,
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

        # 通过 AlphaTierEngine 门禁
        tier_engine = AlphaTierEngine()
        report = sandbox.evaluate_through_gates(mock_market_data, tier_engine=tier_engine)
        assert report.factor_name == "Wyckoff_Classic_Morphology"
        assert isinstance(report.final_tier, AlphaTier)
        assert len(report.gate_results) > 0

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
        assert isinstance(report.final_tier, AlphaTier)

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
        assert isinstance(report.final_tier, AlphaTier)
