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
from ...shared.cost_model import TRANSFER_FEE_PCT, get_stamp_tax_pct
from ...shared.limit_checker import get_board_type
from ...shared.market_rules import get_board_rule
from ...shared.slippage_model import SlippageModel
from ...data.managers.trade_calendar_manager import TradeCalendarManager


@dataclass
class FillResult:
    executed_shares: np.ndarray
    exec_prices: np.ndarray
    commissions: np.ndarray
    stamp_duties: np.ndarray
    slippages: np.ndarray
    transfer_fees: np.ndarray
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
        slippage_model: Optional[SlippageModel] = None,
    ):
        assert 0 < commission_rate < 1
        assert 0 <= stamp_duty_rate < 1
        assert min_commission >= 0
        assert 0 <= slippage_rate < 1

        self.commission_rate = commission_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.min_commission = min_commission
        self.slippage_rate = slippage_rate
        self.slippage_model = slippage_model
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
        symbols: np.ndarray | None = None,
        quantities: np.ndarray | None = None,
        timestamps: np.ndarray | None = None,
    ) -> np.ndarray:
        vol_ratios = np.where(
            (avg_daily_volumes > 0) & (volumes > 0),
            np.minimum(volumes / np.maximum(avg_daily_volumes, 1e-8), 1.0),
            0.0,
        )
        impact = np.minimum(0.001 * np.sqrt(vol_ratios), 0.02)

        if self.slippage_model is not None and symbols is not None and quantities is not None and timestamps is not None:
            direction_str = "buy" if is_buy else "sell"
            model_rates = np.array([
                self.slippage_model.estimate(
                    symbol=s,
                    quantity=int(q),
                    direction=direction_str,
                    price=float(p),
                    timestamp=pd.Timestamp(t),
                )
                for s, q, p, t in zip(symbols, quantities, prices, timestamps)
            ])
            total_slip = model_rates + impact
        else:
            total_slip = self.slippage_rate + impact

        direction = 1.0 if is_buy else -1.0
        return prices * (1.0 + direction * total_slip)

    def compute_limit_status_vectorized(
        self,
        prices: np.ndarray,
        pre_closes: np.ndarray,
        symbols: np.ndarray,
        names: np.ndarray | None = None,
        trading_days_listed: np.ndarray | None = None,
    ) -> Dict[str, np.ndarray]:
        n = len(prices)
        is_limit_up = np.zeros(n, dtype=bool)
        is_limit_down = np.zeros(n, dtype=bool)
        valid = pre_closes > 0
        price_ratios = np.where(valid, prices / np.maximum(pre_closes, 1e-8), 1.0)
        tol = MarketConstants.PRICE_TOLERANCE

        # Fast path: no names or trading_days_listed — fully vectorized
        if names is None and trading_days_listed is None:
            # 预计算所有 symbol 的 board_type，避免 5n 次重复调用
            board_types = np.array([get_board_type(s) for s in symbols])
            for board_type, (up_r, down_r) in MarketConstants.LIMIT_RATIO.items():
                board_mask = board_types == board_type
                mask = board_mask & valid
                is_limit_up |= mask & (price_ratios >= up_r - tol)
                is_limit_down |= mask & (price_ratios <= down_r + tol)
            return {"is_limit_up": is_limit_up, "is_limit_down": is_limit_down}

        # Slow path: element-wise for ST name detection and/or IPO special rules
        for i in range(n):
            if not valid[i]:
                continue

            # Board type with ST name detection
            bt = get_board_type(symbols[i])
            if names is not None and names[i]:
                nu = names[i].upper()
                if any(nu.startswith(p) for p in ("ST", "*ST", "S*ST")):
                    bt = "st"
            pr = price_ratios[i]

            # IPO special rules
            if trading_days_listed is not None and trading_days_listed[i] > 0:
                tdl = int(trading_days_listed[i])
                if bt == "main" and tdl == 1:
                    if pr >= 1.44 - tol:
                        is_limit_up[i] = True
                    if pr <= 0.64 + tol:
                        is_limit_down[i] = True
                    continue
                if bt in ("sci_tech", "gem") and tdl <= 5:
                    continue
                if bt == "beijing" and tdl == 1:
                    continue

            up_r, down_r = MarketConstants.LIMIT_RATIO.get(bt, MarketConstants.LIMIT_RATIO["main"])
            if pr >= up_r - tol:
                is_limit_up[i] = True
            if pr <= down_r + tol:
                is_limit_down[i] = True

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
        names: np.ndarray | None = None,
        trading_days_listed: np.ndarray | None = None,
    ) -> FillResult:
        n = len(prices)
        assert len(shares_requested) == n and len(cash_available) == n

        limit_status = self.compute_limit_status_vectorized(prices, pre_closes, symbols, names, trading_days_listed)
        limit_rejected = limit_status["is_limit_up"]
        volume_zero = np.array([vol <= 0 for vol in volumes], dtype=bool)

        exec_prices = self.compute_execution_prices(prices, volumes, avg_daily_volumes, is_buy=True, symbols=symbols, quantities=shares_requested, timestamps=timestamps)

        values = exec_prices * shares_requested
        commissions = np.maximum(values * self.commission_rate, self.min_commission)
        sh_mask = np.array([s.startswith("60") for s in symbols], dtype=bool)  # 向量化版。标量版在 cost_model.py:48
        transfer_fees = np.where(sh_mask, values * TRANSFER_FEE_PCT, 0.0)  # 过户费(仅沪市)
        total_costs = values + commissions + transfer_fees

        cash_shortfall = total_costs > cash_available
        lot_sizes = np.array([get_board_rule(s).lot_size for s in symbols], dtype=np.int64)
        shares_adj = np.where(
            ~cash_shortfall,
            shares_requested,
            np.where(
                cash_available > commissions + transfer_fees,
                ((cash_available - commissions - transfer_fees) / np.maximum(exec_prices, 1e-8)).astype(np.int64) // lot_sizes * lot_sizes,
                0,
            ),
        )
        shares_adj = np.maximum(shares_adj, 0)
        shares_adj = np.where(limit_rejected, 0, shares_adj)

        values = exec_prices * shares_adj
        commissions = np.maximum(values * self.commission_rate, self.min_commission)
        transfer_fees = np.where(sh_mask, values * TRANSFER_FEE_PCT, 0.0)
        total_costs = values + commissions + transfer_fees

        rejected_mask = limit_rejected | volume_zero | (shares_adj <= 0)
        shares_adj = np.where(rejected_mask, 0, shares_adj)
        return FillResult(
            executed_shares=shares_adj,
            exec_prices=exec_prices,
            commissions=np.where(rejected_mask, 0, commissions),
            stamp_duties=np.zeros(n),
            slippages=np.where(rejected_mask, 0, exec_prices - prices),
            transfer_fees=np.where(rejected_mask, 0, transfer_fees),
            rejected_mask=rejected_mask,
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
        names: np.ndarray | None = None,
        trading_days_listed: np.ndarray | None = None,
    ) -> FillResult:
        n = len(prices)
        assert len(shares_requested) == n and len(positions_held) == n

        limit_status = self.compute_limit_status_vectorized(prices, pre_closes, symbols, names, trading_days_listed)
        limit_rejected = limit_status["is_limit_down"]
        volume_zero = np.array([vol <= 0 for vol in volumes], dtype=bool)

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
        _ = position_costs  # acknowledged unused — PnL tracked at engine level
        exec_prices = self.compute_execution_prices(prices, volumes, avg_daily_volumes, is_buy=False, symbols=symbols, quantities=shares_requested, timestamps=timestamps)

        values = exec_prices * shares_clamped
        commissions = np.maximum(values * self.commission_rate, self.min_commission)
        # 印花税向量化：预计算日期→税率映射，用 NumPy 索引替代 Python 循环
        stamp_dates = pd.to_datetime(timestamps)
        unique_dates = {d.date() for d in stamp_dates}
        date_to_rate = {d: get_stamp_tax_pct(d) for d in unique_dates}
        rates = np.array([date_to_rate[d.date()] for d in stamp_dates])
        stamp_duties = values * rates
        sh_mask = np.array([s.startswith("60") for s in symbols], dtype=bool)  # 向量化版。标量版在 cost_model.py:48
        transfer_fees = np.where(sh_mask, values * TRANSFER_FEE_PCT, 0.0)  # 过户费(仅沪市)

        rejected = limit_rejected | volume_zero | t1_violation | (shares_clamped <= 0)

        return FillResult(
            executed_shares=np.where(rejected, 0, shares_clamped),
            exec_prices=exec_prices,
            commissions=np.where(rejected, 0, commissions),
            stamp_duties=np.where(rejected, 0, stamp_duties),
            slippages=np.where(rejected, 0, prices - exec_prices),
            transfer_fees=np.where(rejected, 0, transfer_fees),
            rejected_mask=rejected,
            t1_violation_mask=t1_violation,
            limit_violation_mask=limit_rejected,
            cash_shortfall_mask=np.zeros(n, dtype=bool),
        )
