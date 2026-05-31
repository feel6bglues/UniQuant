"""
统一向量化撮合引擎
所有执行约束（T+1、涨跌停、印花税、最低佣金、非线性滑点）
强制用于 BacktestEngine 和 PortfolioEngine
"""

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd

from ...shared.constants import BacktestConstants, MarketConstants
from ...shared.cost_model import TRANSFER_FEE_PCT
from ...shared.limit_checker import get_board_type
from ...shared.market_rules import get_board_rule
from ...data.managers.trade_calendar_manager import TradeCalendarManager


@dataclass
class FillResult:
    executed_shares: np.ndarray
    exec_prices: np.ndarray
    commissions: np.ndarray
    stamp_duties: np.ndarray
    slippages: np.ndarray
    rejected_mask: np.ndarray
    t1_violation_mask: np.ndarray
    limit_violation_mask: np.ndarray
    cash_shortfall_mask: np.ndarray


class UnifiedMatchingEngine:
    def __init__(
        self,
        commission_rate: float = BacktestConstants.DEFAULT_COMMISSION_RATE,
        stamp_duty_rate: float = 0.0005,
        min_commission: float = BacktestConstants.DEFAULT_MIN_COMMISSION,
        slippage_rate: float = BacktestConstants.DEFAULT_SLIPPAGE_RATE,
        trade_calendar: Optional[TradeCalendarManager] = None,
    ):
        assert 0 < commission_rate < 1
        assert 0 <= stamp_duty_rate < 1
        assert min_commission >= 0
        assert 0 <= slippage_rate < 1

        self.commission_rate = commission_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.min_commission = min_commission
        self.slippage_rate = slippage_rate
        self.trade_calendar = trade_calendar or TradeCalendarManager()

    def _next_trading_day(self, date: pd.Timestamp) -> pd.Timestamp:
        d = date + pd.Timedelta(days=1)
        for _ in range(10):
            if self.trade_calendar.is_trading_day(d):
                return d
            d += pd.Timedelta(days=1)
        return d

    def compute_execution_prices(
        self,
        prices: np.ndarray,
        volumes: np.ndarray,
        avg_daily_volumes: np.ndarray,
        is_buy: bool,
    ) -> np.ndarray:
        vol_ratios = np.where(
            (avg_daily_volumes > 0) & (volumes > 0),
            np.minimum(volumes / np.maximum(avg_daily_volumes, 1e-8), 1.0),
            0.0,
        )
        impact = np.minimum(0.001 * np.sqrt(vol_ratios), 0.02)
        total_slip = self.slippage_rate + impact
        direction = 1.0 if is_buy else -1.0
        return prices * (1.0 + direction * total_slip)

    def compute_limit_status_vectorized(
        self,
        prices: np.ndarray,
        pre_closes: np.ndarray,
        symbols: np.ndarray,
    ) -> Dict[str, np.ndarray]:
        n = len(prices)
        is_limit_up = np.zeros(n, dtype=bool)
        is_limit_down = np.zeros(n, dtype=bool)
        valid = pre_closes > 0
        price_ratios = np.where(valid, prices / np.maximum(pre_closes, 1e-8), 1.0)

        for board_type, (up_r, down_r) in MarketConstants.LIMIT_RATIO.items():
            board_mask = np.array([get_board_type(s) == board_type for s in symbols])
            mask = board_mask & valid
            tol = MarketConstants.PRICE_TOLERANCE
            is_limit_up |= mask & (price_ratios >= up_r - tol)
            is_limit_down |= mask & (price_ratios <= down_r + tol)

        return {"is_limit_up": is_limit_up, "is_limit_down": is_limit_down}

    def fill_buy(
        self,
        prices: np.ndarray,
        shares_requested: np.ndarray,
        cash_available: np.ndarray,
        pre_closes: np.ndarray,
        symbols: np.ndarray,
        timestamps: np.ndarray,
        volumes: np.ndarray,
        avg_daily_volumes: np.ndarray,
    ) -> FillResult:
        n = len(prices)
        assert len(shares_requested) == n and len(cash_available) == n

        limit_status = self.compute_limit_status_vectorized(prices, pre_closes, symbols)
        limit_rejected = limit_status["is_limit_up"]

        exec_prices = self.compute_execution_prices(prices, volumes, avg_daily_volumes, is_buy=True)

        values = exec_prices * shares_requested
        commissions = np.maximum(values * self.commission_rate, self.min_commission)
        transfer_fees = values * TRANSFER_FEE_PCT  # 过户费
        total_costs = values + commissions + transfer_fees

        cash_shortfall = total_costs > cash_available
        lot_sizes = np.array([get_board_rule(s).lot_size for s in symbols], dtype=np.int64)
        shares_adj = np.where(
            cash_shortfall & (cash_available > commissions + transfer_fees),
            ((cash_available - commissions - transfer_fees) / np.maximum(exec_prices, 1e-8)).astype(np.int64) // lot_sizes * lot_sizes,
            shares_requested,
        )
        shares_adj = np.maximum(shares_adj, 0)

        values = exec_prices * shares_adj
        commissions = np.maximum(values * self.commission_rate, self.min_commission)
        transfer_fees = values * TRANSFER_FEE_PCT
        total_costs = values + commissions + transfer_fees

        return FillResult(
            executed_shares=shares_adj,
            exec_prices=exec_prices,
            commissions=commissions,
            stamp_duties=np.zeros(n),
            slippages=exec_prices - prices,
            rejected_mask=limit_rejected | (shares_adj <= 0),
            t1_violation_mask=np.zeros(n, dtype=bool),
            limit_violation_mask=limit_rejected,
            cash_shortfall_mask=cash_shortfall,
        )

    def fill_sell(
        self,
        prices: np.ndarray,
        shares_requested: np.ndarray,
        positions_held: np.ndarray,
        position_costs: np.ndarray,
        pre_closes: np.ndarray,
        symbols: np.ndarray,
        timestamps: np.ndarray,
        buy_dates: np.ndarray,
        volumes: np.ndarray,
        avg_daily_volumes: np.ndarray,
    ) -> FillResult:
        n = len(prices)
        assert len(shares_requested) == n and len(positions_held) == n

        limit_status = self.compute_limit_status_vectorized(prices, pre_closes, symbols)
        limit_rejected = limit_status["is_limit_down"]

        t1_violation = np.zeros(n, dtype=bool)
        for i in range(n):
            if buy_dates[i] is None:
                continue
            b_ts = pd.Timestamp(buy_dates[i])
            c_ts = pd.Timestamp(timestamps[i])
            b_td = self.trade_calendar.is_trading_day(b_ts)
            c_td = self.trade_calendar.is_trading_day(c_ts)
            if not b_td or not c_td:
                t1_violation[i] = True
            elif c_ts.toordinal() <= b_ts.toordinal():
                t1_violation[i] = True
            else:
                next_td = self._next_trading_day(b_ts)
                if c_ts.toordinal() < next_td.toordinal():
                    t1_violation[i] = True

        shares_clamped = np.minimum(shares_requested, positions_held)
        exec_prices = self.compute_execution_prices(prices, volumes, avg_daily_volumes, is_buy=False)

        values = exec_prices * shares_clamped
        commissions = np.maximum(values * self.commission_rate, self.min_commission)
        stamp_duties = values * self.stamp_duty_rate
        transfer_fees = values * TRANSFER_FEE_PCT  # 过户费
        net_values = values - commissions - stamp_duties - transfer_fees
        cost_bases = position_costs * shares_clamped

        rejected = limit_rejected | t1_violation | (shares_clamped <= 0)

        return FillResult(
            executed_shares=np.where(rejected, 0, shares_clamped),
            exec_prices=exec_prices,
            commissions=commissions,
            stamp_duties=stamp_duties,
            slippages=prices - exec_prices,
            rejected_mask=rejected,
            t1_violation_mask=t1_violation,
            limit_violation_mask=limit_rejected,
            cash_shortfall_mask=np.zeros(n, dtype=bool),
        )
