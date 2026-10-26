# -*- coding: utf-8 -*-
"""
v3.0 威科夫分析引擎 - 唯一入口
合并 analyzer.py + data_engine.py，100% 实现 Promote_v3.0.md
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

import pandas as pd

from uniquant.brain.indicators.indicators import Indicators  # noqa: F401
from uniquant.brain.wyckoff.analysis import (
    analyze_chips,
    analyze_multiframe,
    build_timeframe_snapshot,
    compute_avg_price_deviation,
    compute_money_flow_trend,
    create_no_signal_report,
    merge_multitimeframe_reports,
    resample_ohlcv,
    scan_signal_summary,
)
from uniquant.brain.wyckoff.classifiers import (
    classify_accumulation_sub_phase,
    classify_distribution_sub_phase,
    classify_unknown_candidate,
    classify_volume,
    classify_wyckoff_markup_event,
    detect_limit_moves,
)
from uniquant.brain.wyckoff.constants import (
    ENGINE_DEFAULT_LOOKBACK_DAYS,
    ENGINE_DEFAULT_MONTHLY_LOOKBACK,
    ENGINE_DEFAULT_RANGE_THRESHOLD,
    ENGINE_DEFAULT_TREND_THRESHOLD,
    ENGINE_DEFAULT_WEEKLY_LOOKBACK,
    ENGINE_MONTHLY_MIN_ROWS,
    ENGINE_WEEKLY_MIN_ROWS,
)
from uniquant.brain.wyckoff.event_detector import (
    detect_sos,
    detect_spring,
    detect_utad,
    scan_bc_sc,
    scan_false_breakout,
    scan_spring,
    scan_utad,
    step2_effort_result,
    step3_phase_c_t1,
)
from uniquant.brain.wyckoff.events import detect_all_events
from uniquant.brain.wyckoff.models import (
    BCPoint,
    ChipAnalysis,
    ConfidenceResult,
    ImageEvidenceBundle,
    LimitMove,
    RiskRewardResult,
    Rule0Result,
    SCPoint,
    Step1Result,
    Step2Result,
    Step3Result,
    TimeframeSnapshot,
    V3CounterfactualResult,
    V3TradingPlan,
    VolumeLevel,
    WyckoffPhase,
    WyckoffReport,
    WyckoffStructure,
)
from uniquant.brain.wyckoff.phase_analysis import RegimeAwarePhaseClassifier
from uniquant.brain.wyckoff.phase_detector import (
    compute_step1_context,
    detect_accumulation,
    detect_distribution,
    detect_markdown,
    detect_markup,
    step0_bc_tr_scan,
    step1_phase_determine,
)
from uniquant.brain.wyckoff.plan_builder import (
    apply_a_stock_rules,
    calc_confidence,
    step35_counterfactual,
    step4_risk_reward,
    step5_trading_plan,
)
from uniquant.brain.wyckoff.pnf import PointAndFigure
from uniquant.brain.wyckoff.relative_strength import rs_classify
from uniquant.brain.wyckoff.report_builder import build_wyckoff_report
from uniquant.brain.wyckoff.rules import V3Rules
from uniquant.brain.wyckoff.sequence import WyckoffScorer
from uniquant.brain.wyckoff.structural_adjuster import (
    BASE_AMPLIFICATION,
    _apply_structural_adjustment,
    _compute_structural_score,
    _detect_adjustment_status,
    _downgrade_confidence,
    _downgrade_direction,
)
from uniquant.shared.config_loader import get_config
from uniquant.shared.constants import SPRING_CLOSE_FACTOR, SPRING_LOW_FACTOR  # noqa: F401
from uniquant.shared.logger_factory import get_logger

logger = get_logger(__name__)


class WyckoffEngine:
    """v3.0 威科夫分析引擎 - 唯一入口"""

    def __init__(
        self,
        lookback_days: int = ENGINE_DEFAULT_LOOKBACK_DAYS,
        weekly_lookback: int = ENGINE_DEFAULT_WEEKLY_LOOKBACK,
        monthly_lookback: int = ENGINE_DEFAULT_MONTHLY_LOOKBACK,
        is_st: bool = False,
        range_threshold: float = ENGINE_DEFAULT_RANGE_THRESHOLD,
        trend_threshold: float = ENGINE_DEFAULT_TREND_THRESHOLD,
    ):
        self._is_st = is_st
        self.lookback_days = lookback_days
        self.weekly_min_rows = ENGINE_WEEKLY_MIN_ROWS
        self.monthly_min_rows = ENGINE_MONTHLY_MIN_ROWS
        self.weekly_lookback = weekly_lookback  # 周线回看行数
        self.monthly_lookback = monthly_lookback  # 月线回看行数
        self.range_threshold = range_threshold  # 价格范围阈值（TR判定用）
        self.trend_threshold = trend_threshold  # 短期趋势阈值
        # 计算多周期分析所需的日线数据量
        # 周线: weekly_lookback周 × 7天
        # 月线: monthly_lookback月 × 30天
        weekly_days = weekly_lookback * 7
        monthly_days = monthly_lookback * 30
        self.multi_timeframe_lookback_days = max(lookback_days, weekly_days, monthly_days)
        self.rules = V3Rules()
        self._debug_r8_compare: bool = False
        self._debug_r8_bypass_result: Optional[ConfidenceResult] = None
        self._debug_r8_full_result: Optional[ConfidenceResult] = None

        # P1-D: WSS 接线 — 从 config 读取 feature flag
        self._wss_scorer: Optional[WyckoffScorer] = None
        try:
            cfg = get_config()
            wss_enabled = cfg.get("wyckoff.wss_enabled", False)
            if wss_enabled:
                wss_path = cfg.get("wyckoff.wss_lookup_path", "")
                if wss_path and os.path.exists(wss_path):
                    self._wss_scorer = WyckoffScorer(wss_path=wss_path)
                    logger.info(
                        "WSS enabled: loaded %d sequences from %s",
                        len(self._wss_scorer.wss.lookup),
                        wss_path,
                    )
                else:
                    # P1-1: wss_enabled=true 但查找表缺失 → 显式告警而不是静默回退。
                    # 防止"看似开启实为死分支" (is_loaded 恒 False)。
                    logger.warning(
                        "WSS enabled but lookup path missing (%s) — falling back to "
                        "uncalibrated scoring",
                        wss_path or "<empty>",
                    )
        except (ValueError, KeyError, AttributeError, TypeError, ZeroDivisionError) as e:
            logger.warning(
                "Failed to initialize WSS scorer (%s: %s) — falling back to uncalibrated scoring",
                type(e).__name__,
                e,
                exc_info=True,
            )
            self._wss_scorer = None

        # P0-5 (2026-08-12 深入再研究定稿): structural_adjust 默认关。
        # 门控 _apply_structural_adjustment，保留 structural_score 叙事字段回填。
        try:
            cfg = get_config()
            self._structural_adjust_enabled: bool = bool(
                cfg.get("wyckoff.structural_adjust_enabled", False)
            )
        except (ValueError, KeyError, AttributeError, TypeError, ZeroDivisionError) as e:
            logger.warning(
                "Failed to read wyckoff.structural_adjust_enabled (%s: %s), defaulting to False",
                type(e).__name__,
                e,
                exc_info=True,
            )
            self._structural_adjust_enabled = False

        # 红蓝对抗 (2026-08-07): ACCUMULATION 蓄势超额为负 → 多头方向降 1 档。
        # config wyckoff.accumulation_downgrade (默认 false 向后兼容; config.yaml 已开 true)。
        self._accumulation_downgrade: bool = False
        try:
            cfg = get_config()
            self._accumulation_downgrade = bool(
                cfg.get("wyckoff.accumulation_downgrade", False)
            )
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            logger.warning(
                "accumulation_downgrade config read failed (%s: %s)",
                type(e).__name__,
                e,
                exc_info=True,
            )
        self._code_prefix: str = ""

        # Load calibration thresholds from config (if present)
        self.calibration: dict = {}
        try:
            cfg = get_config()
            calib = cfg.get("wyckoff.calibration", {})
            if isinstance(calib, dict) and calib:
                self.calibration = calib
                logger.info("Loaded Wyckoff calibration from config: %d keys", len(calib))
        except (ValueError, KeyError, AttributeError, TypeError, ZeroDivisionError) as e:
            logger.warning(
                "Failed to load wyckoff.calibration (%s: %s)",
                type(e).__name__,
                e,
                exc_info=True,
            )
            self.calibration = {}

    def _normalize_input_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        if "volume" not in df.columns and "vol" in df.columns:
            return df.rename(columns={"vol": "volume"})
        return df

    def _resample_ohlcv(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        return resample_ohlcv(df, rule)

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        period: str = "日线",
        image_evidence: Optional[ImageEvidenceBundle] = None,
        multi_timeframe: bool = False,
        index_df: Optional[pd.DataFrame] = None,
    ) -> WyckoffReport:
        """主入口 - 支持单周期和多周期"""
        if multi_timeframe:
            return self._analyze_multiframe(df, symbol, image_evidence, index_df)
        return self._analyze_single(df, symbol, period, image_evidence, index_df)

    def _analyze_single(
        self,
        df: pd.DataFrame,
        symbol: str,
        period: str,
        image_evidence: Optional[ImageEvidenceBundle] = None,
        index_df: Optional[pd.DataFrame] = None,
    ) -> WyckoffReport:
        """单周期 - Step 0→5"""
        required_cols = ["date", "open", "high", "low", "close"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning(f"数据缺少必要列: {missing_cols}")
            return self._create_no_signal_report(symbol, period, f"缺少必要列: {missing_cols}")

        if "volume" not in df.columns and "vol" not in df.columns:
            logger.warning(f"数据缺少成交量列: {symbol}")
            return self._create_no_signal_report(symbol, period, "缺少成交量数据")

        if "close" in df.columns:
            close_std = df["close"].std()
            if close_std < 1e-10:
                logger.warning(f"价格序列恒定: {symbol}")
                return self._create_no_signal_report(symbol, period, "价格序列恒定，无波动")

        frame = self._normalize_input_frame(df)

        if period == "日线":
            min_rows = 100
        elif period == "周线":
            min_rows = self.weekly_min_rows
        else:  # 月线
            min_rows = self.monthly_min_rows

        if frame is None or len(frame) < min_rows:
            reason = f"数据不足，需要至少 {min_rows} 根 K 线，当前只有 {len(frame) if frame is not None else 0} 根"
            return self._create_no_signal_report(symbol, period, reason)

        if period == "日线":
            lookback = self.lookback_days
        elif period == "周线":
            lookback = min(len(frame), self.weekly_lookback)
        else:  # 月线
            lookback = min(len(frame), self.monthly_lookback)

        full_frame = frame
        frame = frame.tail(lookback).reset_index(drop=True)

        adjustment_status = _detect_adjustment_status(frame["close"])

        pnf_result: Optional[dict] = None
        try:
            pnf = PointAndFigure(box_size=0.02, reversal=2)
            pnf.build(frame)
            pnf_result = {
                "phase_hint": pnf.wyckoff_phase_hint(),
                "breakout": pnf.breakout_detected(),
                "count_target": pnf.count_target(),
                "congestion_zone": pnf.congestion_zone(),
            }
        except (ValueError, TypeError, KeyError):
            logger.warning("Point and Figure analysis failed", exc_info=True)
            pnf_result = {"phase_hint": "neutral", "breakout": False, "count_target": 0.0}

        rule0 = self._step0_bc_tr_scan(frame, pnf_zone=pnf_result.get("congestion_zone"))

        if rule0.validity == "insufficient":
            return self._create_no_signal_report(symbol, period, "BC和TR均不可见，结构不足")

        step1 = self._step1_phase_determine(frame, rule0, pnf_hint=pnf_result.get("phase_hint"))

        contradictions = 0
        if step1.phase == WyckoffPhase.UNKNOWN and not step1.unknown_candidate:
            contradictions += 1
        if rule0.validity in ("partial", "tr_fallback"):
            contradictions += 1

        struct_clarity = "清晰"
        if step1.phase == WyckoffPhase.UNKNOWN and not step1.unknown_candidate:
            struct_clarity = "混沌"
        elif contradictions >= 2:
            struct_clarity = "矛盾"

        if self.rules.rule4_no_trade_zone(contradictions, struct_clarity):
            return self._create_no_signal_report(
                symbol, period, "信号矛盾或结构混沌，进入No Trade Zone"
            )

        step2 = self._step2_effort_result(frame, step1)
        step3 = self._step3_phase_c_t1(frame, step1, rule0)
        step35 = self._step35_counterfactual(frame, step1, step2, step3, rule0)
        rr_result = self._step4_risk_reward(
            frame, step1, step3, rule0, pnf_count_target=pnf_result.get("count_target", 0.0)
        )
        confidence = self._calc_confidence(rule0, step1, step3, step35, rr_result, False)

        structural_score = 0.0
        try:
            events = detect_all_events(frame)
            event_types = [ev.event_type for ev in events]
            structural_score = _compute_structural_score(
                event_types, step1.phase, step3, scorer=self._wss_scorer
            )
        except (ValueError, TypeError, KeyError):
            logger.warning("structural_score computation failed", exc_info=True)
            structural_score = 0.0

        if self._structural_adjust_enabled:
            confidence = _apply_structural_adjustment(confidence, structural_score)

        v3_plan = self._step5_trading_plan(step1, step3, step35, rr_result, confidence, df=frame)
        v3_plan = self._apply_a_stock_rules(step1, v3_plan)

        regime_phase: Optional[str] = None
        try:
            rpc = RegimeAwarePhaseClassifier()
            phase_str, _ = rpc.classify(
                frame, pd.Timestamp(df["date"].iloc[-1]), period="monthly"
            )
            regime_phase = phase_str
        except (ValueError, TypeError, KeyError, RuntimeError):
            logger.warning("Regime-aware phase classification failed", exc_info=True)
            regime_phase = None

        relative_strength: Optional[str] = None
        relative_strength_detail: Optional[dict] = None
        if index_df is not None:
            try:
                rs_result = rs_classify(frame, index_df)
                relative_strength = rs_result.classification
                relative_strength_detail = {
                    "stock_return_20d": rs_result.stock_return_20d,
                    "index_return_20d": rs_result.index_return_20d,
                    "excess_return": rs_result.excess_return,
                    "stock_vol_ratio": rs_result.stock_vol_ratio,
                    "sufficient_data": rs_result.sufficient_data,
                }
            except (ValueError, TypeError, KeyError):
                logger.warning("Relative strength classification failed", exc_info=True)
                relative_strength = None
                relative_strength_detail = None

        return self._build_report(
            symbol,
            period,
            frame,
            rule0,
            step1,
            step2,
            step3,
            step35,
            rr_result,
            confidence,
            v3_plan,
            pnf_result,
            regime_phase,
            adjustment_status,
            structural_score,
            relative_strength,
            relative_strength_detail,
            pnf_phase_divergence=step1.pnf_phase_divergence,
            full_frame=full_frame,
        )

    def _step0_bc_tr_scan(
        self, df: pd.DataFrame, pnf_zone: Optional[tuple] = None
    ) -> Rule0Result:
        """Step 0: BC/TR 定位扫描"""
        return step0_bc_tr_scan(
            df,
            pnf_zone=pnf_zone,
            scan_bc_sc_fn=self._scan_bc_sc,
            range_threshold=self.range_threshold,
            rules=self.rules,
        )

    def _compute_step1_context(self, df: pd.DataFrame, rule0: Rule0Result) -> dict:
        """Compute preliminary metrics shared by all phase detectors."""
        return compute_step1_context(
            df, rule0, range_threshold=self.range_threshold, trend_threshold=self.trend_threshold
        )

    def _detect_accumulation(
        self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result
    ) -> Optional[dict]:
        return detect_accumulation(df, ctx, rule0, self.calibration)

    def _detect_markup(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        return detect_markup(df, ctx, rule0, self.calibration)

    def _detect_distribution(
        self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result
    ) -> Optional[dict]:
        return detect_distribution(df, ctx, rule0, self.calibration, scan_utad_fn=self._scan_utad)

    def _detect_markdown(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        return detect_markdown(df, ctx, rule0, self.calibration)

    def _detect_spring(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        return detect_spring(df, ctx, rule0)

    def _scan_spring(self, df: pd.DataFrame, boundary_lower: float) -> Optional[dict]:
        return scan_spring(df, boundary_lower)

    def _scan_utad(self, df: pd.DataFrame, boundary_upper: float) -> Optional[dict]:
        return scan_utad(df, boundary_upper)

    def _scan_false_breakout(self, df: pd.DataFrame, boundary_upper: float) -> Optional[dict]:
        return scan_false_breakout(df, boundary_upper)

    def _detect_utad(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        return detect_utad(df, ctx, rule0, scan_utad_fn=self._scan_utad)

    def _detect_sos(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        return detect_sos(df, ctx, rule0)

    def _step1_phase_determine(
        self, df: pd.DataFrame, rule0: Rule0Result, pnf_hint: Optional[str] = None
    ) -> Step1Result:
        detectors = [
            self._detect_markup,
            self._detect_distribution,
            self._detect_markdown,
            self._detect_accumulation,
            self._detect_spring,
            self._detect_utad,
            self._detect_sos,
        ]
        return step1_phase_determine(
            df,
            rule0,
            pnf_hint=pnf_hint,
            range_threshold=self.range_threshold,
            trend_threshold=self.trend_threshold,
            calibration=self.calibration,
            detectors=detectors,
            classify_unknown_candidate_fn=self._classify_unknown_candidate,
            classify_accumulation_sub_phase_fn=self._classify_accumulation_sub_phase,
            classify_distribution_sub_phase_fn=self._classify_distribution_sub_phase,
        )

    def _step2_effort_result(self, df: pd.DataFrame, step1: Step1Result) -> Step2Result:
        return step2_effort_result(df, step1)

    def _step3_phase_c_t1(
        self, df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result
    ) -> Step3Result:
        return step3_phase_c_t1(
            df,
            step1,
            rule0,
            rules=self.rules,
            scan_spring_fn=self._scan_spring,
            scan_utad_fn=self._scan_utad,
            detect_sos_fn=self._detect_sos,
            detect_limit_moves_fn=self._detect_limit_moves,
        )

    def _step35_counterfactual(
        self,
        df: pd.DataFrame,
        step1: Step1Result,
        step2: Step2Result,
        step3: Step3Result,
        rule0: Rule0Result,
    ) -> V3CounterfactualResult:
        return step35_counterfactual(df, step1, step2, step3, rule0, rules=self.rules)

    def _step4_risk_reward(
        self,
        df: pd.DataFrame,
        step1: Step1Result,
        step3: Step3Result,
        rule0: Rule0Result,
        pnf_count_target: Optional[float] = None,
    ) -> RiskRewardResult:
        return step4_risk_reward(
            df, step1, step3, rule0, rules=self.rules, pnf_count_target=pnf_count_target
        )

    def _calc_confidence(
        self,
        rule0: Rule0Result,
        step1: Step1Result,
        step3: Step3Result,
        cf: V3CounterfactualResult,
        rr: RiskRewardResult,
        multiframe: bool,
    ) -> ConfidenceResult:
        res, bypass, full = calc_confidence(
            rule0,
            step1,
            step3,
            cf,
            rr,
            multiframe,
            rules=self.rules,
            debug_r8_compare=self._debug_r8_compare,
        )
        if self._debug_r8_compare:
            self._debug_r8_bypass_result = bypass
            self._debug_r8_full_result = full
        return res

    def _step5_trading_plan(
        self,
        step1: Step1Result,
        step3: Step3Result,
        cf: V3CounterfactualResult,
        rr: RiskRewardResult,
        confidence: ConfidenceResult,
        df: Optional[pd.DataFrame] = None,
    ) -> V3TradingPlan:
        return step5_trading_plan(
            step1,
            step3,
            cf,
            rr,
            confidence,
            df=df,
            rules=self.rules,
            code_prefix=self._code_prefix,
            is_st=self._is_st,
            accumulation_downgrade=self._accumulation_downgrade,
            scan_false_breakout_fn=self._scan_false_breakout,
            classify_markup_event_fn=self._classify_wyckoff_markup_event,
            detect_limit_moves_fn=self._detect_limit_moves,
        )

    def _apply_a_stock_rules(self, step1: Step1Result, plan: V3TradingPlan) -> V3TradingPlan:
        return apply_a_stock_rules(step1, plan, rules=self.rules)

    def _build_report(
        self,
        symbol: str,
        period: str,
        df: pd.DataFrame,
        rule0: Rule0Result,
        step1: Step1Result,
        step2: Step2Result,
        step3: Step3Result,
        step35: V3CounterfactualResult,
        rr: RiskRewardResult,
        confidence: ConfidenceResult,
        v3_plan: V3TradingPlan,
        pnf_result: Optional[dict] = None,
        regime_phase: Optional[str] = None,
        adjustment_status: str = "unknown",
        structural_score: float = 0.0,
        relative_strength: Optional[str] = None,
        relative_strength_detail: Optional[dict] = None,
        pnf_phase_divergence: Optional[str] = None,
        full_frame: Optional[pd.DataFrame] = None,
    ) -> WyckoffReport:
        return build_wyckoff_report(
            symbol=symbol,
            period=period,
            df=df,
            rule0=rule0,
            step1=step1,
            step2=step2,
            step3=step3,
            step35=step35,
            rr=rr,
            confidence=confidence,
            v3_plan=v3_plan,
            pnf_result=pnf_result,
            regime_phase=regime_phase,
            adjustment_status=adjustment_status,
            structural_score=structural_score,
            relative_strength=relative_strength,
            relative_strength_detail=relative_strength_detail,
            pnf_phase_divergence=pnf_phase_divergence,
            full_frame=full_frame,
            classify_markup_event_fn=self._classify_wyckoff_markup_event,
            detect_limit_moves_fn=self._detect_limit_moves,
            analyze_chips_fn=self._analyze_chips,
        )

    def _classify_unknown_candidate(
        self, df: pd.DataFrame, phase: WyckoffPhase, rule0: Rule0Result
    ) -> str:
        return classify_unknown_candidate(df, phase, rule0)

    def _classify_wyckoff_markup_event(self, df: pd.DataFrame, boundary_upper: float) -> str:
        return classify_wyckoff_markup_event(df, boundary_upper)

    def _classify_accumulation_sub_phase(
        self, df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result
    ) -> str:
        return classify_accumulation_sub_phase(df, step1, rule0, self.rules)

    def _classify_distribution_sub_phase(
        self, df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result
    ) -> str:
        return classify_distribution_sub_phase(df, step1, rule0)

    def _classify_volume(self, volume: float, volume_series: pd.Series) -> VolumeLevel:
        return classify_volume(volume, volume_series, self.rules)

    def _scan_bc_sc(self, df: pd.DataFrame) -> Tuple[Optional[BCPoint], Optional[SCPoint]]:
        return scan_bc_sc(df, rules=self.rules)

    def _detect_limit_moves(self, df: pd.DataFrame) -> List[LimitMove]:
        return detect_limit_moves(df, self._code_prefix, self._is_st, self.rules)

    def _analyze_chips(self, df: pd.DataFrame, structure: WyckoffStructure) -> ChipAnalysis:
        return analyze_chips(df, structure)

    def _compute_avg_price_deviation(self, df: pd.DataFrame) -> float:
        return compute_avg_price_deviation(df)

    def _compute_money_flow_trend(self, df: pd.DataFrame) -> float:
        return compute_money_flow_trend(df)

    def _analyze_multiframe(
        self,
        df: pd.DataFrame,
        symbol: str,
        image_evidence: Optional[ImageEvidenceBundle] = None,
        index_df: Optional[pd.DataFrame] = None,
    ) -> WyckoffReport:
        return analyze_multiframe(
            df,
            symbol,
            image_evidence,
            self._normalize_input_frame,
            self._resample_ohlcv,
            self._analyze_single,
            self.multi_timeframe_lookback_days,
            self.rules,
            index_df,
        )

    def _merge_multitimeframe_reports(
        self,
        symbol: str,
        daily_report: WyckoffReport,
        weekly_report: WyckoffReport,
        monthly_report: WyckoffReport,
    ) -> WyckoffReport:
        return merge_multitimeframe_reports(
            symbol,
            daily_report,
            weekly_report,
            monthly_report,
            self.rules,
        )

    def _build_timeframe_snapshot(self, report: WyckoffReport) -> TimeframeSnapshot:
        return build_timeframe_snapshot(report)

    def _create_no_signal_report(self, symbol: str, period: str, reason: str) -> WyckoffReport:
        return create_no_signal_report(symbol, period, reason)

    def _scan_buy_confidence_gate(self) -> float:
        """P0-4: BUY 门槛 (config wyckoff.confidence_gate, 默认 0.40)。"""
        try:
            return float(get_config().get("wyckoff.confidence_gate", 0.40) or 0.40)
        except (ValueError, KeyError, AttributeError, TypeError, ZeroDivisionError) as e:
            logger.warning(
                "Failed to read wyckoff.confidence_gate config (%s: %s), using default 0.40",
                type(e).__name__,
                e,
                exc_info=True,
            )
            return 0.40

    def scan_signal(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
    ) -> dict:
        """轻量级信号扫描 - 仅返回关键信号标签"""
        return scan_signal_summary(self, df, symbol)


def create_a_share_monthly_engine() -> WyckoffEngine:
    """Create a WyckoffEngine configured for A-share monthly data.

    A-share monthly bars have range_pct P50=91% (vs 20% for daily).
    Uses statistically derived thresholds from 500 stocks × 76K monthly snapshots.
    """
    return WyckoffEngine(
        lookback_days=12,
        range_threshold=0.80,
        trend_threshold=0.10,
    )


__all__ = [
    "BASE_AMPLIFICATION",
    "WyckoffEngine",
    "_apply_structural_adjustment",
    "_compute_structural_score",
    "_detect_adjustment_status",
    "_downgrade_confidence",
    "_downgrade_direction",
    "create_a_share_monthly_engine",
]
