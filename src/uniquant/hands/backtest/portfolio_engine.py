"""
[DEPRECATED] 投资组合回测引擎 — 请使用 UnifiedBacktestEngine

此文件已被 unified_engine.py 中的 UnifiedBacktestEngine 替代。
新版引擎支持 List[TradingSignal] 强类型输入，实时现金扣减，T+1 铁律。
"""

import warnings
warnings.warn(
    "PortfolioEngine is deprecated. Use UnifiedBacktestEngine from "
    "uniquant.hands.backtest.unified_engine instead.",
    DeprecationWarning,
    stacklevel=2,
)

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ...shared.constants import BacktestConstants
from ...shared.cost_model import RISK_FREE_RATE, calculate_sharpe_ratio
from ...shared.logger_factory import get_logger
from ...data.managers.trade_calendar_manager import TradeCalendarManager
from .unified_matching_engine import UnifiedMatchingEngine

logger = get_logger(__name__)


@dataclass
class Position:
    symbol: str
    shares: int
    cost_basis: float
    entry_price: float
    entry_time: pd.Timestamp


class PortfolioEngine:
    def __init__(
        self,
        initial_capital: float = BacktestConstants.DEFAULT_INITIAL_CAPITAL,
        max_positions: int = 5,
        commission_rate: float = BacktestConstants.DEFAULT_COMMISSION_RATE,
        stamp_duty_rate: float = 0.0005,
        slippage_rate: float = BacktestConstants.DEFAULT_SLIPPAGE_RATE,
        min_commission: float = BacktestConstants.DEFAULT_MIN_COMMISSION,
        risk_free_rate: float = RISK_FREE_RATE,
        trade_calendar: Optional[TradeCalendarManager] = None,
    ):
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.risk_free_rate = risk_free_rate

        self.matching = UnifiedMatchingEngine(
            commission_rate=commission_rate,
            stamp_duty_rate=stamp_duty_rate,
            min_commission=min_commission,
            slippage_rate=slippage_rate,
            trade_calendar=trade_calendar,
        )

        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.equity_curve: List[float] = []
        self.daily_returns: List[float] = []
        self.trades: List[Dict[str, Any]] = []
        self._pending_signals: List[Dict] = []
        self._prev_equity = initial_capital

    def reset(self) -> None:
        self.cash = self.initial_capital
        self.positions.clear()
        self.equity_curve.clear()
        self.daily_returns.clear()
        self.trades.clear()
        self._pending_signals.clear()
        self._prev_equity = self.initial_capital

    @property
    def current_exposure(self) -> float:
        return sum(p.shares * p.cost_basis for p in self.positions.values())

    def current_equity(self, prices: Dict[str, float]) -> float:
        pv = sum(pos.shares * prices.get(pos.symbol, pos.cost_basis) for pos in self.positions.values())
        return self.cash + pv

    def can_open_new_position(self) -> bool:
        return len(self.positions) < self.max_positions

    def batch_open_positions(
        self,
        signals: Dict[str, float],
        prices: Dict[str, float],
        pre_closes: Dict[str, float],
        timestamps: pd.Timestamp,
        shares_per_trade: int = 0,
        volumes: Optional[Dict[str, float]] = None,
        avg_daily_volumes: Optional[Dict[str, float]] = None,
        sizing_fraction: float = 0.25,
        names: Optional[Dict[str, str]] = None,
        trading_days_listed: Optional[Dict[str, int]] = None,
    ) -> List[Position]:
        if not signals:
            return []

        buy_symbols = [s for s, sig in signals.items() if sig > 0 and s not in self.positions]
        if not buy_symbols:
            return []
        if len(self.positions) + len(buy_symbols) > self.max_positions:
            remaining = self.max_positions - len(self.positions)
            buy_symbols = buy_symbols[:remaining]

        n = len(buy_symbols)
        px_arr = np.array([prices.get(s, 0.0) for s in buy_symbols], dtype=np.float64)
        pc_arr = np.array([pre_closes.get(s, 0.0) for s in buy_symbols], dtype=np.float64)
        sym_arr = np.array(buy_symbols)
        ts_arr = np.full(n, timestamps)
        adv_arr = np.array([avg_daily_volumes.get(s, 0) if avg_daily_volumes else 0 for s in buy_symbols], dtype=np.float64)

        if shares_per_trade > 0:
            sh_arr = np.full(n, shares_per_trade, dtype=np.int64)
        else:
            alloc = self.cash * sizing_fraction / max(n, 1)
            sh_arr = np.maximum((alloc / np.maximum(px_arr, 1e-8)).astype(np.int64) // 100 * 100, 0)  # A股整手取整

        cash_arr = np.full(n, self.cash / max(n, 1), dtype=np.float64)

        fill_kwargs: Dict[str, np.ndarray] = {}
        if names is not None:
            fill_kwargs["names"] = np.array([names.get(s, "") for s in buy_symbols], dtype=object)
        if trading_days_listed is not None:
            fill_kwargs["trading_days_listed"] = np.array([trading_days_listed.get(s, 0) for s in buy_symbols], dtype=np.int64)
        fill = self.matching.fill_buy(px_arr, sh_arr, cash_arr, pc_arr, sym_arr, ts_arr, sh_arr, adv_arr, **fill_kwargs)

        created: List[Position] = []
        for i in range(n):
            if fill.rejected_mask[i]:
                continue
            pos = Position(
                symbol=buy_symbols[i],
                shares=int(fill.executed_shares[i]),
                cost_basis=float(fill.exec_prices[i]),
                entry_price=float(fill.exec_prices[i]),
                entry_time=timestamps,
            )
            self.positions[buy_symbols[i]] = pos
            cost = float(fill.exec_prices[i] * fill.executed_shares[i] + fill.commissions[i] + fill.transfer_fees[i])
            self.cash -= cost
            self.trades.append({
                "timestamp": timestamps, "symbol": buy_symbols[i], "action": "BUY",
                "price": float(fill.exec_prices[i]), "shares": int(fill.executed_shares[i]),
                "commission": float(fill.commissions[i]), "slippage": float(fill.slippages[i]),
            })
            created.append(pos)

        return created

    def batch_close_positions(
        self,
        signals: Dict[str, float],
        prices: Dict[str, float],
        pre_closes: Dict[str, float],
        timestamps: pd.Timestamp,
        volumes: Optional[Dict[str, float]] = None,
        avg_daily_volumes: Optional[Dict[str, float]] = None,
        names: Optional[Dict[str, str]] = None,
        trading_days_listed: Optional[Dict[str, int]] = None,
    ) -> int:
        if not signals:
            return 0

        sell_symbols = [s for s, sig in signals.items() if sig < 0 and s in self.positions]
        if not sell_symbols:
            return 0

        n = len(sell_symbols)
        px_arr = np.array([prices.get(s, 0.0) for s in sell_symbols], dtype=np.float64)
        pc_arr = np.array([pre_closes.get(s, 0.0) for s in sell_symbols], dtype=np.float64)
        sym_arr = np.array(sell_symbols)
        ts_arr = np.full(n, timestamps)
        pos_arr = np.array([self.positions[s].shares for s in sell_symbols], dtype=np.int64)
        pcost_arr = np.array([self.positions[s].cost_basis for s in sell_symbols], dtype=np.float64)
        bd_arr = np.array([self.positions[s].entry_time for s in sell_symbols], dtype=object)
        adv_arr = np.array([avg_daily_volumes.get(s, 0) if avg_daily_volumes else 0 for s in sell_symbols], dtype=np.float64)

        fill_kwargs: Dict[str, np.ndarray] = {}
        if names is not None:
            fill_kwargs["names"] = np.array([names.get(s, "") for s in sell_symbols], dtype=object)
        if trading_days_listed is not None:
            fill_kwargs["trading_days_listed"] = np.array([trading_days_listed.get(s, 0) for s in sell_symbols], dtype=np.int64)
        fill = self.matching.fill_sell(
            px_arr, pos_arr, pos_arr, pcost_arr, pc_arr, sym_arr, ts_arr, bd_arr, pos_arr, adv_arr,
            **fill_kwargs,
        )

        closed = 0
        for i in range(n):
            if fill.rejected_mask[i] or fill.executed_shares[i] <= 0:
                continue
            sym = sell_symbols[i]
            pos = self.positions.pop(sym)
            net_value = float(fill.exec_prices[i] * fill.executed_shares[i] - fill.commissions[i] - fill.stamp_duties[i] - fill.transfer_fees[i])
            cost = pos.cost_basis * int(fill.executed_shares[i])
            pnl = net_value - cost
            self.cash += net_value
            self.trades.append({
                "timestamp": timestamps, "symbol": sym, "action": "SELL",
                "price": float(fill.exec_prices[i]), "shares": int(fill.executed_shares[i]),
                "commission": float(fill.commissions[i]), "stamp_duty": float(fill.stamp_duties[i]),
                "slippage": float(fill.slippages[i]), "pnl": pnl, "pnl_pct": pnl / cost if cost > 0 else 0.0,
            })
            closed += 1

        return closed

    def update_equity(self, prices: Dict[str, float]) -> float:
        equity = self.current_equity(prices)
        self.equity_curve.append(equity)
        dr = (equity - self._prev_equity) / max(self._prev_equity, 1e-8)
        self.daily_returns.append(dr)
        self._prev_equity = equity
        return equity

    def run(
        self,
        signals: pd.DataFrame,
        price_data: pd.DataFrame,
        pre_close_data: pd.DataFrame,
        volume_data: Optional[pd.DataFrame] = None,
        avg_daily_volume_data: Optional[pd.DataFrame] = None,
        symbol_column: str = "symbol",
        signal_column: str = "signal",
        date_column: str = "date",
        shares_per_trade: int = 0,
        sizing_fraction: float = 0.25,
        name_data: Optional[Dict[str, str]] = None,
        trading_days_listed_data: Optional[Dict[str, int]] = None,
    ) -> pd.DataFrame:
        self.reset()

        required = {symbol_column, signal_column, date_column}
        if required - set(signals.columns):
            return pd.DataFrame()

        signals = signals.copy().sort_values(date_column)
        unique_dates = signals[date_column].unique()
        n_dates = len(unique_dates)

        eq_arr = np.empty(n_dates, dtype=np.float64)
        ret_arr = np.empty(n_dates, dtype=np.float64)

        def _build_price_data(date, symbols):
            px: Dict[str, float] = {}
            pc: Dict[str, float] = {}
            vol: Dict[str, float] = {}
            adv: Dict[str, float] = {}
            for sym in symbols:
                try:
                    if isinstance(price_data.index, pd.DatetimeIndex):
                        p = float(price_data.loc[date, sym])
                        pc_val = float(pre_close_data.loc[date, sym])
                    else:
                        index_type = type(price_data.index).__name__
                        raise TypeError(f"price_data must have a DatetimeIndex, got {index_type}")
                    px[sym] = p
                    pc[sym] = pc_val
                    if volume_data is not None and isinstance(volume_data.index, pd.DatetimeIndex):
                        try:
                            adv[sym] = float(avg_daily_volume_data.loc[date, sym]) if avg_daily_volume_data is not None else 0.0
                        except (KeyError, IndexError, TypeError):
                            logger.exception("获取日均成交量失败，跳过")
                            pass
                except (KeyError, IndexError, TypeError):
                    logger.exception("处理价格/成交量数据失败，跳过")
                    pass
            return px, pc, vol, adv

        for t, date in enumerate(unique_dates):
            day_signals = signals[signals[date_column] == date]

            signal_symbols = set(day_signals[symbol_column].unique())
            pending_symbols = {s["symbol"] for s in self._pending_signals}
            all_symbols = signal_symbols | pending_symbols

            day_px, day_pc, day_vol, day_adv = _build_price_data(date, all_symbols)

            if self._pending_signals:
                pending_buys = {s["symbol"]: 1.0 for s in self._pending_signals if s["action"] == "BUY"}
                pending_sells = {s["symbol"]: -1.0 for s in self._pending_signals if s["action"] == "SELL"}
                if pending_sells:
                    self.batch_close_positions(pending_sells, day_px, day_pc, date, day_vol, day_adv,
                                               names=name_data, trading_days_listed=trading_days_listed_data)
                if pending_buys:
                    self.batch_open_positions(pending_buys, day_px, day_pc, date,
                                              shares_per_trade=shares_per_trade,
                                              volumes=day_vol, avg_daily_volumes=day_adv,
                                              sizing_fraction=sizing_fraction,
                                              names=name_data, trading_days_listed=trading_days_listed_data)
                self._pending_signals.clear()

            active = day_signals.loc[day_signals[signal_column] != 0, [symbol_column, signal_column]]
            for sym, sig in active.itertuples(index=False, name=None):
                self._pending_signals.append({
                    "symbol": sym,
                    "action": "BUY" if sig > 0 else "SELL",
                    "shares": abs(int(sig)),
                    "signal_day_index": t,
                })

            if not day_px:
                eq_arr[t] = self.cash
                ret_arr[t] = 0.0
                continue

            if self.positions:
                all_px = dict(day_px)
                for sym in self.positions:
                    if sym not in all_px:
                        all_px[sym] = self.positions[sym].cost_basis
                eq = self.update_equity(all_px)
            else:
                eq = self.cash
                self.equity_curve.append(eq)
                dr = (eq - self._prev_equity) / max(self._prev_equity, 1e-8)
                self.daily_returns.append(dr)
                self._prev_equity = eq

            eq_arr[t] = self.equity_curve[-1]
            ret_arr[t] = self.daily_returns[-1]

        return pd.DataFrame({"equity": eq_arr, "daily_return": ret_arr}, index=unique_dates)

    def calculate_metrics(self, equity_curve: pd.Series) -> Dict[str, Any]:
        if equity_curve.empty or len(equity_curve) < 2:
            return {"total_return": 0.0, "annualized_return": 0.0, "volatility": 0.0,
                    "sharpe_ratio": 0.0, "max_drawdown": 0.0, "calmar_ratio": 0.0,
                    "win_rate": 0.0, "profit_factor": 0.0, "total_trades": 0}

        initial = equity_curve.iloc[0]
        final = equity_curve.iloc[-1]
        total_return = (final - initial) / max(initial, 1e-8)
        daily_ret = equity_curve.pct_change().dropna()
        n_days = max(len(daily_ret), 1)
        annualized_return = (1 + total_return) ** (252 / n_days) - 1
        volatility = float(daily_ret.std() * np.sqrt(252)) if len(daily_ret) > 0 else 0.0
        sharpe = calculate_sharpe_ratio(daily_ret.tolist(), self.risk_free_rate)

        rolling_max = equity_curve.expanding().max()
        drawdown = (equity_curve - rolling_max) / rolling_max
        max_dd = drawdown.min()
        calmar = abs(total_return / max_dd) if max_dd < 0 else 0.0

        closed = [t for t in self.trades if t.get("pnl") is not None]
        total_trades = len(closed)
        win_rate = profit_factor = 0.0
        if total_trades > 0:
            wins = [t["pnl"] for t in closed if t["pnl"] > 0]
            losses = [t["pnl"] for t in closed if t["pnl"] < 0]
            win_rate = len(wins) / total_trades
            gp = sum(wins) if wins else 0
            gl = abs(sum(losses)) if losses else 0
            profit_factor = gp / gl if gl > 0 else (float("inf") if gp > 0 else 0)

        return {
            "total_return": total_return, "annualized_return": annualized_return,
            "volatility": volatility, "sharpe_ratio": sharpe,
            "max_drawdown": max_dd, "calmar_ratio": calmar,
            "win_rate": win_rate, "profit_factor": profit_factor, "total_trades": total_trades,
        }
