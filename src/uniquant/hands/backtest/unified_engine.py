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

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ...data.managers.trade_calendar_manager import TradeCalendarManager
from ...shared.constants import BacktestConstants
from ...shared.cost_model import (
    COMMISSION_PCT,
    MIN_COMMISSION,
    SLIPPAGE_PCT,
    STAMP_TAX_PCT,
)
from ...shared.interfaces import PositionSizerProtocol, TradingSignal
from ...shared.logger_factory import get_logger
from ...shared.market_rules import get_board_rule
from .unified_models import (
    BacktestResult,
    TradeRecord,
    calculate_commission,
    calculate_slippage,
    calculate_stamp_duty,
    calculate_transfer_fee,
    check_limit_price,
    check_t1_compliance,
    get_next_trading_day,
    index_signals_by_date,
    prepare_backtest_dataframe,
    run_sensitivity_scan,
)

logger = get_logger(__name__)

__all__ = [
    "BacktestResult",
    "TradeRecord",
    "UnifiedBacktestEngine",
]


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
        sizer: Optional[PositionSizerProtocol] = None,
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.slippage_rate = slippage_rate
        self.min_commission = min_commission
        self.trade_calendar = trade_calendar or TradeCalendarManager()
        self._sizer = sizer
        self.cash = initial_capital
        self.positions: Dict[str, int] = {}
        self.trades: List[TradeRecord] = []

    def reset(self):
        """重置引擎状态"""
        self.cash = self.initial_capital
        self.positions = {}
        self.trades = []

    # ──────────────────────────────────────────────────────────
    # 公共接口
    # ──────────────────────────────────────────────────────────

    def sensitivity_scan(
        self,
        df: pd.DataFrame,
        signals: List[TradingSignal],
        symbol: str = "",
        name: Optional[str] = None,
        slippages: Optional[List[float]] = None,
        commissions: Optional[List[float]] = None,
        benchmark_returns: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """滑点/佣金敏感性分析

        遍历给定的滑点率和佣金率组合, 分别运行回测,
        返回每个组合下的总收益率、夏普比率、最大回撤、胜率、盈利因子。

        Args:
            df: K线数据
            signals: 标准化信号列表
            symbol: 股票代码
            name: 股票名称
            slippages: 滑点率列表 (默认 [0.0, 0.0005, 0.001, 0.002, 0.003])
            commissions: 佣金率列表 (默认 [0.0, 0.0003, 0.0005, 0.001])
            benchmark_returns: 基准指数收益率序列, 传入后增加 excess_return 列

        Returns:
            DataFrame with columns: slippage, commission, total_return, sharpe,
            max_drawdown, win_rate, profit_factor [, excess_return]
        """
        def _factory(comm: float, slp: float) -> UnifiedBacktestEngine:
            return UnifiedBacktestEngine(
                initial_capital=self.initial_capital,
                commission_rate=comm,
                stamp_duty_rate=self.stamp_duty_rate,
                slippage_rate=slp,
                min_commission=self.min_commission,
                trade_calendar=self.trade_calendar,
            )

        return run_sensitivity_scan(
            engine_factory=_factory,
            df=df,
            signals=signals,
            symbol=symbol,
            name=name,
            slippages=slippages,
            commissions=commissions,
            benchmark_returns=benchmark_returns,
        )

    def run(
        self,
        df: pd.DataFrame,
        signals: List[TradingSignal],
        symbol: str = "",
        name: Optional[str] = None,
        benchmark_returns: Optional[pd.Series] = None,
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
                    if pending_order["action"] == "SELL" and position > 0:
                        retry_count = pending_order.get("retry_count", 0) + 1
                        if retry_count < 30:
                            pending_order["status"] = "RETRYING"
                            pending_order["retry_count"] = retry_count
                            logger.debug(f"停牌结转 (RETRYING {retry_count}/30): {ts} {symbol}")
                        else:
                            logger.warning(f"停牌超过30日上限，放弃结转挂单: {ts} {symbol}")
                            pending_order = None
                    else:
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
                        # 买单执行或涨停拒绝后一律作废 (Auto-Cancel, 不结转)
                        pending_order = None

                    elif pending_order["action"] == "SELL":
                        # 防线 A: T+1 检查
                        if buy_date is not None and not self._check_t1(buy_date, ts):
                            logger.debug(f"T+1拒绝: buy={buy_date} sell={ts}")
                            # T+1 未达，结转至下一交易日
                            pending_order["status"] = "RETRYING"
                            pending_order["retry_count"] = pending_order.get("retry_count", 0) + 1
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
                            else:
                                # 防线 B: 跌停拒卖强制结转 (Mandatory Rollover, INV-6)
                                retry_count = pending_order.get("retry_count", 0) + 1
                                if retry_count < 30 and position > 0:
                                    pending_order["status"] = "RETRYING"
                                    pending_order["retry_count"] = retry_count
                                    pending_order["shares"] = position  # 同步最新持仓
                                    logger.info(
                                        f"跌停拒卖强制结转 (RETRYING {retry_count}/30): "
                                        f"{ts} {symbol} shares={position}"
                                    )
                                else:
                                    logger.warning(
                                        f"跌停结转达到30日上限，执行终局坏账清退 (0元出清, INV-7): {ts} {symbol} shares={position}"
                                    )
                                    if position > 0:
                                        bad_debt_record = TradeRecord(
                                            timestamp=ts,
                                            action="SELL",
                                            symbol=symbol,
                                            price=0.0,
                                            shares=position,
                                            commission=0.0,
                                            stamp_duty=0.0,
                                            transfer_fee=0.0,
                                            slippage=exec_price_raw,
                                            pnl=-position_cost * position,
                                            reason="BAD_DEBT_LIMIT_DOWN_30D_EXPIRED",
                                        )
                                        trades.append(bad_debt_record)
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
            # 互斥排队保护 (INV-6): 若存在处于 RETRYING 结转状态的清仓卖单，严禁被 BUY 信号覆写
            if pending_order is not None and pending_order.get("status") == "RETRYING":
                day_signals = signal_map.get(date_key, [])
                for sig in day_signals:
                    if sig.action == "BUY":
                        logger.warning(
                            f"标的 {symbol} 存在结转中的清仓卖单 (RETRYING), 拦截买入信号"
                        )
                # 保持 pending_order 结转状态不变，次日集合竞价置顶重试
            else:
                day_signals = signal_map.get(date_key, [])
                for sig in day_signals:
                    if (sig.action == "SELL" and position > 0 and pending_order is None
                            and sig.reason and "lppl" in sig.reason.lower()):
                        pending_order = {
                            "action": "SELL",
                            "shares": position,
                            "reason": sig.reason,
                            "status": "PENDING",
                            "retry_count": 0,
                        }
                        break
                if pending_order is None:
                    for sig in day_signals:
                        if sig.action == "BUY" and position == 0:
                            shares = sig.shares if sig.shares > 0 else 100
                            # 如果提供了 PositionSizer，用它重新计算股数
                            if self._sizer is not None:
                                try:
                                    sized = self._sizer.calculate_shares(
                                        price=closes[idx],
                                        stop_loss=closes[idx] * 0.95,
                                        czsc_bottom=None,
                                        market="CN",
                                        symbol=symbol,
                                    )
                                    sized_shares = int(sized.get("suggested_shares", shares))
                                    shares = (sized_shares // get_board_rule(symbol).lot_size) * get_board_rule(symbol).lot_size
                                    if shares <= 0:
                                        shares = 100
                                except (KeyError, TypeError, ValueError, RuntimeError):
                                    shares = 100
                            pending_order = {
                                "action": "BUY",
                                "shares": shares,
                                "reason": sig.reason,
                                "status": "PENDING",
                                "retry_count": 0,
                            }
                            break
                if pending_order is None:
                    for sig in day_signals:
                        if sig.action == "SELL" and position > 0:
                            pending_order = {
                                "action": "SELL",
                                "shares": position,
                                "reason": sig.reason,
                                "status": "PENDING",
                                "retry_count": 0,
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
        except (OSError, KeyError, TypeError):
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

        benchmark_return = 0.0
        if benchmark_returns is not None and len(benchmark_returns) > 0:
            bench_total = float(benchmark_returns.iloc[-1]) - float(benchmark_returns.iloc[0])
            bench_return = bench_total / float(benchmark_returns.iloc[0]) if float(benchmark_returns.iloc[0]) != 0 else 0.0
            portfolio_return = (equity_curve[-1] - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0.0
            benchmark_return = portfolio_return - bench_return

        self.cash = cash
        self.positions = {symbol: position} if position > 0 else {}
        self.trades = trades

        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            daily_returns=daily_returns,
            initial_capital=self.initial_capital,
            final_cash=cash,
            metadata=metadata,
            benchmark_return=benchmark_return,
        )

    # ──────────────────────────────────────────────────────────
    # 内部方法: 数据准备
    # ──────────────────────────────────────────────────────────

    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """准备 DataFrame, 补充缺失列"""
        return prepare_backtest_dataframe(df)

    @staticmethod
    def _index_signals_by_date(
        signals: List[TradingSignal],
    ) -> Dict[str, List[TradingSignal]]:
        """按日期索引信号"""
        return index_signals_by_date(signals)

    # ──────────────────────────────────────────────────────────
    # 内部方法: T+1 检查
    # ──────────────────────────────────────────────────────────

    def _check_t1(self, buy_date: pd.Timestamp, sell_date: pd.Timestamp) -> bool:
        """防线 A: T+1 检查 — 交易日序号差 >= 1"""
        return check_t1_compliance(buy_date, sell_date, self.trade_calendar)

    def _next_trading_day(self, date: pd.Timestamp) -> pd.Timestamp:
        """找到下一个交易日"""
        return get_next_trading_day(date, self.trade_calendar)

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
        return check_limit_price(price, pre_close, action, symbol=symbol, name=name)

    # ──────────────────────────────────────────────────────────
    # 内部方法: 成本计算
    # ──────────────────────────────────────────────────────────

    def _calc_commission(self, value: float) -> float:
        """佣金 = max(value × 费率, 最低佣金)"""
        return calculate_commission(value, self.commission_rate, self.min_commission)

    def _calc_stamp_duty(self, value: float, timestamp: Optional[pd.Timestamp] = None) -> float:
        """印花税 (仅卖方)"""
        return calculate_stamp_duty(value, self.stamp_duty_rate, timestamp=timestamp)

    def _calc_transfer_fee(self, value: float, symbol: str = "") -> float:
        """过户费 (仅沪市60xxxx)"""
        return calculate_transfer_fee(value, symbol=symbol)

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
        return calculate_slippage(
            price,
            is_buy=is_buy,
            trade_volume=trade_volume,
            avg_daily_volume=avg_daily_volume,
            slippage_rate=self.slippage_rate,
        )

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
        transfer_fee = self._calc_transfer_fee(value, symbol)
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
            transfer_fee = self._calc_transfer_fee(value, symbol)
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
        transfer_fee = self._calc_transfer_fee(value, symbol)
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
