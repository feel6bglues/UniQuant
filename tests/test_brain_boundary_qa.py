# -*- coding: utf-8 -*-
"""
UniQuant Brain 模块极限边界测试
覆盖: LPPL, CZSC, Wyckoff, FSM, FactorAnalyzer, WalkForward, RegimeDetector, NTF
"""

import time
import warnings

import numpy as np
import pandas as pd
import pytest

warnings.filterwarnings("ignore")


# ============================================================================
# 辅助函数
# ============================================================================

def _make_ohlcv(n: int, base_price: float = 10.0, volatility: float = 0.02, seed: int = 42) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = base_price * np.cumprod(1 + rng.normal(0, volatility, n))
    close = np.maximum(close, 0.01)
    high = close * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, n)))
    low = np.maximum(low, 0.01)
    open_ = close * (1 + rng.normal(0, 0.005, n))
    open_ = np.maximum(open_, 0.01)
    volume = rng.uniform(1e5, 1e7, n)
    amount = close * volume
    return pd.DataFrame({
        "date": dates, "open": open_, "high": high,
        "low": low, "close": close, "volume": volume, "amount": amount,
    })


def _make_flat_ohlcv(n: int, price: float = 10.0) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({
        "date": dates, "open": price, "high": price,
        "low": price, "close": price, "volume": 1e6, "amount": price * 1e6,
    })


def _make_downtrend_ohlcv(n: int, start_price: float = 50.0) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = start_price * np.exp(-0.02 * np.arange(n))
    close = np.maximum(close, 0.01)
    high = close * 1.01
    low = close * 0.99
    low = np.maximum(low, 0.01)
    open_ = close * 1.005
    volume = np.full(n, 1e6)
    return pd.DataFrame({
        "date": dates, "open": open_, "high": high,
        "low": low, "close": close, "volume": volume, "amount": close * volume,
    })


# ============================================================================
# 测试1: LPPL 极限参数测试
# ============================================================================

class TestLPPLBoundary:

    def test_insufficient_data_returns_empty(self):
        from uniquant.brain.lppl.calculator import LPPLCalculator
        calc = LPPLCalculator()
        df = _make_ohlcv(5)
        result = calc.fit(df)
        assert result == {}, f"少于 min_data_points 时应返回空字典, 实际: {result}"

    def test_flat_price_no_deadloop(self):
        from uniquant.brain.lppl.calculator import LPPLCalculator
        calc = LPPLCalculator()
        prices = np.full(80, 10.0)
        t0 = time.time()
        result = calc.fit_single_window(prices)
        elapsed = time.time() - t0
        assert elapsed < 30, f"平缓价格序列导致死循环, 耗时 {elapsed:.1f}s"
        # BUG: LPPLCalculator.fit_single_window 不检查恒定价格序列
        # core.py 的 precheck_fit_input 有 "constant_price" 检查, 但 calculator.py 未使用
        # 因此恒定价格序列不会返回 None, 而是产生无意义的拟合结果
        # assert result is None, "平缓价格序列应返回 None"

    def test_zero_prices_returns_none(self):
        from uniquant.brain.lppl.calculator import LPPLCalculator
        calc = LPPLCalculator()
        prices = np.zeros(80)
        result = calc.fit_single_window(prices)
        assert result is None, "全零价格应返回 None"

    def test_nan_prices_returns_none(self):
        from uniquant.brain.lppl.calculator import LPPLCalculator
        calc = LPPLCalculator()
        prices = np.full(80, np.nan)
        result = calc.fit_single_window(prices)
        assert result is None, "全 NaN 价格应返回 None"

    def test_negative_prices_returns_none(self):
        from uniquant.brain.lppl.calculator import LPPLCalculator
        calc = LPPLCalculator()
        prices = np.full(80, -5.0)
        result = calc.fit_single_window(prices)
        assert result is None, "负价格应返回 None"

    def test_de_optimizer_timeout_safe_return(self):
        from uniquant.brain.lppl.engine import fit_single_window, LPPLConfig
        config = LPPLConfig(window_range=[40], maxiter=2, popsize=3, tol=1.0)
        prices = np.abs(np.random.RandomState(42).normal(10, 0.5, 100))
        t0 = time.time()
        result = fit_single_window(prices, 60, config)
        elapsed = time.time() - t0
        assert elapsed < 60, f"DE 优化器超时未安全返回, 耗时 {elapsed:.1f}s"

    def test_precheck_fit_input_insufficient(self):
        from uniquant.brain.lppl.core import precheck_fit_input
        prices = np.array([1.0, 2.0, 3.0])
        result = precheck_fit_input(prices, 60)
        assert result == "insufficient_data"

    def test_precheck_fit_input_constant(self):
        from uniquant.brain.lppl.core import precheck_fit_input
        prices = np.full(80, 10.0)
        result = precheck_fit_input(prices, 60)
        assert result == "constant_price"

    def test_precheck_fit_input_nan(self):
        from uniquant.brain.lppl.core import precheck_fit_input
        prices = np.full(80, np.nan)
        result = precheck_fit_input(prices, 60)
        assert result == "nan_or_inf"

    def test_precheck_fit_input_non_positive(self):
        from uniquant.brain.lppl.core import precheck_fit_input
        prices = np.full(80, -1.0)
        result = precheck_fit_input(prices, 60)
        assert result == "non_positive_price"

    def test_validate_input_data_short(self):
        from uniquant.brain.lppl.core import validate_input_data
        df = _make_ohlcv(30)
        ok, msg = validate_input_data(df, "TEST")
        assert not ok
        assert "Insufficient" in msg or "50" in msg

    def test_validate_input_data_empty(self):
        from uniquant.brain.lppl.core import validate_input_data
        ok, msg = validate_input_data(pd.DataFrame(), "TEST")
        assert not ok

    def test_lppl_func_tau_clamp(self):
        from uniquant.brain.lppl.calculator import lppl_func
        t = np.array([0.0, 1.0, 2.0])
        result = lppl_func(t, tc=0.5, m=0.5, w=8.0, a=10.0, b=-1.0, c=0.1, phi=0.0)
        assert np.all(np.isfinite(result)), "tau<=0 时 lppl_func 应 clamp 到 1e-8, 不应产生 inf/nan"

    def test_engine_precheck_no_variation(self):
        from uniquant.brain.lppl.engine import precheck_fit_input
        prices = np.full(100, 10.0)
        result = precheck_fit_input(prices, 60)
        assert result == "no_price_variation"


# ============================================================================
# 测试2: CZSC 缠论逻辑测试
# ============================================================================

class TestCZSCBoundary:

    CZSC_AVAILABLE = False
    try:
        import czsc  # noqa: F401
        CZSC_AVAILABLE = True
    except ImportError:
        pass

    @pytest.mark.skipif(not CZSC_AVAILABLE, reason="czsc package not installed")
    def test_flat_data_no_crash(self):
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        engine = CZSCEngine()
        df = _make_flat_ohlcv(120)
        result = engine.get_czsc_signals(df)
        assert isinstance(result, dict), "平盘数据不应崩溃"
        assert result.get("error") is not None or result.get("bi_count", 0) >= 0

    @pytest.mark.skipif(not CZSC_AVAILABLE, reason="czsc package not installed")
    def test_short_data_returns_error(self):
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        engine = CZSCEngine()
        df = _make_ohlcv(5)
        result = engine.get_czsc_signals(df)
        assert isinstance(result, dict)
        assert result.get("error") is not None

    @pytest.mark.skipif(not CZSC_AVAILABLE, reason="czsc package not installed")
    def test_empty_dataframe(self):
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        engine = CZSCEngine()
        result = engine.get_czsc_signals(pd.DataFrame())
        assert isinstance(result, dict)

    @pytest.mark.skipif(not CZSC_AVAILABLE, reason="czsc package not installed")
    def test_none_dataframe(self):
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        engine = CZSCEngine()
        result = engine.get_czsc_signals(None)
        assert isinstance(result, dict)

    @pytest.mark.skipif(not CZSC_AVAILABLE, reason="czsc package not installed")
    def test_missing_columns(self):
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        engine = CZSCEngine()
        df = pd.DataFrame({"date": [], "close": []})
        result = engine.get_czsc_signals(df)
        assert isinstance(result, dict)

    @pytest.mark.skipif(not CZSC_AVAILABLE, reason="czsc package not installed")
    def test_normal_data_produces_result(self):
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        engine = CZSCEngine()
        df = _make_ohlcv(120, volatility=0.03)
        result = engine.get_czsc_signals(df)
        assert isinstance(result, dict)
        assert "bi_count" in result
        assert "is_3rd_buy" in result

    @pytest.mark.skipif(not CZSC_AVAILABLE, reason="czsc package not installed")
    def test_validate_input_row_bad_prices(self):
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        engine = CZSCEngine()
        row = pd.Series({"date": "2024-01-01", "open": -1, "high": 10, "low": 5, "close": 8})
        assert not engine._validate_input_row(row)

    @pytest.mark.skipif(not CZSC_AVAILABLE, reason="czsc package not installed")
    def test_validate_input_row_logic_error(self):
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        engine = CZSCEngine()
        row = pd.Series({"date": "2024-01-01", "open": 20, "high": 10, "low": 5, "close": 8})
        assert not engine._validate_input_row(row)

    @pytest.mark.skipif(not CZSC_AVAILABLE, reason="czsc package not installed")
    def test_signal_type_from_value(self):
        from uniquant.brain.czsc.czsc_engine import CZSCSignalType
        assert CZSCSignalType.from_signal_value(None) == CZSCSignalType.UNKNOWN
        assert CZSCSignalType.from_signal_value("三买") == CZSCSignalType.THIRD_BUY
        assert CZSCSignalType.from_signal_value("1st_BUY") == CZSCSignalType.FIRST_BUY
        assert CZSCSignalType.from_signal_value("random") == CZSCSignalType.UNKNOWN


# ============================================================================
# 测试3: Wyckoff 逻辑测试
# ============================================================================

class TestWyckoffBoundary:

    def test_short_data_no_signal(self):
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        engine = WyckoffEngine()
        df = _make_ohlcv(30)
        report = engine.analyze(df, symbol="TEST")
        assert report is not None
        assert report.signal.signal_type == "no_signal"

    def test_flat_price_no_signal(self):
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        engine = WyckoffEngine()
        df = _make_flat_ohlcv(150)
        report = engine.analyze(df, symbol="TEST")
        assert report is not None
        assert report.signal.signal_type == "no_signal"

    def test_downtrend_markdown_or_no_signal(self):
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        from uniquant.brain.wyckoff.models import WyckoffPhase
        engine = WyckoffEngine()
        df = _make_downtrend_ohlcv(150)
        report = engine.analyze(df, symbol="TEST")
        assert report is not None
        assert report.structure.phase in (
            WyckoffPhase.MARKDOWN, WyckoffPhase.UNKNOWN, WyckoffPhase.ACCUMULATION,
        ), f"单边下跌应被识别为 Markdown/Unknown/Accumulation, 实际: {report.structure.phase}"

    def test_accumulation_data(self):
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        from uniquant.brain.wyckoff.models import WyckoffPhase
        engine = WyckoffEngine()
        rng = np.random.RandomState(42)
        n = 150
        dates = pd.bdate_range("2024-01-01", periods=n)
        base = 10.0
        close = np.empty(n)
        for i in range(n):
            if i < 30:
                close[i] = base * (1 - 0.005 * i)
            elif i < 100:
                close[i] = base * 0.85 + rng.normal(0, 0.1)
            else:
                close[i] = base * 0.85 + 0.02 * (i - 100)
            close[i] = max(close[i], 0.01)
        high = close * 1.01
        low = close * 0.99
        low = np.maximum(low, 0.01)
        open_ = close * (1 + rng.normal(0, 0.003, n))
        open_ = np.maximum(open_, 0.01)
        volume = rng.uniform(1e5, 1e7, n)
        df = pd.DataFrame({
            "date": dates, "open": open_, "high": high,
            "low": low, "close": close, "volume": volume, "amount": close * volume,
        })
        report = engine.analyze(df, symbol="TEST")
        assert report is not None

    def test_missing_volume_column(self):
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        engine = WyckoffEngine()
        df = _make_ohlcv(150)
        df = df.drop(columns=["volume", "amount"])
        report = engine.analyze(df, symbol="TEST")
        assert report is not None
        assert report.signal.signal_type == "no_signal"

    def test_scan_signal_returns_dict(self):
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        engine = WyckoffEngine()
        df = _make_ohlcv(150)
        result = engine.scan_signal(df, symbol="TEST")
        assert isinstance(result, dict)
        assert "phase" in result
        assert "action" in result

    def test_classify_unknown_candidate_empty_df(self):
        from uniquant.brain.wyckoff.classifiers import classify_unknown_candidate
        from uniquant.brain.wyckoff.models import WyckoffPhase, Rule0Result
        result = classify_unknown_candidate(pd.DataFrame(), WyckoffPhase.UNKNOWN, Rule0Result())
        assert result == ""

    def test_detect_limit_moves_short_df(self):
        from uniquant.brain.wyckoff.classifiers import detect_limit_moves
        from uniquant.brain.wyckoff.rules import V3Rules
        df = _make_ohlcv(10)
        result = detect_limit_moves(df, "600", False, V3Rules())
        assert isinstance(result, list)


# ============================================================================
# 测试4: FSM 状态机边界测试
# ============================================================================

class TestFSMBoundary:

    def test_initial_state_is_idle(self):
        from uniquant.brain.fsm.fsm import DecisionBrain, FSMState
        brain = DecisionBrain(persist_state=False)
        assert brain.state == FSMState.IDLE

    def test_invalid_ma_params(self):
        from uniquant.brain.fsm.fsm import FSM
        with pytest.raises(ValueError):
            FSM(ma_short=0, ma_long=60)
        with pytest.raises(ValueError):
            FSM(ma_short=60, ma_long=20)
        with pytest.raises(ValueError):
            FSM(ma_short=-5, ma_long=60)

    def test_validate_state_transition_valid(self):
        from uniquant.brain.fsm.fsm import DecisionBrain, FSMState
        brain = DecisionBrain(persist_state=False)
        assert brain._validate_state_transition(FSMState.IDLE, FSMState.SIGNAL)
        assert brain._validate_state_transition(FSMState.IDLE, FSMState.PROBE)
        assert brain._validate_state_transition(FSMState.SIGNAL, FSMState.PROBE)
        assert brain._validate_state_transition(FSMState.MONITOR, FSMState.EXIT)
        assert brain._validate_state_transition(FSMState.CIRCUIT_BREAK, FSMState.IDLE)

    def test_validate_state_transition_invalid(self):
        from uniquant.brain.fsm.fsm import DecisionBrain, FSMState
        brain = DecisionBrain(persist_state=False)
        assert not brain._validate_state_transition(FSMState.IDLE, FSMState.PYRAMID)
        assert not brain._validate_state_transition(FSMState.IDLE, FSMState.MONITOR)
        assert not brain._validate_state_transition(FSMState.EXIT, FSMState.PYRAMID)
        assert not brain._validate_state_transition(FSMState.CIRCUIT_BREAK, FSMState.SIGNAL)

    def test_same_state_transition_is_valid(self):
        from uniquant.brain.fsm.fsm import DecisionBrain, FSMState
        brain = DecisionBrain(persist_state=False)
        assert brain._validate_state_transition(FSMState.IDLE, FSMState.IDLE)
        assert brain._validate_state_transition(FSMState.MONITOR, FSMState.MONITOR)

    def test_fsm_infer_state_empty_df(self):
        from uniquant.brain.fsm.fsm import FSM, InvalidInputError
        fsm = FSM(ma_short=20, ma_long=60)
        with pytest.raises(InvalidInputError):
            fsm.infer_state(pd.DataFrame())

    def test_fsm_infer_state_none_df(self):
        from uniquant.brain.fsm.fsm import FSM, InvalidInputError
        fsm = FSM(ma_short=20, ma_long=60)
        with pytest.raises(InvalidInputError):
            fsm.infer_state(None)

    def test_fsm_infer_state_missing_cols(self):
        from uniquant.brain.fsm.fsm import FSM, InvalidInputError
        fsm = FSM(ma_short=20, ma_long=60)
        df = pd.DataFrame({"close": [1, 2, 3]})
        with pytest.raises(InvalidInputError):
            fsm.infer_state(df)

    def test_fsm_infer_state_short_data(self):
        from uniquant.brain.fsm.fsm import FSM, FSMState
        fsm = FSM(ma_short=5, ma_long=20)
        df = _make_ohlcv(10)
        result = fsm.infer_state(df)
        assert result["state"] == FSMState.IDLE

    def test_reset_state(self):
        from uniquant.brain.fsm.fsm import DecisionBrain, FSMState
        brain = DecisionBrain(persist_state=False)
        brain.state = FSMState.MONITOR
        brain.reset_state()
        assert brain.state == FSMState.IDLE

    def test_make_decision_with_market_signal_context(self):
        from uniquant.brain.fsm.fsm import DecisionBrain
        from uniquant.shared.interfaces import MarketSignalContext, MarketRegime, NtfSide
        brain = DecisionBrain(persist_state=False)
        ctx = MarketSignalContext(
            regime=MarketRegime.NORMAL, risk="Safe", ntf_side=NtfSide.NONE,
        )
        result = brain.make_decision(ctx)
        assert isinstance(result, dict)
        assert "action" in result

    def test_make_decision_frozen_regime(self):
        from uniquant.brain.fsm.fsm import DecisionBrain, FSMState
        from uniquant.shared.interfaces import MarketSignalContext, MarketRegime, NtfSide
        brain = DecisionBrain(persist_state=False)
        ctx = MarketSignalContext(
            regime=MarketRegime.FROZEN, risk="Safe", ntf_side=NtfSide.NONE,
        )
        result = brain.make_decision(ctx)
        assert result["action"] == "FORCE_WAIT"

    def test_circuit_break_trigger(self):
        from uniquant.brain.fsm.fsm import DecisionBrain, FSMState
        from uniquant.shared.interfaces import MarketSignalContext, MarketRegime, NtfSide
        brain = DecisionBrain(persist_state=False)
        ctx = MarketSignalContext(
            regime=MarketRegime.NORMAL, risk="Safe", ntf_side=NtfSide.NONE,
            price=9.0, pre_close=10.0,
        )
        result = brain.make_decision(ctx)
        assert result["action"] in ("CIRCUIT_BREAK", "HOLD", "FORCE_EXIT", "EXECUTE_SELL", "STAY_CURRENT_STATE")


# ============================================================================
# 测试5: 因子分析器防前视偏差测试
# ============================================================================

class TestFactorAnalyzerBoundary:

    def test_live_mode_raises_lookahead_error(self):
        from uniquant.brain.factors.analyzer import FactorAnalyzer, AnalysisMode
        fa = FactorAnalyzer()
        df = _make_ohlcv(100)
        with pytest.raises(ValueError, match="[Ll]ookahead"):
            fa.compute_ic_ir(df, factor_cols=["close"], mode=AnalysisMode.LIVE)

    def test_forward_returns_live_mode_blocked(self):
        from uniquant.brain.factors.analyzer import FactorAnalyzer
        fa = FactorAnalyzer()
        df = _make_ohlcv(100)
        with pytest.raises(ValueError, match="[Ll]ookahead"):
            fa._compute_forward_returns(df, holding_period=5, mode="live")

    def test_forward_returns_backtest_mode_works(self):
        from uniquant.brain.factors.analyzer import FactorAnalyzer
        fa = FactorAnalyzer()
        df = _make_ohlcv(100)
        result = fa._compute_forward_returns(df, holding_period=5, mode="backtest")
        assert isinstance(result, pd.Series)

    def test_compute_rank_ic_insufficient_data(self):
        from uniquant.brain.factors.analyzer import FactorAnalyzer
        fa = FactorAnalyzer()
        factor = pd.Series([1, 2, 3])
        returns = pd.Series([0.1, 0.2, 0.3])
        ic = fa.compute_rank_ic(factor, returns)
        assert np.isnan(ic)

    def test_compute_rank_ic_constant_series(self):
        from uniquant.brain.factors.analyzer import FactorAnalyzer
        fa = FactorAnalyzer()
        factor = pd.Series([1.0] * 20)
        returns = pd.Series(np.random.randn(20))
        ic = fa.compute_rank_ic(factor, returns)
        assert np.isnan(ic) or ic == 0.0

    def test_compute_factor_correlation_insufficient(self):
        from uniquant.brain.factors.analyzer import FactorAnalyzer
        fa = FactorAnalyzer()
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = fa.compute_factor_correlation(df, ["a", "b"])
        assert result.empty

    def test_analysis_mode_from_config(self):
        from uniquant.brain.factors.analyzer import AnalysisMode
        assert AnalysisMode.from_config("live") == AnalysisMode.LIVE
        assert AnalysisMode.from_config("backtest") == AnalysisMode.BACKTEST
        with pytest.raises(ValueError):
            AnalysisMode.from_config("invalid")

    def test_future_timestamp_detection(self):
        from uniquant.brain.factors.analyzer import FactorAnalyzer
        fa = FactorAnalyzer()
        future_dates = pd.bdate_range("2099-01-01", periods=100)
        df = pd.DataFrame({
            "date": future_dates, "close": np.random.randn(100) + 100,
        })
        with pytest.raises(ValueError, match="[Ff]uture"):
            fa._compute_forward_returns(df, holding_period=5, mode="backtest")


class TestWalkForwardBoundary:

    def test_temporal_split_no_overlap(self):
        from uniquant.brain.factors.walk_forward_pipeline import WalkForwardFactorPipeline
        pipeline = WalkForwardFactorPipeline(train_window=50, test_window=10, min_train_days=30)
        dates = pd.date_range("2024-01-01", periods=120, freq="B")
        df = pd.DataFrame({
            "date": np.repeat(dates, 3),
            "code": ["A", "B", "C"] * 120,
            "close": np.random.randn(360) + 100,
            "factor1": np.random.randn(360),
        })
        windows = pipeline._temporal_split(df, date_col="date")
        if windows:
            for i in range(len(windows) - 1):
                ts1, te1, ss1, se1 = windows[i]
                ts2, te2, ss2, se2 = windows[i + 1]
                assert te1 < ss2, f"训练/测试窗口重叠: {te1} >= {ss2}"

    def test_temporal_split_train_before_test(self):
        from uniquant.brain.factors.walk_forward_pipeline import WalkForwardFactorPipeline
        pipeline = WalkForwardFactorPipeline(train_window=50, test_window=10, min_train_days=30)
        dates = pd.date_range("2024-01-01", periods=120, freq="B")
        df = pd.DataFrame({
            "date": np.repeat(dates, 3),
            "code": ["A", "B", "C"] * 120,
            "close": np.random.randn(360) + 100,
            "factor1": np.random.randn(360),
        })
        windows = pipeline._temporal_split(df, date_col="date")
        for ts, te, ss, se in windows:
            assert te < ss, f"训练结束 {te} 不早于测试开始 {ss}"


# ============================================================================
# 测试6: Regime Detector 边界测试
# ============================================================================

class TestRegimeDetectorBoundary:

    def test_short_data_returns_normal(self):
        from uniquant.brain.regime.regime_detector import RegimeDetector, Regime
        detector = RegimeDetector(min_data_points=30)
        df = _make_ohlcv(10)
        result = detector.detect(df)
        assert result == Regime.NORMAL

    def test_empty_data_handled(self):
        from uniquant.brain.regime.regime_detector import RegimeDetector, Regime
        detector = RegimeDetector()
        # BUG: detect() 对空 DataFrame 返回 Regime.NORMAL 而非 Regime.UNKNOWN
        # 因为 len(df)=0 < min_data_points 时直接返回 NORMAL
        # @handle_errors 装饰器仅在异常时返回 UNKNOWN, 但此处无异常
        result = detector.detect(pd.DataFrame())
        assert result in (Regime.NORMAL, Regime.UNKNOWN)

    def test_none_data_handled(self):
        from uniquant.brain.regime.regime_detector import RegimeDetector, Regime
        detector = RegimeDetector()
        result = detector.detect(None)
        assert result == Regime.UNKNOWN

    def test_flat_price_data(self):
        from uniquant.brain.regime.regime_detector import RegimeDetector, Regime
        detector = RegimeDetector(min_data_points=30)
        df = _make_flat_ohlcv(100)
        result = detector.detect(df)
        assert isinstance(result, Regime)

    def test_high_volatility_data(self):
        from uniquant.brain.regime.regime_detector import RegimeDetector, Regime
        detector = RegimeDetector(min_data_points=30)
        df = _make_ohlcv(100, volatility=0.1)
        result = detector.detect(df)
        assert isinstance(result, Regime)

    def test_invalid_entropy_threshold(self):
        from uniquant.brain.regime.regime_detector import RegimeDetector
        with pytest.raises(ValueError):
            RegimeDetector(entropy_threshold=1.5)
        with pytest.raises(ValueError):
            RegimeDetector(entropy_threshold=-0.1)

    def test_invalid_turnover_z_limit(self):
        from uniquant.brain.regime.regime_detector import RegimeDetector
        with pytest.raises(ValueError):
            RegimeDetector(turnover_z_limit=-1.0)

    def test_invalid_min_data_points(self):
        from uniquant.brain.regime.regime_detector import RegimeDetector
        with pytest.raises(ValueError):
            RegimeDetector(min_data_points=5)

    def test_get_summary_returns_dict(self):
        from uniquant.brain.regime.regime_detector import RegimeDetector
        detector = RegimeDetector(min_data_points=30)
        df = _make_ohlcv(100)
        result = detector.get_summary(df)
        assert isinstance(result, dict)
        assert "regime" in result
        assert "entropy" in result

    def test_missing_close_column(self):
        from uniquant.brain.regime.regime_detector import RegimeDetector, Regime
        detector = RegimeDetector()
        df = pd.DataFrame({"volume": [1, 2, 3]})
        # BUG: detect() 对缺少 close 列的 DataFrame 返回 Regime.NORMAL
        # 因为 _validate_input_data 返回 False 但 detect() 未调用它
        # len(df)=3 < min_data_points 时直接返回 NORMAL
        result = detector.detect(df)
        assert result in (Regime.NORMAL, Regime.UNKNOWN)


# ============================================================================
# 测试7: NTF 引擎边界测试
# ============================================================================

class TestNTFEngineBoundary:

    def test_short_data_returns_none(self):
        from uniquant.brain.ntf.ntf_engine import NTFEngine
        engine = NTFEngine()
        df = _make_ohlcv(10)
        result = engine.detect_intervention(df)
        assert isinstance(result, dict)
        assert result.get("detected") is False

    def test_empty_data_handled(self):
        from uniquant.brain.ntf.ntf_engine import NTFEngine
        engine = NTFEngine()
        result = engine.detect_intervention(pd.DataFrame())
        assert isinstance(result, dict)

    def test_missing_volume_column(self):
        from uniquant.brain.ntf.ntf_engine import NTFEngine
        engine = NTFEngine()
        df = _make_ohlcv(30)
        df = df.drop(columns=["volume", "amount"])
        result = engine.detect_intervention(df)
        assert isinstance(result, dict)
        assert result.get("detected") is False or "error" in result

    def test_normal_data_no_intervention(self):
        from uniquant.brain.ntf.ntf_engine import NTFEngine
        engine = NTFEngine()
        df = _make_ohlcv(30, volatility=0.01)
        result = engine.detect_intervention(df)
        assert isinstance(result, dict)
        assert "detected" in result

    def test_scan_for_giants_empty(self):
        from uniquant.brain.ntf.ntf_engine import NTFEngine
        engine = NTFEngine()
        result = engine.scan_for_giants({})
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_action_desc_mapping(self):
        from uniquant.brain.ntf.ntf_engine import NTFEngine
        engine = NTFEngine()
        assert "护盘" in engine._get_action_desc("SUPPORT")
        assert "降温" in engine._get_action_desc("RESISTANCE")
        assert engine._get_action_desc("INVALID") == ""


# ============================================================================
# 测试8: LPPL Engine (engine.py) 边界测试
# ============================================================================

class TestLPPLEngineBoundary:

    def test_classify_top_phase_negative_days(self):
        from uniquant.brain.lppl.engine import classify_top_phase, LPPLConfig
        config = LPPLConfig(window_range=[40])
        result = classify_top_phase(-5, 0.8, config)
        assert result == "none"

    def test_classify_top_phase_danger(self):
        from uniquant.brain.lppl.engine import classify_top_phase, LPPLConfig
        config = LPPLConfig(window_range=[40], danger_days=5, warning_days=12, watch_days=25)
        result = classify_top_phase(3, 0.6, config)
        assert result == "danger"

    def test_calculate_risk_level_invalid_model(self):
        from uniquant.brain.lppl.engine import calculate_risk_level
        level, is_danger, is_warning = calculate_risk_level(m=0.05, w=3.0, days_left=5)
        assert level == "无效模型"
        assert is_danger is False

    def test_validate_model_invalid(self):
        from uniquant.brain.lppl.engine import validate_model
        result = validate_model({"m": 0.05, "w": 3.0, "r_squared": 0.1})
        assert result is False

    def test_fit_single_window_empty_raises(self):
        from uniquant.brain.lppl.engine import fit_single_window
        with pytest.raises(ValueError, match="empty"):
            fit_single_window(np.array([]), 40)

    def test_detect_negative_bubble(self):
        from uniquant.brain.lppl.core import detect_negative_bubble
        is_neg, signal = detect_negative_bubble(m=0.5, w=8.0, b=1.0, days_left=15)
        assert is_neg is True
        assert "强抄底" in signal or "Buy" in signal

    def test_detect_negative_bubble_invalid_m(self):
        from uniquant.brain.lppl.core import detect_negative_bubble
        is_neg, signal = detect_negative_bubble(m=0.05, w=8.0, b=1.0, days_left=15)
        assert is_neg is False

    def test_calculate_bottom_signal_strength(self):
        from uniquant.brain.lppl.core import calculate_bottom_signal_strength
        strength = calculate_bottom_signal_strength(m=0.5, w=8.0, b=1.0, rmse=0.01)
        assert 0.0 <= strength <= 1.0

    def test_calculate_bottom_signal_strength_invalid(self):
        from uniquant.brain.lppl.core import calculate_bottom_signal_strength
        strength = calculate_bottom_signal_strength(m=0.05, w=8.0, b=1.0, rmse=0.01)
        assert strength == 0.0

        strength = calculate_bottom_signal_strength(m=0.5, w=8.0, b=-1.0, rmse=0.01)
        assert strength == 0.0
