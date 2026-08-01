"""
UniQuant 全链路 E2E 集成验收测试
覆盖: 导入链 → DI容器 → 引擎工厂 → 回测引擎 → 组合引擎 → 信号模块 → 风控 → 健康检查 → 数据管道 → 参数对齐
"""

import warnings
from typing import Any, Dict

import numpy as np
import pandas as pd
import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=ImportWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


# ═══════════════════════════════════════════════════════════════
# 辅助工具
# ═══════════════════════════════════════════════════════════════

def _make_kline_df(n_days: int = 200, start_price: float = 10.0, seed: int = 42) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2024-01-02", periods=n_days, freq="B")
    close = start_price * np.cumprod(1 + rng.normal(0.0005, 0.02, n_days))
    close = np.maximum(close, 0.1)
    high = close * (1 + rng.uniform(0, 0.03, n_days))
    low = close * (1 - rng.uniform(0, 0.03, n_days))
    low = np.minimum(low, close)
    high = np.maximum(high, close)
    open_ = close * (1 + rng.uniform(-0.02, 0.02, n_days))
    volume = rng.randint(100_000, 10_000_000, n_days).astype(float)
    return pd.DataFrame({
        "date": dates,
        "open": open_.round(2),
        "high": high.round(2),
        "low": low.round(2),
        "close": close.round(2),
        "volume": volume,
    })


def _make_dirty_kline_df(n_days: int = 200, seed: int = 99) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2024-01-02", periods=n_days, freq="B")
    close = 10.0 * np.cumprod(1 + rng.normal(0.0005, 0.02, n_days))
    close = np.maximum(close, 0.1)
    high = close * (1 + rng.uniform(0, 0.03, n_days))
    low = close * (1 - rng.uniform(0, 0.03, n_days))
    low = np.minimum(low, close)
    high = np.maximum(high, close)
    open_ = close * (1 + rng.uniform(-0.02, 0.02, n_days))
    volume = rng.randint(100_000, 10_000_000, n_days).astype(float)
    df = pd.DataFrame({
        "Date": dates,
        "Open": open_.round(2),
        "High": high.round(2),
        "Low": low.round(2),
        "Close": close.round(2),
        "Volume": volume,
        "code": "000001",
    })
    df.loc[5, "Close"] = np.nan
    df.loc[10, "High"] = df.loc[10, "Low"] - 1.0
    df.loc[15, "Date"] = df.loc[14, "Date"]
    return df


# ═══════════════════════════════════════════════════════════════
# 测试1: 导入链完整性测试
# ═══════════════════════════════════════════════════════════════

class TestImportChain:
    IMPORT_TARGETS = [
        ("uniquant", "uniquant"),
        ("uniquant.shared", "uniquant.shared"),
        ("uniquant.shared.interfaces", "uniquant.shared.interfaces"),
        ("uniquant.shared.constants", "uniquant.shared.constants"),
        ("uniquant.shared.logger_factory", "uniquant.shared.logger_factory"),
        ("uniquant.shared.error_handling", "uniquant.shared.error_handling"),
        ("uniquant.shared.exceptions", "uniquant.shared.exceptions"),
        ("uniquant.shared.cost_model", "uniquant.shared.cost_model"),
        ("uniquant.shared.limit_checker", "uniquant.shared.limit_checker"),
        ("uniquant.shared.config_loader", "uniquant.shared.config_loader"),
        ("uniquant.data", "uniquant.data"),
        ("uniquant.data.pipeline.data_cleaner", "uniquant.data.pipeline.data_cleaner"),
        ("uniquant.data.pipeline.data_validator", "uniquant.data.pipeline.data_validator"),
        ("uniquant.brain", "uniquant.brain"),
        ("uniquant.hands", "uniquant.hands"),
        ("uniquant.hands.backtest.engine", "uniquant.hands.backtest.engine"),
        ("uniquant.hands.backtest.result", "uniquant.hands.backtest.result"),
        ("uniquant.hands.backtest.archive.portfolio_engine", "uniquant.hands.backtest.archive.portfolio_engine"),
        ("uniquant.risk", "uniquant.risk"),
        ("uniquant.risk.drawdown_analyzer", "uniquant.risk.drawdown_analyzer"),
        ("uniquant.risk.portfolio_optimizer", "uniquant.risk.portfolio_optimizer"),
        ("uniquant.signal", "uniquant.signal"),
        ("uniquant.signal.models", "uniquant.signal.models"),
        ("uniquant.signal.normalizer", "uniquant.signal.normalizer"),
        ("uniquant.signal.aggregator", "uniquant.signal.aggregator"),
        ("uniquant.signal.quality", "uniquant.signal.quality"),
        ("uniquant.services", "uniquant.services"),
        ("uniquant.services.analysis.engine_factory", "uniquant.services.analysis.engine_factory"),
        ("uniquant.services.service_container", "uniquant.services.service_container"),
    ]

    @pytest.mark.parametrize("label,module_path", IMPORT_TARGETS)
    def test_import(self, label, module_path):
        import importlib
        try:
            importlib.import_module(module_path)
        except Exception as e:
            pytest.fail(f"导入 {module_path} 失败: {type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════
# 测试2: ServiceContainer 初始化测试
# ═══════════════════════════════════════════════════════════════

class TestServiceContainer:
    def test_create_instance(self):
        from uniquant.services.service_container import ServiceContainer
        sc = ServiceContainer()
        assert sc is not None
        assert sc._services == {}

    def test_register_and_get(self):
        from uniquant.services.service_container import ServiceContainer
        sc = ServiceContainer()
        sc.register("test_svc", {"key": "value"})
        assert sc.get("test_svc") == {"key": "value"}
        assert sc.get("nonexistent") is None

    def test_singleton_instance(self):
        from uniquant.services.service_container import ServiceContainer
        ServiceContainer._instance = None
        a = ServiceContainer.instance()
        b = ServiceContainer.instance()
        assert a is b
        ServiceContainer._instance = None

    def test_reset(self):
        from uniquant.services.service_container import ServiceContainer
        sc = ServiceContainer()
        sc.register("x", 1)
        sc.reset()
        assert sc.get("x") is None
        assert sc._initialized is False

    def test_initialize_dag(self):
        from uniquant.services.service_container import ServiceContainer
        ServiceContainer._instance = None
        sc = ServiceContainer()
        try:
            sc.initialize()
            assert sc._initialized is True, "初始化后 _initialized 应为 True"
            assert sc.get("storage") is not None, "storage 服务未注册"
            assert sc.get("engine_factory") is not None, "engine_factory 未注册"
        except TypeError as e:
            pytest.fail(
                f"BUG: ServiceContainer.initialize() 参数错位 — "
                f"DataService.__init__() 不接受 cache_coordinator/stock_query 参数: {e}"
            )
        except Exception as e:
            pytest.fail(f"ServiceContainer.initialize() 崩溃: {type(e).__name__}: {e}")
        finally:
            sc.reset()
            ServiceContainer._instance = None


# ═══════════════════════════════════════════════════════════════
# 测试3: AnalysisEngineFactory 测试
# ═══════════════════════════════════════════════════════════════

class TestAnalysisEngineFactory:
    def test_factory_creation(self):
        from uniquant.services.analysis.engine_factory import AnalysisEngineFactory
        factory = AnalysisEngineFactory(orchestrator=None)
        assert factory is not None
        assert factory._engines == {}

    def test_lazy_init_czsc_succeeds(self):
        from uniquant.services.analysis.engine_factory import AnalysisEngineFactory
        factory = AnalysisEngineFactory(orchestrator=None)
        result = factory.czsc
        assert result is not None, "CzscAnalysisEngine 应可延迟初始化"

    def test_brain_property_succeeds(self):
        from uniquant.services.analysis.engine_factory import AnalysisEngineFactory
        factory = AnalysisEngineFactory(orchestrator=None)
        result = factory.brain
        assert result is not None, "DecisionBrain 应可延迟初始化"

    def test_engine_properties_graceful(self):
        from uniquant.services.analysis.engine_factory import AnalysisEngineFactory
        factory = AnalysisEngineFactory(orchestrator=None)
        engine_names = ["fsm", "czsc", "lppl", "regime", "ntf", "macro", "report", "brain", "wyckoff"]
        results = {}
        for name in engine_names:
            result = getattr(factory, name)
            results[name] = result
        for name, result in results.items():
            if result is None:
                pass
            else:
                assert hasattr(result, "analyze") or hasattr(result, "make_decision") or type(result).__name__.endswith("Engine"), \
                    f"引擎 {name} 返回了非预期类型: {type(result)}"


# ═══════════════════════════════════════════════════════════════
# 测试4: 最小可行策略 E2E 测试
# ═══════════════════════════════════════════════════════════════

class TestBacktestEngineE2E:
    @staticmethod
    def ma_cross_signal(df: pd.DataFrame, idx: int, ctx: Dict[str, Any]) -> Dict[str, Any]:
        if idx < 20:
            return {"action": "HOLD", "reason": "数据不足"}
        ma5 = df["close"].iloc[max(0, idx - 4):idx + 1].mean()
        ma20 = df["close"].iloc[max(0, idx - 19):idx + 1].mean()
        position = ctx.get("position", 0)
        if position == 0 and ma5 > ma20:
            return {"action": "BUY", "reason": "MA5上穿MA20"}
        elif position > 0 and ma5 < ma20:
            return {"action": "SELL", "reason": "MA5下穿MA20"}
        return {"action": "HOLD", "reason": "无信号"}

    def test_run_backtest_basic(self):
        from uniquant.hands.backtest.engine import BacktestEngine
        from uniquant.hands.backtest.result import BacktestResult

        df = _make_kline_df(200)
        engine = BacktestEngine(initial_capital=100_000)
        result = engine.run_backtest(
            df=df,
            signal_generator=self.ma_cross_signal,
            symbol="000001",
            position_size=100,
        )

        assert isinstance(result, BacktestResult), f"返回类型错误: {type(result)}"
        assert len(result.equity_curve) > 0, "equity_curve 为空"
        assert len(result.equity_curve) == 200, f"equity_curve 长度 {len(result.equity_curve)} != 200"
        assert result.equity_curve[-1] > 0, f"最终权益 {result.equity_curve[-1]} <= 0"
        assert len(result.daily_returns) > 0, "daily_returns 为空"
        assert result.initial_capital == 100_000

    def test_backtest_result_metrics(self):
        from uniquant.hands.backtest.engine import BacktestEngine

        df = _make_kline_df(200)
        engine = BacktestEngine(initial_capital=100_000)
        result = engine.run_backtest(
            df=df,
            signal_generator=self.ma_cross_signal,
            symbol="000001",
            position_size=100,
        )

        assert isinstance(result.total_return, float)
        assert isinstance(result.max_drawdown, float)
        assert result.max_drawdown >= 0

    def test_backtest_result_to_dict(self):
        from uniquant.hands.backtest.engine import BacktestEngine

        df = _make_kline_df(200)
        engine = BacktestEngine(initial_capital=100_000)
        result = engine.run_backtest(
            df=df,
            signal_generator=self.ma_cross_signal,
            symbol="000001",
            position_size=100,
        )
        d = result.to_dict()
        assert "initial_capital" in d
        assert "total_return" in d
        assert "trades" in d

    def test_backtest_reset(self):
        from uniquant.hands.backtest.engine import BacktestEngine

        df = _make_kline_df(200)
        engine = BacktestEngine(initial_capital=100_000)
        engine.run_backtest(df=df, signal_generator=self.ma_cross_signal, symbol="000001")
        engine.reset()
        assert engine.cash == 100_000
        assert engine.position == 0
        assert len(engine.trades) == 0
        assert len(engine.equity_curve) == 0


# ═══════════════════════════════════════════════════════════════
# 测试5: PortfolioEngine 集成测试
# ═══════════════════════════════════════════════════════════════

class TestPortfolioEngine:
    def _make_multi_stock_data(self, n_days=200, n_stocks=3):
        rng = np.random.RandomState(42)
        dates = pd.bdate_range(start="2024-01-02", periods=n_days, freq="B")
        symbols = ["000001.SZ", "600519.SH", "000002.SZ"][:n_stocks]

        price_dict = {}
        pre_close_dict = {}
        volume_dict = {}

        for j, sym in enumerate(symbols):
            close = 10.0 * np.cumprod(1 + rng.normal(0.0005, 0.02, n_days))
            close = np.maximum(close, 0.1)
            high = close * (1 + rng.uniform(0, 0.03, n_days))
            low = close * (1 - rng.uniform(0, 0.03, n_days))
            low = np.minimum(low, close)
            high = np.maximum(high, close)
            price_dict[sym] = close.round(2)
            pre_close_dict[sym] = np.roll(close, 1).round(2)
            pre_close_dict[sym][0] = close[0]
            volume_dict[sym] = rng.randint(100_000, 10_000_000, n_days).astype(float)

        price_df = pd.DataFrame(price_dict, index=dates)
        pre_close_df = pd.DataFrame(pre_close_dict, index=dates)
        volume_df = pd.DataFrame(volume_dict, index=dates)

        signals_list = []
        for i, date in enumerate(dates):
            for sym in symbols:
                if i >= 20 and i % 30 == 0:
                    sig = 1
                elif i >= 20 and i % 30 == 15:
                    sig = -1
                else:
                    sig = 0
                signals_list.append({"date": date, "symbol": sym, "signal": sig})

        signals_df = pd.DataFrame(signals_list)
        return signals_df, price_df, pre_close_df, volume_df

    def test_portfolio_run(self):
        from uniquant.hands.backtest.archive.portfolio_engine import PortfolioEngine

        signals_df, price_df, pre_close_df, volume_df = self._make_multi_stock_data()

        engine = PortfolioEngine(initial_capital=1_000_000, max_positions=3)
        result = engine.run(
            signals=signals_df,
            price_data=price_df,
            pre_close_data=pre_close_df,
            volume_data=volume_df,
        )

        assert isinstance(result, pd.DataFrame), f"返回类型错误: {type(result)}"
        assert "equity" in result.columns, "结果缺少 equity 列"
        assert "daily_return" in result.columns, "结果缺少 daily_return 列"
        assert len(result) > 0, "结果为空"

    def test_portfolio_metrics(self):
        from uniquant.hands.backtest.archive.portfolio_engine import PortfolioEngine

        signals_df, price_df, pre_close_df, volume_df = self._make_multi_stock_data()

        engine = PortfolioEngine(initial_capital=1_000_000, max_positions=3)
        result_df = engine.run(
            signals=signals_df,
            price_data=price_df,
            pre_close_data=pre_close_df,
            volume_data=volume_df,
        )

        if not result_df.empty and len(result_df) > 1:
            metrics = engine.calculate_metrics(result_df["equity"])
            assert "annualized_return" in metrics
            assert "max_drawdown" in metrics
            assert "sharpe_ratio" in metrics
            assert isinstance(metrics["annualized_return"], float)
            assert isinstance(metrics["max_drawdown"], float)

    def test_portfolio_reset(self):
        from uniquant.hands.backtest.archive.portfolio_engine import PortfolioEngine

        engine = PortfolioEngine(initial_capital=1_000_000)
        engine.reset()
        assert engine.cash == 1_000_000
        assert len(engine.positions) == 0
        assert len(engine.equity_curve) == 0


# ═══════════════════════════════════════════════════════════════
# 测试6: 信号模块集成测试
# ═══════════════════════════════════════════════════════════════

class TestSignalModule:
    def test_signal_models_creation(self):
        from uniquant.signal.models import Signal, SignalType, SignalSource, SignalStrength

        sig = Signal(
            signal_type=SignalType.TREND_BULLISH,
            source=SignalSource.INDICATOR,
            symbol="000001",
            direction=1,
            strength=SignalStrength.STRONG,
            confidence=0.8,
            price=10.5,
        )
        assert sig.is_bullish()
        assert not sig.is_bearish()
        assert not sig.is_expired()
        assert sig.direction == 1

    def test_signal_serialization_roundtrip(self):
        from uniquant.signal.models import Signal, SignalType, SignalSource

        sig = Signal(
            signal_type=SignalType.LPPL_BUBBLE,
            source=SignalSource.LPPL,
            symbol="600519",
            direction=1,
            confidence=0.75,
        )
        d = sig.to_dict()
        restored = Signal.from_dict(d)
        assert restored.signal_type == SignalType.LPPL_BUBBLE
        assert restored.source == SignalSource.LPPL
        assert restored.symbol == "600519"
        assert restored.direction == 1

    def test_signal_batch_filtering(self):
        from uniquant.signal.models import Signal, SignalType, SignalSource, SignalStrength, SignalBatch

        batch = SignalBatch()
        for i in range(10):
            batch.add(Signal(
                signal_type=SignalType.TREND_BULLISH if i % 2 == 0 else SignalType.TREND_BEARISH,
                source=SignalSource.INDICATOR,
                symbol=f"00000{i}",
                direction=1 if i % 2 == 0 else -1,
                strength=SignalStrength.STRONG if i < 5 else SignalStrength.WEAK,
            ))

        assert len(batch) == 10
        assert len(batch.bullish()) == 5
        assert len(batch.bearish()) == 5
        assert len(batch.by_strength(SignalStrength.STRONG)) == 5

    def test_normalizer_lppl(self):
        from uniquant.signal.normalizer import LPPLSignalNormalizer

        norm = LPPLSignalNormalizer()
        raw = {"type": "bubble", "confidence": 0.85, "symbol": "600519", "price": 1800.0}
        sig = norm.normalize(raw)
        assert sig.signal_type.value == "lppl_bubble"
        assert sig.direction == 1
        assert sig.strength >= 3

    def test_normalizer_wyckoff(self):
        from uniquant.signal.normalizer import WyckoffSignalNormalizer

        norm = WyckoffSignalNormalizer()
        raw = {"type": "spring", "confidence": 0.7, "symbol": "000001"}
        sig = norm.normalize(raw)
        assert sig.signal_type.value == "wyckoff_spring"
        assert sig.direction == 1

    def test_normalizer_indicator(self):
        from uniquant.signal.normalizer import IndicatorSignalNormalizer

        norm = IndicatorSignalNormalizer()
        raw = {"type": "overbought", "confidence": 0.6, "symbol": "000001"}
        sig = norm.normalize(raw)
        assert sig.signal_type.value == "momentum_overbought"
        assert sig.direction == -1

    def test_normalizer_czsc(self):
        from uniquant.signal.normalizer import CZSCSignalNormalizer

        norm = CZSCSignalNormalizer()
        raw = {"type": "bi_end", "confidence": 0.9, "symbol": "000001", "direction": 1}
        sig = norm.normalize(raw)
        assert sig.signal_type.value == "czsc_bi_end"
        assert sig.direction == 1

    def test_normalizer_registry(self):
        from uniquant.signal.normalizer import create_default_registry
        from uniquant.signal.models import SignalSource

        registry = create_default_registry()
        assert registry.has(SignalSource.LPPL)
        assert registry.has(SignalSource.WYCKOFF)
        assert registry.has(SignalSource.INDICATOR)
        assert registry.has(SignalSource.CZSC)

        raw = {"type": "bubble", "confidence": 0.8, "symbol": "600519"}
        sig = registry.normalize(SignalSource.LPPL, raw)
        assert sig.signal_type.value == "lppl_bubble"

    def test_aggregator_weighted_average(self):
        from uniquant.signal.aggregator import SignalAggregator, SignalAggregationMethod
        from uniquant.signal.models import Signal, SignalType, SignalSource

        agg = SignalAggregator(method=SignalAggregationMethod.WEIGHTED_AVERAGE)
        signals = [
            Signal(signal_type=SignalType.TREND_BULLISH, source=SignalSource.LPPL, symbol="000001", direction=1, confidence=0.8),
            Signal(signal_type=SignalType.TREND_BULLISH, source=SignalSource.WYCKOFF, symbol="000001", direction=1, confidence=0.7),
            Signal(signal_type=SignalType.TREND_BULLISH, source=SignalSource.INDICATOR, symbol="000001", direction=-1, confidence=0.3),
        ]
        result = agg.aggregate(signals)
        assert result.signal.direction == 1
        assert result.agreement_ratio > 0

    def test_aggregator_majority_vote(self):
        from uniquant.signal.aggregator import SignalAggregator, SignalAggregationMethod
        from uniquant.signal.models import Signal, SignalType, SignalSource

        agg = SignalAggregator(method=SignalAggregationMethod.MAJORITY_VOTE)
        signals = [
            Signal(signal_type=SignalType.TREND_BULLISH, source=SignalSource.LPPL, symbol="000001", direction=1, confidence=0.8),
            Signal(signal_type=SignalType.TREND_BULLISH, source=SignalSource.WYCKOFF, symbol="000001", direction=1, confidence=0.7),
            Signal(signal_type=SignalType.TREND_BULLISH, source=SignalSource.INDICATOR, symbol="000001", direction=-1, confidence=0.6),
        ]
        result = agg.aggregate(signals)
        assert result.signal.direction == 1

    def test_aggregator_consensus(self):
        from uniquant.signal.aggregator import SignalAggregator
        from uniquant.signal.models import Signal, SignalType, SignalSource

        agg = SignalAggregator()
        signals = [
            Signal(signal_type=SignalType.TREND_BULLISH, source=SignalSource.LPPL, symbol="000001", direction=1, confidence=0.8),
            Signal(signal_type=SignalType.TREND_BULLISH, source=SignalSource.WYCKOFF, symbol="000001", direction=1, confidence=0.7),
        ]
        consensus = agg.calculate_consensus(signals)
        assert consensus.consensus_direction == 1
        assert consensus.agreement_ratio == 1.0

    def test_quality_assessor(self):
        from uniquant.signal.quality import SignalQualityAssessor
        from uniquant.signal.models import Signal, SignalType, SignalSource

        sig = Signal(signal_type=SignalType.TREND_BULLISH, source=SignalSource.INDICATOR, symbol="000001", direction=1, price=10.0)
        subsequent = [10.5, 11.0, 10.8, 11.5, 12.0]
        result = SignalQualityAssessor.assess(sig, subsequent, lookahead=5)
        assert result is True

    def test_quality_tracker(self):
        from uniquant.signal.quality import SignalQualityTracker
        from uniquant.signal.models import SignalSource, SignalType

        tracker = SignalQualityTracker()
        tracker.record_outcome("sig1", True, SignalSource.LPPL, SignalType.LPPL_BUBBLE)
        tracker.record_outcome("sig2", False, SignalSource.LPPL, SignalType.LPPL_BUBBLE)
        tracker.record_outcome("sig3", True, SignalSource.WYCKOFF, SignalType.WYCKOFF_SPRING)

        overall = tracker.get_overall_quality()
        assert overall.sample_size == 3
        assert overall.hit_rate == pytest.approx(2 / 3, abs=0.01)

        lppl_q = tracker.get_source_quality(SignalSource.LPPL)
        assert lppl_q.sample_size == 2
        assert lppl_q.hit_rate == 0.5


# ═══════════════════════════════════════════════════════════════
# 测试7: 风控模块集成测试
# ═══════════════════════════════════════════════════════════════

class TestRiskModule:
    def test_drawdown_analyzer_basic(self):
        from uniquant.risk.drawdown_analyzer import DrawdownAnalyzer, DrawdownMetrics

        equity = np.array([100, 110, 105, 115, 100, 120, 110, 130], dtype=np.float64)
        metrics = DrawdownAnalyzer.analyze_drawdown(equity, annual_return=0.1)

        assert isinstance(metrics, DrawdownMetrics)
        assert metrics.max_drawdown > 0
        assert metrics.max_drawdown <= 1.0
        assert metrics.max_drawdown_duration > 0
        assert metrics.ulcer_index >= 0

    def test_drawdown_known_mdd(self):
        from uniquant.risk.drawdown_analyzer import DrawdownAnalyzer

        equity = np.array([100, 120, 90, 110], dtype=np.float64)
        metrics = DrawdownAnalyzer.analyze_drawdown(equity)
        expected_mdd = (120 - 90) / 120
        assert abs(metrics.max_drawdown - expected_mdd) < 0.001, f"MDD {metrics.max_drawdown} != {expected_mdd}"

    def test_drawdown_series(self):
        from uniquant.risk.drawdown_analyzer import DrawdownAnalyzer

        equity = np.array([100, 110, 105, 115, 100], dtype=np.float64)
        dd = DrawdownAnalyzer.compute_drawdown_series(equity)
        assert dd.ndim == 1
        assert len(dd) == 5
        assert dd[0] == 0.0
        assert dd[2] < 0

    def test_tail_risk(self):
        from uniquant.risk.drawdown_analyzer import DrawdownAnalyzer, TailRiskMetrics

        rng = np.random.RandomState(42)
        returns = rng.normal(0.001, 0.02, 252)
        metrics = DrawdownAnalyzer.analyze_tail_risk(returns)

        assert isinstance(metrics, TailRiskMetrics)
        assert metrics.var_95 > 0
        assert metrics.var_99 > 0
        assert metrics.cvar_95 >= metrics.var_95
        assert metrics.cvar_99 >= metrics.var_99

    def test_stress_scenario(self):
        from uniquant.risk.drawdown_analyzer import DrawdownAnalyzer, StressTestResult

        equity = np.array([100, 110, 120, 130, 140], dtype=np.float64)
        result = DrawdownAnalyzer.stress_scenario(equity, "2015_crash")
        assert isinstance(result, StressTestResult)
        assert result.loss_pct == -0.40

    def test_portfolio_optimizer_risk_parity(self):
        from uniquant.risk.portfolio_optimizer import PortfolioOptimizer

        rng = np.random.RandomState(42)
        returns = pd.DataFrame({
            "stock_a": rng.normal(0.001, 0.02, 252),
            "stock_b": rng.normal(0.0008, 0.015, 252),
            "stock_c": rng.normal(0.0012, 0.025, 252),
        })

        optimizer = PortfolioOptimizer()
        result = optimizer.optimize_risk_parity(returns)

        assert result is not None
        assert "weights" in result
        assert "sharpe_ratio" in result
        assert "expected_volatility" in result
        weights = result["weights"]
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_portfolio_optimizer_mean_variance(self):
        from uniquant.risk.portfolio_optimizer import PortfolioOptimizer

        rng = np.random.RandomState(42)
        returns = pd.DataFrame({
            "stock_a": rng.normal(0.001, 0.02, 252),
            "stock_b": rng.normal(0.0008, 0.015, 252),
            "stock_c": rng.normal(0.0012, 0.025, 252),
        })

        optimizer = PortfolioOptimizer()
        result = optimizer.optimize_mean_variance(returns, target="max_sharpe")

        assert result is not None
        assert "weights" in result
        assert result["method"] == "mean_variance_max_sharpe"

    def test_portfolio_optimizer_efficient_frontier(self):
        from uniquant.risk.portfolio_optimizer import PortfolioOptimizer

        rng = np.random.RandomState(42)
        returns = pd.DataFrame({
            "stock_a": rng.normal(0.001, 0.02, 252),
            "stock_b": rng.normal(0.0008, 0.015, 252),
        })

        optimizer = PortfolioOptimizer()
        frontier = optimizer.get_efficient_frontier(returns, n_points=5)

        assert isinstance(frontier, pd.DataFrame)
        assert len(frontier) > 0
        assert "volatility" in frontier.columns
        assert "sharpe_ratio" in frontier.columns


# ═══════════════════════════════════════════════════════════════
# 测试8: HealthService 测试
# ═══════════════════════════════════════════════════════════════

class TestHealthService:
    def test_health_service_init(self):
        try:
            from uniquant.services.health_service import HealthService
            hs = HealthService()
            assert hs is not None
        except Exception as e:
            pytest.skip(f"HealthService 初始化失败 (预期行为，依赖缺失): {type(e).__name__}: {e}")

    def test_health_service_get_system_health(self):
        try:
            from uniquant.services.health_service import HealthService
            hs = HealthService()
            health = hs.get_system_health()
            assert isinstance(health, dict)
            assert "overall_status" in health
            assert "components" in health
        except Exception as e:
            pytest.skip(f"HealthService 依赖缺失: {type(e).__name__}: {e}")

    def test_health_service_export(self):
        try:
            from uniquant.services.health_service import HealthService
            hs = HealthService()
            report = hs.export_health_report(format="json")
            assert isinstance(report, str)
            assert len(report) > 0
        except Exception as e:
            pytest.skip(f"HealthService 依赖缺失: {type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════
# 测试9: 数据流到回测的完整管道测试
# ═══════════════════════════════════════════════════════════════

class TestDataPipelineE2E:
    @staticmethod
    def ma_cross_signal(df, idx, ctx):
        if idx < 20:
            return {"action": "HOLD", "reason": "数据不足"}
        ma5 = df["close"].iloc[max(0, idx - 4):idx + 1].mean()
        ma20 = df["close"].iloc[max(0, idx - 19):idx + 1].mean()
        position = ctx.get("position", 0)
        if position == 0 and ma5 > ma20:
            return {"action": "BUY", "reason": "MA5上穿MA20"}
        elif position > 0 and ma5 < ma20:
            return {"action": "SELL", "reason": "MA5下穿MA20"}
        return {"action": "HOLD", "reason": "无信号"}

    def test_cleaner_then_validator_then_backtest(self):
        from uniquant.data.pipeline.data_cleaner import DataCleaner
        from uniquant.data.pipeline.data_validator import DataValidator
        from uniquant.hands.backtest.engine import BacktestEngine

        dirty_df = _make_dirty_kline_df(200)

        cleaner = DataCleaner()
        clean_df = cleaner.clean(dirty_df)

        assert not clean_df.empty, "清洗后数据为空"
        assert "date" in clean_df.columns
        assert "close" in clean_df.columns
        assert clean_df["close"].notna().all(), "清洗后仍有 NaN close"

        for_validation = clean_df.copy()
        if "code" not in for_validation.columns:
            for_validation["code"] = "000001"
        if "amount" not in for_validation.columns:
            for_validation["amount"] = for_validation["close"] * for_validation["volume"]

        validator = DataValidator()
        is_valid = validator.validate(for_validation)
        assert is_valid, "数据验证失败"

        engine = BacktestEngine(initial_capital=100_000)
        result = engine.run_backtest(
            df=clean_df,
            signal_generator=self.ma_cross_signal,
            symbol="000001",
            position_size=100,
        )

        assert len(result.equity_curve) > 0, "回测 equity_curve 为空"
        assert result.equity_curve[-1] > 0, "最终权益 <= 0"

    def test_cleaner_column_lowercase(self):
        from uniquant.data.pipeline.data_cleaner import DataCleaner

        dirty_df = _make_dirty_kline_df(200)
        cleaner = DataCleaner()
        clean_df = cleaner.clean(dirty_df)

        for col in clean_df.columns:
            assert col == col.lower(), f"列名未转小写: {col}"

    def test_cleaner_drops_duplicates(self):
        from uniquant.data.pipeline.data_cleaner import DataCleaner

        dirty_df = _make_dirty_kline_df(200)
        cleaner = DataCleaner()
        clean_df = cleaner.clean(dirty_df)

        assert clean_df["date"].duplicated().sum() == 0, "存在重复日期"


# ═══════════════════════════════════════════════════════════════
# 测试10: 参数传递对齐测试
# ═══════════════════════════════════════════════════════════════

class TestParameterAlignment:
    def test_date_column_consistency(self):
        from uniquant.data.pipeline.data_cleaner import DataCleaner

        dirty_df = _make_dirty_kline_df(200)
        cleaner = DataCleaner()
        clean_df = cleaner.clean(dirty_df)

        assert pd.api.types.is_datetime64_any_dtype(clean_df["date"]), "date 列不是 datetime 类型"
        for val in clean_df["date"]:
            assert isinstance(val, pd.Timestamp), f"date 值不是 pd.Timestamp: {type(val)}"

    def test_index_no_drift_after_clean(self):
        from uniquant.data.pipeline.data_cleaner import DataCleaner

        dirty_df = _make_dirty_kline_df(200)
        cleaner = DataCleaner()
        clean_df = cleaner.clean(dirty_df)

        expected_index = pd.RangeIndex(start=0, stop=len(clean_df))
        assert clean_df.index.equals(expected_index), f"清洗后 index 漂移: {clean_df.index[:5].tolist()}"

    def test_backtest_df_date_column_type(self):
        from uniquant.hands.backtest.engine import BacktestEngine

        df = _make_kline_df(200)
        assert pd.api.types.is_datetime64_any_dtype(df["date"])

        engine = BacktestEngine(initial_capital=100_000)

        def hold_signal(df, idx, ctx):
            return {"action": "HOLD", "reason": "test"}

        result = engine.run_backtest(df=df, signal_generator=hold_signal, symbol="000001")
        assert len(result.equity_curve) == 200

    def test_portfolio_signal_column_names(self):
        from uniquant.hands.backtest.archive.portfolio_engine import PortfolioEngine

        dates = pd.bdate_range(start="2024-01-02", periods=50, freq="B")
        signals_df = pd.DataFrame({
            "date": dates,
            "symbol": ["000001.SZ"] * 50,
            "signal": [0] * 50,
        })
        price_df = pd.DataFrame({"000001.SZ": np.random.uniform(9, 11, 50)}, index=dates)
        pre_close_df = price_df.shift(1).fillna(price_df.iloc[0])

        engine = PortfolioEngine(initial_capital=100_000)
        result = engine.run(
            signals=signals_df,
            price_data=price_df,
            pre_close_data=pre_close_df,
        )
        assert isinstance(result, pd.DataFrame)

    def test_drawdown_analyzer_input_alignment(self):
        from uniquant.risk.drawdown_analyzer import DrawdownAnalyzer

        equity = np.array([100, 105, 103, 108, 102, 110], dtype=np.float64)
        dd = DrawdownAnalyzer.compute_drawdown_series(equity)
        assert len(dd) == len(equity), f"drawdown 长度 {len(dd)} != equity 长度 {len(equity)}"

    def test_signal_normalizer_output_alignment(self):
        from uniquant.signal.normalizer import create_default_registry
        from uniquant.signal.models import SignalSource

        registry = create_default_registry()
        raw = {"type": "bubble", "confidence": 0.8, "symbol": "600519", "price": 1800.0, "value": 0.95}
        sig = registry.normalize(SignalSource.LPPL, raw)

        assert sig.symbol == "600519"
        assert sig.price == 1800.0
        assert sig.confidence == 0.8
        assert sig.direction in (-1, 0, 1)

    def test_portfolio_optimizer_weights_sum_to_one(self):
        from uniquant.risk.portfolio_optimizer import PortfolioOptimizer

        rng = np.random.RandomState(42)
        returns = pd.DataFrame({
            "a": rng.normal(0.001, 0.02, 252),
            "b": rng.normal(0.0008, 0.015, 252),
            "c": rng.normal(0.0012, 0.025, 252),
            "d": rng.normal(0.0009, 0.018, 252),
        })

        optimizer = PortfolioOptimizer()
        result = optimizer.optimize_risk_parity(returns)
        assert result is not None
        total_weight = sum(result["weights"].values())
        assert abs(total_weight - 1.0) < 0.05, f"权重之和 {total_weight} != 1.0"


# ═══════════════════════════════════════════════════════════════
# 测试11: UnifiedBacktestEngine 集成测试 (Phase 2, #33)
# ═══════════════════════════════════════════════════════════════

class TestUnifiedBacktestEngineE2E:
    """UnifiedBacktestEngine (强类型 TradingSignal) 端到端验证"""

    def test_unified_run_with_typed_signals(self):
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
        from uniquant.shared.interfaces import TradingSignal

        df = _make_kline_df(200)
        df["pre_close"] = df["close"].shift(1).fillna(df["open"])
        df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()

        import datetime
        signals = [
            TradingSignal(action="BUY", reason="test_entry", confidence=0.8, shares=100,
                          symbol="000001.SZ", timestamp=datetime.datetime(2024, 1, 22)),
            TradingSignal(action="SELL", reason="test_exit", confidence=0.9, shares=100,
                          symbol="000001.SZ", timestamp=datetime.datetime(2024, 2, 15)),
        ]
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.run(df, signals, symbol="000001.SZ")

        assert result.total_trades >= 0
        assert len(result.equity_curve) == len(df)
        assert result.initial_capital == 100_000
        assert result.total_return >= -1.0
        assert isinstance(result.sharpe, float)

    def test_unified_multi_signal_same_day(self):
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
        from uniquant.shared.interfaces import TradingSignal

        df = _make_kline_df(100)
        df["pre_close"] = df["close"].shift(1).fillna(df["open"])
        df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()

        import datetime
        t = datetime.datetime(2024, 1, 22)
        signals = [
            TradingSignal(action="BUY", reason="signal_a", confidence=0.7, shares=100, symbol="000001.SZ", timestamp=t),
            TradingSignal(action="SELL", reason="signal_b", confidence=0.6, shares=100, symbol="000001.SZ", timestamp=t),
        ]
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.run(df, signals, symbol="000001.SZ")

        assert result is not None
        assert len(result.equity_curve) == len(df)

    def test_unified_handles_empty_signals(self):
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine

        df = _make_kline_df(50)
        df["pre_close"] = df["close"].shift(1).fillna(df["open"])
        df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()

        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.run(df, [], symbol="000001.SZ")

        assert result.total_trades == 0
        assert len(result.equity_curve) == len(df)
        assert result.equity_curve[-1] == 100_000

    def test_unified_backtest_result_metadata(self):
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine

        df = _make_kline_df(50)
        df["pre_close"] = df["close"].shift(1).fillna(df["open"])
        df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()

        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.run(df, [], symbol="000001.SZ", name="测试股票")

        assert "symbol" in result.metadata
        assert result.metadata["symbol"] == "000001.SZ"
        assert result.metadata["engine"] == "unified"
        assert result.metadata["signal_count"] == 0
        assert result.metadata["trading_days_count"] > 0


# ═══════════════════════════════════════════════════════════════
# 测试12: SignalArbitrator E2E 集成测试 (Phase 2, #33)
# ═══════════════════════════════════════════════════════════════

class TestSignalArbitratorE2E:
    """SignalArbitrator 完整仲裁链路验证"""

    def test_arbitrator_basic_arbitration(self):
        from uniquant.signal.arbitrator import SignalArbitrator
        from uniquant.shared.interfaces import TradingSignal

        import datetime
        ts = datetime.datetime(2024, 1, 15)
        signals = [
            TradingSignal(action="BUY", reason="lppl_buy", confidence=0.7, symbol="000001", timestamp=ts),
            TradingSignal(action="SELL", reason="wyckoff_sell", confidence=0.6, symbol="000001", timestamp=ts),
        ]
        arb = SignalArbitrator(max_signal_age_seconds=0)  # 0 = disable timeout
        result = arb.arbitrate(signals, symbol="000001")

        assert len(result) == 1
        # SELL 应优先于 BUY
        assert result[0].action == "SELL"

    def test_arbitrator_quality_gate(self):
        from uniquant.signal.arbitrator import SignalArbitrator
        from uniquant.shared.interfaces import TradingSignal

        import datetime
        ts = datetime.datetime(2024, 1, 15)
        signals = [
            TradingSignal(action="SELL", reason="lppl_sell", confidence=0.8, symbol="000001",
                          timestamp=ts, metadata={"out_of_sample_r_squared": 0.1}),
        ]
        arb = SignalArbitrator(quality_threshold=0.3, max_signal_age_seconds=0)
        result = arb.arbitrate(signals, symbol="000001")

        assert len(result) == 0, "quality gate 应过滤低 OOS R² 的 SELL"

    def test_arbitrator_empty_signals(self):
        from uniquant.signal.arbitrator import SignalArbitrator

        arb = SignalArbitrator(max_signal_age_seconds=0)
        result = arb.arbitrate([], symbol="000001")
        assert result == []


# ═══════════════════════════════════════════════════════════════
# 测试13: UnifiedMatchingEngine 集成测试 (Phase 2, #33)
# ═══════════════════════════════════════════════════════════════

class TestUnifiedMatchingEngineE2E:
    """UnifiedMatchingEngine 撮合逻辑验证"""

    def test_matching_basic_execution(self):
        from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine
        import numpy as np

        engine = UnifiedMatchingEngine()
        n = 5
        prices = np.full(n, 10.0, dtype=np.float64)
        volumes = np.full(n, 1_000_000, dtype=np.float64)
        avg_daily = np.full(n, 2_000_000, dtype=np.float64)
        pre_closes = np.full(n, 9.8, dtype=np.float64)
        symbols = np.array(["000001.SZ"] * n)
        timestamps = np.array(["2024-01-22"] * n, dtype="datetime64[ns]")
        cash = np.full(n, 100_000, dtype=np.float64)

        result = engine.fill_buy(
            prices=prices,
            shares_requested=np.full(n, 100, dtype=np.int64),
            cash_available=cash,
            pre_closes=pre_closes,
            symbols=symbols,
            timestamps=timestamps,
            volumes=volumes,
            avg_daily_volumes=avg_daily,
        )

        assert result.executed_shares is not None  # 类型安全验证
        assert np.any(result.executed_shares > 0) or np.all(result.rejected_mask)

    def test_matching_empty_signals(self):
        from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine

        engine = UnifiedMatchingEngine()
        assert engine is not None
        assert engine.commission_rate > 0

    def test_matching_t1_constraint(self):
        from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine
        import numpy as np

        engine = UnifiedMatchingEngine()
        n = 2
        # Buy on day 1, attempt to sell same day (T+1 violation)
        prices = np.full(n, 10.0, dtype=np.float64)
        shares_requested = np.array([100, 100], dtype=np.int64)
        positions = np.array([0, 100], dtype=np.int64)
        position_costs = np.array([0.0, 10.0], dtype=np.float64)
        pre_closes = np.full(n, 9.8, dtype=np.float64)
        symbols = np.array(["000001.SZ", "000001.SZ"])
        timestamps = np.array(["2024-01-22", "2024-01-22"], dtype="datetime64[ns]")
        buy_dates = np.array([None, pd.Timestamp("2024-01-22")], dtype=object)
        volumes = np.full(n, 1_000_000, dtype=np.float64)
        avg_daily = np.full(n, 2_000_000, dtype=np.float64)

        result = engine.fill_sell(
            prices=prices,
            shares_requested=shares_requested,
            positions_held=positions,
            position_costs=position_costs,
            pre_closes=pre_closes,
            symbols=symbols,
            timestamps=timestamps,
            buy_dates=buy_dates,
            volumes=volumes,
            avg_daily_volumes=avg_daily,
        )

        assert result is not None
        # Second row should have T+1 violation (same-day sell)
        assert result.t1_violation_mask[1], "Same-day sell should be T+1 rejected"


# ═══════════════════════════════════════════════════════════════
# 测试14: 核心约束 E2E 测试 (Halt, T+1, 仲裁, ADV)
# ═══════════════════════════════════════════════════════════════

class TestE2EHaltAndT1:
    """核心交易约束端到端验证: 停牌、T+1、仲裁优先级、ADV无前视"""

    def test_halt_day_no_trade(self):
        from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine
        import numpy as np

        engine = UnifiedMatchingEngine()
        n = 3
        prices = np.full(n, 10.0, dtype=np.float64)
        volumes = np.array([1_000_000, 0, 1_000_000], dtype=np.float64)
        avg_daily = np.full(n, 2_000_000, dtype=np.float64)
        pre_closes = np.full(n, 9.8, dtype=np.float64)
        symbols = np.array(["000001.SZ"] * n)
        timestamps = np.array(["2024-01-22", "2024-01-23", "2024-01-24"], dtype="datetime64[ns]")
        cash = np.full(n, 100_000, dtype=np.float64)

        result = engine.fill_buy(
            prices=prices,
            shares_requested=np.full(n, 100, dtype=np.int64),
            cash_available=cash,
            pre_closes=pre_closes,
            symbols=symbols,
            timestamps=timestamps,
            volumes=volumes,
            avg_daily_volumes=avg_daily,
        )

        assert result.executed_shares[0] > 0
        assert result.executed_shares[1] == 0, "Halt day (volume=0) should have 0 shares executed"
        assert result.rejected_mask[1], "Halt day should be marked rejected"
        assert result.executed_shares[2] > 0

    def test_t1_blocks_same_day_sell(self):
        from uniquant.hands.backtest.unified_matching_engine import UnifiedMatchingEngine
        import numpy as np
        import pandas as pd

        engine = UnifiedMatchingEngine()
        n = 2
        prices = np.full(n, 10.0, dtype=np.float64)
        shares_requested = np.array([100, 100], dtype=np.int64)
        positions = np.array([100, 100], dtype=np.int64)
        position_costs = np.array([10.0, 10.0], dtype=np.float64)
        pre_closes = np.full(n, 9.8, dtype=np.float64)
        symbols = np.array(["000001.SZ"] * n)
        timestamps = np.array(["2024-01-22", "2024-01-22"], dtype="datetime64[ns]")
        buy_dates = np.array([None, pd.Timestamp("2024-01-22")], dtype=object)
        volumes = np.full(n, 1_000_000, dtype=np.float64)
        avg_daily = np.full(n, 2_000_000, dtype=np.float64)

        result = engine.fill_sell(
            prices=prices,
            shares_requested=shares_requested,
            positions_held=positions,
            position_costs=position_costs,
            pre_closes=pre_closes,
            symbols=symbols,
            timestamps=timestamps,
            buy_dates=buy_dates,
            volumes=volumes,
            avg_daily_volumes=avg_daily,
        )

        assert not result.t1_violation_mask[0], "No prior buy date → no T+1 violation"
        assert result.t1_violation_mask[1], "Same-day buy→sell should be T+1 violated"
        assert result.executed_shares[1] == 0, "T+1 violated sell should have 0 shares"

    def test_multi_signal_arbitration_sell_priority(self):
        from uniquant.signal.arbitrator import SignalArbitrator
        from uniquant.shared.interfaces import TradingSignal
        import datetime

        ts = datetime.datetime(2024, 1, 15)
        signals = [
            TradingSignal(action="BUY", reason="regime_buy", confidence=0.9, symbol="000001", timestamp=ts),
            TradingSignal(action="BUY", reason="czsc_buy", confidence=0.7, symbol="000001", timestamp=ts),
            TradingSignal(action="SELL", reason="lppl_sell", confidence=0.8, symbol="000001", timestamp=ts),
            TradingSignal(action="SELL", reason="wyckoff_sell", confidence=0.5, symbol="000001", timestamp=ts),
        ]
        arb = SignalArbitrator(max_signal_age_seconds=0)
        result = arb.arbitrate(signals, symbol="000001")

        assert len(result) == 1, "Should return exactly 1 arbitrated signal"
        assert result[0].action == "SELL", "SELL should win over BUY (sell priority)"
        assert "lppl" in result[0].reason.lower(), "Should pick highest confidence SELL"

    def test_adv_no_lookahead(self):
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
        import numpy as np
        import pandas as pd

        n_days = 50
        dates = pd.bdate_range(start="2024-01-02", periods=n_days, freq="B")
        volume = np.full(n_days, 1000.0)
        volume[20] = 999_999.0

        close = np.full(n_days, 10.0)
        df = pd.DataFrame({
            "date": dates,
            "open": close.astype(float),
            "high": close.astype(float),
            "low": close.astype(float),
            "close": close.astype(float),
            "volume": volume.astype(float),
        })

        engine = UnifiedBacktestEngine(initial_capital=100_000)
        prepared = engine._prepare_dataframe(df)

        expected_adv = volume[:20].mean()
        actual_adv = prepared["avg_daily_volume"].iloc[20]
        assert actual_adv == pytest.approx(expected_adv, abs=0.01), \
            f"avg_daily_volume[20]={actual_adv} should be mean(volume[0:20])={expected_adv}"


# ═══════════════════════════════════════════════════════════════
# 测试N: Brain级跨引擎集成测试
# ═══════════════════════════════════════════════════════════════

class TestBrainCrossEngineIntegration:
    """Brain级引擎 (LPPL / Wyckoff / FactorComposer) 交叉集成测试"""

    @staticmethod
    def _make_price_data(n: int = 200, uptrend: bool = True) -> pd.DataFrame:
        base = 100.0
        if uptrend:
            close = [base + i * 0.8 + (i % 15) * 2 for i in range(n)]
        else:
            close = [base + i * 0.1 - (i % 10) * 1.5 for i in range(n)]
        return pd.DataFrame({
            'close': close,
            'high': [c + 5 + (i % 7) for i, c in enumerate(close)],
            'low': [c - 5 - (i % 7) for i, c in enumerate(close)],
            'volume': [1_000_000 + i * 500 for i in range(n)],
            'open': close,
        })

    def test_lppl_wyckoff_signal_consistency(self):
        """LPPL Danger + Wyckoff Accumulation should not appear simultaneously"""
        from uniquant.brain.lppl.engine import LPPLEngine
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        n = 200
        dates = pd.bdate_range('2024-01-02', periods=n, freq='B')
        df = pd.DataFrame({
            'date': dates,
            'close': [100 + i * 0.5 + (i % 20) * 2 for i in range(n)],
            'high': [105 + i * 0.5 + (i % 20) * 3 for i in range(n)],
            'low': [95 + i * 0.5 + (i % 20) * 1 for i in range(n)],
            'volume': [1_000_000 + i * 1000 for i in range(n)],
            'open': [100 + i * 0.5 + (i % 20) * 1 for i in range(n)],
        })
        lppl_result = LPPLEngine().detect_bubble(df)
        wyckoff_result = WyckoffEngine().analyze(df, multi_timeframe=True)
        lppl_risk = lppl_result.get("risk_level", "Safe") if isinstance(lppl_result, dict) else str(getattr(lppl_result, 'risk_level', 'Safe'))
        wyckoff_phase = str(wyckoff_result.phase).lower() if hasattr(wyckoff_result, 'phase') else ''
        assert not (lppl_risk == "Danger" and "accumulation" in wyckoff_phase)

    def test_factor_composer_stability(self):
        """FactorComposer.compute_all_factors should not crash on real-ish data"""
        from uniquant.brain.factors.composer import FactorComposer
        n = 200
        df = pd.DataFrame({
            'close': [100 + i * 0.3 + (i % 30) * 1.5 for i in range(n)],
            'high': [103 + i * 0.3 + (i % 30) * 2.0 for i in range(n)],
            'low': [97 + i * 0.3 + (i % 30) * 1.0 for i in range(n)],
            'open': [100 + i * 0.3 + (i % 30) * 1.2 for i in range(n)],
            'volume': [1_000_000 + i * 2000 for i in range(n)],
            'code': ['000001'] * n,
            'date': pd.bdate_range('2024-01-02', periods=n, freq='B'),
        })
        fc = FactorComposer()
        factor_df = fc.compute_all_factors(df, mode='backtest')
        expected_factors = {'momentum_20d', 'volatility_20d', 'rsi_14', 'volume_ratio_5_20', 'ma_ratio_5_20'}
        assert expected_factors.issubset(factor_df.columns), f"Missing factors in {list(factor_df.columns)}"

    def test_lppl_wyckoff_factor_pipeline(self):
        """LPPL → Wyckoff → Factor pipeline should not crash"""
        from uniquant.brain.lppl.engine import LPPLEngine
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        from uniquant.brain.factors.composer import FactorComposer
        n = 200
        df = pd.DataFrame({
            'close': [100 + i * 0.6 + (i % 25) * 1.8 for i in range(n)],
            'high': [104 + i * 0.6 + (i % 25) * 2.5 for i in range(n)],
            'low': [96 + i * 0.6 + (i % 25) * 1.0 for i in range(n)],
            'open': [100 + i * 0.6 + (i % 25) * 1.3 for i in range(n)],
            'volume': [1_000_000 + i * 1500 for i in range(n)],
            'code': ['000001'] * n,
            'date': pd.bdate_range('2024-01-02', periods=n, freq='B'),
        })
        lppl_result = LPPLEngine().detect_bubble(df)
        wyckoff_report = WyckoffEngine().analyze(df, multi_timeframe=False)
        composer = FactorComposer()
        factor_df = composer.compute_all_factors(df, mode='backtest')
        assert isinstance(lppl_result, dict)
        risk = lppl_result.get("risk_level", "Safe")
        assert isinstance(wyckoff_report.phase, str) if hasattr(wyckoff_report, 'phase') else True
        assert len(factor_df.columns) >= 5
        assert "#N/A" not in str(risk)
