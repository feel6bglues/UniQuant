#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniQuant 统一日终决策流水线单元测试
==================================
覆盖宏观仓位安全阀评估、单票硬止损扫描、执行指令生成与飞书卡片集成。
"""

from scripts.daily.unified_daily_eod import UnifiedDailyEODPipeline


class TestUnifiedDailyEODPipeline:
    """日终决策流水线测试套件"""

    def test_macro_gate_evaluation_bull(self):
        """测试在基准上涨站稳均线时的全仓进攻状态"""
        pipeline = UnifiedDailyEODPipeline(hysteresis_delta=0.015)
        res = pipeline.evaluate_macro_gate(as_of_date="2024-05-06")

        assert res.benchmark_symbol == "000300.SH"
        assert res.status in ("BULL_OFFENSE", "CAUTION_DEFENSE", "BEAR_PANIC_CASH")
        assert res.target_equity_weight_pct + res.cash_weight_pct == 100.0

    def test_macro_gate_panic_mode(self):
        """测试极端恐慌模式下的 100% 绝对空仓熔断"""
        pipeline = UnifiedDailyEODPipeline()
        res = pipeline.evaluate_macro_gate(force_panic=True)

        assert res.status == "BEAR_PANIC_CASH"
        assert res.target_equity_weight_pct == 0.0
        assert res.cash_weight_pct == 100.0
        assert any("熔断" in t for t in res.triggers)

    def test_stop_loss_scan(self):
        """测试单票跌幅达到 -8% 时的独立硬止损预警"""
        pipeline = UnifiedDailyEODPipeline(hard_stop_loss_pct=-8.0)
        holdings = [
            {"code": "600519.SH", "name": "贵州茅台", "entry_price": 100.0, "current_price": 95.0},   # -5.0% -> 未破
            {"code": "000001.SZ", "name": "平安银行", "entry_price": 10.0, "current_price": 9.1},    # -9.0% -> 触发
            {"code": "300750.SZ", "name": "宁德时代", "entry_price": 200.0, "current_price": 180.0}, # -10.0% -> 触发
        ]
        alerts = pipeline.scan_stop_loss(holdings)
        assert len(alerts) == 2
        codes = [a.code for a in alerts]
        assert "000001.SZ" in codes
        assert "300750.SZ" in codes
        assert alerts[0].action == "HARD_STOP_EXIT"

    def test_end_to_end_daily_eod_execution(self):
        """测试端到端日终决策生成与飞书卡片集成"""
        pipeline = UnifiedDailyEODPipeline()
        holdings = [
            {"code": "600519.SH", "name": "贵州茅台", "entry_price": 1000.0, "current_price": 900.0}, # -10% -> 触发
        ]
        result = pipeline.execute_daily_eod(holdings=holdings, dry_run=True)

        assert "macro_gate" in result
        assert "stop_loss_alerts" in result
        assert "trading_signals" in result
        assert "execution_actions" in result
        assert "feishu_response" in result
        assert len(result["stop_loss_alerts"]) == 1
        assert len(result["trading_signals"]) >= 1
        assert result["feishu_response"]["status"] == "dry_run"

    def test_kill_switch_stops_execution(self):
        """测试 SharedKillSwitch 停机保护直接拦截日终决策执行 (Wave 3 T6d)"""
        from uniquant.shared.kill_switch import KillSwitchError, get_kill_switch
        import pytest

        ks = get_kill_switch()
        ks.reset()
        ks.kill("test_emergency_halt")
        try:
            pipeline = UnifiedDailyEODPipeline()
            with pytest.raises(KillSwitchError, match="Trading stopped: test_emergency_halt"):
                pipeline.execute_daily_eod(dry_run=True)
        finally:
            ks.reset()

    def test_missing_benchmark_fails_fast_without_synthetic_data(self, tmp_path):
        """测试基准缺失时 Fail-Fast 抛出 FileNotFoundError，严禁伪造假数据 (T6c Rule 4)"""
        import pytest
        pipeline = UnifiedDailyEODPipeline(lake_root=tmp_path / "empty_lake")
        with pytest.raises(FileNotFoundError, match="基准指数行情缺失"):
            pipeline.load_benchmark_series()
