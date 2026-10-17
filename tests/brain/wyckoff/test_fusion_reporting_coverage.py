"""第九轮（2026-10-17）覆盖率补测：Wyckoff 融合引擎与报告生成器。

覆盖两个此前低覆盖的 ``brain/wyckoff`` 模块（CI 口径）：

- ``fusion_engine.py``：``FusionEngine.fuse`` 的数据路径与日线规则路径、
  冲突检测、T+1 风险评估、决策推导、放弃原因，以及 ``StateManager``
  的状态持久化。
- ``reporting.py``：``WyckoffReportGenerator`` 的 Markdown / HTML / CSV /
  JSON 渲染与字典序列化。

全部使用**合成数据**驱动：直接构造 ``WyckoffReport`` /
``DailyRuleResult`` / ``ImageEvidenceBundle`` / ``AnalysisResult``。
不触网、不读 ``data/``、不依赖 czsc/backtrader/mootdx/akshare/baostock；
任何文件输出一律落在 pytest 的 ``tmp_path`` 下。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uniquant.brain.wyckoff.fusion_engine import FusionEngine, StateManager
from uniquant.brain.wyckoff.models import (
    AnalysisResult,
    AnalysisState,
    BCResult,
    BCPoint,
    ChartManifest,
    ChartManifestItem,
    ConfidenceLevel,
    CounterfactualResult,
    DailyRuleResult,
    EffortResult,
    ImageEvidenceBundle,
    PhaseCTestResult,
    PhaseResult,
    PreprocessingResult,
    RiskAssessment,
    RiskRewardProjection,
    StressTest,
    TradingPlan,
    VisualEvidence,
    VolumeLevel,
    WyckoffPhase,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
)
from uniquant.brain.wyckoff.reporting import WyckoffReportGenerator


# ─────────────────────────── 合成对象构造器 ───────────────────────────


def _structure(**overrides: object) -> WyckoffStructure:
    base: dict = {
        "phase": WyckoffPhase.MARKUP,
        "bc_point": BCPoint(
            date="2026-01-02", price=10.0, volume_level=VolumeLevel.HIGH
        ),
        "trading_range_high": 15.0,
        "trading_range_low": 9.0,
        "current_date": "2026-05-15",
    }
    base.update(overrides)
    return WyckoffStructure(**base)


def _signal(**overrides: object) -> WyckoffSignal:
    base: dict = {
        "signal_type": "no_signal",
        "confidence": ConfidenceLevel.B,
        "phase": WyckoffPhase.MARKUP,
        "volume_confirmation": VolumeLevel.AVERAGE,
    }
    base.update(overrides)
    return WyckoffSignal(**base)


def _risk_reward(ratio: float = 6.0) -> RiskRewardProjection:
    return RiskRewardProjection(
        entry_price=10.0,
        stop_loss=9.5,
        first_target=13.0,
        reward_risk_ratio=ratio,
    )


def _plan(**overrides: object) -> TradingPlan:
    base: dict = {
        "direction": "做多",
        "trigger_condition": "突破 15",
        "invalidation_point": "9",
        "first_target": "13",
    }
    base.update(overrides)
    return TradingPlan(**base)


def _report(**overrides: object) -> WyckoffReport:
    base: dict = {
        "symbol": "000001.SZ",
        "period": "daily",
        "structure": _structure(),
        "signal": _signal(),
        "risk_reward": _risk_reward(),
        "trading_plan": _plan(),
    }
    base.update(overrides)
    return WyckoffReport(**base)


def _bundle(**overrides: object) -> ImageEvidenceBundle:
    base: dict = {
        "files": ["/tmp/charts/000001.SZ_daily.png"],
        "detected_timeframe": "daily",
        "image_quality": "high",
        "trust_level": "medium",
    }
    base.update(overrides)
    return ImageEvidenceBundle(**base)


def _manifest(symbol: str = "000001.SZ") -> ChartManifest:
    return ChartManifest(
        files=[
            ChartManifestItem(
                file_path=f"/tmp/charts/{symbol}_daily.png",
                file_name=f"{symbol}_daily.png",
                relative_dir="",
                modified_time="2026-05-15T15:00:00",
                symbol=symbol,
                inferred_timeframe="daily",
                image_quality="high",
            )
        ],
        total_count=1,
        usable_count=1,
        scan_time="2026-05-15T15:00:01",
    )


def _analysis_result(**overrides: object) -> AnalysisResult:
    base: dict = {
        "symbol": "000001.SZ",
        "asset_type": "stock",
        "analysis_date": "2026-05-15",
        "input_sources": ["data", "images"],
        "timeframes_seen": ["daily"],
        "bc_found": True,
        "phase": "markup",
        "micro_action": "观察",
        "boundary_upper_zone": "15",
        "boundary_lower_zone": "9",
        "volume_profile_label": "高于平均",
        "spring_detected": True,
        "utad_detected": False,
        "counterfactual_summary": "压力测试通过",
        "t1_risk_assessment": "可接受",
        "rr_assessment": "pass",
        "decision": "long_setup",
        "trigger": "突破 15",
        "invalidation": "9",
        "target_1": "13",
        "confidence": "B",
        "abandon_reason": "",
        "conflicts": ["阶段冲突：数据=markup, 图像=possible_markdown"],
        "consistency_score": "conflicted",
        "weekly_context": "周线上行",
        "intraday_context": "盘中止跌",
    }
    base.update(overrides)
    return AnalysisResult(**base)


def _daily_rule_result(**overrides: object) -> DailyRuleResult:
    base: dict = {
        "symbol": "000001.SZ",
        "asset_type": "stock",
        "analysis_date": "2026-05-15",
        "input_source": "data",
        "preprocessing": PreprocessingResult(
            trend_direction="up",
            volume_label="高于平均",
            volatility_layer="medium",
        ),
        "bc_result": BCResult(
            found=True,
            candidate_index=0,
            candidate_date="2026-01-02",
            candidate_price=10.0,
            volume_label="高于平均",
        ),
        "phase_result": PhaseResult(
            phase="markup",
            boundary_upper_zone="15",
            boundary_lower_zone="9",
        ),
        "effort_result": EffortResult(),
        "phase_c_test": PhaseCTestResult(spring_detected=True, utad_detected=False),
        "counterfactual": CounterfactualResult(),
        "risk": RiskAssessment(t1_risk_level="安全", rr_assessment="pass"),
        "plan": _plan(current_assessment="观察"),
        "confidence": "B",
        "decision": "long_setup",
        "abandon_reason": "",
    }
    base.update(overrides)
    return DailyRuleResult(**base)


# ─────────────────────────── FusionEngine ───────────────────────────


class TestFusionEngineInit:
    def test_conflict_matrix_populated(self) -> None:
        engine = FusionEngine(config={"threshold": 1})
        assert engine.config == {"threshold": 1}
        assert engine.conflict_matrix[("markup", "possible_markdown")] == "high"

    def test_default_config_is_none(self) -> None:
        assert FusionEngine().config is None


class TestFuseDataPath:
    def test_fuse_without_image_evidence(self) -> None:
        engine = FusionEngine()
        result = engine.fuse(_report())

        assert result.symbol == "000001.SZ"
        assert result.analysis_date == "2026-05-15"
        assert result.input_sources == ["data"]
        assert result.timeframes_seen == []
        assert result.bc_found is True
        assert result.phase == "markup"
        assert result.micro_action == "no_signal"
        assert result.decision == "no_trade_zone"

    def test_fuse_without_image_evidence_keeps_abandon_reason(self) -> None:
        engine = FusionEngine()
        report = _report(
            structure=_structure(bc_point=None),
            risk_reward=_risk_reward(1.0),
        )
        result = engine.fuse(report, None)

        assert "未找到 BC 点" in result.abandon_reason
        assert "盈亏比不足 1:2.5" in result.abandon_reason

    def test_fuse_with_image_evidence_timeframes(self) -> None:
        engine = FusionEngine()
        result = engine.fuse(_report(), _bundle())

        assert result.input_sources == ["data", "images"]
        assert result.timeframes_seen == ["daily"]

    def test_fuse_with_image_evidence_unknown_timeframe(self) -> None:
        engine = FusionEngine()
        # 默认 ``unknown_tf`` → 不产出任何可见周期
        result = engine.fuse(_report(), _bundle(detected_timeframe="unknown_tf"))

        assert result.timeframes_seen == []

    def test_fuse_structure_none_and_phase_none(self) -> None:
        engine = FusionEngine()
        report = _report(structure=None, signal=_signal(phase=None))
        result = engine.fuse(report)

        # structure 缺失 → analysis_date 回退空串、bc_found 为 False
        assert result.analysis_date == ""
        assert result.bc_found is False
        # phase 缺失 → 映射为 no_trade_zone
        assert result.phase == "no_trade_zone"

    def test_fuse_phase_as_plain_string(self) -> None:
        engine = FusionEngine()
        report = _report(signal=_signal(phase="markup"))
        assert engine.fuse(report).phase == "markup"

    def test_fuse_phase_unknown_string_maps_to_no_trade_zone(self) -> None:
        engine = FusionEngine()
        report = _report(signal=_signal(phase="unknown"))
        assert engine.fuse(report).phase == "no_trade_zone"

    def test_fuse_boundaries_volume_and_special_signals(self) -> None:
        engine = FusionEngine()
        report = _report(
            structure=_structure(trading_range_high=18.5, trading_range_low=8.25),
            signal=_signal(
                signal_type="spring",
                volume_confirmation=VolumeLevel.HIGH,
            ),
        )
        result = engine.fuse(report)

        assert result.boundary_upper_zone == "18.5"
        assert result.boundary_lower_zone == "8.25"
        assert result.volume_profile_label == "高于平均"
        assert result.spring_detected is True
        assert result.utad_detected is False

    def test_fuse_utad_and_unset_boundaries(self) -> None:
        engine = FusionEngine()
        report = _report(
            structure=_structure(
                trading_range_high=None, trading_range_low=None, phase=WyckoffPhase.DISTRIBUTION
            ),
            signal=_signal(signal_type="utad", volume_confirmation=None),
        )
        result = engine.fuse(report)

        assert result.boundary_upper_zone == ""
        assert result.boundary_lower_zone == ""
        assert result.volume_profile_label == ""
        assert result.spring_detected is False
        assert result.utad_detected is True

    def test_fuse_volume_confirmation_as_plain_string(self) -> None:
        engine = FusionEngine()
        report = _report(signal=_signal(volume_confirmation="contracted"))
        assert engine.fuse(report).volume_profile_label == "contracted"

    def test_fuse_stress_tests_and_rr_pass(self) -> None:
        engine = FusionEngine()
        report = _report(
            stress_tests=[StressTest(scenario_name="崩盘", passes=True, risk_level="低")],
            risk_reward=_risk_reward(3.0),
        )
        result = engine.fuse(report)

        assert result.counterfactual_summary == "压力测试通过"
        assert result.t1_risk_assessment == "可接受"
        assert result.rr_assessment == "pass"

    def test_fuse_no_stress_tests_summary(self) -> None:
        engine = FusionEngine()
        result = engine.fuse(_report(risk_reward=_risk_reward(1.0)))

        assert result.counterfactual_summary == "未执行压力测试"
        assert result.rr_assessment == "fail"

    def test_fuse_trading_plan_fields_projected(self) -> None:
        engine = FusionEngine()
        result = engine.fuse(_report())

        assert result.trigger == "突破 15"
        assert result.invalidation == "9"
        assert result.target_1 == "13"

    def test_fuse_without_trading_plan(self) -> None:
        engine = FusionEngine()
        result = engine.fuse(_report(trading_plan=None))

        assert result.trigger == ""
        assert result.invalidation == ""
        assert result.target_1 == ""

    def test_fuse_confidence_enum_and_plain_string(self) -> None:
        engine = FusionEngine()

        enum_result = engine.fuse(_report(signal=_signal(confidence=ConfidenceLevel.A)))
        assert enum_result.confidence == "A"

        str_result = engine.fuse(_report(signal=_signal(confidence="C")))
        assert str_result.confidence == "C"

    def test_fuse_confidence_none_falls_back_to_d(self) -> None:
        engine = FusionEngine()
        assert engine.fuse(_report(signal=_signal(confidence=None))).confidence == "D"

    def test_fuse_records_conflicts(self) -> None:
        engine = FusionEngine()
        bundle = _bundle(
            visual_phase_hint="possible_markdown",
            visual_trend="downtrend",
            image_quality="low",
        )
        result = engine.fuse(_report(), bundle)

        assert result.conflicts
        assert any("阶段冲突" in c for c in result.conflicts)
        assert any("趋势冲突" in c for c in result.conflicts)
        assert any("图像质量警告" in c for c in result.conflicts)

    def test_fuse_abandon_reason_by_conflict_and_unusable_image(self) -> None:
        engine = FusionEngine()
        report = _report(structure=_structure(bc_point=None), risk_reward=_risk_reward(1.0))
        bundle = _bundle(
            visual_phase_hint="possible_markdown",
            image_quality="unusable",
        )
        result = engine.fuse(report, bundle)

        assert "未找到 BC 点" in result.abandon_reason
        assert "盈亏比不足 1:2.5" in result.abandon_reason
        assert "图像质量不可用" in result.abandon_reason
        assert "数据与图像结论冲突" in result.abandon_reason


class TestExtractTimeframes:
    def test_known_timeframe(self) -> None:
        assert FusionEngine()._extract_timeframes(_bundle()) == ["daily"]

    def test_unknown_and_empty_timeframes(self) -> None:
        engine = FusionEngine()
        assert engine._extract_timeframes(_bundle(detected_timeframe="unknown_tf")) == []
        assert engine._extract_timeframes(_bundle(detected_timeframe="")) == []


class TestDetectConflicts:
    def test_phase_trend_and_quality_conflicts(self) -> None:
        engine = FusionEngine()
        bundle = _bundle(
            visual_phase_hint="possible_markdown",
            visual_trend="downtrend",
            image_quality="low",
        )
        conflicts = engine._detect_conflicts(_report(), bundle)
        assert len(conflicts) == 3

    def test_uptrend_conflict_on_bearish_phase(self) -> None:
        engine = FusionEngine()
        report = _report(signal=_signal(phase=WyckoffPhase.DISTRIBUTION))
        conflicts = engine._detect_conflicts(
            report, _bundle(visual_trend="uptrend", image_quality="high")
        )
        assert any("数据看空" in c for c in conflicts)

    def test_phase_plain_string_no_conflict(self) -> None:
        engine = FusionEngine()
        report = _report(signal=_signal(phase="markup"))
        # 字符串 phase 走 str(...) 分支，且 unclear 提示不构成冲突
        assert engine._detect_conflicts(report, _bundle()) == []

    def test_no_conflict_when_image_agrees(self) -> None:
        engine = FusionEngine()
        bundle = _bundle(
            visual_phase_hint="possible_markup",
            visual_trend="uptrend",
            image_quality="high",
        )
        assert engine._detect_conflicts(_report(), bundle) == []


class TestDetectDailyRuleConflicts:
    def test_conflict_via_visual_evidence(self) -> None:
        engine = FusionEngine()
        bundle = _bundle(
            visual_evidence_list=[
                VisualEvidence(
                    visual_trend="downtrend",
                    visual_phase_hint="possible_markdown",
                )
            ]
        )
        conflicts = engine._detect_daily_rule_conflicts(_daily_rule_result(), bundle)
        assert any("阶段冲突" in c for c in conflicts)
        assert any("数据看多" in c for c in conflicts)

    def test_bearish_phase_with_uptrend(self) -> None:
        engine = FusionEngine()
        rule = _daily_rule_result(
            phase_result=PhaseResult(
                phase="distribution",
                boundary_upper_zone="15",
                boundary_lower_zone="9",
            )
        )
        bundle = _bundle(
            visual_evidence_list=[
                VisualEvidence(
                    visual_trend="uptrend",
                    visual_phase_hint="possible_accumulation",
                )
            ]
        )
        conflicts = engine._detect_daily_rule_conflicts(rule, bundle)
        assert any("数据看空" in c for c in conflicts)

    def test_empty_visual_evidence_no_conflict(self) -> None:
        engine = FusionEngine()
        assert (
            engine._detect_daily_rule_conflicts(_daily_rule_result(), _bundle()) == []
        )


class TestMapPhase:
    @pytest.mark.parametrize(
        ("phase", "expected"),
        [
            ("accumulation", "accumulation"),
            ("markup", "markup"),
            ("distribution", "distribution"),
            ("markdown", "markdown"),
            ("unknown", "no_trade_zone"),
            ("something_else", "no_trade_zone"),
        ],
    )
    def test_phase_mapping(self, phase: str, expected: str) -> None:
        assert FusionEngine()._map_phase(phase) == expected


class TestAssessT1Risk:
    def test_no_stress_tests(self) -> None:
        assert FusionEngine()._assess_t1_risk(_report()) == "未评估"

    def test_high_risk_when_failed_high_scenario(self) -> None:
        report = _report(
            stress_tests=[StressTest(scenario_name="崩盘", passes=False, risk_level="高")]
        )
        assert FusionEngine()._assess_t1_risk(report) == "高风险"

    def test_medium_risk_when_any_failure(self) -> None:
        report = _report(
            stress_tests=[StressTest(scenario_name="回撤", passes=False, risk_level="中")]
        )
        assert FusionEngine()._assess_t1_risk(report) == "中等风险"

    def test_acceptable_when_all_pass(self) -> None:
        report = _report(stress_tests=[StressTest(scenario_name="回撤", passes=True)])
        assert FusionEngine()._assess_t1_risk(report) == "可接受"


class TestDetermineDecision:
    def test_t1_blocked_wins(self) -> None:
        engine = FusionEngine()
        report = _report(trading_plan=_plan(t1_blocked=True))
        assert engine._determine_decision(report, None) == "no_trade_zone"

    def test_low_rr_blocks_entry(self) -> None:
        engine = FusionEngine()
        report = _report(risk_reward=_risk_reward(2.0))
        assert engine._determine_decision(report, None) == "no_trade_zone"

    def test_distribution_phase_blocks_entry(self) -> None:
        engine = FusionEngine()
        report = _report(signal=_signal(phase=WyckoffPhase.DISTRIBUTION))
        assert engine._determine_decision(report, None) == "no_trade_zone"

    def test_spring_is_watch_only(self) -> None:
        engine = FusionEngine()
        report = _report(signal=_signal(signal_type="spring"))
        assert engine._determine_decision(report, None) == "watch_only"

    def test_accumulation_signal_is_watch_only(self) -> None:
        engine = FusionEngine()
        report = _report(signal=_signal(signal_type="accumulation"))
        assert engine._determine_decision(report, None) == "watch_only"

    def test_no_signal_is_no_trade_zone(self) -> None:
        engine = FusionEngine()
        assert engine._determine_decision(_report(), None) == "no_trade_zone"

    def test_long_direction_yields_long_setup(self) -> None:
        engine = FusionEngine()
        report = _report(
            signal=_signal(signal_type="sos", phase=WyckoffPhase.MARKUP),
            trading_plan=_plan(direction="做多"),
        )
        assert engine._determine_decision(report, None) == "long_setup"

    def test_unusable_image_downgrades_long_setup(self) -> None:
        engine = FusionEngine()
        report = _report(signal=_signal(signal_type="sos"))
        bundle = _bundle(image_quality="unusable")
        assert engine._determine_decision(report, bundle) == "watch_only"

    def test_low_trust_downgrades_long_setup(self) -> None:
        engine = FusionEngine()
        report = _report(signal=_signal(signal_type="sos"))
        bundle = _bundle(trust_level="low")
        assert engine._determine_decision(report, bundle) == "watch_only"

    def test_conflict_downgrades_long_setup(self) -> None:
        engine = FusionEngine()
        report = _report(signal=_signal(signal_type="sos"))
        bundle = _bundle(
            visual_phase_hint="possible_markdown",
            image_quality="high",
            trust_level="medium",
        )
        assert engine._determine_decision(report, bundle) == "watch_only"

    def test_no_signal_and_no_plan_stays_flat(self) -> None:
        engine = FusionEngine()
        report = _report(signal=None, trading_plan=None)
        assert engine._determine_decision(report, None) == "no_trade_zone"


class TestGetAbandonReason:
    def test_no_reasons_returns_empty(self) -> None:
        assert FusionEngine()._get_abandon_reason(_report(), None) == ""

    def test_all_reasons_composed(self) -> None:
        engine = FusionEngine()
        report = _report(structure=_structure(bc_point=None), risk_reward=_risk_reward(1.0))
        bundle = _bundle(
            visual_phase_hint="possible_markdown",
            image_quality="unusable",
        )
        reason = engine._get_abandon_reason(report, bundle)
        assert reason.split("; ") == [
            "未找到 BC 点",
            "盈亏比不足 1:2.5",
            "图像质量不可用",
            "数据与图像结论冲突",
        ]


class TestFuseDailyRulePath:
    def test_daily_rule_aligned(self) -> None:
        engine = FusionEngine()
        result = engine.fuse(_daily_rule_result())

        assert result.symbol == "000001.SZ"
        assert result.input_sources == ["data"]
        assert result.bc_found is True
        assert result.phase == "markup"
        assert result.micro_action == "观察"
        assert result.spring_detected is True
        assert result.utad_detected is False
        assert result.rr_assessment == "pass"
        assert result.decision == "long_setup"
        assert result.consistency_score == "high_alignment"
        assert result.conflicts == []

    def test_daily_rule_with_image_conflicts(self) -> None:
        engine = FusionEngine()
        bundle = _bundle(
            visual_evidence_list=[
                VisualEvidence(
                    visual_trend="downtrend",
                    visual_phase_hint="possible_markdown",
                )
            ]
        )
        result = engine.fuse(_daily_rule_result(), bundle)

        assert result.input_sources == ["data", "images"]
        assert result.timeframes_seen == ["daily"]
        assert result.consistency_score == "conflicted"
        assert result.conflicts

    def test_daily_rule_rr_fail_abandons_with_reason(self) -> None:
        engine = FusionEngine()
        rule = _daily_rule_result(risk=RiskAssessment(rr_assessment="fail"))
        result = engine.fuse(rule)

        assert result.decision == "abandon"
        assert result.abandon_reason == "unfavorable_rr_or_structure"

    def test_daily_rule_rr_fail_keeps_existing_reason(self) -> None:
        engine = FusionEngine()
        rule = _daily_rule_result(
            risk=RiskAssessment(rr_assessment="fail"),
            abandon_reason="自定义放弃原因",
        )
        result = engine.fuse(rule)

        assert result.decision == "abandon"
        assert result.abandon_reason == "自定义放弃原因"

    def test_daily_rule_bearish_phase_is_watch_only(self) -> None:
        engine = FusionEngine()
        rule = _daily_rule_result(
            phase_result=PhaseResult(
                phase="distribution",
                boundary_upper_zone="15",
                boundary_lower_zone="9",
            )
        )
        result = engine.fuse(rule)

        assert result.decision == "watch_only"

    def test_daily_rule_missing_optionals_use_defaults(self) -> None:
        engine = FusionEngine()
        rule = _daily_rule_result(
            phase_c_test=None,
            counterfactual=None,
            risk=None,
            plan=None,
        )
        result = engine.fuse(rule)

        assert result.spring_detected is False
        assert result.utad_detected is False
        assert result.counterfactual_summary == "not_overturned"
        assert result.t1_risk_assessment == "unknown"
        assert result.rr_assessment == "fail"
        assert result.micro_action == ""
        assert result.trigger == ""
        assert result.invalidation == ""
        assert result.target_1 == ""
        assert result.decision == "abandon"

    def test_daily_rule_overturned_counterfactual(self) -> None:
        engine = FusionEngine()
        rule = _daily_rule_result(
            counterfactual=CounterfactualResult(conclusion_overturned=True)
        )
        assert engine.fuse(rule).counterfactual_summary == "conclusion_overturned"

    def test_daily_rule_no_plan_micro_action_empty(self) -> None:
        engine = FusionEngine()
        rule = _daily_rule_result(plan=None)
        assert engine.fuse(rule).micro_action == ""


# ─────────────────────────── StateManager ───────────────────────────


class TestStateManager:
    def test_init_creates_state_dir(self, tmp_path: Path) -> None:
        manager = StateManager(str(tmp_path / "out"))
        assert manager.state_dir.exists()
        assert manager.state_dir.is_dir()

    def test_get_state_path_sanitizes_symbol(self, tmp_path: Path) -> None:
        manager = StateManager(str(tmp_path))
        path = manager._get_state_path("600519.SH")
        assert path.name == "600519_SH_wyckoff_state.json"

    def test_create_state_long_setup_arms_trigger(self, tmp_path: Path) -> None:
        manager = StateManager(str(tmp_path))
        state = manager.create_state_from_result(
            _analysis_result(decision="long_setup")
        )

        assert state.symbol == "000001.SZ"
        assert state.last_phase == "markup"
        assert state.watch_status == "watching"
        assert state.trigger_armed is True
        assert state.freeze_until is None

    def test_create_state_neutral_decision_not_armed(self, tmp_path: Path) -> None:
        manager = StateManager(str(tmp_path))
        state = manager.create_state_from_result(
            _analysis_result(decision="no_trade_zone")
        )

        assert state.watch_status == "none"
        assert state.trigger_armed is False
        assert state.last_decision == "no_trade_zone"

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        manager = StateManager(str(tmp_path / "state_root"))
        result = _analysis_result()
        state = manager.create_state_from_result(result)

        saved_path = manager.save_state(state)
        assert Path(saved_path).exists()

        reloaded = manager.load_state(result.symbol)
        assert reloaded is not None
        assert reloaded.symbol == state.symbol
        assert reloaded.last_decision == state.last_decision
        assert reloaded.trigger_armed == state.trigger_armed
        assert reloaded.conflict_summary == state.conflict_summary
        assert reloaded.abandon_reason == state.abandon_reason

    def test_load_missing_state_returns_none(self, tmp_path: Path) -> None:
        manager = StateManager(str(tmp_path))
        assert manager.load_state("999999.SZ") is None

    def test_generate_continuity_template_without_previous(self, tmp_path: Path) -> None:
        manager = StateManager(str(tmp_path))
        template = manager.generate_continuity_template(_analysis_result(), None)

        assert template == {"phase_changed": False, "freeze_period_ended": False}

    def test_generate_continuity_template_detects_changes(self, tmp_path: Path) -> None:
        manager = StateManager(str(tmp_path))
        previous = AnalysisState(
            symbol="000001.SZ",
            last_phase="accumulation",
            freeze_until="2026-01-01",
        )
        template = manager.generate_continuity_template(
            _analysis_result(phase="markup", spring_detected=False), previous
        )

        assert template["phase_changed"] is True
        assert template["freeze_period_ended"] is True

    def test_generate_continuity_template_spring_holds_freeze(
        self, tmp_path: Path
    ) -> None:
        manager = StateManager(str(tmp_path))
        previous = AnalysisState(
            symbol="000001.SZ",
            last_phase="markup",
            freeze_until="2026-01-01",
        )
        template = manager.generate_continuity_template(
            _analysis_result(phase="markup", spring_detected=True), previous
        )

        assert template["phase_changed"] is False
        assert template["freeze_period_ended"] is False


# ─────────────────────────── WyckoffReportGenerator ───────────────────────────


class TestReportGeneratorInit:
    def test_creates_all_output_dirs(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path / "reports_root"))

        assert Path(gen.raw_dir).is_dir()
        assert Path(gen.reports_dir).is_dir()
        assert Path(gen.summary_dir).is_dir()
        assert Path(gen.evidence_dir).is_dir()


class TestMarkdownReport:
    def test_full_report_with_state_and_bundle(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path))
        state = AnalysisState(
            symbol="000001.SZ",
            last_phase="accumulation",
            last_decision="watch_only",
        )
        path = gen.generate_markdown_report(
            _analysis_result(), state=state, image_bundle=_bundle(manifest=_manifest())
        )

        text = Path(path).read_text(encoding="utf-8")
        assert "000001.SZ" in text
        assert "## Step 0: BC 定位" in text
        assert "上次阶段" in text
        assert "图像总数" in text

    def test_minimal_report_without_state_or_bundle(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path))
        path = gen.generate_markdown_report(
            _analysis_result(
                bc_found=False,
                abandon_reason="未找到 BC 点",
                conflicts=[],
            )
        )

        text = Path(path).read_text(encoding="utf-8")
        assert "放弃原因" in text
        assert "首次分析，无历史状态" in text
        assert "无图像数据" in text


class TestHtmlReport:
    def test_html_with_context_and_bundle(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path))
        path = gen.generate_html_report(
            _analysis_result(rr_assessment="excellent"),
            image_bundle=_bundle(manifest=_manifest()),
        )

        html = Path(path).read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html
        assert "周线上行" in html
        assert "图像总数：1" in html

    def test_html_without_context_or_bundle(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path))
        path = gen.generate_html_report(
            _analysis_result(weekly_context="", rr_assessment="fail")
        )

        html = Path(path).read_text(encoding="utf-8")
        assert "首次分析，无历史状态" in html
        assert "无图像数据" in html


class TestSummaryAndJson:
    def test_summary_csv(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path))
        path = gen.generate_summary_csv(_analysis_result())

        content = Path(path).read_text(encoding="utf-8-sig")
        assert "symbol" in content
        assert "000001.SZ" in content

    def test_raw_json(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path))
        path = gen.generate_raw_json(_analysis_result())

        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        assert payload["symbol"] == "000001.SZ"
        assert payload["conflicts"]
        assert payload["weekly_context"] == "周线上行"

    def test_evidence_json_with_files(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path))
        bundle = _bundle(manifest=_manifest())
        path = gen.generate_evidence_json(bundle)

        assert Path(path).name == "image_evidence_000001.SZ.json"
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        assert payload["manifest"]["total_count"] == 1
        assert payload["manifest"]["files"][0]["symbol"] == "000001.SZ"

    def test_evidence_json_without_files(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path))
        bundle = _bundle(manifest=ChartManifest())
        path = gen.generate_evidence_json(bundle)

        assert Path(path).name == "image_evidence_unknown.json"

    def test_conflicts_json(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path))
        path = gen.generate_conflicts_json(
            [{"type": "phase", "detail": "possible_markdown"}]
        )

        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        assert payload == [{"type": "phase", "detail": "possible_markdown"}]


class TestSerializationHelpers:
    def test_result_to_dict_fields(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path))
        result = _analysis_result()
        payload = gen._result_to_dict(result)

        assert payload["symbol"] == "000001.SZ"
        assert payload["input_sources"] == ["data", "images"]
        assert payload["consistency_score"] == "conflicted"
        assert payload["intraday_context"] == "盘中止跌"

    def test_bundle_to_dict_fields(self, tmp_path: Path) -> None:
        gen = WyckoffReportGenerator(str(tmp_path))
        bundle = _bundle(
            manifest=_manifest(),
            visual_evidence_list=[
                VisualEvidence(
                    visual_trend="uptrend",
                    visual_phase_hint="possible_markup",
                )
            ],
        )
        payload = gen._bundle_to_dict(bundle)

        assert payload["manifest"]["usable_count"] == 1
        assert payload["detected_timeframes"] == ["daily"]
        assert payload["visual_evidence_count"] == 1


# ─────────────────────────── 集成：fuse → 报告 ───────────────────────────


class TestFuseThenReport:
    def test_fused_result_renders_to_markdown(self, tmp_path: Path) -> None:
        engine = FusionEngine()
        fused: AnalysisResult = engine.fuse(_report(), _bundle(manifest=_manifest()))

        gen = WyckoffReportGenerator(str(tmp_path))
        path = gen.generate_markdown_report(fused, image_bundle=_bundle())

        assert "000001.SZ" in Path(path).read_text(encoding="utf-8")
