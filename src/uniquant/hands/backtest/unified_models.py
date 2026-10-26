"""
Unified Backtest Data Structures, Models and Helper Routines.
=============================================================

Defines the core data contracts (TradeRecord, BacktestResult) and pure calculation
routines (commissions, slippage, limits, T+1 checks) for UnifiedBacktestEngine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import math
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from ...shared.constants import MarketConstants
from ...shared.cost_model import (
    TRANSFER_FEE_PCT,
    _has_transfer_fee,
    calculate_sharpe_ratio,
    get_stamp_tax_pct,
)
from ...shared.limit_checker import get_board_type


# ══════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    """成交记录"""
    timestamp: datetime.datetime
    action: str  # "BUY" | "SELL"
    symbol: str
    price: float
    shares: int
    commission: float
    stamp_duty: float = 0.0
    transfer_fee: float = 0.0
    slippage: float = 0.0
    pnl: float = 0.0
    reason: str = ""


@dataclass
class BacktestResult:
    """回测结果"""
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)
    initial_capital: float = 0.0
    final_cash: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    benchmark_return: float = 0.0

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def total_return(self) -> float:
        if not self.equity_curve or self.initial_capital <= 0:
            return 0.0
        return (self.equity_curve[-1] - self.initial_capital) / self.initial_capital

    @property
    def sharpe(self) -> float:
        if len(self.daily_returns) < 2:
            return 0.0
        return calculate_sharpe_ratio(self.daily_returns, period_days=1)

    @property
    def sharpe_ratio(self) -> float:
        return self.sharpe

    @property
    def annualized_return(self) -> float:
        if not self.equity_curve or self.initial_capital <= 0 or len(self.daily_returns) == 0:
            return 0.0
        n_days = len(self.daily_returns)
        tr = (self.equity_curve[-1] - self.initial_capital) / self.initial_capital
        if tr <= -1.0:
            return -1.0
        return float((1.0 + tr) ** (252.0 / max(1, n_days)) - 1.0)

    @property
    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        ec = np.array(self.equity_curve, dtype=np.float64)
        rolling_max = np.maximum.accumulate(ec)
        dd = (rolling_max - ec) / np.maximum(rolling_max, 1e-10)
        return float(np.max(dd))

    @property
    def win_rate(self) -> float:
        closed = [t for t in self.trades if t.action == "SELL"]
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t.pnl > 0)
        return wins / len(closed)

    @property
    def profit_factor(self) -> float:
        closed = [t for t in self.trades if t.action == "SELL"]
        if not closed:
            return 0.0
        total_profit = sum(t.pnl for t in closed if t.pnl > 0)
        total_loss = abs(sum(t.pnl for t in closed if t.pnl < 0))
        if total_loss == 0:
            return float("inf") if total_profit > 0 else 0.0
        return total_profit / total_loss

    def compare(self, other: "BacktestResult") -> dict:
        """比较两个回测结果, 返回差值字典。

        参数敏感性分析:
            r1 = engine.run(df, signals_a, symbol)
            r2 = engine.run(df, signals_b, symbol)
            diff = r1.compare(r2)
        """
        def _safe_sub(a: float | None, b: float | None) -> float:
            if a is None and b is None:
                return 0.0
            a_val = a or 0.0
            b_val = b or 0.0
            result = a_val - b_val
            if not math.isfinite(result):
                return 0.0
            return result

        return {
            "total_return_diff": _safe_sub(self.total_return, other.total_return),
            "sharpe_diff": _safe_sub(self.sharpe, other.sharpe),
            "max_drawdown_diff": _safe_sub(self.max_drawdown, other.max_drawdown),
            "total_trades_diff": len(self.trades) - len(other.trades),
            "win_rate_diff": _safe_sub(self.win_rate, other.win_rate),
            "profit_factor_diff": _safe_sub(self.profit_factor, other.profit_factor),
        }

    def to_dict(self) -> Dict[str, Any]:
        """将回测指标转换为字典"""
        return {
            "initial_capital": self.initial_capital,
            "final_cash": self.final_cash,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe,
            "win_rate": self.win_rate,
            "total_trades": self.total_trades,
            "trades": [
                {
                    "timestamp": t.timestamp.isoformat() if hasattr(t.timestamp, "isoformat") else str(t.timestamp),
                    "action": t.action,
                    "price": t.price,
                    "shares": t.shares,
                    "commission": t.commission,
                    "stamp_duty": getattr(t, "stamp_duty", 0.0),
                    "slippage": getattr(t, "slippage", 0.0),
                    "pnl": getattr(t, "pnl", 0.0),
                }
                for t in self.trades
            ],
            "metadata": self.metadata,
        }


# ══════════════════════════════════════════════════════════════
# 计算与检验辅助函数
# ══════════════════════════════════════════════════════════════

def prepare_backtest_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """准备 DataFrame, 补充必需列与滚动均量"""
    df = df.copy()
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"缺少必需列: {missing}")

    if "pre_close" not in df.columns:
        df["pre_close"] = df["close"].shift(1).fillna(df["open"])

    if "avg_daily_volume" not in df.columns:
        adv = df["volume"].rolling(20, min_periods=1).mean()
        df["avg_daily_volume"] = adv.shift(1).fillna(adv)

    return df


def index_signals_by_date(signals: List[Any]) -> Dict[str, List[Any]]:
    """按日期索引信号"""
    by_date: Dict[str, List[Any]] = {}
    for sig in signals:
        if sig.timestamp is not None:
            key = pd.Timestamp(sig.timestamp).strftime("%Y-%m-%d")
        else:
            key = "unknown"
        by_date.setdefault(key, []).append(sig)
    return by_date


def get_next_trading_day(date: pd.Timestamp, trade_calendar: Any) -> pd.Timestamp:
    """找到下一个交易日"""
    d = date + pd.Timedelta(days=1)
    for _ in range(10):
        if trade_calendar.is_trading_day(d):
            return d
        d += pd.Timedelta(days=1)
    return d


def check_t1_compliance(
    buy_date: Optional[pd.Timestamp],
    sell_date: pd.Timestamp,
    trade_calendar: Any,
) -> bool:
    """防线 A: T+1 检查 — 交易日序号差 >= 1"""
    if buy_date is None:
        return True

    buy_ord = buy_date.toordinal()
    sell_ord = sell_date.toordinal()

    if sell_ord <= buy_ord:
        return False

    next_td = get_next_trading_day(buy_date, trade_calendar)
    return sell_date.toordinal() >= next_td.toordinal()


def check_limit_price(
    price: float,
    pre_close: float,
    action: str,
    symbol: str = "",
    name: Optional[str] = None,
) -> bool:
    """防线 B: 涨跌停检查

    Returns:
        True = 允许交易, False = 拒绝
    """
    if pre_close <= 0:
        return True

    ratio = price / pre_close
    board = get_board_type(symbol, name)
    up_ratio, down_ratio = MarketConstants.LIMIT_RATIO.get(
        board, MarketConstants.LIMIT_RATIO["main"]
    )
    tol = MarketConstants.PRICE_TOLERANCE

    if action == "BUY" and ratio >= up_ratio - tol:
        return False
    if action == "SELL" and ratio <= down_ratio + tol:
        return False
    return True


def calculate_commission(value: float, commission_rate: float, min_commission: float) -> float:
    """佣金 = max(value × 费率, 最低佣金)"""
    return max(value * commission_rate, min_commission)


def calculate_stamp_duty(
    value: float,
    stamp_duty_rate: float,
    timestamp: Optional[pd.Timestamp] = None,
) -> float:
    """印花税 (仅卖方)"""
    if timestamp is not None:
        rate = get_stamp_tax_pct(timestamp.date())
    else:
        rate = stamp_duty_rate
    return value * rate


def calculate_transfer_fee(value: float, symbol: str = "") -> float:
    """过户费 (仅沪市60xxxx)"""
    return value * TRANSFER_FEE_PCT if _has_transfer_fee(symbol) else 0.0


def calculate_slippage(
    price: float,
    is_buy: bool,
    trade_volume: int,
    avg_daily_volume: float,
    slippage_rate: float,
) -> float:
    """防线 F: 滑点计算 — 使用交易量, 不是日均量

    Returns:
        执行价格 (含滑点)
    """
    impact = 0.0
    if avg_daily_volume > 0 and trade_volume > 0:
        ratio = trade_volume / avg_daily_volume
        impact = min(0.001 * (ratio ** 0.5), 0.02)

    total = slippage_rate + impact
    if is_buy:
        return price * (1 + total)
    else:
        return price * (1 - total)


def run_sensitivity_scan(
    engine_factory: Callable[[float, float], Any],
    df: pd.DataFrame,
    signals: List[Any],
    symbol: str = "",
    name: Optional[str] = None,
    slippages: Optional[List[float]] = None,
    commissions: Optional[List[float]] = None,
    benchmark_returns: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """滑点/佣金敏感性分析核心逻辑"""
    if slippages is None:
        slippages = [0.0, 0.0005, 0.001, 0.002, 0.003]
    if commissions is None:
        commissions = [0.0, 0.0003, 0.0005, 0.001]

    rows: List[Dict[str, float]] = []

    for slp in slippages:
        for comm in commissions:
            engine = engine_factory(comm, slp)
            result = engine.run(
                df,
                signals,
                symbol=symbol,
                name=name,
                benchmark_returns=benchmark_returns,
            )
            rows.append({
                "slippage": slp,
                "commission": comm,
                "total_return": result.total_return,
                "sharpe": result.sharpe,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
            })

    return pd.DataFrame(rows)
