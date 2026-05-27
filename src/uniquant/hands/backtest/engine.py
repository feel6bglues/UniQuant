from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

import numpy as np
import pandas as pd

from uniquant.data.managers.trade_calendar_manager import TradeCalendarManager
from uniquant.shared.constants import BacktestConstants, RiskCalculationConstants
from uniquant.shared.error_handling import handle_errors
from uniquant.shared.exceptions import BacktestError
from uniquant.shared.limit_checker import check_limit_status
from uniquant.shared.logger_factory import get_logger
from .result import BacktestResult, TradeRecord

logger = get_logger(__name__)


class StrategyProtocol(Protocol):
    """策略协议"""
    def generate_signal(self, df: pd.DataFrame, idx: int) -> Dict[str, Any]:
        """生成交易信号"""
        ...


class BacktestEngine:
    """
    回测引擎
    
    支持:
    - Rolling window 滚动回测
    - Walk-forward 验证
    - 交易成本处理 (佣金 + 印花税 + 滑点)
    - A股 T+1 + 涨跌停约束
    """
    
    def __init__(
        self,
        initial_capital: float = BacktestConstants.DEFAULT_INITIAL_CAPITAL,
        commission_rate: float = BacktestConstants.DEFAULT_COMMISSION_RATE,
        stamp_duty_rate: float = BacktestConstants.DEFAULT_STAMP_DUTY_RATE,
        slippage_rate: float = BacktestConstants.DEFAULT_SLIPPAGE_RATE,
        min_commission: float = BacktestConstants.DEFAULT_MIN_COMMISSION,
        trade_calendar: Optional[TradeCalendarManager] = None,
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.slippage_rate = slippage_rate
        self.min_commission = min_commission
        self.trade_calendar = trade_calendar or TradeCalendarManager()
        
        self.cash = initial_capital
        self.position = 0
        self.position_cost = 0.0
        self.trades: List[TradeRecord] = []
        self.equity_curve: List[float] = []
        self.daily_returns: List[float] = []
        
        self._prev_equity = initial_capital
    
    def reset(self) -> None:
        """重置回测状态"""
        self.cash = self.initial_capital
        self.position = 0
        self.position_cost = 0.0
        self.trades = []
        self.equity_curve = []
        self.daily_returns = []
        self._prev_equity = self.initial_capital
    
    def _calculate_commission(self, value: float, is_sell: bool = False) -> float:
        """计算交易成本"""
        commission = max(value * self.commission_rate, self.min_commission)
        stamp_duty = value * self.stamp_duty_rate if is_sell else 0
        return commission + stamp_duty
    
    def _calculate_slippage(
        self, 
        price: float, 
        is_buy: bool = True, 
        volume: int = 0,
        avg_daily_volume: float = 0,
    ) -> float:
        """
        计算滑点 - 非线性滑点模型
        
        滑点 = 基础滑点 + 冲击成本
        冲击成本与交易量占日均成交量的比例呈非线性关系
        
        Args:
            price: 当前价格
            is_buy: 是否买入
            volume: 交易量
            avg_daily_volume: 日均成交量（用于计算冲击成本）
            
        Returns:
            执行价格（含滑点）
        """
        base_slippage = self.slippage_rate
        
        impact_slippage = 0.0
        if avg_daily_volume > 0 and volume > 0:
            volume_ratio = volume / avg_daily_volume
            impact_slippage = 0.001 * (volume_ratio ** 0.5)
            impact_slippage = min(impact_slippage, 0.02)
        
        total_slippage = base_slippage + impact_slippage
        
        if is_buy:
            return price * (1 + total_slippage)
        else:
            return price * (1 - total_slippage)
    
    def _check_t1_constraint(self, buy_date: datetime, current_date: datetime) -> bool:
        """检查T+1约束 - 使用真实交易日历"""
        if buy_date is None:
            return True
        
        if not self.trade_calendar.is_trading_day(current_date):
            return False
        
        trading_days = self.trade_calendar.get_trade_calendar(
            start_date=buy_date.strftime("%Y-%m-%d"),
            end_date=current_date.strftime("%Y-%m-%d")
        )
        
        if trading_days.empty:
            # 保守策略：无法确认交易日历时拒绝卖出
            return False
        
        trade_dates = trading_days['trade_date'].values
        buy_idx = np.where(trade_dates == pd.Timestamp(buy_date))[0]
        current_idx = np.where(trade_dates == pd.Timestamp(current_date))[0]
        
        if len(buy_idx) == 0 or len(current_idx) == 0:
            # 保守策略：日期不在交易日历中时拒绝卖出
            return False
        
        return bool(current_idx[0] - buy_idx[0] >= 1)
    
    def _check_limit_constraint(
        self, 
        price: float, 
        pre_close: float, 
        action: str,
        symbol: str = "",
    ) -> bool:
        """检查涨跌停约束"""
        limit_status = check_limit_status(price, pre_close, symbol)
        if action == "BUY" and limit_status.is_limit_up:
            return False
        if action == "SELL" and limit_status.is_limit_down:
            return False
        return True
    
    def execute_buy(
        self,
        price: float,
        shares: int,
        timestamp: datetime,
        reason: str = "",
        pre_close: float = 0,
        symbol: str = "",
        volume: int = 0,
        avg_daily_volume: float = 0,
    ) -> Optional[TradeRecord]:
        """执行买入"""
        if shares <= 0:
            return None
        
        if pre_close > 0 and not self._check_limit_constraint(price, pre_close, "BUY", symbol):
            logger.debug(f"涨停无法买入: {timestamp}")
            return None
        
        exec_price = self._calculate_slippage(price, is_buy=True, volume=shares, avg_daily_volume=avg_daily_volume)
        value = exec_price * shares
        commission = self._calculate_commission(value, is_sell=False)
        total_cost = value + commission
        
        if total_cost > self.cash:
            shares = int((self.cash - commission) / exec_price)
            if shares <= 0:
                return None
            value = exec_price * shares
            total_cost = value + commission
        
        self.cash -= total_cost
        avg_cost = (self.position_cost * self.position + value) / (self.position + shares)
        self.position += shares
        self.position_cost = avg_cost
        
        trade = TradeRecord(
            timestamp=timestamp,
            action="BUY",
            price=exec_price,
            shares=shares,
            commission=commission,
            slippage=exec_price - price,
            reason=reason,
        )
        self.trades.append(trade)
        logger.debug(f"买入执行: {timestamp}, 价格: {exec_price:.2f}, 数量: {shares}")
        
        return trade
    
    def execute_sell(
        self,
        price: float,
        shares: int,
        timestamp: datetime,
        reason: str = "",
        pre_close: float = 0,
        symbol: str = "",
        buy_date: Optional[datetime] = None,
        volume: int = 0,
        avg_daily_volume: float = 0,
    ) -> Optional[TradeRecord]:
        """执行卖出"""
        if shares <= 0 or self.position <= 0:
            return None
        
        if buy_date and not self._check_t1_constraint(buy_date, timestamp):
            logger.debug(f"T+1约束无法卖出: {timestamp}")
            return None
        
        if pre_close > 0 and not self._check_limit_constraint(price, pre_close, "SELL", symbol):
            logger.debug(f"跌停无法卖出: {timestamp}")
            return None
        
        shares = min(shares, self.position)
        exec_price = self._calculate_slippage(price, is_buy=False, volume=shares, avg_daily_volume=avg_daily_volume)
        value = exec_price * shares
        commission = self._calculate_commission(value, is_sell=True)
        
        cost = self.position_cost * shares
        pnl = value - cost - commission
        pnl_pct = pnl / cost if cost > 0 else 0
        
        self.cash += value - commission
        self.position -= shares
        if self.position == 0:
            self.position_cost = 0.0
        
        trade = TradeRecord(
            timestamp=timestamp,
            action="SELL",
            price=exec_price,
            shares=shares,
            commission=commission,
            slippage=price - exec_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
        )
        self.trades.append(trade)
        logger.debug(f"卖出执行: {timestamp}, 价格: {exec_price:.2f}, 数量: {shares}, 盈亏: {pnl:.2f}")
        
        return trade
    
    def update_equity(self, current_price: float) -> float:
        """更新权益"""
        equity = self.cash + self.position * current_price
        self.equity_curve.append(equity)
        
        daily_return = (equity - self._prev_equity) / self._prev_equity
        self.daily_returns.append(daily_return)
        self._prev_equity = equity
        
        return equity
    
    def get_current_equity(self, current_price: float) -> float:
        """获取当前权益"""
        return self.cash + self.position * current_price
    
    @handle_errors(
        ValueError,
        TypeError,
        BacktestError,
        default_return=BacktestResult(),
    )
    def run_backtest(
        self,
        df: pd.DataFrame,
        signal_generator: Callable[[pd.DataFrame, int, Dict[str, Any]], Dict[str, Any]],
        symbol: str = "",
        position_size: int = 100,
    ) -> BacktestResult:
        """
        运行回测
        
        Args:
            df: K线数据，必须包含 date, open, high, low, close 列
            signal_generator: 信号生成函数，返回 {"action": "BUY"/"SELL"/"HOLD", "reason": "..."}
            symbol: 股票代码
            position_size: 每次交易股数
            
        Returns:
            BacktestResult: 回测结果
        """
        self.reset()
        
        required_cols = {"date", "open", "high", "low", "close"}
        missing = required_cols - set(df.columns)
        if missing:
            raise BacktestError(f"缺少必需列: {missing}")
        
        if "pre_close" not in df.columns:
            df = df.copy()
            df["pre_close"] = df["close"].shift(1)
            df["pre_close"] = df["pre_close"].fillna(df["open"])
        
        dates = pd.to_datetime(df["date"])
        start_date = dates.iloc[0]
        end_date = dates.iloc[-1]
        
        buy_date = None
        
        for idx in range(len(df)):
            row = df.iloc[idx]
            current_price = row["close"]
            pre_close = row.get("pre_close", row["open"])
            timestamp = dates.iloc[idx]
            
            signal = signal_generator(df, idx, {
                "position": self.position,
                "position_cost": self.position_cost,
                "cash": self.cash,
            })
            
            action = signal.get("action", "HOLD")
            reason = signal.get("reason", "")
            
            if action == "BUY" and self.position == 0:
                trade = self.execute_buy(
                    price=current_price,
                    shares=position_size,
                    timestamp=timestamp,
                    reason=reason,
                    pre_close=pre_close,
                    symbol=symbol,
                )
                if trade:
                    buy_date = timestamp
            
            elif action == "SELL" and self.position > 0:
                trade = self.execute_sell(
                    price=current_price,
                    shares=self.position,
                    timestamp=timestamp,
                    reason=reason,
                    pre_close=pre_close,
                    symbol=symbol,
                    buy_date=buy_date,
                )
                if trade:
                    buy_date = None
            
            self.update_equity(current_price)
        
        result = BacktestResult(
            initial_capital=self.initial_capital,
            trades=self.trades,
            equity_curve=self.equity_curve,
            daily_returns=self.daily_returns,
            start_date=start_date.to_pydatetime(),
            end_date=end_date.to_pydatetime(),
        )
        result.calculate_metrics()
        
        return result
    
    @handle_errors(
        ValueError,
        TypeError,
        BacktestError,
        default_return=BacktestResult(),
    )
    def run_rolling_backtest(
        self,
        df: pd.DataFrame,
        signal_generator: Callable,
        symbol: str = "",
        position_size: int = 100,
        train_window: int = 252,
        test_window: int = 63,
    ) -> List[BacktestResult]:
        """
        滚动窗口回测
        
        Args:
            df: K线数据
            signal_generator: 信号生成函数
            symbol: 股票代码
            position_size: 每次交易股数
            train_window: 训练窗口 (天)
            test_window: 测试窗口 (天)
            
        Returns:
            List[BacktestResult]: 每个窗口的回测结果
        """
        results: List[BacktestResult] = []
        n = len(df)
        
        if n < train_window + test_window:
            logger.warning(f"数据不足，无法进行滚动回测: {n} < {train_window + test_window}")
            return results
        
        for start in range(train_window, n - test_window, test_window):
            test_df = df.iloc[start:start + test_window].copy()
            
            self.reset()
            result = self.run_backtest(
                df=test_df,
                signal_generator=signal_generator,
                symbol=symbol,
                position_size=position_size,
            )
            results.append(result)
        
        return results
    
    @handle_errors(
        ValueError,
        TypeError,
        BacktestError,
        default_return=BacktestResult(),
    )
    def run_walk_forward(
        self,
        df: pd.DataFrame,
        signal_generator_factory: Callable,
        symbol: str = "",
        position_size: int = 100,
        train_window: int = 252,
        test_window: int = 63,
    ) -> List[BacktestResult]:
        """
        Walk-forward 验证
        
        Args:
            df: K线数据
            signal_generator_factory: 信号生成器工厂函数，接收训练数据返回信号生成器
            symbol: 股票代码
            position_size: 每次交易股数
            train_window: 训练窗口 (天)
            test_window: 测试窗口 (天)
            
        Returns:
            List[BacktestResult]: 每个窗口的回测结果
        """
        results: List[BacktestResult] = []
        n = len(df)
        
        if n < train_window + test_window:
            logger.warning(f"数据不足，无法进行Walk-forward验证: {n} < {train_window + test_window}")
            return results
        
        for start in range(0, n - train_window - test_window, test_window):
            train_df = df.iloc[start:start + train_window]
            test_df = df.iloc[start + train_window:start + train_window + test_window]
            
            signal_generator = signal_generator_factory(train_df)
            
            self.reset()
            result = self.run_backtest(
                df=test_df,
                signal_generator=signal_generator,
                symbol=symbol,
                position_size=position_size,
            )
            results.append(result)
        
        return results
    
    def run_stress_test(
        self,
        df: pd.DataFrame,
        signal_generator: Callable,
        symbol: str = "",
        position_size: int = 100,
        scenarios: Optional[List[str]] = None,
    ) -> Dict[str, BacktestResult]:
        """
        压力测试回测
        
        Args:
            df: K线数据
            signal_generator: 信号生成函数
            symbol: 股票代码
            position_size: 每次交易股数
            scenarios: 压力场景列表
            
        Returns:
            Dict[str, BacktestResult]: 各场景的回测结果
        """
        if scenarios is None:
            scenarios = list(RiskCalculationConstants.CRASH_SCENARIOS.keys())
        
        results = {}
        
        for scenario in scenarios:
            if scenario not in RiskCalculationConstants.CRASH_SCENARIOS:
                continue
            
            crash_pct = RiskCalculationConstants.CRASH_SCENARIOS[scenario]
            stressed_df = df.copy()
            stressed_df["close"] = stressed_df["close"] * (1 + crash_pct)
            stressed_df["open"] = stressed_df["open"] * (1 + crash_pct)
            stressed_df["high"] = stressed_df["high"] * (1 + crash_pct)
            stressed_df["low"] = stressed_df["low"] * (1 + crash_pct)
            
            self.reset()
            result = self.run_backtest(
                df=stressed_df,
                signal_generator=signal_generator,
                symbol=symbol,
                position_size=position_size,
            )
            results[scenario] = result
        
        return results
