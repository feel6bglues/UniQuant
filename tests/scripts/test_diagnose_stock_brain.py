#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniQuant 大脑综合诊断器单元测试
================================
验证多大脑联动诊断、宏观否决、法医一票否决与单票硬止损判定。
"""

from scripts.analysis.diagnose_stock_brain import StockBrainDiagnoser


class TestStockBrainDiagnoser:
    """大脑综合诊断器测试套件"""

    def test_diagnose_stock_basic_flow(self):
        """测试正常标的的多大脑联动诊断"""
        diagnoser = StockBrainDiagnoser()
        # 诊断贵州茅台
        res = diagnoser.diagnose_stock("600519.SH", as_of_date="2024-05-06")
        assert res.symbol == "600519.SH"
        assert res.macro_regime in ("BULL_OFFENSE", "CAUTION_DEFENSE", "BEAR_PANIC_CASH")
        assert res.final_action in ("BUY_PROBE", "BUY_AGGRESSIVE", "HOLD", "EXIT_STOP_LOSS", "VETO_CASH")
        assert res.hard_stop_price > 0
        assert len(res.decision_reasons) > 0

    def test_hard_stop_loss_trigger(self):
        """测试成本价亏损超 -8% 时的立即止损清仓动作"""
        diagnoser = StockBrainDiagnoser()
        # 假设买入成本为 2500 元，当前价格在 1700 左右，跌幅远超 -8%
        res = diagnoser.diagnose_stock("600519.SH", as_of_date="2024-05-06", cost_price=2500.0)
        assert res.final_action == "EXIT_STOP_LOSS"
        assert res.recommended_position_pct == 0.0
        assert any("硬止损触发" in r for r in res.decision_reasons)

    def test_missing_symbol_fallback(self):
        """测试对不存在的虚拟标的的防崩退化处理"""
        diagnoser = StockBrainDiagnoser()
        res = diagnoser.diagnose_stock("999999.SH", as_of_date="2024-05-06", cost_price=50.0)
        assert res.symbol == "999999.SH"
        assert res.hard_stop_price == 46.0  # 50 * 0.92
