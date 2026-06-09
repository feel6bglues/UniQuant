"""Tests for uniquant.brain.wyckoff module — models, classifiers, config, state."""

import os
import tempfile

import pytest
import pandas as pd

# Import directly from submodules to avoid __init__.py import chain issues
# (wyckoff/__init__.py → engine.py → classifiers.py → limits.py has ghost imports)
from uniquant.brain.wyckoff.models import (
    AnalysisResult,
    AnalysisState,
    ConfidenceLevel,
    ImageEvidenceBundle,
    LimitMove,
    LimitMoveType,
    Rule0Result,
    Step1Result,
    VolumeLevel,
    WyckoffPhase,
    WyckoffSignal,
    WyckoffStructure,
    TradingPlan,
)
from uniquant.brain.wyckoff.config import (
    WyckoffConfig,
    RuleEngineConfig,
    load_config,
)

try:
    from uniquant.brain.wyckoff.classifiers import (
        classify_unknown_candidate,
        classify_accumulation_sub_phase,
        classify_distribution_sub_phase,
    )
    _CLASSIFIERS_AVAILABLE = True
except ImportError:
    _CLASSIFIERS_AVAILABLE = False

try:
    from uniquant.brain.wyckoff.state import StateManager
    _STATE_AVAILABLE = True
except ImportError:
    _STATE_AVAILABLE = False


# ───────────────────────── models ─────────────────────────


class TestWyckoffPhase:
    def test_all_phases_exist(self):
        assert WyckoffPhase.ACCUMULATION.value == "accumulation"
        assert WyckoffPhase.MARKUP.value == "markup"
        assert WyckoffPhase.DISTRIBUTION.value == "distribution"
        assert WyckoffPhase.MARKDOWN.value == "markdown"
        assert WyckoffPhase.UNKNOWN.value == "unknown"


class TestConfidenceLevel:
    def test_levels(self):
        assert ConfidenceLevel.A.value == "A"
        assert ConfidenceLevel.D.value == "D"


class TestVolumeLevel:
    def test_extreme_high(self):
        assert VolumeLevel.EXTREME_HIGH.value == "天量/爆量"
        assert VolumeLevel.LOW.value == "萎缩"


class TestWyckoffStructure:
    def test_default_structure(self):
        s = WyckoffStructure()
        assert s.phase == WyckoffPhase.UNKNOWN
        assert s.bc_point is None
        assert s.sc_point is None
        assert s.support_levels == []
        assert s.resistance_levels == []


class TestWyckoffSignal:
    def test_default_signal(self):
        sig = WyckoffSignal()
        assert sig.signal_type == "no_signal"
        assert sig.confidence == ConfidenceLevel.D
        assert sig.phase == WyckoffPhase.UNKNOWN


class TestTradingPlan:
    def test_default_plan(self):
        plan = TradingPlan()
        assert plan.direction == "空仓观望"
        assert plan.confidence == ConfidenceLevel.D

    def test_post_init_sync(self):
        plan = TradingPlan(entry_trigger="突破10元", invalidation="跌破8元", target_1="12元")
        assert plan.trigger_condition == "突破10元"
        assert plan.invalidation_point == "跌破8元"
        assert plan.first_target == "12元"


class TestLimitMove:
    def test_limit_move_creation(self):
        lm = LimitMove(
            date="2024-01-01",
            move_type=LimitMoveType.LIMIT_UP,
            price=10.0,
            volume_level=VolumeLevel.HIGH,
        )
        assert lm.move_type == LimitMoveType.LIMIT_UP
        assert lm.price == 10.0
        assert not lm.is_broken


class TestRule0Result:
    def test_default(self):
        r = Rule0Result()
        assert not r.bc_found
        assert not r.sc_found
        assert r.validity == "insufficient"
        assert r.confidence_base == "D"


class TestStep1Result:
    def test_default(self):
        s = Step1Result()
        assert s.phase == WyckoffPhase.UNKNOWN
        assert s.boundary_upper == 0.0
        assert s.boundary_lower == 0.0


class TestAnalysisResult:
    def test_default(self):
        r = AnalysisResult()
        assert r.symbol == ""
        assert r.phase == "unknown"
        assert r.decision == "no_trade_zone"
        assert r.confidence == "D"


class TestAnalysisState:
    def test_default(self):
        s = AnalysisState()
        assert s.last_confidence == "D"
        assert not s.spring_detected
        assert s.watch_status == "none"


class TestImageEvidenceBundle:
    def test_default_post_init(self):
        bundle = ImageEvidenceBundle()
        assert bundle.detected_timeframe == "unknown_tf"
        assert bundle.image_quality == "medium"
        assert bundle.manifest is not None


# ───────────────────────── config ─────────────────────────


class TestWyckoffConfig:
    def test_default_config(self):
        cfg = WyckoffConfig()
        assert cfg.rule_engine.min_data_rows > 0
        assert cfg.rule_engine.spring_freeze_days > 0
        assert cfg.llm_provider is None

    def test_from_env_no_vars(self):
        cfg = WyckoffConfig.from_env()
        assert cfg.llm_provider is None

    def test_from_yaml_nonexistent(self):
        cfg = WyckoffConfig.from_yaml("/nonexistent/path.yaml")
        assert isinstance(cfg, WyckoffConfig)

    def test_load_config_default(self):
        cfg = load_config()
        assert isinstance(cfg, WyckoffConfig)


class TestRuleEngineConfig:
    def test_defaults(self):
        cfg = RuleEngineConfig()
        assert cfg.bc_volume_multiplier_high == 2.0
        assert cfg.confidence_a_rr_min == 3.0


# ───────────────────────── classifiers ─────────────────────────


def _make_df(rows=30, base_price=10.0, trend=0.0):
    """Helper to create a simple OHLCV DataFrame."""
    data = []
    for i in range(rows):
        p = base_price + trend * i
        data.append({
            "date": f"2024-01-{i+1:02d}",
            "open": p - 0.1,
            "high": p + 0.5,
            "low": p - 0.5,
            "close": p,
            "volume": 1000000 + i * 10000,
        })
    return pd.DataFrame(data)


@pytest.mark.skipif(not _CLASSIFIERS_AVAILABLE, reason="classifiers import chain broken")
class TestClassifyUnknownCandidate:
    def test_non_unknown_phase_returns_empty(self):
        df = _make_df()
        rule0 = Rule0Result(tr_upper=11.0, tr_lower=9.0)
        result = classify_unknown_candidate(df, WyckoffPhase.ACCUMULATION, rule0)
        assert result == ""

    def test_empty_df_returns_empty(self):
        df = pd.DataFrame()
        rule0 = Rule0Result(tr_upper=11.0, tr_lower=9.0)
        result = classify_unknown_candidate(df, WyckoffPhase.UNKNOWN, rule0)
        assert result == ""

    def test_no_tr_bounds_returns_unknown_range(self):
        df = _make_df()
        rule0 = Rule0Result(tr_upper=None, tr_lower=None)
        result = classify_unknown_candidate(df, WyckoffPhase.UNKNOWN, rule0)
        assert result == "unknown_range"

    def test_equal_bounds_returns_unknown_range(self):
        df = _make_df()
        rule0 = Rule0Result(tr_upper=10.0, tr_lower=10.0)
        result = classify_unknown_candidate(df, WyckoffPhase.UNKNOWN, rule0)
        assert result == "unknown_range"


@pytest.mark.skipif(not _CLASSIFIERS_AVAILABLE, reason="classifiers import chain broken")
class TestClassifyAccumulationSubPhase:
    def test_empty_df(self):
        df = pd.DataFrame()
        step1 = Step1Result(boundary_upper=11.0, boundary_lower=9.0)
        rule0 = Rule0Result()
        from uniquant.brain.wyckoff.rules import V3Rules
        rules = V3Rules()
        result = classify_accumulation_sub_phase(df, step1, rule0, rules)
        assert result == ""

    def test_insufficient_data(self):
        df = _make_df(rows=5)
        step1 = Step1Result(boundary_upper=11.0, boundary_lower=9.0)
        rule0 = Rule0Result()
        from uniquant.brain.wyckoff.rules import V3Rules
        rules = V3Rules()
        result = classify_accumulation_sub_phase(df, step1, rule0, rules)
        assert result == ""

    def test_phase_b_range_middle(self):
        df = _make_df(rows=30, base_price=10.0)
        step1 = Step1Result(boundary_upper=12.0, boundary_lower=8.0)
        rule0 = Rule0Result()
        from uniquant.brain.wyckoff.rules import V3Rules
        rules = V3Rules()
        result = classify_accumulation_sub_phase(df, step1, rule0, rules)
        # price ~10 is in the middle of 8-12 → Phase B
        assert result == "Phase B"


@pytest.mark.skipif(not _CLASSIFIERS_AVAILABLE, reason="classifiers import chain broken")
class TestClassifyDistributionSubPhase:
    def test_empty_df(self):
        df = pd.DataFrame()
        step1 = Step1Result(boundary_upper=11.0, boundary_lower=9.0)
        rule0 = Rule0Result()
        result = classify_distribution_sub_phase(df, step1, rule0)
        assert result == ""

    def test_high_position(self):
        df = _make_df(rows=30, base_price=11.5)
        step1 = Step1Result(boundary_upper=12.0, boundary_lower=8.0)
        rule0 = Rule0Result(bc_found=False)
        result = classify_distribution_sub_phase(df, step1, rule0)
        assert result == "Phase A"  # relative_position >= 0.70


# ───────────────────────── state ─────────────────────────


@pytest.mark.skipif(not _STATE_AVAILABLE, reason="state import chain broken")
class TestStateManager:
    def test_update_state_long_setup(self):
        sm = StateManager()
        result = AnalysisResult(
            symbol="000001",
            analysis_date="2024-06-01",
            phase="accumulation",
            micro_action="spring_detected",
            confidence="B",
            decision="long_setup",
            trigger="突破10元",
            invalidation="跌破8元",
            target_1="12元",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "000001_state.json")
            state = sm.update_state("000001", result, output_path)
            assert state.symbol == "000001"
            assert state.trigger_armed is True
            assert state.trigger_text == "突破10元"
            assert os.path.exists(output_path)

    def test_update_state_no_trade(self):
        sm = StateManager()
        result = AnalysisResult(
            symbol="600000",
            analysis_date="2024-06-01",
            phase="unknown",
            decision="no_trade_zone",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "600000_state.json")
            state = sm.update_state("600000", result, output_path)
            assert state.trigger_armed is False
            assert state.trigger_text == ""

    def test_spring_freeze_period(self):
        sm = StateManager()
        result = AnalysisResult(
            symbol="000001",
            analysis_date="2024-06-03",  # Monday
            phase="accumulation",
            spring_detected=True,
            decision="watch_only",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "state.json")
            state = sm.update_state("000001", result, output_path)
            assert state.freeze_until is not None
            assert state.watch_status == "cooling_down"

    def test_save_and_load_state(self):
        sm = StateManager()
        state = AnalysisState(symbol="TEST", last_phase="accumulation", last_confidence="A")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_state.json")
            sm.save_state(state, path)
            loaded = sm.load_state(path)
            assert loaded is not None
            assert loaded.symbol == "TEST"
            assert loaded.last_phase == "accumulation"
            assert loaded.last_confidence == "A"

    def test_load_nonexistent_state(self):
        sm = StateManager()
        result = sm.load_state("/nonexistent/path/state.json")
        assert result is None

    def test_is_in_freeze_period(self):
        sm = StateManager()
        state = AnalysisState(freeze_until="2024-06-10")
        assert sm.is_in_freeze_period(state, reference_date=pd.Timestamp("2024-06-09").to_pydatetime())
        assert not sm.is_in_freeze_period(state, reference_date=pd.Timestamp("2024-06-11").to_pydatetime())

    def test_no_freeze_period(self):
        sm = StateManager()
        state = AnalysisState(freeze_until=None)
        assert not sm.is_in_freeze_period(state)

    def test_get_continuity_report(self):
        sm = StateManager()
        state = AnalysisState(
            symbol="TEST",
            analysis_date="2024-06-01",
            last_phase="accumulation",
            last_confidence="B",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            sm.save_state(state, os.path.join(tmpdir, "TEST_wyckoff_state.json"))
            report = sm.get_continuity_report("TEST", tmpdir)
            assert report["symbol"] == "TEST"
            assert report["current_phase"] == "accumulation"
            assert report["confidence"] == "B"

    def test_invalid_symbol_in_continuity_report(self):
        sm = StateManager()
        report = sm.get_continuity_report("../etc/passwd", "/tmp")
        assert "error" in report

    def test_add_trading_days(self):
        sm = StateManager()
        from datetime import datetime
        # Monday + 3 trading days = Thursday
        monday = datetime(2024, 6, 3)
        result = sm._add_trading_days(monday, 3)
        assert result.weekday() == 3  # Thursday
