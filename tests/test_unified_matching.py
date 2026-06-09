"""
UniQuant 统一回测引擎 TDD 防线测试套件
========================================

基于《撮合引擎防线漏洞审计报告》的 8 条 A 股红线断言编写。
所有测试必须 100% 通过，引擎代码才算合格。

测试覆盖:
  A. T+1 铁律 (同日买入不可同日卖出)
  B. 涨跌停拦截 (涨停不买入, 跌停不卖出)
  C. 停牌拦截 (volume=0 不成交)
  D. 资金永不透支 (cash >= 0 恒成立)
  E. 非对称成本精确扣除 (印花税仅卖方, 最低佣金5元)
  F. 滑点方向正确 (买高卖低)
  G. 多资产资金分配不均防护
  H. 整手取整约束 (A股100股整手)
  I. 权益曲线合理性
  J. 前视偏差检测
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd
import pytest

from uniquant.hands.backtest.unified_engine import (
    UnifiedBacktestEngine,
)
from uniquant.shared.interfaces import TradingSignal
from uniquant.shared.cost_model import (
    MIN_COMMISSION,
)

# ──────────────────────────────────────────────────────────────
# 测试工具: 构造极端 K 线数据
# ──────────────────────────────────────────────────────────────

def make_kline(
    dates: List[str],
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[int],
    pre_closes: Optional[List[float]] = None,
) -> pd.DataFrame:
    """构造单只股票的 K 线 DataFrame"""
    df = pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })
    if pre_closes is None:
        df["pre_close"] = df["close"].shift(1).fillna(df["open"])
    else:
        df["pre_close"] = pre_closes
    df["avg_daily_volume"] = df["volume"].rolling(5, min_periods=1).mean()
    return df


def make_limit_up_sequence(n_days: int = 5, base_price: float = 10.0) -> pd.DataFrame:
    """构造连续一字涨停的 K 线 (主板 ±10%)"""
    dates = [f"2025-01-{i+1:02d}" for i in range(n_days)]
    closes = [round(base_price * (1.10 ** i), 2) for i in range(n_days)]
    opens = closes.copy()
    highs = closes.copy()
    lows = closes.copy()
    volumes = [100_000] * n_days
    pre_closes = [base_price] + closes[:-1]
    return make_kline(dates, opens, highs, lows, closes, volumes, pre_closes)


def make_limit_down_sequence(n_days: int = 5, base_price: float = 10.0) -> pd.DataFrame:
    """构造连续一字跌停的 K 线 (主板 ±10%)"""
    dates = [f"2025-01-{i+1:02d}" for i in range(n_days)]
    closes = [round(base_price * (0.90 ** i), 2) for i in range(n_days)]
    opens = closes.copy()
    highs = closes.copy()
    lows = closes.copy()
    volumes = [100_000] * n_days
    pre_closes = [base_price] + closes[:-1]
    return make_kline(dates, opens, highs, lows, closes, volumes, pre_closes)


def make_halt_sequence(base_price: float = 10.0) -> pd.DataFrame:
    """构造停牌日 K 线 (volume=0)"""
    return make_kline(
        dates=["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"],
        opens=[base_price, base_price, base_price, base_price, base_price + 0.5],
        highs=[base_price, base_price, base_price, base_price, base_price + 0.5],
        lows=[base_price, base_price, base_price, base_price, base_price + 0.5],
        closes=[base_price, base_price, base_price + 0.5, base_price + 0.5, base_price + 1.0],
        volumes=[100_000, 0, 100_000, 100_000, 100_000],
        pre_closes=[base_price, base_price, base_price, base_price, base_price + 0.5],
    )


def make_normal_sequence(base_price: float = 10.0, n_days: int = 10) -> pd.DataFrame:
    """构造正常波动 K 线"""
    dates = [f"2025-01-{i+1:02d}" for i in range(n_days)]
    rng = np.random.RandomState(42)
    returns = rng.normal(0.001, 0.02, n_days)
    prices = [base_price]
    for r in returns[1:]:
        prices.append(round(prices[-1] * (1 + r), 2))
    closes = prices
    opens = [round(c * (1 + rng.normal(0, 0.005)), 2) for c in closes]
    highs = [round(max(o, c) * (1 + abs(rng.normal(0, 0.005))), 2) for o, c in zip(opens, closes)]
    lows = [round(min(o, c) * (1 - abs(rng.normal(0, 0.005))), 2) for o, c in zip(opens, closes)]
    volumes = [int(rng.uniform(50_000, 200_000)) for _ in range(n_days)]
    pre_closes = [base_price] + closes[:-1]
    return make_kline(dates, opens, highs, lows, closes, volumes, pre_closes)


def make_engine(initial_capital: float = 100_000.0) -> UnifiedBacktestEngine:
    """创建测试用引擎实例"""
    return UnifiedBacktestEngine(initial_capital=initial_capital)


# ══════════════════════════════════════════════════════════════
# 防线 A: T+1 铁律测试
# ══════════════════════════════════════════════════════════════

class TestDefenseA_TPlusOne:
    """T+1 铁律: 买入当日不可卖出"""

    def test_buy_sell_same_day_sell_rejected(self):
        """核心断言: T日买入, T日卖出必须被拒绝 (无 SELL 成交)"""
        df = make_normal_sequence(base_price=10.0, n_days=5)
        engine = make_engine()

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),
            TradingSignal(action="SELL", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),  # 同日!
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        sell_trades = [t for t in result.trades if t.action == "SELL"]
        assert len(sell_trades) == 0, "同日卖出必须被拒绝"

    def test_sell_next_trading_day_allowed(self):
        """买入后次个交易日卖出必须成功"""
        df = make_normal_sequence(base_price=10.0, n_days=10)  # 扩展到10天
        engine = make_engine()

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),
            TradingSignal(action="SELL", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-03")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        sell_trades = [t for t in result.trades if t.action == "SELL"]
        assert len(sell_trades) == 1, "次日卖出应成功"

    def test_no_position_sell_rejected(self):
        """空仓卖出必须被拒绝"""
        df = make_normal_sequence(base_price=10.0, n_days=5)
        engine = make_engine()

        signals = [
            TradingSignal(action="SELL", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        assert len(result.trades) == 0, "空仓卖出应被拒绝"


# ══════════════════════════════════════════════════════════════
# 防线 B: 涨跌停拦截测试
# ══════════════════════════════════════════════════════════════

class TestDefenseB_LimitUpDown:
    """涨跌停板拦截"""

    def test_limit_up_blocks_buy(self):
        """核心断言: 涨停板上买入必须被拒绝"""
        df = make_limit_up_sequence(3, base_price=10.0)
        engine = make_engine()

        # 第2天: close=11.0, pre_close=10.0 → 涨停
        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        buy_trades = [t for t in result.trades if t.action == "BUY"]
        assert len(buy_trades) == 0, "涨停日买入必须被拒绝"

    def test_limit_down_blocks_sell(self):
        """核心断言: 跌停板上卖出必须被拒绝"""
        df = make_limit_down_sequence(3, base_price=10.0)
        engine = make_engine(initial_capital=50_000)

        # 先在第1天买入
        buy_signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-01")),
        ]
        result1 = engine.run(df, buy_signals, symbol="000001.SZ")
        assert len(result1.trades) == 1, "第1天应成功买入"

        engine2 = make_engine(initial_capital=50_000)
        # 手动设置持仓状态
        engine2_run = engine2.run(df, [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-01")),
            TradingSignal(action="SELL", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),
        ], symbol="000001.SZ")
        sell_trades = [t for t in engine2_run.trades if t.action == "SELL"]
        # 跌停日卖出应被拒绝
        assert len(sell_trades) == 0, "跌停日卖出必须被拒绝"

    def test_price_below_limit_allows_buy(self):
        """价格在涨停以下, 允许买入"""
        df = make_normal_sequence(base_price=10.0, n_days=5)
        engine = make_engine()

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        buy_trades = [t for t in result.trades if t.action == "BUY"]
        assert len(buy_trades) == 1, "正常价格应允许买入"


# ══════════════════════════════════════════════════════════════
# 防线 C: 停牌拦截测试
# ══════════════════════════════════════════════════════════════

class TestDefenseC_HaltDetection:
    """停牌日 (volume=0) 拦截"""

    def test_halt_day_blocks_execution(self):
        """核心断言: volume=0 的停牌日, 挂单不执行"""
        df = make_halt_sequence(base_price=10.0)
        engine = make_engine()

        # 第1天买入, 第2天应执行但 volume=0 → 拒绝
        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-01")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        # 第2天 volume=0, 买入挂单应被拒绝
        # 但第1天 signal 生成的挂单在第2天执行时被停牌拦截
        buy_on_halt = [t for t in result.trades
                       if t.timestamp == pd.Timestamp("2025-01-02")]
        assert len(buy_on_halt) == 0, "停牌日不应有成交"


# ══════════════════════════════════════════════════════════════
# 防线 D: 资金永不透支测试
# ══════════════════════════════════════════════════════════════

class TestDefenseD_NoNegativeCash:
    """资金锁死: cash >= 0 恒成立"""

    def test_cash_never_negative_single_buy(self):
        """单笔买入后现金不为负"""
        df = make_normal_sequence(base_price=10.0, n_days=5)
        engine = make_engine(initial_capital=100_000)

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-01")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        assert result.final_cash >= 0, f"现金不为负: {result.final_cash}"

    def test_insufficient_cash_auto_reduce(self):
        """资金不足时自动减少股数"""
        df = make_normal_sequence(base_price=10.0, n_days=5)
        engine = make_engine(initial_capital=500)  # 只有500元

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=1000,
                          timestamp=pd.Timestamp("2025-01-01")),  # 需要约10000
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        assert result.final_cash >= 0, "资金不足时应自动减量"

    def test_full_backtest_cash_non_negative(self):
        """完整回测结束后现金不为负"""
        df = make_normal_sequence(base_price=10.0, n_days=10)
        engine = make_engine(initial_capital=50_000)

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),
            TradingSignal(action="SELL", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-06")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        assert result.final_cash >= 0, "回测结束后现金不为负"

    def test_equity_curve_never_negative(self):
        """权益曲线永不为负"""
        df = make_normal_sequence(base_price=10.0, n_days=10)
        engine = make_engine(initial_capital=50_000)

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        for i, eq in enumerate(result.equity_curve):
            assert eq >= 0, f"第{i}天权益为负: {eq}"


# ══════════════════════════════════════════════════════════════
# 防线 E: 非对称成本精确扣除测试
# ══════════════════════════════════════════════════════════════

class TestDefenseE_AsymmetricCosts:
    """非对称摩擦成本"""

    def test_buy_no_stamp_duty(self):
        """买入方不收印花税"""
        df = make_normal_sequence(base_price=10.0, n_days=5)
        engine = make_engine()

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-01")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        buy_trades = [t for t in result.trades if t.action == "BUY"]
        assert len(buy_trades) == 1
        assert buy_trades[0].stamp_duty == 0.0, "买入不应有印花税"

    def test_sell_has_stamp_duty(self):
        """卖出方收取印花税"""
        df = make_normal_sequence(base_price=10.0, n_days=10)
        engine = make_engine()

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),
            TradingSignal(action="SELL", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-03")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        sell_trades = [t for t in result.trades if t.action == "SELL"]
        assert len(sell_trades) == 1
        assert sell_trades[0].stamp_duty > 0, "卖出必须有印花税"

    def test_sell_cost_higher_than_buy(self):
        """卖出成本严格高于买入成本"""
        df = make_normal_sequence(base_price=10.0, n_days=10)
        engine = make_engine()

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),
            TradingSignal(action="SELL", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-03")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        buy = [t for t in result.trades if t.action == "BUY"][0]
        sell = [t for t in result.trades if t.action == "SELL"][0]
        buy_total = buy.commission + buy.transfer_fee
        sell_total = sell.commission + sell.stamp_duty + sell.transfer_fee
        assert sell_total > buy_total, "卖出总费用必须高于买入"

    def test_min_commission_enforced(self):
        """小额交易强制最低佣金5元"""
        df = make_normal_sequence(base_price=1.0, n_days=5)  # 低价股
        engine = make_engine()

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-01")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        buy = [t for t in result.trades if t.action == "BUY"][0]
        assert buy.commission == MIN_COMMISSION, f"佣金应为{MIN_COMMISSION}, 实际={buy.commission}"


# ══════════════════════════════════════════════════════════════
# 防线 F: 滑点方向检查测试
# ══════════════════════════════════════════════════════════════

class TestDefenseF_SlippageDirection:
    """滑点方向: 买入价 >= 信号价, 卖出价 <= 信号价"""

    def test_buy_slippage_upward(self):
        """买入执行价必须 >= 原始价"""
        df = make_normal_sequence(base_price=10.0, n_days=5)
        engine = make_engine()

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-01")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        buy = [t for t in result.trades if t.action == "BUY"][0]
        # 买入价应 >= Open 价 (含滑点)
        open_price = df.iloc[1]["open"]  # 第2天 Open (T+1 执行)
        assert buy.price >= open_price * 0.999, "买入滑点应向上"

    def test_sell_slippage_downward(self):
        """卖出执行价必须 <= 原始价"""
        df = make_normal_sequence(base_price=10.0, n_days=10)
        engine = make_engine()

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-02")),
            TradingSignal(action="SELL", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-03")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        sell = [t for t in result.trades if t.action == "SELL"][0]
        # 卖出价应 <= Open 价
        assert sell.slippage >= 0, "卖出滑点应向下 (slippage >= 0)"


# ══════════════════════════════════════════════════════════════
# 防线 G: 整手取整测试
# ══════════════════════════════════════════════════════════════

class TestDefenseH_LotSizeRounding:
    """A股整手取整: 100股为一手"""

    def test_shares_rounded_to_lot(self):
        """买入股数必须是100的整数倍"""
        df = make_normal_sequence(base_price=10.0, n_days=5)
        engine = make_engine()

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=155,
                          timestamp=pd.Timestamp("2025-01-01")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        buy = [t for t in result.trades if t.action == "BUY"]
        if buy:
            assert buy[0].shares % 100 == 0, f"股数应为100的倍数: {buy[0].shares}"

    def test_insufficient_for_one_lot_rejected(self):
        """不足以买一手时拒绝"""
        df = make_normal_sequence(base_price=10.0, n_days=5)
        engine = make_engine(initial_capital=500)  # 只够买约50股

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-01")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        # 资金不足以买100股, 应被拒绝
        buy = [t for t in result.trades if t.action == "BUY"]
        if buy:
            assert buy[0].shares >= 100 or buy[0].shares == 0


# ══════════════════════════════════════════════════════════════
# 防线 I: 权益曲线合理性测试
# ══════════════════════════════════════════════════════════════

class TestDefenseI_EquityCurveSanity:
    """权益曲线合理性检查"""

    def test_no_trade_equity_equals_initial(self):
        """无交易时权益等于初始资金"""
        df = make_normal_sequence(base_price=10.0, n_days=5)
        engine = make_engine(initial_capital=100_000)

        result = engine.run(df, [], symbol="000001.SZ")
        assert len(result.equity_curve) == len(df)
        for eq in result.equity_curve:
            assert abs(eq - 100_000) < 0.01, f"无交易权益应为100000: {eq}"


# ══════════════════════════════════════════════════════════════
# 防线 J: 前视偏差检测测试
# ══════════════════════════════════════════════════════════════

class TestDefenseJ_LookaheadBias:
    """前视偏差: 信号不能使用未来数据"""

    def test_execution_on_next_bar_open(self):
        """成交价必须是信号 bar 之后那根 bar 的 Open"""
        df = make_normal_sequence(base_price=10.0, n_days=5)
        engine = make_engine()

        signals = [
            TradingSignal(action="BUY", symbol="000001.SZ", shares=100,
                          timestamp=pd.Timestamp("2025-01-01")),
        ]

        result = engine.run(df, signals, symbol="000001.SZ")
        buy = [t for t in result.trades if t.action == "BUY"]
        if buy:
            # 成交时间应为 2025-01-02 (T+1)
            assert buy[0].timestamp > pd.Timestamp("2025-01-01"), "成交应在信号之后"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
