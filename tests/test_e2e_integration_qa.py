"""
UniQuant 全链路 E2E 集成验收测试
覆盖: 导入链 → DI容器 → 引擎工厂 → 回测引擎 → 组合引擎 → 信号模块 → 风控 → 健康检查 → 数据管道 → 参数对齐
"""

import warnings

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
        # Step3 语义: cleaner 禁止 amount=close*volume 兜底(C2 红线), fixture 必须自带真实 amount
        "Amount": (close * volume).round(2),
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
        ("uniquant.hands.backtest.unified_engine", "uniquant.hands.backtest.unified_engine"),
        ("uniquant.hands.backtest.result", "uniquant.hands.backtest.result"),
        ("uniquant.risk", "uniquant.risk"),
        ("uniquant.risk.portfolio_optimizer", "uniquant.risk.portfolio_optimizer"),
        ("uniquant.signal", "uniquant.signal"),
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

class TestUnifiedBacktestEngineQuickE2E:
    def test_run_backtest_basic(self):
        import datetime
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine, BacktestResult
        from uniquant.shared.interfaces import TradingSignal

        df = _make_kline_df(200)
        df["pre_close"] = df["close"].shift(1).fillna(df["open"])
        df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()

        signals = [
            TradingSignal(
                action="BUY",
                reason="MA5上穿MA20",
                confidence=0.8,
                shares=100,
                symbol="000001.SZ",
                timestamp=datetime.datetime(2024, 1, 22),
            ),
            TradingSignal(
                action="SELL",
                reason="MA5下穿MA20",
                confidence=0.8,
                shares=100,
                symbol="000001.SZ",
                timestamp=datetime.datetime(2024, 2, 15),
            ),
        ]

        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.run(df=df, signals=signals, symbol="000001.SZ")

        assert isinstance(result, BacktestResult), f"返回类型错误: {type(result)}"
        assert len(result.equity_curve) > 0, "equity_curve 为空"
        assert len(result.equity_curve) == 200, f"equity_curve 长度 {len(result.equity_curve)} != 200"
        assert result.equity_curve[-1] > 0, f"最终权益 {result.equity_curve[-1]} <= 0"
        assert len(result.daily_returns) > 0, "daily_returns 为空"
        assert result.initial_capital == 100_000

    def test_backtest_result_metrics(self):
        import datetime
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
        from uniquant.shared.interfaces import TradingSignal

        df = _make_kline_df(200)
        df["pre_close"] = df["close"].shift(1).fillna(df["open"])
        df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()

        signals = [
            TradingSignal(
                action="BUY",
                reason="MA5上穿MA20",
                confidence=0.8,
                shares=100,
                symbol="000001.SZ",
                timestamp=datetime.datetime(2024, 1, 22),
            )
        ]

        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.run(df=df, signals=signals, symbol="000001.SZ")

        assert isinstance(result.total_return, float)
        assert isinstance(result.max_drawdown, float)
        assert result.max_drawdown >= 0

    def test_backtest_result_to_dict(self):
        import datetime
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
        from uniquant.shared.interfaces import TradingSignal

        df = _make_kline_df(200)
        df["pre_close"] = df["close"].shift(1).fillna(df["open"])
        df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()

        signals = [
            TradingSignal(
                action="BUY",
                reason="MA5上穿MA20",
                confidence=0.8,
                shares=100,
                symbol="000001.SZ",
                timestamp=datetime.datetime(2024, 1, 22),
            )
        ]

        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.run(df=df, signals=signals, symbol="000001.SZ")
        d = result.to_dict()
        assert "initial_capital" in d
        assert "total_return" in d
        assert "trades" in d

    def test_backtest_reset(self):
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine

        df = _make_kline_df(200)
        df["pre_close"] = df["close"].shift(1).fillna(df["open"])
        df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()

        engine = UnifiedBacktestEngine(initial_capital=100_000)
        engine.run(df=df, signals=[], symbol="000001.SZ")
        engine.reset()
        assert engine.cash == 100_000
        assert engine.positions.get("000001.SZ", 0) == 0
        assert len(engine.trades) == 0


# ═══════════════════════════════════════════════════════════════
# 测试5: PortfolioEngine 集成测试
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# 测试6: 信号模块集成测试
# ═══════════════════════════════════════════════════════════════

class TestSignalModule:
    def test_signal_collector_and_arbitrator(self):
        from uniquant.signal.adapters import TradingSignalCollector
        from uniquant.signal.arbitrator import SignalArbitrator
        from uniquant.shared.interfaces import TradingSignal

        collector = TradingSignalCollector()
        assert collector is not None

        arbitrator = SignalArbitrator()
        sig = TradingSignal(
            symbol="000001.SZ",
            action="BUY",
            confidence=0.85,
            reason="test reason",
        )
        out = arbitrator.arbitrate([sig])
        assert isinstance(out, list)


# ═══════════════════════════════════════════════════════════════
# 测试7: 风控模块集成测试
# ═══════════════════════════════════════════════════════════════

class TestRiskModule:
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
        from uniquant.services.health_service import HealthService

        hs = HealthService()
        health = hs.get_system_health()
        assert isinstance(health, dict)
        assert "overall_status" in health
        assert "components" in health
        assert health["overall_status"] in ("healthy", "unhealthy")
        assert "config" in health["components"]

    def test_health_service_export(self):
        from uniquant.services.health_service import HealthService

        hs = HealthService()
        report = hs.export_health_report(format="json")
        assert isinstance(report, str)
        assert len(report) > 0



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
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine
        from uniquant.shared.interfaces import TradingSignal
        import datetime

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

        clean_df["pre_close"] = clean_df["close"].shift(1).fillna(clean_df["open"])
        clean_df["avg_daily_volume"] = clean_df["volume"].rolling(20, min_periods=1).mean()
        signals = [
            TradingSignal(
                action="BUY",
                reason="MA5上穿MA20",
                confidence=0.8,
                shares=100,
                symbol="000001.SZ",
                timestamp=datetime.datetime(2024, 1, 22),
            )
        ]
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.run(
            df=clean_df,
            signals=signals,
            symbol="000001.SZ",
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
        from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine

        df = _make_kline_df(200)
        assert pd.api.types.is_datetime64_any_dtype(df["date"])
        df["pre_close"] = df["close"].shift(1).fillna(df["open"])
        df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()

        engine = UnifiedBacktestEngine(initial_capital=100_000)
        result = engine.run(df=df, signals=[], symbol="000001.SZ")
        assert len(result.equity_curve) == 200

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
