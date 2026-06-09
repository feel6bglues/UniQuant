"""
测试 UnifiedMatchingEngine.fill_sell T+1 约束边界条件

核心目标：
1. 验证交易日历查询失败时保守拒绝而非宽松放行
2. 验证节假日场景（周五买、周一卖）正确放行
3. 验证正常交易日场景（周一买、周二卖）正确放行
"""

from datetime import datetime

import pandas as pd
import numpy as np

from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine


class FakeTradeCalendarManager:
    """模拟交易日历，用于精确控制边界条件"""

    def __init__(self, trading_days=None):
        self._trading_days = trading_days or []

    def get_trade_calendar(self, start_date, end_date):
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        days = [d for d in self._trading_days if start <= d <= end]
        return pd.DataFrame({"trade_date": days})

    def is_trading_day(self, date):
        return date in self._trading_days


class TestT1ConstraintBoundary:
    """T+1 约束边界条件测试"""

    def _make_engine(self, trading_days):
        return UnifiedMatchingEngine(
            trade_calendar=FakeTradeCalendarManager(trading_days),
        )

    def _make_fill_sell(self, engine, price=10.0, shares=100, position=100,
                        position_cost=9.0, pre_close=10.0, symbol="000001.SZ",
                        timestamp="2024-01-02", buy_date=None,
                        volume=1000.0, adv=10000.0):
        return engine.fill_sell(
            np.array([price]), np.array([shares]), np.array([position]),
            np.array([position_cost]), np.array([pre_close]), np.array([symbol]),
            np.array([pd.Timestamp(timestamp)]), np.array([pd.Timestamp(buy_date)]),
            np.array([volume]), np.array([adv]),
        )

    # ------------------------------------------------------------------ #
    #  测试 1：正常 T+1 — 周一买、周二卖 → 应允许
    # ------------------------------------------------------------------ #
    def test_t1_normal_allow(self):
        """周一买入，周二卖出（间隔 1 个交易日），应允许。"""
        trading_days = [
            datetime(2024, 1, 15),  # 周一
            datetime(2024, 1, 16),  # 周二
            datetime(2024, 1, 17),  # 周三
        ]
        engine = self._make_engine(trading_days)
        fill = self._make_fill_sell(
            engine,
            timestamp="2024-01-16",
            buy_date="2024-01-15",
        )
        assert not fill.rejected_mask[0], "T+1 should be allowed"

    # ------------------------------------------------------------------ #
    #  测试 2：T+0 — 同一天买卖 → 应拒绝
    # ------------------------------------------------------------------ #
    def test_t0_reject(self):
        """同一天买入并卖出，应拒绝。"""
        trading_days = [
            datetime(2024, 1, 15),
            datetime(2024, 1, 16),
        ]
        engine = self._make_engine(trading_days)
        fill = self._make_fill_sell(
            engine,
            timestamp="2024-01-15",
            buy_date="2024-01-15",
        )
        assert fill.rejected_mask[0], "T+0 sell on same day should be rejected"
        assert fill.t1_violation_mask[0], "Should be T+1 violation"

    # ------------------------------------------------------------------ #
    #  测试 3：节假日场景 — 周五买、周一卖 → 应允许
    # ------------------------------------------------------------------ #
    def test_weekend_t1_allow(self):
        """周五买入，下周一卖出（间隔 1 个交易日），应允许。"""
        trading_days = [
            datetime(2024, 1, 12),  # 周五
            datetime(2024, 1, 15),  # 周一（跳过周末）
        ]
        engine = self._make_engine(trading_days)
        fill = self._make_fill_sell(
            engine,
            timestamp="2024-01-15",
            buy_date="2024-01-12",
        )
        assert not fill.rejected_mask[0], "Weekend T+1 should be allowed"

    # ------------------------------------------------------------------ #
    #  测试 4：buy_date 不在交易日历中 → 应保守拒绝
    # ------------------------------------------------------------------ #
    def test_buy_date_not_in_calendar_reject(self):
        """买入日期不在交易日历中，应保守拒绝。"""
        trading_days = [
            datetime(2024, 1, 15),  # 周一
            datetime(2024, 1, 16),  # 周二
        ]
        engine = self._make_engine(trading_days)
        # 买入日期是周日（不在日历中），卖出是周一
        fill = self._make_fill_sell(
            engine,
            timestamp="2024-01-15",
            buy_date="2024-01-14",
        )
        assert fill.rejected_mask[0], "buy_date not in calendar should be rejected"

    # ------------------------------------------------------------------ #
    #  测试 5：current_date 不在交易日历中 → 应拒绝
    # ------------------------------------------------------------------ #
    def test_current_date_not_in_calendar_reject(self):
        """当前日期不在交易日历中，应拒绝。"""
        trading_days = [
            datetime(2024, 1, 15),
            datetime(2024, 1, 16),
        ]
        engine = self._make_engine(trading_days)
        fill = self._make_fill_sell(
            engine,
            timestamp="2024-01-20",
            buy_date="2024-01-15",
        )
        assert fill.rejected_mask[0], "current_date not in calendar should be rejected"

    # ------------------------------------------------------------------ #
    #  测试 6：交易日历为空 → 应保守拒绝
    # ------------------------------------------------------------------ #
    def test_empty_calendar_reject(self):
        """交易日历为空时，应保守拒绝。"""
        engine = self._make_engine([])
        fill = self._make_fill_sell(
            engine,
            timestamp="2024-01-16",
            buy_date="2024-01-15",
        )
        assert fill.rejected_mask[0], "empty calendar should reject"

    # ------------------------------------------------------------------ #
    #  测试 7：buy_date 为 None → 应允许（无持仓）
    # ------------------------------------------------------------------ #
    def test_none_buy_date_allow(self):
        """buy_date 为 None 表示无持仓，应允许。"""
        engine = self._make_engine([datetime(2024, 1, 15)])
        fill = engine.fill_sell(
            np.array([10.0]), np.array([100]), np.array([100]),
            np.array([9.0]), np.array([10.0]), np.array(["000001.SZ"]),
            np.array([pd.Timestamp("2024-01-15")]), np.array([None]),
            np.array([1000.0]), np.array([10000.0]),
        )
        assert not fill.rejected_mask[0], "None buy_date should be allowed (no position)"

    # ------------------------------------------------------------------ #
    #  测试 8：current_date 不是交易日 → 应拒绝
    # ------------------------------------------------------------------ #
    def test_current_not_trading_day_reject(self):
        """当前日期不是交易日，应直接拒绝。"""
        trading_days = [
            datetime(2024, 1, 15),
            datetime(2024, 1, 16),
        ]
        engine = self._make_engine(trading_days)
        fill = self._make_fill_sell(
            engine,
            timestamp="2024-01-20",
            buy_date="2024-01-15",
        )
        assert fill.rejected_mask[0], "non-trading day should be rejected"

    # ------------------------------------------------------------------ #
    #  测试 9：节假日 — 周四买、周一卖 → 应允许
    # ------------------------------------------------------------------ #
    def test_holiday_t1_allow(self):
        """
        周四买入，下周一卖出（跳过周五节假日+周末），
        间隔 1 个交易日，应允许。
        """
        trading_days = [
            datetime(2024, 1, 11),  # 周四
            datetime(2024, 1, 15),  # 周一（跳过周五节假日+周末）
        ]
        engine = self._make_engine(trading_days)
        fill = self._make_fill_sell(
            engine,
            timestamp="2024-01-15",
            buy_date="2024-01-11",
        )
        assert not fill.rejected_mask[0], "Holiday T+1 should be allowed"

    # ------------------------------------------------------------------ #
    #  测试 10：T+2 — 周一买、周三卖 → 应允许
    # ------------------------------------------------------------------ #
    def test_t2_allow(self):
        """周一买入，周三卖出（间隔 2 个交易日），应允许。"""
        trading_days = [
            datetime(2024, 1, 15),  # 周一
            datetime(2024, 1, 16),  # 周二
            datetime(2024, 1, 17),  # 周三
        ]
        engine = self._make_engine(trading_days)
        fill = self._make_fill_sell(
            engine,
            timestamp="2024-01-17",
            buy_date="2024-01-15",
        )
        assert not fill.rejected_mask[0], "T+2 should be allowed"
