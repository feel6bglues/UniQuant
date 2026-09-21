"""
Tests for UnifiedBacktestEngine limit-down sell mandatory rollover (RETRYING state machine)
and execution invariants (INV-6, INV-3).
"""

import pandas as pd

from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
from uniquant.shared.interfaces import TradingSignal


def _create_daily_bars(dates, opens, highs, lows, closes, volumes, pre_closes=None):
    if pre_closes is None:
        pre_closes = [opens[0]] + list(closes[:-1])
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "pre_close": pre_closes,
        "avg_daily_volume": [1_000_000.0] * len(dates),
    })


class TestLimitDownRolloverStateMachine:
    """验证跌停拒卖结转状态机 (RETRYING) 与互斥排队保护 (INV-6)"""

    def test_limit_down_sell_rolls_over_and_fills_when_unlocked(self):
        """
        场景:
        - Day 0 (2024-01-02): 发出 BUY 信号
        - Day 1 (2024-01-03): 买入成交 100 股 (开盘 10.0), 收盘发出 SELL 信号
        - Day 2 (2024-01-04): 跌停开盘 (开盘 9.0, 跌停拒卖) -> 进入 RETRYING 状态
        - Day 3 (2024-01-05): 跌停打开 (开盘 9.2) -> RETRYING 挂单开盘成交，仓位清零！
        """
        dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
        # 主板跌停 10%: pre_close=10.0 -> limit_down = 9.0
        opens = [10.0, 10.0, 9.0, 9.2, 9.5]
        highs = [10.2, 10.2, 9.0, 9.4, 9.6]
        lows = [9.8, 9.9, 9.0, 9.1, 9.4]
        closes = [10.0, 10.0, 9.0, 9.3, 9.5]
        volumes = [500_000] * 5
        pre_closes = [10.0, 10.0, 10.0, 9.0, 9.3]

        df = _create_daily_bars(dates, opens, highs, lows, closes, volumes, pre_closes)

        # 仅在 Day 0 发 BUY，Day 1 发 SELL（后续不再补发 SELL 信号，验证自动结转）
        signals = [
            TradingSignal(
                symbol="600000.SH",
                action="BUY",
                shares=100,
                timestamp=pd.Timestamp("2024-01-02"),
                reason="buy_signal",
            ),
            TradingSignal(
                symbol="600000.SH",
                action="SELL",
                shares=100,
                timestamp=pd.Timestamp("2024-01-03"),
                reason="sell_signal",
            ),
        ]

        engine = UnifiedBacktestEngine(initial_capital=100_000.0)
        result = engine.run(df=df, signals=signals, symbol="600000.SH")

        assert result is not None
        # 应包含 1 笔买入 + 1 笔结转后成功卖出
        assert len(result.trades) == 2
        buy_trade = result.trades[0]
        sell_trade = result.trades[1]

        assert buy_trade.action == "BUY"
        assert buy_trade.timestamp == pd.Timestamp("2024-01-03")

        assert sell_trade.action == "SELL"
        # 验证结转到 Day 3 (2024-01-05) 成交
        assert sell_trade.timestamp == pd.Timestamp("2024-01-05")
        # 最终持仓清零，现金与权益正常闭包
        assert result.final_cash > 0
        assert result.equity_curve[-1] > 0

    def test_mutex_queue_protection_blocks_buy_while_retrying(self):
        """
        场景:
        - 标的正处于跌停结转状态 (RETRYING)
        - 策略新发出 BUY 信号
        - 撮合引擎坚决拦截新 BUY 信号，防止持仓错乱覆写
        """
        dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
        opens = [10.0, 10.0, 9.0, 9.5]
        highs = [10.2, 10.2, 9.0, 9.6]
        lows = [9.8, 9.9, 9.0, 9.4]
        closes = [10.0, 10.0, 9.0, 9.5]
        volumes = [500_000] * 4
        pre_closes = [10.0, 10.0, 10.0, 9.0]

        df = _create_daily_bars(dates, opens, highs, lows, closes, volumes, pre_closes)

        signals = [
            TradingSignal(
                symbol="600000.SH",
                action="BUY",
                shares=100,
                timestamp=pd.Timestamp("2024-01-02"),
            ),
            TradingSignal(
                symbol="600000.SH",
                action="SELL",
                shares=100,
                timestamp=pd.Timestamp("2024-01-03"),
            ),
            # Day 2 跌停日，策略错误发出了 BUY 信号，应被互斥排队机制丢弃
            TradingSignal(
                symbol="600000.SH",
                action="BUY",
                shares=200,
                timestamp=pd.Timestamp("2024-01-04"),
            ),
        ]

        engine = UnifiedBacktestEngine(initial_capital=100_000.0)
        result = engine.run(df=df, signals=signals, symbol="600000.SH")

        assert len(result.trades) == 2
        # 第一笔 BUY (100股)
        assert result.trades[0].shares == 100
        # 第二笔 SELL (100股结转后成功卖出)
        assert result.trades[1].action == "SELL"
        assert result.trades[1].timestamp == pd.Timestamp("2024-01-05")
        # 没有任何新的 BUY (200股) 被执行

    def test_buy_limit_up_auto_cancels_without_rollover(self):
        """
        场景:
        - 买单涨停被拒 (INV-3) -> 立即作废 (Auto-Cancel)，次日决不自动追高
        """
        dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
        # Day 1: 开盘涨停 11.0 (pre_close=10.0)
        opens = [10.0, 11.0, 10.5]
        highs = [10.0, 11.0, 10.8]
        lows = [10.0, 11.0, 10.2]
        closes = [10.0, 11.0, 10.5]
        volumes = [500_000] * 3
        pre_closes = [10.0, 10.0, 11.0]

        df = _create_daily_bars(dates, opens, highs, lows, closes, volumes, pre_closes)

        signals = [
            TradingSignal(
                symbol="600000.SH",
                action="BUY",
                shares=100,
                timestamp=pd.Timestamp("2024-01-02"),
            ),
        ]

        engine = UnifiedBacktestEngine(initial_capital=100_000.0)
        result = engine.run(df=df, signals=signals, symbol="600000.SH")

        # 涨停拒绝后作废，无任何成交
        assert len(result.trades) == 0

    def test_limit_down_reaches_max_retry_cap(self):
        """
        场景:
        - 连续超过30个交易日跌停 (极端流动性踩踏)
        - 结转达到 30 次上限后，挂单被自动清理，不再无限结转
        """
        n_days = 50
        dates = pd.date_range("2024-01-02", periods=n_days, freq="B").strftime("%Y-%m-%d").tolist()
        opens = [10.0, 10.0] + [9.0] * (n_days - 2)
        highs = [10.2, 10.2] + [9.0] * (n_days - 2)
        lows = [9.8, 9.9] + [9.0] * (n_days - 2)
        closes = [10.0, 10.0] + [9.0] * (n_days - 2)
        volumes = [500_000] * n_days
        pre_closes = [10.0, 10.0, 10.0] + [10.0] * (n_days - 3)

        df = _create_daily_bars(dates, opens, highs, lows, closes, volumes, pre_closes)

        signals = [
            TradingSignal(
                symbol="600000.SH",
                action="BUY",
                shares=100,
                timestamp=pd.Timestamp(dates[0]),
            ),
            TradingSignal(
                symbol="600000.SH",
                action="SELL",
                shares=100,
                timestamp=pd.Timestamp(dates[1]),
            ),
        ]

        engine = UnifiedBacktestEngine(initial_capital=100_000.0)
        result = engine.run(df=df, signals=signals, symbol="600000.SH")

        # 初始买单成交 (Day 0) + 达到30日上限终局坏账清退 (Day 31 0元清算)
        assert len(result.trades) == 2
        assert result.trades[0].action == "BUY"
        assert result.trades[1].action == "SELL"
        assert result.trades[1].price == 0.0
        assert result.trades[1].reason == "BAD_DEBT_LIMIT_DOWN_30D_EXPIRED"
        # 确认账户不再持有任何该标的持仓
        assert result.trades[1].shares == 100
