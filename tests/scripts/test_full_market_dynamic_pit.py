#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Full Market Dynamic PIT Backtest Runner
"""

import pytest
import pandas as pd

from scripts.backtest.run_full_market_dynamic_pit import FullMarketDynamicPITBacktest


@pytest.mark.requires_lake
class TestFullMarketDynamicPITBacktest:
    """验证全市场动态点在时回测引擎"""

    def test_rebalance_schedule_construction(self):
        """验证每年 5 月首个交易日调仓调度构建"""
        engine = FullMarketDynamicPITBacktest(start_year=2022, end_year=2024)
        schedule = engine.build_rebalance_schedule()
        assert len(schedule) == 3
        assert schedule[0]["rebalance_year"] == 2022
        assert schedule[0]["fiscal_year"] == 2021
        assert schedule[0]["d0"] == "2022-05-05"
        assert schedule[2]["d0"] == "2024-05-06"

    def test_short_horizon_execution(self):
        """验证 2023-2024 短周期执行，确保指标完整生成且无异常"""
        engine = FullMarketDynamicPITBacktest(start_year=2023, end_year=2024, top_n=20)
        df_annual, df_summary = engine.run_backtest()

        assert isinstance(df_annual, pd.DataFrame)
        assert len(df_annual) == 2
        assert "r_s6_ex_net_pct" in df_annual.columns
        assert "eligible_candidates" in df_annual.columns

        # 断言全市场合规标的大于 4,000 只
        assert df_annual["eligible_candidates"].iloc[-1] > 4000

        # 断言单步时延在 200ms 以内
        assert (df_annual["step_latency_ms"] < 200.0).all()

        assert isinstance(df_summary, pd.DataFrame)
        assert len(df_summary) == 5
        assert "cagr_pct" in df_summary.columns
