"""
统一回测引擎 — UnifiedBacktestEngine
=====================================

强类型输入: List[TradingSignal] (完全解耦策略生成与撮合)

防线清单:
  A. T+1 铁律: 交易日序号差 >= 1
  B. 涨跌停拦截: 涨停不买入, 跌停不卖出
  C. 停牌拦截: volume=0 不成交
  D. 资金永不透支: 实时 cash_available 全局扣减
  E. 非对称成本: 印花税仅卖方, 最低佣金5元
  F. 滑点方向: 买高卖低, 使用交易量而非日均量
  G. 整手取整: A股100股为一手
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ...shared.constants import BacktestConstants, MarketConstants
from ...shared.cost_model import (
    COMMISSION_PCT,
    MIN_COMMISSION,
    SLIPPAGE_PCT,
    STAMP_TAX_PCT,
    TRANSFER_FEE_PCT,
    get_stamp_tax_pct,
)
from ...shared.interfaces import TradingSignal
from ...shared.limit_checker import get_board_type
from ...shared.logger_factory import get_logger
from ...shared.market_rules import get_board_rule
from ...data.managers.trade_calendar_manager import TradeCalendarManager

logger = get_logger(__name__)


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
        arr = np.array(self.daily_returns, dtype=np.float64)
        if np.std(arr) == 0:
            return 0.0
        return float(np.mean(arr) / np.std(arr) * np.sqrt(252))

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


# ══════════════════════════════════════════════════════════════
# 统一回测引擎
# ══════════════════════════════════════════════════════════════

class UnifiedBacktestEngine:
    """统一回测引擎

    核心纪律:
      - 输入必须是 List[TradingSignal] (强类型)
      - 每根 bar 先执行挂单, 再更新权益, 最后收集信号
      - 信号 T 日生成, T+1 日 Open 成交
      - 现金实时扣减, 永不透支
    """

    def __init__(
        self,
        initial_capital: float = BacktestConstants.DEFAULT_INITIAL_CAPITAL,
        commission_rate: float = COMMISSION_PCT,
        stamp_duty_rate: float = STAMP_TAX_PCT,
        slippage_rate: float = SLIPPAGE_PCT,
        min_commission: float = MIN_COMMISSION,
        trade_calendar: Optional[TradeCalendarManager] = None,
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.slippage_rate = slippage_rate
        self.min_commission = min_commission
        self.trade_calendar = trade_calendar or TradeCalendarManager()

    # ──────────────────────────────────────────────────────────
    # 公共接口
    # ──────────────────────────────────────────────────────────

    def run(
        self,
        df: pd.DataFrame,
        signals: List[TradingSignal],
        symbol: str = "",
        name: Optional[str] = None,
    ) -> BacktestResult:
        """运行回测

        Args:
            df: K线数据, 必须包含 date/open/high/low/close/volume
            signals: 标准化信号列表 (来自 TradingSignalCollector 或手动构造)
            symbol: 股票代码
            name: 股票名称 (用于 ST 识别)

        Returns:
            BacktestResult
        """
        df = self._prepare_dataframe(df)
        signal_map = self._index_signals_by_date(signals)

        cash = self.initial_capital
        position = 0
        position_cost = 0.0
        buy_date: Optional[pd.Timestamp] = None
        trades: List[TradeRecord] = []
        equity_curve: List[float] = []
        daily_returns: List[float] = []
        prev_equity = self.initial_capital
        trading_days_count: int = 0
        max_position: int = 0

        dates = pd.to_datetime(df["date"]).values
        opens = df["open"].values.astype(np.float64)
        closes = df["close"].values.astype(np.float64)
        volumes = df["volume"].values.astype(np.float64)
        pre_closes = df["pre_close"].values.astype(np.float64)
        avg_daily_volumes = df["avg_daily_volume"].values.astype(np.float64)

        pending_order: Optional[Dict] = None

        for idx in range(len(df)):
            ts = pd.Timestamp(dates[idx])
            date_key = ts.strftime("%Y-%m-%d")

            # 跳过非交易日 (周末/节假日)
            if not self.trade_calendar.is_trading_day(ts):
                # 非交易日也更新权益 (使用收盘价)
                equity = cash + position * closes[idx]
                equity_curve.append(equity)
                if prev_equity > 0:
                    daily_returns.append((equity - prev_equity) / prev_equity)
                else:
                    daily_returns.append(0.0)
                prev_equity = equity
                continue

            trading_days_count += 1

            # ── Step 1: 执行前一根 bar 的挂单 (T+1 延迟) ──
            if pending_order is not None:
                exec_price_raw = opens[idx]
                vol = int(volumes[idx])
                pc = pre_closes[idx]
                adv = avg_daily_volumes[idx]

                # 防线 C: 停牌拦截
                if vol <= 0:
                    logger.debug(f"停牌拒绝: {date_key} volume=0")
                    pending_order = None
                else:
                    if pending_order["action"] == "BUY":
                        record, cash = self._execute_buy(
                            price_raw=exec_price_raw,
                            shares_requested=pending_order["shares"],
                            cash_available=cash,
                            pre_close=pc,
                            timestamp=ts,
                            symbol=symbol,
                            name=name,
                            trade_volume=pending_order["shares"],
                            avg_daily_volume=adv,
                            reason=pending_order.get("reason", ""),
                        )
                        if record is not None:
                            trades.append(record)
                            position += record.shares
                            position_cost = record.price
                            buy_date = ts
                            max_position = max(max_position, position)

                    elif pending_order["action"] == "SELL":
                        # 防线 A: T+1 检查
                        if buy_date is not None and not self._check_t1(buy_date, ts):
                            logger.debug(f"T+1拒绝: buy={buy_date} sell={ts}")
                        else:
                            record, cash = self._execute_sell(
                                price_raw=exec_price_raw,
                                shares_to_sell=min(pending_order["shares"], position),
                                cash=cash,
                                position_cost=position_cost,
                                pre_close=pc,
                                timestamp=ts,
                                symbol=symbol,
                                name=name,
                                trade_volume=min(pending_order["shares"], position),
                                avg_daily_volume=adv,
                                reason=pending_order.get("reason", ""),
                            )
                            if record is not None:
                                trades.append(record)
                                position -= record.shares
                                if position <= 0:
                                    position = 0
                                    position_cost = 0.0
                                    buy_date = None

                    pending_order = None

            # ── Step 2: 更新权益 ──
            equity = cash + position * closes[idx]
            equity_curve.append(equity)
            if prev_equity > 0:
                daily_returns.append((equity - prev_equity) / prev_equity)
            else:
                daily_returns.append(0.0)
            prev_equity = equity

            # ── Step 3: 收集当日信号 → 生成挂单 ──
            # 规则: LPPL SELL > BUY > 非LPPL SELL
            # 说明: 当仲裁器输出多个信号同天到达时, 按此顺序尝试执行。
            #       这是一个执行层调度, 非仲裁层逻辑。
            #       SignalArbitrator 决定"生成哪些信号",
            #       此优先级决定"同天多个信号时先执行哪个"。
            day_signals = signal_map.get(date_key, [])
            for sig in day_signals:
                if (sig.action == "SELL" and position > 0 and pending_order is None
                        and sig.reason and "lppl" in sig.reason.lower()):
                    pending_order = {
                        "action": "SELL",
                        "shares": position,
                        "reason": sig.reason,
                    }
                    break
            if pending_order is None:
                for sig in day_signals:
                    if sig.action == "BUY" and position == 0:
                        shares = sig.shares if sig.shares > 0 else 100
                        pending_order = {
                            "action": "BUY",
                            "shares": shares,
                            "reason": sig.reason,
                        }
                        break
            if pending_order is None:
                for sig in day_signals:
                    if sig.action == "SELL" and position > 0:
                        pending_order = {
                            "action": "SELL",
                            "shares": position,
                            "reason": sig.reason,
                        }
                        break

        # Survivorship bias check (conditional — only if delist data available)
        survivorship_warning = ""
        try:
            from ...data.managers.stock_metadata_manager import StockMetadataManager
            mgr = StockMetadataManager()
            delist_date = mgr.get_delist_date(symbol) if hasattr(mgr, 'get_delist_date') else None
            if delist_date is not None:
                last_bar = pd.to_datetime(df["date"].iloc[-1]) if len(df) else None
                if last_bar is not None and pd.to_datetime(delist_date) <= last_bar:
                    survivorship_warning = (
                        f"Symbol delisted {delist_date}; "
                        f"backtest extends to {last_bar.date()}"
                    )
        except Exception:
            pass

        metadata: Dict[str, Any] = {
            "symbol": symbol if symbol else "",
            "engine": "unified",
            "start_date": str(pd.to_datetime(df["date"].iloc[0]).date()) if len(df) else "",
            "end_date": str(pd.to_datetime(df["date"].iloc[-1]).date()) if len(df) else "",
            "signal_count": len(signals),
            "trading_days_count": trading_days_count,
            "final_equity": float(equity_curve[-1]) if equity_curve else 0.0,
            "max_position": max_position,
            "commission_rate": self.commission_rate,
            "stamp_duty_rate": self.stamp_duty_rate,
            "slippage_rate": self.slippage_rate,
            "min_commission": self.min_commission,
        }
        if survivorship_warning:
            metadata["survivorship_warning"] = survivorship_warning

        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            daily_returns=daily_returns,
            initial_capital=self.initial_capital,
            final_cash=cash,
            metadata=metadata,
        )

    # ──────────────────────────────────────────────────────────
    # 内部方法: 数据准备
    # ──────────────────────────────────────────────────────────

    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """准备 DataFrame, 补充缺失列"""
        df = df.copy()
        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"缺少必需列: {missing}")

        if "pre_close" not in df.columns:
            df["pre_close"] = df["close"].shift(1).fillna(df["open"])

        if "avg_daily_volume" not in df.columns:
            df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()

        return df

    @staticmethod
    def _index_signals_by_date(
        signals: List[TradingSignal],
    ) -> Dict[str, List[TradingSignal]]:
        """按日期索引信号"""
        by_date: Dict[str, List[TradingSignal]] = {}
        for sig in signals:
            if sig.timestamp is not None:
                key = pd.Timestamp(sig.timestamp).strftime("%Y-%m-%d")
            else:
                key = "unknown"
            by_date.setdefault(key, []).append(sig)
        return by_date

    # ──────────────────────────────────────────────────────────
    # 内部方法: T+1 检查
    # ──────────────────────────────────────────────────────────

    def _check_t1(self, buy_date: pd.Timestamp, sell_date: pd.Timestamp) -> bool:
        """防线 A: T+1 检查 — 交易日序号差 >= 1"""
        if buy_date is None:
            return True

        buy_ord = buy_date.toordinal()
        sell_ord = sell_date.toordinal()

        # 必须至少隔一个自然日
        if sell_ord <= buy_ord:
            return False

        # 找到买入日的下一个交易日
        next_td = self._next_trading_day(buy_date)
        return sell_date.toordinal() >= next_td.toordinal()

    def _next_trading_day(self, date: pd.Timestamp) -> pd.Timestamp:
        """找到下一个交易日"""
        d = date + pd.Timedelta(days=1)
        for _ in range(10):
            if self.trade_calendar.is_trading_day(d):
                return d
            d += pd.Timedelta(days=1)
        return d

    # ──────────────────────────────────────────────────────────
    # 内部方法: 涨跌停检查
    # ──────────────────────────────────────────────────────────

    def _check_limit(
        self,
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
            return False  # 涨停拒绝买入
        if action == "SELL" and ratio <= down_ratio + tol:
            return False  # 跌停拒绝卖出
        return True

    # ──────────────────────────────────────────────────────────
    # 内部方法: 成本计算
    # ──────────────────────────────────────────────────────────

    def _calc_commission(self, value: float) -> float:
        """佣金 = max(value × 费率, 最低佣金)"""
        return max(value * self.commission_rate, self.min_commission)

    def _calc_stamp_duty(self, value: float, timestamp: Optional[pd.Timestamp] = None) -> float:
        """印花税 (仅卖方)"""
        if timestamp is not None:
            rate = get_stamp_tax_pct(timestamp.date())
        else:
            rate = self.stamp_duty_rate
        return value * rate

    def _calc_transfer_fee(self, value: float) -> float:
        """过户费"""
        return value * TRANSFER_FEE_PCT

    def _calc_slippage(
        self,
        price: float,
        is_buy: bool,
        trade_volume: int,
        avg_daily_volume: float,
    ) -> float:
        """防线 F: 滑点计算 — 使用交易量, 不是日均量

        Returns:
            执行价格 (含滑点)
        """
        base = self.slippage_rate

        impact = 0.0
        if avg_daily_volume > 0 and trade_volume > 0:
            # 关键修复: 使用 trade_volume (本次交易量)
            # 而非 daily_volume (当日总成交量)
            ratio = trade_volume / avg_daily_volume
            impact = min(0.001 * (ratio ** 0.5), 0.02)

        total = base + impact
        if is_buy:
            return price * (1 + total)
        else:
            return price * (1 - total)

    # ──────────────────────────────────────────────────────────
    # 内部方法: 执行买入
    # ──────────────────────────────────────────────────────────

    def _execute_buy(
        self,
        price_raw: float,
        shares_requested: int,
        cash_available: float,
        pre_close: float,
        timestamp: pd.Timestamp,
        symbol: str,
        name: Optional[str],
        trade_volume: int,
        avg_daily_volume: float,
        reason: str,
    ) -> tuple[Optional[TradeRecord], float]:
        """执行买入

        Returns:
            (TradeRecord or None, remaining_cash)
        """
        # 防线 B: 涨停检查
        if not self._check_limit(price_raw, pre_close, "BUY", symbol, name):
            logger.debug(f"涨停拒绝买入: {timestamp}")
            return None, cash_available

        # 滑点 (使用交易量)
        exec_price = self._calc_slippage(
            price_raw, is_buy=True,
            trade_volume=trade_volume,
            avg_daily_volume=avg_daily_volume,
        )

        # 防线 G: 整手取整
        lot_size = get_board_rule(symbol).lot_size
        shares = (shares_requested // lot_size) * lot_size
        if shares <= 0:
            return None, cash_available

        # 成本计算
        value = exec_price * shares
        commission = self._calc_commission(value)
        transfer_fee = self._calc_transfer_fee(value)
        total_cost = value + commission + transfer_fee

        # 防线 D: 资金不足时自动减量
        if total_cost > cash_available:
            # 重新计算可买股数
            affordable = int((cash_available - commission - transfer_fee) / exec_price)
            shares = (affordable // lot_size) * lot_size
            if shares <= 0:
                return None, cash_available
            value = exec_price * shares
            commission = self._calc_commission(value)
            transfer_fee = self._calc_transfer_fee(value)
            total_cost = value + commission + transfer_fee

        # 防线 D: 最终检查
        if total_cost > cash_available:
            return None, cash_available

        remaining_cash = cash_available - total_cost

        record = TradeRecord(
            timestamp=timestamp,
            action="BUY",
            symbol=symbol,
            price=exec_price,
            shares=shares,
            commission=commission,
            stamp_duty=0.0,  # 买入无印花税
            transfer_fee=transfer_fee,
            slippage=exec_price - price_raw,
            reason=reason,
        )
        return record, remaining_cash

    # ──────────────────────────────────────────────────────────
    # 内部方法: 执行卖出
    # ──────────────────────────────────────────────────────────

    def _execute_sell(
        self,
        price_raw: float,
        shares_to_sell: int,
        cash: float,
        position_cost: float,
        pre_close: float,
        timestamp: pd.Timestamp,
        symbol: str,
        name: Optional[str],
        trade_volume: int,
        avg_daily_volume: float,
        reason: str,
    ) -> tuple[Optional[TradeRecord], float]:
        """执行卖出

        Returns:
            (TradeRecord or None, remaining_cash)
        """
        if shares_to_sell <= 0:
            return None, cash

        # 防线 B: 跌停检查
        if not self._check_limit(price_raw, pre_close, "SELL", symbol, name):
            logger.debug(f"跌停拒绝卖出: {timestamp}")
            return None, cash

        # 滑点 (使用交易量)
        exec_price = self._calc_slippage(
            price_raw, is_buy=False,
            trade_volume=trade_volume,
            avg_daily_volume=avg_daily_volume,
        )

        value = exec_price * shares_to_sell
        commission = self._calc_commission(value)
        stamp_duty = self._calc_stamp_duty(value, timestamp)
        transfer_fee = self._calc_transfer_fee(value)
        net_value = value - commission - stamp_duty - transfer_fee

        cost_basis = position_cost * shares_to_sell
        pnl = net_value - cost_basis

        remaining_cash = cash + net_value

        record = TradeRecord(
            timestamp=timestamp,
            action="SELL",
            symbol=symbol,
            price=exec_price,
            shares=shares_to_sell,
            commission=commission,
            stamp_duty=stamp_duty,
            transfer_fee=transfer_fee,
            slippage=price_raw - exec_price,
            pnl=pnl,
            reason=reason,
        )
        return record, remaining_cash
