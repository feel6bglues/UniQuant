import pytest
from datetime import datetime
import pandas as pd
import numpy as np

from uniquant.hands.backtest.engine import BacktestEngine
from uniquant.hands.backtest.result import BacktestResult, TradeRecord
from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine


class FakeTradeCalendarManager:
    def __init__(self, trading_days=None):
        self._trading_days = trading_days or []

    def get_trade_calendar(self, start_date, end_date):
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        days = [d for d in self._trading_days if start <= d <= end]
        return pd.DataFrame({"trade_date": days})

    def is_trading_day(self, date):
        return date in self._trading_days


class TestTradeRecord:
    """TradeRecord 测试"""
    
    def test_trade_record_creation(self):
        """测试交易记录创建"""
        record = TradeRecord(
            timestamp=datetime(2024, 1, 15, 9, 30),
            action="BUY",
            price=10.5,
            shares=100,
            commission=5.0,
            slippage=0.01,
        )
        assert record.action == "BUY"
        assert record.price == 10.5
        assert record.shares == 100
    
    def test_trade_record_to_dict(self):
        """测试交易记录转字典"""
        record = TradeRecord(
            timestamp=datetime(2024, 1, 15),
            action="SELL",
            price=11.0,
            shares=100,
            commission=5.5,
            slippage=0.01,
            pnl=50.0,
            pnl_pct=0.05,
        )
        d = record.to_dict()
        assert d["action"] == "SELL"
        assert d["pnl"] == 50.0
        assert d["pnl_pct"] == 0.05


class TestBacktestResult:
    """BacktestResult 测试"""
    
    def test_result_creation(self):
        """测试回测结果创建"""
        result = BacktestResult(initial_capital=100000.0)
        assert result.initial_capital == 100000.0
        assert result.total_trades == 0
    
    def test_calculate_metrics_empty(self):
        """测试空交易统计"""
        result = BacktestResult()
        result.calculate_metrics()
        assert result.total_trades == 0
        assert result.win_rate == 0
    
    def test_calculate_metrics_with_trades(self):
        """测试有交易的统计"""
        result = BacktestResult(initial_capital=100000.0)
        result.trades = [
            TradeRecord(datetime(2024, 1, 10), "BUY", 10.0, 100, 5.0, 0.01),
            TradeRecord(datetime(2024, 1, 15), "SELL", 11.0, 100, 5.5, 0.01, pnl=50.0, pnl_pct=0.05),
            TradeRecord(datetime(2024, 1, 20), "BUY", 12.0, 100, 6.0, 0.01),
            TradeRecord(datetime(2024, 1, 25), "SELL", 11.0, 100, 5.5, 0.01, pnl=-50.0, pnl_pct=-0.04),
        ]
        result.equity_curve = [100000, 100500, 100000, 99500]
        result.daily_returns = [0, 0.005, -0.005, -0.005]
        result.calculate_metrics()
        
        assert result.total_trades == 2
        assert result.winning_trades == 1
        assert result.losing_trades == 1
        assert result.win_rate == 0.5
    
    def test_to_dict(self):
        """测试转字典"""
        result = BacktestResult(
            initial_capital=100000.0,
            final_capital=110000.0,
            total_return=0.1,
        )
        d = result.to_dict()
        assert d["initial_capital"] == 100000.0
        assert d["total_return"] == 0.1
    
    def test_to_dataframe(self):
        """测试转DataFrame"""
        result = BacktestResult()
        result.trades = [
            TradeRecord(datetime(2024, 1, 10), "BUY", 10.0, 100, 5.0, 0.01),
        ]
        df = result.to_dataframe()
        assert len(df) == 1
        assert "action" in df.columns
    
    def test_generate_report(self):
        """测试生成报告"""
        result = BacktestResult(
            initial_capital=100000.0,
            final_capital=110000.0,
            total_return=0.1,
            max_drawdown=0.05,
            sharpe_ratio=1.5,
            total_trades=10,
            win_rate=0.6,
        )
        report = result.generate_report()
        assert "回测报告" in report
        assert "10.00%" in report


class TestBacktestEngine:
    """BacktestEngine 测试"""
    
    @pytest.fixture
    def engine(self):
        return BacktestEngine(initial_capital=100000.0)
    
    @pytest.fixture
    def sample_df(self):
        """创建测试数据"""
        dates = pd.date_range(start="2024-01-01", periods=100, freq="D")
        np.random.seed(42)
        close = 10 + np.cumsum(np.random.randn(100) * 0.1)
        df = pd.DataFrame({
            "date": dates,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": np.random.randint(100000, 500000, 100),
        })
        return df
    
    def test_engine_creation(self, engine):
        """测试引擎创建"""
        assert engine.initial_capital == 100000.0
        assert engine.cash == 100000.0
        assert engine.position == 0
    
    def test_reset(self, engine):
        """测试重置"""
        engine.cash = 50000
        engine.position = 100
        engine.reset()
        assert engine.cash == 100000.0
        assert engine.position == 0
    
    def test_calculate_commission(self):
        """测试佣金计算"""
        me = UnifiedMatchingEngine(commission_rate=0.0003, min_commission=5.0, stamp_duty_rate=0.001)
        fill = me.fill_buy(
            np.array([10.0]), np.array([1000]), np.array([50000.0]),
            np.array([9.9]), np.array(["000001.SZ"]), np.array(["2024-01-02"]),
            np.array([100000.0]), np.array([500000.0]),
        )
        assert fill.commissions[0] >= 5.0
    
    def test_calculate_slippage(self):
        """测试滑点计算"""
        me = UnifiedMatchingEngine(slippage_rate=0.001)
        fill = me.fill_buy(
            np.array([10.0]), np.array([100]), np.array([5000.0]),
            np.array([9.9]), np.array(["000001.SZ"]), np.array(["2024-01-02"]),
            np.array([1000.0]), np.array([10000.0]),
        )
        assert fill.exec_prices[0] > 10.0
        assert fill.exec_prices[0] < 10.5
    
    def test_execute_buy(self, engine):
        """测试买入执行"""
        trade = engine.execute_buy(
            price=10.0,
            shares=100,
            timestamp=datetime(2024, 1, 10),
            reason="测试买入",
        )
        assert trade is not None
        assert trade.action == "BUY"
        assert engine.position == 100
        assert engine.cash < 100000.0
    
    def test_execute_buy_insufficient_cash(self, engine):
        """测试资金不足买入"""
        trade = engine.execute_buy(
            price=10000.0,
            shares=100,
            timestamp=datetime(2024, 1, 10),
        )
        assert trade is None or engine.position < 100
    
    def test_execute_sell(self):
        """测试卖出执行"""
        me = UnifiedMatchingEngine(
            min_commission=5.0, stamp_duty_rate=0.001,
            trade_calendar=FakeTradeCalendarManager([
                datetime(2023, 12, 1),
                datetime(2024, 1, 2),
            ]),
        )
        fill = me.fill_sell(
            np.array([10.0]), np.array([100]), np.array([100]),
            np.array([9.0]), np.array([10.0]), np.array(["000001.SZ"]),
            np.array([pd.Timestamp("2024-01-02")]), np.array([pd.Timestamp("2023-12-01")]),
            np.array([1000.0]), np.array([10000.0]),
        )
        assert not fill.rejected_mask[0]
        assert fill.executed_shares[0] == 100
    
    def test_execute_sell_t1_constraint(self, engine):
        """测试T+1约束"""
        engine.execute_buy(price=10.0, shares=100, timestamp=datetime(2024, 1, 10))
        
        trade = engine.execute_sell(
            price=11.0,
            shares=100,
            timestamp=datetime(2024, 1, 10),
            buy_date=datetime(2024, 1, 10),
        )
        assert trade is None
    
    def test_execute_sell_limit_down(self, engine):
        """测试跌停无法卖出"""
        engine.execute_buy(price=10.0, shares=100, timestamp=datetime(2024, 1, 10))
        
        trade = engine.execute_sell(
            price=9.0,
            shares=100,
            timestamp=datetime(2024, 1, 15),
            pre_close=10.0,
            buy_date=datetime(2024, 1, 10),
        )
        assert trade is None
    
    def test_update_equity(self, engine):
        """测试权益更新"""
        equity = engine.update_equity(10.0)
        assert equity == 100000.0
        
        engine.execute_buy(price=10.0, shares=1000, timestamp=datetime(2024, 1, 10))
        equity = engine.update_equity(11.0)
        assert equity > 100000.0
    
    def test_run_backtest_simple(self, engine, sample_df):
        """测试简单回测"""
        def simple_signal(df, idx, state):
            if idx < 20:
                return {"action": "HOLD"}
            
            ma20 = df["close"].iloc[idx-20:idx].mean()
            price = df["close"].iloc[idx]
            
            if price > ma20 and state["position"] == 0:
                return {"action": "BUY", "reason": "突破MA20"}
            elif price < ma20 and state["position"] > 0:
                return {"action": "SELL", "reason": "跌破MA20"}
            return {"action": "HOLD"}
        
        result = engine.run_backtest(sample_df, simple_signal)
        
        assert isinstance(result, BacktestResult)
        assert result.start_date is not None
        assert result.end_date is not None
    
    def test_run_backtest_with_limit_check(self, engine, sample_df):
        """测试带涨跌停检查的回测"""
        def signal_with_limit(df, idx, state):
            if idx < 5:
                return {"action": "HOLD"}
            
            pre_close = df["close"].iloc[idx-1]
            price = df["close"].iloc[idx]
            
            if state["position"] == 0 and price < pre_close * 0.95:
                return {"action": "BUY", "reason": "低吸"}
            elif state["position"] > 0 and price > pre_close * 1.05:
                return {"action": "SELL", "reason": "高抛"}
            return {"action": "HOLD"}
        
        result = engine.run_backtest(sample_df, signal_with_limit, symbol="600000.SH")
        assert isinstance(result, BacktestResult)
    
    def test_run_rolling_backtest(self, engine, sample_df):
        """测试滚动回测"""
        def simple_signal(df, idx, state):
            return {"action": "HOLD"}
        
        results = engine.run_rolling_backtest(
            sample_df,
            simple_signal,
            train_window=50,
            test_window=20,
        )
        
        assert isinstance(results, list)
    
    def test_run_stress_test(self, engine, sample_df):
        """测试压力测试"""
        def simple_signal(df, idx, state):
            return {"action": "HOLD"}
        
        results = engine.run_stress_test(
            sample_df,
            simple_signal,
            scenarios=["market_crash_2015"],
        )
        
        assert "market_crash_2015" in results
        assert isinstance(results["market_crash_2015"], BacktestResult)


class TestBacktestIntegration:
    """回测集成测试"""
    
    def test_full_backtest_cycle(self):
        """测试完整回测周期"""
        engine = BacktestEngine(initial_capital=100000.0)
        
        dates = pd.date_range(start="2024-01-01", periods=200, freq="D")
        np.random.seed(42)
        close = 10 + np.cumsum(np.random.randn(200) * 0.1)
        df = pd.DataFrame({
            "date": dates,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": np.random.randint(100000, 500000, 200),
        })
        
        def ma_strategy(df, idx, state):
            if idx < 60:
                return {"action": "HOLD"}
            
            ma20 = df["close"].iloc[idx-20:idx].mean()
            ma60 = df["close"].iloc[idx-60:idx].mean()
            
            if ma20 > ma60 and state["position"] == 0:
                return {"action": "BUY", "reason": "MA金叉"}
            elif ma20 < ma60 and state["position"] > 0:
                return {"action": "SELL", "reason": "MA死叉"}
            return {"action": "HOLD"}
        
        result = engine.run_backtest(df, ma_strategy)
        
        assert result.initial_capital == 100000.0
        assert len(result.equity_curve) == 200
        
        report = result.generate_report()
        assert "回测报告" in report
