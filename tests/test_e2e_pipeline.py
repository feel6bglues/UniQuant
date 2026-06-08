"""
E2E 集成测试 — 全链路贯通验证
================================

验证完整数据流:
  DataFetcher → Brain Engine → data_pack → TradingSignalCollector
  → List[TradingSignal] → UnifiedBacktestEngine → BacktestResult

使用 Mock 数据，不依赖外部数据源。
"""

from __future__ import annotations

import datetime
from typing import Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from uniquant.hands.backtest.unified_engine import (
    BacktestResult,
    UnifiedBacktestEngine,
)
from uniquant.services.market_cache import MarketLevelCache
from uniquant.shared.interfaces import TradingSignal
from uniquant.signal.adapters import (
    TradingSignalCollector,
    create_default_registry,
)


# ──────────────────────────────────────────────────────────────
# 测试工具
# ──────────────────────────────────────────────────────────────

def make_mock_stock_data(n_days: int = 60, base_price: float = 10.0) -> pd.DataFrame:
    """构造 Mock K 线数据"""
    rng = np.random.RandomState(42)
    dates = pd.bdate_range("2025-01-01", periods=n_days)
    returns = rng.normal(0.001, 0.02, n_days)
    prices = [base_price]
    for r in returns[1:]:
        prices.append(prices[-1] * (1 + r))
    closes = [round(p, 2) for p in prices]
    opens = [round(c * (1 + rng.normal(0, 0.005)), 2) for c in closes]
    highs = [round(max(o, c) * 1.005, 2) for o, c in zip(opens, closes)]
    lows = [round(min(o, c) * 0.995, 2) for o, c in zip(opens, closes)]
    volumes = [int(rng.uniform(50_000, 200_000)) for _ in range(n_days)]

    df = pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })
    df["pre_close"] = df["close"].shift(1).fillna(df["open"])
    df["avg_daily_volume"] = df["volume"].rolling(5, min_periods=1).mean()
    return df


def make_mock_data_pack(symbol: str = "000001.SZ") -> Dict:
    """构造 Mock data_pack (模拟 AnalysisService 输出)"""
    stock_df = make_mock_stock_data()
    return {
        "stock": stock_df,
        "symbol": symbol,
        "market": "CN",
        "regime": "NORMAL",
        "risk": "Safe",
        "bubble_confidence": 0.2,
        "ntf_side": "NONE",
        "ntf_intensity": 0.0,
        "is_3rd_buy": True,  # 触发 BUY 信号
        "bi_count": 5,
        "wyckoff_phase": "accumulation",
        "wyckoff_confidence": 0.7,
        "wyckoff_spring": True,
        "wyckoff_utad": False,
        "alpha_score": 0.6,
        "ma_status": "MA20 > MA60",
        "price": stock_df.iloc[-1]["close"],
        "atr_stop": stock_df.iloc[-1]["close"] * 0.95,
        "returns": stock_df["close"].pct_change().dropna(),
    }


# ══════════════════════════════════════════════════════════════
# E2E 测试: TradingSignalCollector → UnifiedBacktestEngine
# ══════════════════════════════════════════════════════════════

class TestE2E_CollectorToEngine:
    """信号收集器到回测引擎的全链路测试"""

    def test_collector_produces_signals_from_data_pack(self):
        """Collector 能从 data_pack 中提取信号"""
        collector = TradingSignalCollector(create_default_registry())
        data_pack = make_mock_data_pack()

        signals = collector.collect(data_pack, default_shares=100)

        assert len(signals) > 0, "应从 data_pack 中提取到信号"
        for sig in signals:
            assert isinstance(sig, TradingSignal)
            assert sig.symbol == "000001.SZ"
            assert sig.action in ("BUY", "SELL", "HOLD")

    def test_signals_flow_into_engine(self):
        """信号能正确流入 UnifiedBacktestEngine"""
        collector = TradingSignalCollector(create_default_registry())
        data_pack = make_mock_data_pack()
        stock_df = data_pack["stock"]

        # 收集信号
        signals = collector.collect(data_pack, default_shares=100)
        assert len(signals) > 0

        # 喂给引擎
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.run(stock_df, signals, symbol="000001.SZ")

        assert isinstance(result, BacktestResult)
        assert len(result.equity_curve) == len(stock_df)
        assert result.final_cash >= 0, "现金不为负"

    def test_buy_signal_generates_trade(self):
        """BUY 信号能产生成交记录"""
        collector = TradingSignalCollector(create_default_registry())
        data_pack = make_mock_data_pack()
        stock_df = data_pack["stock"]

        # 收集信号, 使用 df 中的日期作为时间戳
        trade_date = stock_df.iloc[2]["date"]
        signals = collector.collect(
            data_pack, default_shares=100,
            timestamp=pd.Timestamp(trade_date),
        )
        buy_signals = [s for s in signals if s.action == "BUY"]

        if buy_signals:
            engine = UnifiedBacktestEngine(initial_capital=100_000)
            result = engine.run(stock_df, signals, symbol="000001.SZ")

            buy_trades = [t for t in result.trades if t.action == "BUY"]
            assert len(buy_trades) > 0, "BUY 信号应产生成交"

    def test_full_pipeline_with_sell(self):
        """完整流水线: BUY → 持仓 → SELL"""
        stock_df = make_mock_stock_data(n_days=20)

        # 手动构造信号: 第 3 天买入, 第 8 天卖出
        signals = [
            TradingSignal(
                action="BUY", symbol="000001.SZ", shares=100,
                timestamp=stock_df.iloc[2]["date"],
            ),
            TradingSignal(
                action="SELL", symbol="000001.SZ", shares=100,
                timestamp=stock_df.iloc[7]["date"],
            ),
        ]

        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.run(stock_df, signals, symbol="000001.SZ")

        assert len(result.trades) >= 2, "应有 BUY 和 SELL 成交"
        buy = [t for t in result.trades if t.action == "BUY"][0]
        sell = [t for t in result.trades if t.action == "SELL"][0]
        assert sell.timestamp > buy.timestamp, "SELL 在 BUY 之后"
        assert sell.stamp_duty > 0, "卖出有印花税"
        assert buy.stamp_duty == 0, "买入无印花税"


# ══════════════════════════════════════════════════════════════
# E2E 测试: MarketLevelCache
# ══════════════════════════════════════════════════════════════

class TestE2E_MarketLevelCache:
    """市场级缓存测试"""

    def test_cache_set_and_get(self):
        """设置和获取缓存"""
        cache = MarketLevelCache()
        cache.set_regime("NORMAL", {"entropy": 0.5, "turnover_z": 0.3})

        assert cache.get_regime() == "NORMAL"
        details = cache.get_regime_details()
        assert details["entropy"] == 0.5

    def test_cache_clear(self):
        """清除缓存"""
        cache = MarketLevelCache()
        cache.set_regime("STRESSED", {})
        cache.clear()

        assert cache.get_regime() is None

    def test_cache_status(self):
        """缓存状态"""
        cache = MarketLevelCache()
        cache.set_regime("NORMAL", {})
        cache.set_ntf({"side": "SUPPORT", "intensity": 0.5})

        status = cache.status()
        assert status["has_regime"] is True
        assert status["has_ntf"] is True


# ══════════════════════════════════════════════════════════════
# E2E 测试: PipelineResult
# ══════════════════════════════════════════════════════════════

class TestE2E_PipelineResult:
    """流水线结果对象测试"""

    def test_pipeline_result_properties(self):
        """PipelineResult 属性正确"""
        from uniquant.services.research_pipeline import PipelineResult

        result = PipelineResult(
            symbol="000001.SZ",
            data_pack={"stock": pd.DataFrame()},
            decision={"action": "BUY"},
            signals=[
                TradingSignal(action="BUY", symbol="000001.SZ"),
                TradingSignal(action="SELL", symbol="000001.SZ"),
            ],
            backtest=BacktestResult(
                trades=[],
                equity_curve=[100_000, 101_000],
                initial_capital=100_000,
                final_cash=101_000,
            ),
            success=True,
        )

        assert result.symbol == "000001.SZ"
        assert result.total_signals == 2
        assert result.total_trades == 0
        assert result.total_return == pytest.approx(0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
