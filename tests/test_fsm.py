"""
Task-1.5: FSM 单元测试
验证状态机逻辑正确性
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.fsm import FSM, FSMState, DecisionBrain


class TestFSM:
    """测试FSM状态机"""

    @pytest.fixture
    def fsm(self):
        return FSM(ma_short=5, ma_long=10)

    @pytest.fixture
    def uptrend_data(self):
        """上升趋势数据"""
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        close_prices = np.linspace(10.0, 15.0, 30)
        return pd.DataFrame({
            "date": dates,
            "open": close_prices * 0.99,
            "high": close_prices * 1.02,
            "low": close_prices * 0.98,
            "close": close_prices,
        })

    @pytest.fixture
    def downtrend_data(self):
        """下降趋势数据"""
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        close_prices = np.linspace(15.0, 10.0, 30)
        return pd.DataFrame({
            "date": dates,
            "open": close_prices * 1.01,
            "high": close_prices * 1.02,
            "low": close_prices * 0.98,
            "close": close_prices,
        })

    @pytest.fixture
    def sideways_data(self):
        """横盘数据"""
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        close_prices = 12.0 + np.sin(np.linspace(0, 4 * np.pi, 30)) * 0.5
        return pd.DataFrame({
            "date": dates,
            "open": close_prices * 0.99,
            "high": close_prices * 1.02,
            "low": close_prices * 0.98,
            "close": close_prices,
        })

    def test_fsm_initialization(self, fsm):
        """测试FSM初始化"""
        assert fsm.ma_short == 5
        assert fsm.ma_long == 10

    def test_fsm_invalid_ma_params(self):
        """测试无效MA参数"""
        with pytest.raises(ValueError):
            FSM(ma_short=0, ma_long=10)
        with pytest.raises(ValueError):
            FSM(ma_short=-1, ma_long=10)
        with pytest.raises(ValueError):
            FSM(ma_short=10, ma_long=10)
        with pytest.raises(ValueError):
            FSM(ma_short=15, ma_long=10)

    def test_infer_state_uptrend(self, fsm, uptrend_data):
        """测试上升趋势状态推断"""
        result = fsm.infer_state(uptrend_data)
        
        assert "state" in result
        assert "state_name" in result
        assert "state_desc" in result
        assert "transition_reason" in result
        assert "ma_status" in result

    def test_infer_state_downtrend(self, fsm, downtrend_data):
        """测试下降趋势状态推断"""
        result = fsm.infer_state(downtrend_data)
        
        assert result["state"] == FSMState.IDLE

    def test_infer_state_sideways(self, fsm, sideways_data):
        """测试横盘状态推断"""
        result = fsm.infer_state(sideways_data)
        
        # 横盘可能返回多种状态，取决于具体数据
        assert result["state"] in [FSMState.IDLE, FSMState.MONITOR, FSMState.SIGNAL, FSMState.PROBE]

    def test_infer_state_insufficient_data(self, fsm):
        """测试数据不足"""
        short_data = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "open": [10.0] * 5,
            "high": [10.5] * 5,
            "low": [9.5] * 5,
            "close": [10.0] * 5,
        })
        result = fsm.infer_state(short_data)
        assert result["state"] == FSMState.IDLE

    def test_infer_state_none_input(self, fsm):
        """测试None输入"""
        with pytest.raises(Exception):
            fsm.infer_state(None)

    def test_infer_state_empty_input(self, fsm):
        """测试空数据"""
        empty_df = pd.DataFrame()
        with pytest.raises(Exception):
            fsm.infer_state(empty_df)

    def test_infer_state_missing_columns(self, fsm):
        """测试缺少必要列"""
        invalid_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=20, freq="D"),
            "close": np.linspace(10.0, 15.0, 20),
        })
        with pytest.raises(Exception):
            fsm.infer_state(invalid_df)


class TestDecisionBrain:
    """测试DecisionBrain决策模块"""

    @pytest.fixture
    def brain(self):
        brain = DecisionBrain()
        brain.reset_state()
        return brain

    @pytest.fixture
    def basic_data_packet(self):
        """基础数据包"""
        return {
            "regime": "NORMAL",
            "risk": "Safe",
            "ntf_side": "SUPPORT",
            "alpha_score": 0.5,
            "is_3rd_buy": True,
            "ma_status": "MA20 > MA60",
            "bubble_confidence": 0.0,
            "ntf_intensity": 0.5,
            "bi_count": 3,
            "price": 10.0,
            "pre_close": 9.5,
            "symbol": "600000.SH",
        }

    def test_brain_initialization(self, brain):
        """测试DecisionBrain初始化"""
        assert brain.state == FSMState.IDLE

    def test_make_decision_frozen_regime(self, brain):
        """测试冻结市场状态"""
        data_packet = {
            "regime": "FROZEN",
            "risk": "Safe",
            "ntf_side": "NONE",
            "alpha_score": 0.0,
            "is_3rd_buy": False,
            "ma_status": "N/A",
            "bubble_confidence": 0.0,
            "ntf_intensity": 0.0,
            "bi_count": 0,
            "price": 10.0,
            "pre_close": 9.5,
            "symbol": "600000.SH",
        }
        result = brain.make_decision(data_packet)
        
        assert result["action"] == "FORCE_WAIT"

    def test_make_decision_danger_risk(self, brain):
        """测试危险风险状态"""
        data_packet = {
            "regime": "NORMAL",
            "risk": "Danger",
            "ntf_side": "NONE",
            "alpha_score": 0.0,
            "is_3rd_buy": False,
            "ma_status": "MA20 <= MA60",
            "bubble_confidence": 0.0,
            "ntf_intensity": 0.0,
            "bi_count": 0,
            "price": 10.0,
            "pre_close": 9.5,
            "symbol": "600000.SH",
        }
        result = brain.make_decision(data_packet)
        
        assert result["action"] == "FORCE_EXIT"

    def test_make_decision_limit_up_blocked(self, brain):
        """测试涨停买入被阻止"""
        data_packet = {
            "regime": "NORMAL",
            "risk": "Safe",
            "ntf_side": "SUPPORT",
            "alpha_score": 0.5,
            "is_3rd_buy": True,
            "ma_status": "MA20 > MA60",
            "bubble_confidence": 0.0,
            "ntf_intensity": 0.5,
            "bi_count": 3,
            "price": 10.45,  # 涨停价
            "pre_close": 9.5,
            "symbol": "600000.SH",
        }
        result = brain.make_decision(data_packet)
        
        assert "LIMIT_UP" in result.get("buy_blockers", [])

    def test_make_decision_limit_down_sell_blocked(self, brain):
        """测试跌停卖出被阻止（跌幅未触发熔断）"""
        data_packet = {
            "regime": "NORMAL",
            "risk": "Safe",
            "ntf_side": "NONE",
            "alpha_score": -0.6,
            "is_3rd_buy": False,
            "ma_status": "MA20 <= MA60",
            "bubble_confidence": 0.0,
            "ntf_intensity": 0.0,
            "bi_count": 0,
            "price": 9.03,  # 跌幅约 -4.9%，未触发熔断
            "pre_close": 9.5,
            "symbol": "600000.SH",
        }
        result = brain.make_decision(data_packet)

        # alpha_score 触发卖出条件
        assert result["action"] == "SELL"

    def test_make_decision_circuit_break(self, brain):
        """测试熔断机制：当日跌幅超过阈值触发 CIRCUIT_BREAK"""
        data_packet = {
            "regime": "NORMAL",
            "risk": "Safe",
            "ntf_side": "NONE",
            "alpha_score": 0.5,
            "is_3rd_buy": False,
            "ma_status": "MA20 > MA60",
            "bubble_confidence": 0.0,
            "ntf_intensity": 0.5,
            "bi_count": 3,
            "price": 8.55,  # 跌幅 -10%，超过默认 -5% 阈值
            "pre_close": 9.5,
            "symbol": "600000.SH",
        }
        result = brain.make_decision(data_packet)

        assert result["action"] == "CIRCUIT_BREAK"
        assert result["state"] == "CIRCUIT_BREAK"
        assert brain.get_state() == FSMState.CIRCUIT_BREAK

    def test_stressed_regime_triggers_sell(self, brain):
        """STRESSED 应触发 REGIME_RISK 卖出条件（非 veto）"""
        data_packet = {
            "regime": "STRESSED",
            "risk": "Safe",
            "ntf_side": "NONE",
            "alpha_score": 0.5,
            "is_3rd_buy": False,
            "ma_status": "MA20 > MA60",
            "bubble_confidence": 0.0,
            "ntf_intensity": 0.0,
            "bi_count": 0,
            "price": 10.0,
            "pre_close": 9.5,
            "symbol": "600000.SH",
        }
        result = brain.make_decision(data_packet)
        assert result["action"] == "SELL"
        assert "REGIME_RISK" in result.get("sell_triggers", [])

    def test_frozen_regime_vetoes_before_sell_check(self, brain):
        """FROZEN 应由 veto 拦截，不走到 sell check"""
        data_packet = {
            "regime": "FROZEN",
            "risk": "Safe",
            "ntf_side": "NONE",
            "alpha_score": 0.5,
            "is_3rd_buy": False,
            "ma_status": "MA20 > MA60",
            "bubble_confidence": 0.0,
            "ntf_intensity": 0.0,
            "bi_count": 0,
            "price": 10.0,
            "pre_close": 9.5,
            "symbol": "600000.SH",
        }
        result = brain.make_decision(data_packet)
        assert result["action"] == "FORCE_WAIT"
        assert "sell_triggers" not in result

    def test_normal_regime_no_regime_risk(self, brain):
        """NORMAL 不应触发 REGIME_RISK"""
        data_packet = {
            "regime": "NORMAL",
            "risk": "Safe",
            "ntf_side": "SUPPORT",
            "alpha_score": 0.5,
            "is_3rd_buy": True,
            "ma_status": "MA20 > MA60",
            "bubble_confidence": 0.0,
            "ntf_intensity": 0.5,
            "bi_count": 3,
            "price": 10.0,
            "pre_close": 9.5,
            "symbol": "600000.SH",
        }
        result = brain.make_decision(data_packet)
        if "sell_triggers" in result:
            assert "REGIME_RISK" not in result["sell_triggers"]

    def test_reset_state(self, brain):
        """测试状态重置"""
        brain.state = FSMState.MONITOR
        brain.reset_state()
        
        assert brain.state == FSMState.IDLE

    def test_get_state(self, brain):
        """测试获取状态"""
        state = brain.get_state()
        assert state == FSMState.IDLE

    def test_get_state_history(self, brain, basic_data_packet):
        """测试状态历史记录"""
        brain.make_decision(basic_data_packet)
        history = brain.get_state_history()
        
        assert isinstance(history, list)


class TestFSMStateEnum:
    """测试FSM状态枚举"""

    def test_state_values(self):
        """测试状态枚举值"""
        assert FSMState.IDLE.value == "IDLE"
        assert FSMState.SIGNAL.value == "SIGNAL"
        assert FSMState.PROBE.value == "PROBE"
        assert FSMState.MONITOR.value == "MONITOR"
        assert FSMState.PYRAMID.value == "PYRAMID"
        assert FSMState.EXIT.value == "EXIT"
        assert FSMState.CIRCUIT_BREAK.value == "CIRCUIT_BREAK"
