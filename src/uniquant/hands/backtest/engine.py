"""
[DEPRECATED] 旧版回测引擎 — 请使用 UnifiedBacktestEngine

此文件已被 unified_engine.py 中的 UnifiedBacktestEngine 替代。
新引擎特性:
  - 强类型输入: List[TradingSignal]
  - T+1 铁律: 交易日序号差检查
  - 涨跌停拦截: 主板/ST/创业板/北交所
  - 停牌拦截: volume=0 不成交
  - 资金不透支: 实时现金扣减
  - 正确滑点: 使用交易量而非日均量

迁移指南:
  旧: engine = BacktestEngine(); result = engine.run_backtest(df, signal_generator)
  新: engine = UnifiedBacktestEngine(); result = engine.run(df, signals, symbol)
"""

import warnings
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

import numpy as np
import pandas as pd

from uniquant.data.managers.trade_calendar_manager import TradeCalendarManager
from uniquant.shared.constants import BacktestConstants, RiskCalculationConstants, RANDOM_SEED
from uniquant.shared.error_handling import handle_errors
from uniquant.shared.exceptions import BacktestError
from uniquant.shared.limit_checker import check_limit_status
from uniquant.shared.logger_factory import get_logger
from .result import BacktestResult, TradeRecord
from .unified_matching_engine import UnifiedMatchingEngine

from ...shared.cost_model import TRANSFER_FEE_PCT, get_stamp_tax_pct

warnings.warn(
    "BacktestEngine is deprecated. Use UnifiedBacktestEngine from "
    "uniquant.hands.backtest.unified_engine instead.",
    DeprecationWarning,
    stacklevel=2,
)

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
        stamp_date_aware: bool = True,
        monte_carlo_seed: Optional[int] = RANDOM_SEED,
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.slippage_rate = slippage_rate
        self.min_commission = min_commission
        self.trade_calendar = trade_calendar or TradeCalendarManager()
        self.stamp_date_aware = stamp_date_aware
        self.monte_carlo_seed = monte_carlo_seed
        self.matching = UnifiedMatchingEngine(
            commission_rate=commission_rate,
            stamp_duty_rate=stamp_duty_rate,
            min_commission=min_commission,
            slippage_rate=slippage_rate,
            trade_calendar=self.trade_calendar,
        )
        
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
    
    def _calculate_commission(self, value: float, timestamp: Optional[datetime] = None, is_sell: bool = False) -> float:
        """计算交易成本"""
        commission = max(value * self.commission_rate, self.min_commission)
        stamp_duty = 0.0
        if is_sell:
            rate = get_stamp_tax_pct(timestamp.date()) if (self.stamp_date_aware and timestamp is not None) else self.stamp_duty_rate
            stamp_duty = value * rate
        transfer_fee = value * TRANSFER_FEE_PCT
        return commission + stamp_duty + transfer_fee
    
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
        """检查T+1约束 - 使用预加载的交易日序号数组 + searchsorted"""
        if buy_date is None:
            return True
        
        if not self.trade_calendar.is_trading_day(current_date):
            return False
        
        # 预加载交易日序号映射 (缓存到实例)
        if not hasattr(self, '_td_ordinal_map'):
            cal = self.trade_calendar.get_trade_calendar(
                start_date="2010-01-01", end_date="2030-12-31"
            )
            if cal.empty:
                return False
            self._td_ordinal_map = {
                pd.Timestamp(d).toordinal(): i
                for i, d in enumerate(cal['trade_date'].values)
            }
        
        buy_ord = pd.Timestamp(buy_date).toordinal()
        cur_ord = pd.Timestamp(current_date).toordinal()
        
        buy_idx = self._td_ordinal_map.get(buy_ord)
        cur_idx = self._td_ordinal_map.get(cur_ord)
        
        if buy_idx is None or cur_idx is None:
            return False
        
        return cur_idx - buy_idx >= 1
    
    def _check_limit_constraint(
        self,
        price: float,
        pre_close: float,
        action: str,
        symbol: str = "",
        name: Optional[str] = None,
    ) -> bool:
        """检查涨跌停约束"""
        limit_status = check_limit_status(price, pre_close, symbol, name)
        if action == "BUY" and limit_status.is_limit_up:
            return False
        if action == "SELL" and limit_status.is_limit_down:
            return False
        return True

    @staticmethod
    def _matching_symbol(symbol: str) -> str:
        """旧版直接 API 允许省略 symbol；撮合器内部需要可识别的 A 股板块。"""
        if not symbol:
            return "600000.SH"

        upper = symbol.upper()
        if upper.endswith((".SH", ".SZ", ".BJ")):
            return upper

        code = upper.replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
        if len(code) == 6 and code.isdigit():
            if code.startswith(("4", "8")):
                return f"{code}.BJ"
            if code.startswith(("0", "2", "3")):
                return f"{code}.SZ"
            return f"{code}.SH"

        return upper
    
    def execute_buy(
        self,
        price: float,
        shares: int,
        timestamp: datetime,
        reason: str = "",
        pre_close: float = 0,
        symbol: str = "",
        name: Optional[str] = None,
        volume: Optional[int] = None,
        avg_daily_volume: float = 0,
    ) -> Optional[TradeRecord]:
        """执行买入"""
        if shares <= 0:
            return None

        if volume is not None and volume <= 0:
            logger.debug(f"停牌无法买入: {timestamp}")
            return None

        fill = self.matching.fill_buy(
            prices=np.array([price], dtype=np.float64),
            shares_requested=np.array([shares], dtype=np.int64),
            cash_available=np.array([self.cash], dtype=np.float64),
            pre_closes=np.array([pre_close], dtype=np.float64),
            symbols=np.array([self._matching_symbol(symbol)], dtype=object),
            timestamps=np.array([pd.Timestamp(timestamp)], dtype=object),
            volumes=np.array([shares], dtype=np.float64),
            avg_daily_volumes=np.array([avg_daily_volume], dtype=np.float64),
            names=np.array([name or ""], dtype=object),
        )
        if fill.rejected_mask[0] or fill.executed_shares[0] <= 0:
            return None

        shares = int(fill.executed_shares[0])
        exec_price = float(fill.exec_prices[0])
        value = exec_price * shares
        commission = float(fill.commissions[0] + fill.transfer_fees[0])
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
            slippage=float(fill.slippages[0]),
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
        name: Optional[str] = None,
        buy_date: Optional[datetime] = None,
        volume: Optional[int] = None,
        avg_daily_volume: float = 0,
    ) -> Optional[TradeRecord]:
        """执行卖出"""
        if shares <= 0 or self.position <= 0:
            return None

        if volume is not None and volume <= 0:
            logger.debug(f"停牌无法卖出: {timestamp}")
            return None

        shares = min(shares, self.position)
        fill = self.matching.fill_sell(
            prices=np.array([price], dtype=np.float64),
            shares_requested=np.array([shares], dtype=np.int64),
            positions_held=np.array([self.position], dtype=np.int64),
            position_costs=np.array([self.position_cost], dtype=np.float64),
            pre_closes=np.array([pre_close], dtype=np.float64),
            symbols=np.array([self._matching_symbol(symbol)], dtype=object),
            timestamps=np.array([pd.Timestamp(timestamp)], dtype=object),
            buy_dates=np.array([pd.Timestamp(buy_date) if buy_date else None], dtype=object),
            volumes=np.array([shares], dtype=np.float64),
            avg_daily_volumes=np.array([avg_daily_volume], dtype=np.float64),
            names=np.array([name or ""], dtype=object),
        )
        if fill.rejected_mask[0] or fill.executed_shares[0] <= 0:
            return None

        shares = int(fill.executed_shares[0])
        exec_price = float(fill.exec_prices[0])
        value = exec_price * shares
        commission = float(
            fill.commissions[0] + fill.stamp_duties[0] + fill.transfer_fees[0]
        )

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
            slippage=float(fill.slippages[0]),
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
        name: Optional[str] = None,
        position_size: int = 100,
    ) -> BacktestResult:
        """
        运行回测
        
        Args:
            df: K线数据，必须包含 date, open, high, low, close 列
            signal_generator: 信号生成函数，返回 {"action": "BUY"/"SELL"/"HOLD", "reason": "..."}
            symbol: 股票代码
            name: 股票名称（用于 ST 识别）
            position_size: 每次交易股数
            
        Returns:
            BacktestResult: 回测结果
        """
        self.reset()
        
        required_cols = {"date", "open", "high", "low", "close", "volume"}
        missing = required_cols - set(df.columns)
        if missing:
            raise BacktestError(f"缺少必需列: {missing}")
        
        if "pre_close" not in df.columns or "avg_daily_volume" not in df.columns:
            df = df.copy()
            if "pre_close" not in df.columns:
                df["pre_close"] = df["close"].shift(1)
                df["pre_close"] = df["pre_close"].fillna(df["open"])
            if "avg_daily_volume" not in df.columns:
                df["avg_daily_volume"] = df["volume"].rolling(20).mean().fillna(0)
        
        dates_arr = pd.to_datetime(df["date"]).values
        opens_arr = df["open"].values.astype(np.float64)
        closes_arr = df["close"].values.astype(np.float64)
        volumes_arr = df["volume"].values.astype(np.float64)
        pre_close_arr = df["pre_close"].values.astype(np.float64)
        avg_daily_vol_arr = df["avg_daily_volume"].values.astype(np.float64)
        
        dates = pd.to_datetime(df["date"])
        start_date = dates.iloc[0]
        end_date = dates.iloc[-1]
        
        buy_date = None

        pending_order = None

        for idx in range(len(df)):
            current_price = closes_arr[idx]

            if pending_order is not None:
                exec_price = opens_arr[idx]
                exec_ts = pd.Timestamp(dates_arr[idx])

                if pending_order["action"] == "BUY":
                    pre_close_next = pre_close_arr[idx]
                    trade = self.execute_buy(
                        price=exec_price,
                        shares=pending_order["size"],
                        timestamp=exec_ts,
                        reason=pending_order["reason"],
                        pre_close=pre_close_next,
                        symbol=symbol,
                        name=name,
                        volume=int(volumes_arr[idx]),
                        avg_daily_volume=float(avg_daily_vol_arr[idx]),
                    )
                    if trade:
                        buy_date = exec_ts

                elif pending_order["action"] == "SELL":
                    pre_close_next = pre_close_arr[idx]
                    trade = self.execute_sell(
                        price=exec_price,
                        shares=pending_order["size"],
                        timestamp=exec_ts,
                        reason=pending_order["reason"],
                        pre_close=pre_close_next,
                        symbol=symbol,
                        name=name,
                        buy_date=pending_order["buy_date"],
                        volume=int(volumes_arr[idx]),
                        avg_daily_volume=float(avg_daily_vol_arr[idx]),
                    )
                    if trade:
                        buy_date = None

                pending_order = None

            self.update_equity(current_price)

            signal = signal_generator(df, idx, {
                "position": self.position,
                "position_cost": self.position_cost,
                "cash": self.cash,
            })

            action = signal.get("action", "HOLD")
            reason = signal.get("reason", "")
            next_idx = idx + 1

            if action in ("BUY", "SELL", "ADD") and next_idx < len(df):
                if action in ("BUY", "ADD") and self.position == 0:
                    pending_order = {
                        "action": "BUY",
                        "size": position_size,
                        "reason": reason,
                    }
                elif action == "SELL" and self.position > 0:
                    pending_order = {
                        "action": "SELL",
                        "size": self.position,
                        "reason": reason,
                        "buy_date": buy_date,
                    }
        
        result = BacktestResult(
            initial_capital=self.initial_capital,
            trades=self.trades,
            equity_curve=self.equity_curve,
            daily_returns=self.daily_returns,
            start_date=start_date.to_pydatetime(),
            end_date=end_date.to_pydatetime(),
        )
        result.calculate_metrics()

        try:
            from .overfitting_detector import OverfittingDetector
            from .monte_carlo import MonteCarloSimulator
            import scipy.stats as scipy_stats

            if len(self.trades) >= 20:
                returns_arr = np.array(self.daily_returns, dtype=np.float64)
                n_obs = len(returns_arr)
                if n_obs > 1 and np.std(returns_arr) > 0:
                    detector = OverfittingDetector()
                    sharpe = result.sharpe_ratio
                    skewness = float(scipy_stats.skew(returns_arr))
                    kurtosis = float(scipy_stats.kurtosis(returns_arr, fisher=False))
                    dsr = detector.deflated_sharpe_ratio(
                        observed_sharpe=sharpe,
                        n_trials=100,
                        num_observations=n_obs,
                        skewness=skewness,
                        kurtosis=kurtosis,
                    )
                    mdd_p = detector.mdd_p_value(result.max_drawdown, n_obs)
                    result.overfitting_metrics = {
                        "dsr": dsr,
                        "mdd_p_value": mdd_p,
                        "num_trials": 100,
                        "num_observations": n_obs,
                    }
                if n_obs >= 10:
                    mc = MonteCarloSimulator(
                        n_simulations=200,
                        seed=self.monte_carlo_seed,
                    )
                    result.metadata["monte_carlo_seed"] = self.monte_carlo_seed
                    result.metadata["monte_carlo_shuffle"] = mc.run_shuffle(
                        pd.Series(self.daily_returns)
                    )
                    result.metadata["monte_carlo_bootstrap"] = mc.run_bootstrap(
                        pd.Series(self.equity_curve)
                    )
        except Exception:
            logger.exception("Monte Carlo 引导分析失败，跳过")
            pass

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
        name: Optional[str] = None,
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
            name: 股票名称
            
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
                name=name,
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
        name: Optional[str] = None,
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
            name: 股票名称
            
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
                name=name,
                position_size=position_size,
            )
            results.append(result)

        try:
            if len(results) >= 2:
                from .robustness_checker import RobustnessChecker
                checker = RobustnessChecker()
                combined = np.concatenate([r.daily_returns for r in results if r.daily_returns])
                if len(combined) > 0:
                    consistency = checker.check_subperiod_consistency(
                        pd.Series(combined), n_splits=len(results)
                    )
                    for r in results:
                        r.metadata["robustness"] = consistency
        except Exception:
            logger.exception("稳健性检查失败，跳过")
            pass

        return results
    
    def run_stress_test(
        self,
        df: pd.DataFrame,
        signal_generator: Callable,
        symbol: str = "",
        position_size: int = 100,
        scenarios: Optional[List[str]] = None,
        name: Optional[str] = None,
    ) -> Dict[str, BacktestResult]:
        """
        压力测试回测
        
        Args:
            df: K线数据
            signal_generator: 信号生成函数
            symbol: 股票代码
            position_size: 每次交易股数
            scenarios: 压力场景列表
            name: 股票名称
            
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
                name=name,
                position_size=position_size,
            )
            results[scenario] = result

        return results

    def run_historical_stress_test(
        self,
        df: pd.DataFrame,
        signal_generator: Callable,
        historical_returns: np.ndarray,
        symbol: str = "",
        position_size: int = 100,
        name: Optional[str] = None,
    ) -> BacktestResult:
        crash_len = min(len(historical_returns), len(df))
        crash_df = df.iloc[:crash_len].copy()
        crash_df.reset_index(drop=True, inplace=True)
        cum_ret = np.cumprod(1 + historical_returns[:crash_len])
        base_close = float(crash_df["close"].iloc[0])
        crash_df["close"] = base_close * cum_ret
        crash_df["open"] = crash_df["close"] * 0.99
        crash_df["high"] = np.maximum(crash_df["close"], crash_df["open"]) * 1.01
        crash_df["low"] = np.minimum(crash_df["close"], crash_df["open"]) * 0.99
        if "pre_close" in crash_df.columns:
            crash_df["pre_close"] = crash_df["close"].shift(1).fillna(crash_df["close"].iloc[0])
        self.reset()
        return self.run_backtest(crash_df, signal_generator, symbol, name, position_size)
