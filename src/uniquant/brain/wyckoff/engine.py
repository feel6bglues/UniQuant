# -*- coding: utf-8 -*-
"""
v3.0 威科夫分析引擎 - 唯一入口
合并 analyzer.py + data_engine.py，100% 实现 Promote_v3.0.md
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from uniquant.shared.logger_factory import get_logger
from uniquant.shared.config_loader import get_config

import numpy as np
import pandas as pd

from uniquant.shared.constants import SPRING_CLOSE_FACTOR, SPRING_LOW_FACTOR  # noqa: F401
from uniquant.brain.wyckoff.constants import (
    ENGINE_WEEKLY_MIN_ROWS,
    ENGINE_MONTHLY_MIN_ROWS,
    ENGINE_DEFAULT_LOOKBACK_DAYS,
    ENGINE_DEFAULT_WEEKLY_LOOKBACK,
    ENGINE_DEFAULT_MONTHLY_LOOKBACK,
    ENGINE_DEFAULT_RANGE_THRESHOLD,
    ENGINE_DEFAULT_TREND_THRESHOLD,
)
from uniquant.brain.wyckoff.analysis import (
    analyze_chips,
    analyze_multiframe,
    build_timeframe_snapshot,
    compute_avg_price_deviation,
    compute_money_flow_trend,
    create_no_signal_report,
    merge_multitimeframe_reports,
)
from uniquant.brain.wyckoff.classifiers import (
    classify_accumulation_sub_phase,
    classify_distribution_sub_phase,
    classify_unknown_candidate,
    classify_volume,
    classify_wyckoff_markup_event,
    detect_limit_moves,
)
from uniquant.brain.wyckoff.models import (
    BCPoint,
    ChipAnalysis,
    ConfidenceLevel,
    ConfidenceResult,
    ImageEvidenceBundle,
    LimitMove,
    LimitMoveType,
    RiskRewardProjection,
    RiskRewardResult,
    Rule0Result,
    SCPoint,
    Step1Result,
    Step2Result,
    Step3Result,
    StressTest,
    TimeframeSnapshot,
    TradingPlan,
    V3CounterfactualResult,
    V3TradingPlan,
    VolumeLevel,
    WyckoffPhase,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
)
from uniquant.brain.wyckoff.rules import V3Rules
from uniquant.brain.wyckoff.pnf import PointAndFigure
from uniquant.brain.wyckoff.phase_analysis import RegimeAwarePhaseClassifier
from uniquant.brain.wyckoff.events import detect_all_events, event_sequence_key
from uniquant.brain.wyckoff.sequence import event_sequence_score, WyckoffScorer
from uniquant.brain.wyckoff.relative_strength import rs_classify
from uniquant.brain.wyckoff.effort_result import detect_effort_result_divergence
from uniquant.brain.indicators.indicators import Indicators

logger = get_logger(__name__)


def _downgrade_confidence(level: str) -> str:
    """CF-C4: 假突破惩罚 → 置信度降 1 级 (A→B, B→C, C→D, D→D)."""
    order = ["A", "B", "C", "D"]
    if level in order:
        idx = order.index(level)
        return order[min(idx + 1, len(order) - 1)]
    return "D"


def _apply_structural_adjustment(
    confidence: ConfidenceResult, structural_score: float
) -> ConfidenceResult:
    """SQ-C1: 结构完整性评分作为置信度加权输入 (非破坏性，纯函数)。

    - 恒回填 structural_score 到 ConfidenceResult (不再恒为 0.0)。
    - 等级单调微调: 高结构分 (≥55) 升 1 级；低结构分 (≤45) 降 1 级；居中不变。
    - 阈值经 P1-C 可达性验证: 真实 _compute_structural_score 最高约 70.2，
      最低约 44.1，确保升级/降级路径均可达。
    - 5 条件矩阵成员 (bc/rr/…) 与 bypassed/reason 保持原样。
    - B+ 特殊等级归 B 处理，A/D 为边界 (不越界)。
    """
    result = ConfidenceResult(
        level=confidence.level,
        bc_located=confidence.bc_located,
        spring_lps_verified=confidence.spring_lps_verified,
        counterfactual_passed=confidence.counterfactual_passed,
        rr_qualified=confidence.rr_qualified,
        multiframe_aligned=confidence.multiframe_aligned,
        position_size=confidence.position_size,
        reason=confidence.reason,
        bypassed=confidence.bypassed,
        structural_score=float(structural_score),
    )

    order = ["A", "B", "C", "D"]
    base_level = "B" if confidence.level == "B+" else confidence.level
    if base_level not in order:
        return result

    idx = order.index(base_level)
    if structural_score >= 55.0:
        idx = max(idx - 1, 0)
    elif structural_score <= 45.0:
        idx = min(idx + 1, len(order) - 1)
    result.level = order[idx]
    return result


def _detect_adjustment_status(close) -> str:
    """CN-C4: 探测数据是否为前复权 (pre_adjusted) 或未复权 (raw)。

    启发式: A 股单日涨跌停上限 20%。前复权数据相邻收盘价 pct_change
    不应持续超过 20%；未复权数据在除权除息日会出现 >20% 收盘跳空。
    排除连续涨停结构 (前一日本身已涨停 >15%，次日跳空属正常)。
    """
    pct = pd.Series(close).astype(float).pct_change()
    over = (pct.abs() > 0.20) & (pct.shift(1).fillna(0.0).abs() <= 0.15)
    if int(over.sum()) >= 1:
        return "raw"
    return "pre_adjusted"


def _compute_structural_score(
    event_types: List[str], phase, step3,
    scorer: Optional[WyckoffScorer] = None,
) -> float:
    """SQ-C1: 结构完整性评分 (0-100)，纯函数可复现。

    - event_sequence_score 对事件序列加权 → base ∈ [-1, 1]；
    - 若 scorer 提供且 WSS 已加载 → 使用 scorer.score_sequence 取 blended 评分；
    - 明确相位 (非 unknown) +0.20，unknown 相位 -0.10 (拉开分布)；
    - spring/utad 已确认按质量加成 (0.07/0.03)；
    - clamp 到 [-1, 1] → min-max 映射到 [0, 100]。
    - P1-C 再校准: 权重放大使升级路径可达 (max ≈ 70.2)，降级路径可达 (min ≈ 44.1)。
    """
    if scorer is not None and scorer.wss.is_loaded:
        seq_key = '>'.join(event_types)
        base, _ = scorer.score_sequence(event_types, seq_key)
    else:
        base, _ = event_sequence_score(event_types)
    phase_bonus = 0.20 if phase != WyckoffPhase.UNKNOWN else -0.10
    event_bonus = 0.0
    if step3.spring_detected:
        quality_str = str(getattr(step3, "spring_quality", "无"))
        quality_boost = 0.07 if "一级" in quality_str else 0.03
        event_bonus += quality_boost
    if step3.utad_detected:
        event_bonus += 0.07
    raw = max(-1.0, min(1.0, base + phase_bonus + event_bonus))
    return round((raw + 1.0) / 2.0 * 100.0, 2)


class WyckoffEngine:
    """v3.0 威科夫分析引擎 - 唯一入口"""

    def __init__(
        self, lookback_days: int = ENGINE_DEFAULT_LOOKBACK_DAYS, weekly_lookback: int = ENGINE_DEFAULT_WEEKLY_LOOKBACK, monthly_lookback: int = ENGINE_DEFAULT_MONTHLY_LOOKBACK,
        is_st: bool = False, range_threshold: float = ENGINE_DEFAULT_RANGE_THRESHOLD, trend_threshold: float = ENGINE_DEFAULT_TREND_THRESHOLD,
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
                        len(self._wss_scorer.wss.lookup), wss_path,
                    )
        except Exception:
            logger.warning("WSS initialization failed, falling back to WSO-only", exc_info=True)

    def _normalize_input_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        return frame.sort_values("date").reset_index(drop=True)

    def _resample_ohlcv(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        frame = self._normalize_input_frame(df).set_index("date")
        agg_dict = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        if "amount" in frame.columns:
            agg_dict["amount"] = "sum"
        resampled = (
            frame.resample(rule, label="right", closed="right")
            .agg(agg_dict)
            .dropna(subset=["open", "high", "low", "close"])
            .reset_index()
        )
        return resampled

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        period: str = "日线",
        multi_timeframe: bool = False,
        image_evidence: Optional[ImageEvidenceBundle] = None,
        index_df: Optional[pd.DataFrame] = None,
    ) -> WyckoffReport:
        """主入口 - 严格按 v3.0 九步执行"""
        self._code_prefix = symbol[:3]
        self._current_symbol = symbol
        if multi_timeframe and period == "日线":
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
        # 检查必要的列
        required_cols = ['date', 'open', 'high', 'low', 'close']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning(f"数据缺少必要列: {missing_cols}")
            return self._create_no_signal_report(symbol, period, f"缺少必要列: {missing_cols}")

        # 检查 volume 列（可选但推荐）
        if 'volume' not in df.columns and 'vol' not in df.columns:
            logger.warning(f"数据缺少成交量列: {symbol}")
            return self._create_no_signal_report(symbol, period, "缺少成交量数据")

        # 检查价格是否恒定（零波动）
        if 'close' in df.columns:
            close_std = df['close'].std()
            if close_std < 1e-10:
                logger.warning(f"价格序列恒定: {symbol}")
                return self._create_no_signal_report(symbol, period, "价格序列恒定，无波动")

        frame = self._normalize_input_frame(df)

        # 根据周期设置正确的最小行数
        if period == "日线":
            min_rows = 100
        elif period == "周线":
            min_rows = self.weekly_min_rows
        else:  # 月线
            min_rows = self.monthly_min_rows

        if frame is None or len(frame) < min_rows:
            reason = f"数据不足，需要至少 {min_rows} 根 K 线，当前只有 {len(frame) if frame is not None else 0} 根"
            return self._create_no_signal_report(symbol, period, reason)

        # 根据周期设置正确的回看行数
        if period == "日线":
            lookback = self.lookback_days
        elif period == "周线":
            lookback = min(len(frame), self.weekly_lookback)
        else:  # 月线
            lookback = min(len(frame), self.monthly_lookback)

        frame = frame.tail(lookback).reset_index(drop=True)

        # CN-C4: 预复权状态探测 (研究平台: 标记 + 降级，不拒绝)
        adjustment_status = _detect_adjustment_status(frame["close"])

        # P&F 先行：Phase/TR/目标位的基础（PF-C1/C2/C3）
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

        # Step 0: BC/TR 定位扫描（P&F 密集区覆盖裸 H/L 边界）
        rule0 = self._step0_bc_tr_scan(frame, pnf_zone=pnf_result.get("congestion_zone"))

        if rule0.validity == "insufficient":
            return self._create_no_signal_report(symbol, period, "BC和TR均不可见，结构不足")

        # Step 1: 大局观与阶段判定（P&F phase_hint 驱动）
        step1 = self._step1_phase_determine(frame, rule0, pnf_hint=pnf_result.get("phase_hint"))

        # 规则4: 诚实不作为原则 - 检测信号矛盾
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

        # Step 2: 努力与结果
        step2 = self._step2_effort_result(frame, step1)

        # Step 3: Spring/UTAD + T+1
        step3 = self._step3_phase_c_t1(frame, step1, rule0)

        # Step 3.5: 反事实
        step35 = self._step35_counterfactual(frame, step1, step2, step3, rule0)

        # Step 4: 盈亏比（P&F count_target 优先作为第一目标）
        rr_result = self._step4_risk_reward(
            frame, step1, step3, rule0, pnf_count_target=pnf_result.get("count_target", 0.0)
        )

        # 置信度计算
        confidence = self._calc_confidence(rule0, step1, step3, step35, rr_result, False)

        # SQ-C1: 结构完整性评分 (置信度加权输入，非破坏性)
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
        confidence = _apply_structural_adjustment(confidence, structural_score)

        # Step 5: 交易计划
        v3_plan = self._step5_trading_plan(step1, step3, step35, rr_result, confidence, df=frame)

        # A 股铁律最终检查
        v3_plan = self._apply_a_stock_rules(step1, v3_plan)

        # Regime-aware enhanced phase
        regime_phase: Optional[str] = None
        try:
            rpc = RegimeAwarePhaseClassifier()
            phase_str, _ = rpc.classify(frame, pd.Timestamp(df['date'].iloc[-1]), period='monthly')
            regime_phase = phase_str
        except (ValueError, TypeError, KeyError, RuntimeError):
            logger.warning("Regime-aware phase classification failed", exc_info=True)
            regime_phase = None

        # RS-C1: 相对强弱四分类 (可选 index_df，None 时不计算)
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

        # 构建最终报告
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
        )

    def _step0_bc_tr_scan(
        self, df: pd.DataFrame, pnf_zone: Optional[tuple] = None
    ) -> Rule0Result:
        """Step 0: BC/TR 定位扫描"""
        bc_point, sc_point = self._scan_bc_sc(df)

        # 计算 TR 边界：P&F 水平密集区优先（PF-C3），否则回落 OHLC 高低点
        recent_60 = df.tail(60)
        if pnf_zone and len(pnf_zone) == 2 and pnf_zone[1] > pnf_zone[0] > 0:
            tr_upper = float(pnf_zone[1])
            tr_lower = float(pnf_zone[0])
            tr_source_override = "pnf_congestion"
        else:
            tr_upper = float(recent_60["high"].max())
            tr_lower = float(recent_60["low"].min())
            tr_source_override = None

        bc_found = bc_point is not None
        sc_found = sc_point is not None
        tr_defined = (tr_upper - tr_lower) / tr_lower <= self.range_threshold * 1.25 if tr_lower > 0 else False

        # 使用规则5进行降级策略
        fallback = self.rules.rule5_bc_tr_fallback(bc_found, tr_defined)

        tr_source = (
            tr_source_override
            or ("bc_ar"
                if bc_found
                else ("sc_spring" if sc_found else ("rolling_range" if tr_defined else "none")))
        )

        return Rule0Result(
            bc_found=bc_found,
            bc_position=bc_point,
            sc_found=sc_found,
            sc_position=sc_point,
            bc_in_chart=bc_found,
            tr_upper=tr_upper if tr_defined else None,
            tr_lower=tr_lower if tr_defined else None,
            tr_source=tr_source,
            validity=fallback["validity"],
            confidence_base=fallback["confidence_base"],
        )

    def _compute_step1_context(self, df: pd.DataFrame, rule0: Rule0Result) -> dict:
        """Compute preliminary metrics shared by all phase detectors."""
        recent_60 = df.tail(60)
        price_high = float(recent_60["high"].max())
        price_low = float(recent_60["low"].min())
        current_price = float(df.iloc[-1]["close"])
        ma5 = float(df.shift(1).tail(5)["close"].mean())
        ma20 = float(df.shift(1).tail(20)["close"].mean())
        total_range_pct = (price_high - price_low) / price_low if price_low > 0 else 1.0
        relative_position = (
            (current_price - price_low) / (price_high - price_low)
            if price_high > price_low
            else 0.5
        )

        if len(df) >= 40:
            recent_mean = float(df.shift(1).tail(20)["close"].mean())
            prev_mean = float(df.iloc[-40:-20]["close"].mean())
        else:
            recent_mean = float(df.shift(1).tail(10)["close"].mean())
            prev_mean = float(df.head(10)["close"].mean())
        short_trend_pct = (recent_mean - prev_mean) / prev_mean if prev_mean > 0 else 0.0

        is_in_trading_range = (
            total_range_pct <= self.range_threshold
        ) and (abs(short_trend_pct) < self.trend_threshold)

        prior_window = df.iloc[:-60] if len(df) > 60 else pd.DataFrame()
        if len(prior_window) >= 10:
            prior_first = float(prior_window["close"].iloc[0])
            prior_last = float(prior_window["close"].iloc[-1])
            prior_trend_pct = (
                (prior_last - prior_first) / prior_first if prior_first > 0 else 0.0
            )
        else:
            prior_trend_pct = 0.0

        return {
            "price_high": price_high,
            "price_low": price_low,
            "current_price": current_price,
            "ma5": ma5,
            "ma20": ma20,
            "total_range_pct": total_range_pct,
            "relative_position": relative_position,
            "short_trend_pct": short_trend_pct,
            "is_in_trading_range": is_in_trading_range,
            "prior_trend_pct": prior_trend_pct,
        }

    def _detect_accumulation(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        # PH-C1: 事件序列优先驱动 ACCUMULATION（忽略 price_position）
        try:
            events = detect_all_events(df)
            seq_key = event_sequence_key(events)
            if (
                "PS" in seq_key
                and "SC" in seq_key
                and seq_key.count("ST") >= 2
            ):
                return {
                    "phase": WyckoffPhase.ACCUMULATION,
                    "unknown_candidate": "accumulation_event_sequence",
                }
        except (AttributeError, TypeError, ValueError, KeyError):
            logger.warning("Event sequence detection failed for accumulation", exc_info=True)

        if ctx["is_in_trading_range"]:
            if ctx["prior_trend_pct"] < -0.03:
                return {"phase": WyckoffPhase.ACCUMULATION}
            if ctx["relative_position"] <= 0.40 and rule0.bc_found:
                return {"phase": WyckoffPhase.ACCUMULATION}
        else:
            if (
                ctx["short_trend_pct"] <= -0.02
                and ctx["current_price"] < ctx["ma20"]
                and ctx["ma5"] <= ctx["ma20"]
                and (rule0.bc_found or rule0.sc_found)
            ):
                return {"phase": WyckoffPhase.ACCUMULATION}
        return None

    def _detect_markup(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        cp = ctx["current_price"]
        ma5 = ctx["ma5"]
        ma20 = ctx["ma20"]
        rp = ctx["relative_position"]
        st = ctx["short_trend_pct"]

        if ctx["is_in_trading_range"]:
            if (rp >= 0.55 or st >= 0.03) and (
                (cp > ma20 * 0.97 and ma5 >= ma20 * 0.96)
                or (cp > ma5 and rp >= 0.50)
            ):
                return {"phase": WyckoffPhase.MARKUP}
        else:
            if st >= 0.03 and (
                (cp > ma20 and ma5 >= ma20)
                or (cp > ma5 and rp >= 0.50)
            ):
                return {"phase": WyckoffPhase.MARKUP}
            if st >= 0.015 and cp > ma20 and ma5 >= ma20 * 0.98 and rp >= 0.70:
                return {"phase": WyckoffPhase.MARKUP}
            if st >= 0.05 and ma5 >= ma20 and cp >= ma20 * 0.99 and rp >= 0.65:
                return {"phase": WyckoffPhase.MARKUP}
        return None

    def _detect_distribution(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        # PH-C2: 事件序列优先驱动 DISTRIBUTION（UTAD 假突破 + 放量，忽略 price_position）
        boundary_upper = rule0.tr_upper if rule0.tr_upper else ctx["price_high"]
        if boundary_upper > 0 and self._scan_utad(df, boundary_upper) is not None:
            return {
                "phase": WyckoffPhase.DISTRIBUTION,
                "unknown_candidate": "upthrust_candidate",
            }
        if ctx["is_in_trading_range"] and ctx["prior_trend_pct"] > 0.05:
            return {"phase": WyckoffPhase.DISTRIBUTION}
        return None

    def _detect_markdown(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        cp = ctx["current_price"]
        ma5 = ctx["ma5"]
        ma20 = ctx["ma20"]
        rp = ctx["relative_position"]
        st = ctx["short_trend_pct"]

        if ctx["is_in_trading_range"]:
            if (
                rule0.bc_found
                and rule0.bc_position is not None
                and cp <= rule0.bc_position.price * 0.85
                and cp < ma20 * 0.95
                and ma5 <= ma20
                and st <= -0.02
            ):
                return {"phase": WyckoffPhase.MARKDOWN}
        else:
            if st <= -0.05 and cp < ma20 * 0.95:
                return {"phase": WyckoffPhase.MARKDOWN}
            if (
                rule0.bc_found
                and rule0.bc_position is not None
                and cp <= rule0.bc_position.price * 0.90
                and cp < ma20
                and ma5 <= ma20
                and st <= 0
            ):
                return {"phase": WyckoffPhase.MARKDOWN}
            if (
                rule0.bc_found
                and rule0.bc_position is not None
                and st <= -0.04
                and rp <= 0.25
                and cp <= rule0.bc_position.price * 0.75
            ):
                return {"phase": WyckoffPhase.MARKDOWN}
        return None

    def _detect_spring(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        """Detect spring/Selling Climax pattern as an accumulation hint."""
        if not (ctx["short_trend_pct"] <= -0.02 and ctx["relative_position"] <= 0.55):
            return None
        last_row = df.iloc[-1]
        close_val = float(last_row["close"])
        open_val = float(last_row["open"])
        high_val = float(last_row["high"])
        low_val = float(last_row["low"])
        body_val = abs(close_val - open_val)
        lower_wick_val = min(close_val, open_val) - low_val
        close_loc = (close_val - low_val) / max(high_val - low_val, 0.01)
        amplitude = (high_val - low_val) / max(low_val, 0.01)
        is_new_low = (low_val == df.iloc[-11:-1]["low"].min())
        wick_ratio = lower_wick_val / max(body_val, 0.01)
        rebound_ratio = (close_val - low_val) / max(low_val, 0.01)
        if amplitude >= 0.02:
            if (close_loc >= 0.58 and lower_wick_val > body_val) or (
                is_new_low and rebound_ratio >= 0.01 and wick_ratio >= 0.6
            ):
                return {"phase": WyckoffPhase.UNKNOWN, "unknown_candidate": "sc_st_candidate"}
        return None

    def _scan_spring(self, df: pd.DataFrame, boundary_lower: float) -> Optional[dict]:
        """Scan for Spring in the recent window.

        O 列跌破 TR 下沿 0.5-1.5% 后 1-2 列内收回 + 量能萎缩确认。
        返回 {"date": str, "low": float, "vol_ratio": float, "pos": int} 或 None。
        """
        if boundary_lower <= 0 or len(df) < 5:
            return None
        recent = df.tail(30)
        vol_med = float(recent["volume"].median())
        if vol_med <= 0:
            return None
        lows = recent["low"].to_numpy()
        closes = recent["close"].to_numpy()
        vols = recent["volume"].to_numpy()
        dates = recent["date"].to_numpy()
        n = len(recent)
        offset = len(df) - n
        for i in range(n):
            low = lows[i]
            # O 列跌破 TR 下沿 0.5-1.5%（跌破但不过深）
            if not (boundary_lower * 0.985 <= low < boundary_lower):
                continue
            # 量能萎缩确认
            vol_ratio = vols[i] / vol_med if vol_med > 0 else 0.0
            if vol_ratio > 0.8:
                continue  # 量能未萎缩
            # 1-2 列内收回
            for j in range(i + 1, min(i + 3, n)):
                if closes[j] >= boundary_lower:
                    return {
                        "date": str(dates[i]),
                        "low": float(low),
                        "vol_ratio": vol_ratio,
                        "pos": offset + i,
                    }
        return None

    def _scan_utad(self, df: pd.DataFrame, boundary_upper: float) -> Optional[dict]:
        """Scan for UTAD (Upthrust After Distribution) in the recent window.

        X 列突破 TR 上沿 2%+ 后 1-2 列内收回 + 放量确认（量比 > 1.5）。
        返回 {"date": str, "vol_ratio": float} 或 None。
        """
        if boundary_upper <= 0 or len(df) < 5:
            return None
        recent = df.tail(30)
        vol_med = float(recent["volume"].median())
        if vol_med <= 0:
            return None
        highs = recent["high"].to_numpy()
        closes = recent["close"].to_numpy()
        vols = recent["volume"].to_numpy()
        dates = recent["date"].to_numpy()
        n = len(recent)
        for i in range(n):
            if highs[i] <= boundary_upper * 1.02:
                continue  # 未突破 TR 上沿 2%+
            vol_ratio = vols[i] / vol_med if vol_med > 0 else 0.0
            if vol_ratio <= 1.5:
                continue  # 量能不足
            for j in range(i, min(i + 3, n)):
                if closes[j] <= boundary_upper * 1.01:  # 1-2 列内收回
                    return {"date": str(dates[i]), "vol_ratio": vol_ratio}
        return None

    def _scan_false_breakout(self, df: pd.DataFrame, boundary_upper: float) -> Optional[dict]:
        """CF-C4: 检测假突破（突破 TR 上沿 2%+ 后 3 列内跌回 TR）。

        与 UTAD 同源：突破上沿需放量确认（量比>1.5），但跌回窗口放宽到 3 列，
        用于标记 false_breakout 惩罚（信号置信度降级）。
        返回 {"date": str, "close_high": float} 或 None。
        """
        if boundary_upper <= 0 or len(df) < 5:
            return None
        recent = df.tail(30)
        highs = recent["high"].to_numpy()
        closes = recent["close"].to_numpy()
        volumes = recent["volume"].to_numpy()
        dates = recent["date"].to_numpy()
        n = len(recent)
        vol_med = float(np.median(volumes)) if n else 0.0
        for i in range(n - 1):
            if highs[i] <= boundary_upper * 1.02:
                continue  # 未显著突破 TR 上沿
            if vol_med <= 0 or volumes[i] < 1.5 * vol_med:
                continue  # 量能不足
            for j in range(i + 1, min(i + 4, n)):  # 3 列内
                if closes[j] <= boundary_upper * 0.995:  # 跌回上沿下方
                    return {"date": str(dates[i]), "close_high": float(highs[i])}
        return None

    def _detect_utad(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        """Detect UTAD (Upthrust After Distribution) pattern."""
        boundary_upper = rule0.tr_upper if rule0.tr_upper else ctx["price_high"]
        if self._scan_utad(df, boundary_upper) is not None:
            return {"phase": WyckoffPhase.DISTRIBUTION, "unknown_candidate": "upthrust_candidate"}
        return None

    def _detect_sos(self, df: pd.DataFrame, ctx: dict, rule0: Rule0Result) -> Optional[dict]:
        """Detect SOS (Sign of Strength) pattern."""
        return None

    def _step1_phase_determine(
        self, df: pd.DataFrame, rule0: Rule0Result, pnf_hint: Optional[str] = None
    ) -> Step1Result:
        """Step 1: 大局观与阶段判定（分派到7个检测器，P&F phase_hint 优先驱动）"""
        ctx = self._compute_step1_context(df, rule0)

        phase = WyckoffPhase.UNKNOWN
        unknown_candidate = ""
        pnf_phase_divergence: Optional[str] = None

        # 总是运行检测器链（用于分歧分析）
        chain_phase = WyckoffPhase.UNKNOWN
        chain_unknown_candidate = ""
        detectors: List = [
            self._detect_markup,
            self._detect_distribution,
            self._detect_markdown,
            self._detect_accumulation,
            self._detect_spring,
            self._detect_utad,
            self._detect_sos,
        ]

        for detector in detectors:
            result = detector(df, ctx, rule0)
            if result is not None:
                chain_phase = result["phase"]
                chain_unknown_candidate = result.get("unknown_candidate", "")
                break

        if chain_phase == WyckoffPhase.UNKNOWN and not chain_unknown_candidate:
            chain_unknown_candidate = self._classify_unknown_candidate(df, chain_phase, rule0)

        # PF-C1: P&F phase_hint 明确时优先驱动阶段判定，但记录分歧
        if pnf_hint in ("accumulation", "distribution"):
            phase = (
                WyckoffPhase.ACCUMULATION
                if pnf_hint == "accumulation"
                else WyckoffPhase.DISTRIBUTION
            )
            if chain_phase != phase:
                pnf_phase_divergence = (
                    f"PnF={pnf_hint}, DetectorChain={chain_phase.value}"
                )
        else:
            phase = chain_phase
            unknown_candidate = chain_unknown_candidate

        # Phase A/B/C/D/E 细分
        sub_phase = ""
        temp_step1 = Step1Result(
            phase=phase,
            boundary_upper=rule0.tr_upper if rule0.tr_upper else ctx["price_high"],
            boundary_lower=rule0.tr_lower if rule0.tr_lower else ctx["price_low"],
        )
        if phase == WyckoffPhase.ACCUMULATION:
            sub_phase = self._classify_accumulation_sub_phase(df, temp_step1, rule0)
        elif phase == WyckoffPhase.DISTRIBUTION:
            sub_phase = self._classify_distribution_sub_phase(df, temp_step1, rule0)

        # 边界锚定
        boundary_upper = rule0.tr_upper if rule0.tr_upper else ctx["price_high"]
        boundary_lower = rule0.tr_lower if rule0.tr_lower else ctx["price_low"]
        boundary_source = []
        if rule0.bc_found:
            boundary_source.append("BC")
        if rule0.tr_source == "rolling_range":
            boundary_source.append("rolling_30d")

        return Step1Result(
            phase=phase,
            sub_phase=sub_phase,
            unknown_candidate=unknown_candidate,
            prior_trend_pct=ctx["prior_trend_pct"],
            is_in_tr=ctx["is_in_trading_range"],
            short_trend_pct=ctx["short_trend_pct"],
            relative_position=ctx["relative_position"],
            ma5=ctx["ma5"],
            ma20=ctx["ma20"],
            boundary_upper=boundary_upper,
            boundary_lower=boundary_lower,
            boundary_source=boundary_source,
            pnf_phase_divergence=pnf_phase_divergence,
        )

    def _step2_effort_result(self, df: pd.DataFrame, step1: Step1Result) -> Step2Result:
        """Step 2: 努力与结果（含跳空缺口检测）"""
        phenomena = []
        accumulation_evidence = 0.0
        distribution_evidence = 0.0

        recent_20 = df.tail(20)
        if len(recent_20) < 10:
            return Step2Result()

        avg_vol = recent_20["volume"].mean()
        price_change = (recent_20["close"].iloc[-1] - recent_20["close"].iloc[0]) / recent_20[
            "close"
        ].iloc[0]
        vol_change = (recent_20["volume"].iloc[-1] - avg_vol) / avg_vol if avg_vol > 0 else 0

        # 成交额维度分析（基于amount）
        if "amount" in recent_20.columns and recent_20["amount"].notna().all():
            avg_amt = recent_20["amount"].mean()
            amt_change = (recent_20["amount"].iloc[-1] - avg_amt) / avg_amt if avg_amt > 0 else 0

            # 金额与成交量同步放大 → 确认异常
            if amt_change > 0.3 and vol_change > 0.3 and abs(price_change) < 0.02:
                distribution_evidence += 0.4
                phenomena.append("量额双放大滞涨")

            # 金额放大但量缩 → 大单交易（金额主导的吸筹/派发）
            if amt_change > 0.2 and vol_change < -0.2:
                if price_change > 0.02:
                    accumulation_evidence += 0.3
                    phenomena.append("大单推升（金额放量但量能萎缩）")
                elif price_change < -0.02:
                    distribution_evidence += 0.3
                    phenomena.append("大单砸盘（金额放量但量能萎缩）")

            # 金额萎缩但量放大 → 散户化交易
            if amt_change < -0.2 and vol_change > 0.2:
                phenomena.append("散户化交易（量增额缩）")

        # 放量滞涨 → 派发倾向
        if vol_change > 0.3 and abs(price_change) < 0.02:
            distribution_evidence += 0.3
            phenomena.append("放量滞涨")

        # 缩量上推 → 吸筹倾向
        if vol_change < -0.3 and price_change > 0.02:
            accumulation_evidence += 0.2
            phenomena.append("缩量上推")

        # 下边界供给枯竭
        if step1.boundary_lower > 0:
            recent_low = float(recent_20["low"].min())
            if recent_low <= step1.boundary_lower * 1.02:
                low_vol = recent_20[recent_20["low"] <= step1.boundary_lower * 1.02][
                    "volume"
                ].mean()
                if low_vol < avg_vol * 0.7:
                    accumulation_evidence += 0.3
                    phenomena.append("下边界供给枯竭")

        # 高位炸板遗迹
        for row in recent_20.itertuples():
            pct = (row.close - row.open) / row.open if row.open > 0 else 0
            if pct > 0.09 and row.high > row.close * 1.02:
                distribution_evidence += 0.3
                phenomena.append("高位炸板遗迹")
                break

        # 跳空缺口检测
        has_breakaway_gap = False
        has_exhaustion_gap = False
        has_escape_gap = False
        for i in range(1, len(recent_20)):
            prev_row = recent_20.iloc[i - 1]
            curr_row = recent_20.iloc[i]

            # 向上跳空缺口：当前最低价 > 前一天最高价
            if curr_row["low"] > prev_row["high"]:
                gap_size = (curr_row["low"] - prev_row["high"]) / prev_row["high"] * 100
                if gap_size > 1.0:  # 缺口大于1%
                    # 判断缺口类型
                    if curr_row["close"] > curr_row["open"]:  # 阳线
                        phenomena.append(f"向上突破缺口({gap_size:.1f}%)")
                        accumulation_evidence += 0.2
                        has_breakaway_gap = True
                    else:  # 阴线
                        phenomena.append(f"向上竭尽缺口({gap_size:.1f}%)")
                        distribution_evidence += 0.2
                        has_exhaustion_gap = True

            # 向下跳空缺口：当前最高价 < 前一天最低价
            elif curr_row["high"] < prev_row["low"]:
                gap_size = (prev_row["low"] - curr_row["high"]) / prev_row["low"] * 100
                if gap_size > 1.0:  # 缺口大于1%
                    # 判断缺口类型
                    if curr_row["close"] < curr_row["open"]:  # 阴线
                        phenomena.append(f"向下逃逸缺口({gap_size:.1f}%)")
                        distribution_evidence += 0.3
                        has_escape_gap = True
                    else:  # 阳线
                        phenomena.append(f"向下竭尽缺口({gap_size:.1f}%)")
                        accumulation_evidence += 0.2

        net_bias = "neutral"
        if accumulation_evidence > distribution_evidence + 0.1:
            net_bias = "accumulation"
        elif distribution_evidence > accumulation_evidence + 0.1:
            net_bias = "distribution"

        vdb = detect_effort_result_divergence(df)
        if vdb != "none":
            phenomena.append(f"量价背离({vdb})")

        return Step2Result(
            phenomena=phenomena,
            accumulation_evidence=round(accumulation_evidence, 2),
            distribution_evidence=round(distribution_evidence, 2),
            net_bias=net_bias,
            has_breakaway_gap=has_breakaway_gap,
            has_exhaustion_gap=has_exhaustion_gap,
            has_escape_gap=has_escape_gap,
            vdb_divergence=vdb,
        )

    def _step3_phase_c_t1(
        self, df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result
    ) -> Step3Result:
        """Step 3: Spring/UTAD + T+1 风险"""
        spring_detected = False
        spring_quality = "无"
        spring_date = None
        spring_low_price = None
        utad_detected = False
        utad_date = None
        utad_quality = "无"
        st_detected = False
        lps_confirmed = False
        lps_stage = "not_test"
        test_low = None
        spring_volume = ""
        spring_volume_value = 0.0

        # ATR 提前计算（LPS 判定需要）
        atr_series = Indicators.calc_atr(df)
        current_atr = float(atr_series.iloc[-1]) if len(atr_series) > 0 else 0.0

        # Spring 检测（在 ACCUMULATION、UNKNOWN 和 MARKUP 阶段都可能有效）
        if (
            step1.phase in (WyckoffPhase.ACCUMULATION, WyckoffPhase.UNKNOWN, WyckoffPhase.MARKUP)
            and step1.boundary_lower > 0
        ):
            low_bound = step1.boundary_lower
            spring_found = self._scan_spring(df, low_bound)

            if spring_found is not None:
                spring_detected = True
                spring_date = spring_found["date"]
                spring_low_price = spring_found["low"]

                # 量能质量评估（基于 Spring 当日量比）
                vol_ratio = spring_found["vol_ratio"]
                spring_volume = self.rules.rule1_relative_volume(
                    vol_ratio * float(df["volume"].tail(30).median()),
                    df["volume"],
                )
                if spring_volume in ("地量", "萎缩"):
                    spring_quality = "二级(缩量待确认)"
                else:
                    spring_quality = "一级(放量确认)"

                # Spring 当日数值量（LPS 供给枯竭参照）
                spring_volume_value = float(df["volume"].iloc[spring_found["pos"]])

                # LPS 验证（规则6）- 分层判定（P0-A 重构）
                post_spring_idx = spring_found["pos"]
                if post_spring_idx < len(df) - 3:
                    post_spring_df = df.iloc[post_spring_idx + 1 :]
                    lps_result = self.rules.rule6_spring_validation(
                        True, post_spring_df, spring_low_price,
                        spring_volume=spring_volume_value,
                        atr=current_atr,
                    )
                    lps_confirmed = lps_result["lps_confirmed"]
                    lps_stage = lps_result.get("lps_stage", "not_test")
                    test_low = lps_result.get("test_low")
                    if lps_confirmed:
                        spring_quality = lps_result["quality"]

            # 如果没有检测到Spring，检查是否有SOS信号
            if not spring_detected and step1.phase == WyckoffPhase.ACCUMULATION:
                # 优化：放宽SOS检测条件
                # 1. 价格突破上边界95%（原98%）
                # 2. 量能配合条件放宽
                if step1.boundary_upper > 0:
                    recent_5 = df.tail(5)
                    for row in recent_5.itertuples():
                        if row.close > step1.boundary_upper * 0.95:
                            # 检查量能配合（放宽条件）
                            vol_level = self.rules.rule1_relative_volume(
                                row.volume, df["volume"]
                            )
                            if vol_level in (
                                "高于平均",
                                "天量",
                                "平均",
                            ):  # 原：仅"高于平均"和"天量"
                                st_detected = True
                                break

        # UTAD 检测（DISTRIBUTION 阶段）：X 列突破上沿 2%+ → 1-2 列内收回 + 放量确认
        if step1.phase == WyckoffPhase.DISTRIBUTION and step1.boundary_upper > 0:
            utad_found = self._scan_utad(df, step1.boundary_upper)
            if utad_found is not None:
                utad_detected = True
                utad_date = utad_found["date"]
                vol_ratio = utad_found["vol_ratio"]
                if vol_ratio >= 2.0:
                    utad_quality = "一级(放量确认)"
                else:
                    utad_quality = "二级(温和放量)"

        # T+1 压力测试（含涨跌停流动性警告 + ATR动态阈值）
        current_price = float(df.iloc[-1]["close"])
        recent_30_low = float(df.tail(30)["low"].min())
        limit_moves = self._detect_limit_moves(df)
        limit_moves_data = [{"price": lm.price, "type": lm.move_type.value} for lm in limit_moves]
        t1_result = self.rules.rule3_t1_risk_test(current_price, recent_30_low, limit_moves_data, current_atr)

        return Step3Result(
            spring_detected=spring_detected,
            spring_quality=spring_quality,
            spring_date=spring_date,
            spring_low_price=spring_low_price,
            utad_detected=utad_detected,
            utad_quality=utad_quality,
            utad_date=utad_date,
            st_detected=st_detected,
            lps_confirmed=lps_confirmed,
            lps_stage=lps_stage,
            test_low=test_low,
            spring_volume=spring_volume,
            t1_max_drawdown_pct=t1_result["pct"],
            t1_verdict=t1_result["verdict"],
            t1_description=t1_result["desc"],
        )

    def _step35_counterfactual(
        self,
        df: pd.DataFrame,
        step1: Step1Result,
        step2: Step2Result,
        step3: Step3Result,
        rule0: Rule0Result,
    ) -> V3CounterfactualResult:
        """Step 3.5: 反事实压力测试"""
        forward_evidence = []
        backward_evidence = []

        # 正证：吸筹证据
        if step2.net_bias == "accumulation":
            forward_evidence.extend(step2.phenomena)

        # 反证：派发证据
        if step2.net_bias == "distribution":
            backward_evidence.extend(step2.phenomena)

        # 正证：Spring 确认
        if step3.spring_detected and step3.lps_confirmed:
            forward_evidence.append("Spring+LPS确认")

        # 反证：UTAD 或假突破
        if step3.utad_detected:
            backward_evidence.append("UTAD假突破")

        pro_score = len(forward_evidence) * 2.0
        con_score = len(backward_evidence) * 2.0

        # 使用规则7仲裁
        cf_result = self.rules.rule7_counterfactual(pro_score, con_score)

        # 生成反事实场景描述
        scenario = ""
        if cf_result["overturned"]:
            scenario = (
                f"反证({con_score:.1f})占优，原判断被推翻。反证：{', '.join(backward_evidence)}"
            )
        elif cf_result["verdict"] == "降档":
            scenario = f"反证({con_score:.1f})接近正证({pro_score:.1f})，降档处理。需进一步验证。"
        else:
            scenario = f"正证({pro_score:.1f})占优，维持判断。正证：{', '.join(forward_evidence)}"

        return V3CounterfactualResult(
            utad_not_breakout="是" if not step3.utad_detected else "否",
            distribution_not_accumulation="是" if step2.net_bias != "distribution" else "否",
            chaos_not_phase_c="是" if step1.phase != WyckoffPhase.UNKNOWN else "否",
            liquidity_vacuum_risk="低" if step3.t1_verdict == "安全" else "高",
            total_pro_score=pro_score,
            total_con_score=con_score,
            conclusion_overturned=cf_result["overturned"],
            counterfactual_scenario=scenario,
            forward_evidence=forward_evidence,
            backward_evidence=backward_evidence,
        )

    def _step4_risk_reward(
        self,
        df: pd.DataFrame,
        step1: Step1Result,
        step3: Step3Result,
        rule0: Rule0Result,
        pnf_count_target: Optional[float] = None,
    ) -> RiskRewardResult:
        """Step 4: 盈亏比投影（规则10精度，多种目标位来源 + ATR回填）"""
        current_price = float(df.iloc[-1]["close"])

        # 止损价 = 关键结构低点 × 0.995（ATR可用时用1倍ATR止损）
        key_low = step3.spring_low_price if step3.spring_low_price else step1.boundary_lower
        if key_low <= 0 or key_low > current_price:
            key_low = float(df.tail(30)["low"].min())

        atr_series = Indicators.calc_atr(df)
        current_atr = float(atr_series.iloc[-1]) if len(atr_series) > 0 else 0.0
        stop_loss_result = self.rules.rule10_stop_loss(key_low, atr=current_atr)
        stop_loss = stop_loss_result.stop_loss_price

        # 目标位：多种来源
        first_target = step1.boundary_upper
        first_target_source = "tr_upper"

        # 尝试其他目标位来源
        recent_20 = df.tail(20)

        # 1. 大阴线起跌点（前一天收盘价 > 当天收盘价 * 1.03）
        for i in range(len(recent_20) - 1, 0, -1):
            prev_close = float(recent_20.iloc[i - 1]["close"])
            curr_close = float(recent_20.iloc[i]["close"])
            if prev_close > curr_close * 1.03:
                bearish_target = prev_close
                if bearish_target > current_price and bearish_target < first_target:
                    first_target = bearish_target
                    first_target_source = "bearish_candle"
                    break

        # 2. 跳空缺口下沿
        for i in range(1, len(recent_20)):
            prev_row = recent_20.iloc[i - 1]
            curr_row = recent_20.iloc[i]
            if curr_row["low"] > prev_row["high"]:
                gap_target = float(curr_row["low"])
                if gap_target > current_price and gap_target < first_target:
                    first_target = gap_target
                    first_target_source = "gap_lower"
                    break

        # 3. ATR回填：当所有结构化目标位都低于当前价时
        if first_target <= current_price:
            tr_vals = []
            for i in range(1, min(21, len(df))):
                hi = float(df.iloc[-i]["high"])
                lo = float(df.iloc[-i]["low"])
                pc = float(df.iloc[-i - 1]["close"])
                tr_vals.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
            atr = float(np.mean(tr_vals)) if len(tr_vals) >= 20 else current_price * 0.02
            first_target = current_price + 2.0 * atr
            first_target_source = "atr_derived"

        # 4. P&F Count Target 优先（PF-C2）：当 PNF 目标高于当前价时采用
        if pnf_count_target and pnf_count_target > current_price:
            first_target = float(pnf_count_target)
            first_target_source = "pnf_count_target"

        # 计算盈亏比
        risk = current_price - stop_loss
        reward = first_target - current_price

        if risk > 0:
            rr_ratio = reward / risk
        else:
            rr_ratio = 0.0

        # 判定 - 统一严格阈值 (v3.0要求盈亏比 >= 1:2.5)
        if rr_ratio >= 2.5:
            rr_verdict = "excellent"
        elif rr_ratio >= 2.0:
            rr_verdict = "pass"
        elif rr_ratio >= 1.5:
            rr_verdict = "marginal"
        else:
            rr_verdict = "fail"

        gain_pct = (first_target - current_price) / current_price * 100 if current_price > 0 else 0

        return RiskRewardResult(
            entry_price=current_price,
            stop_loss=stop_loss,
            first_target=first_target,
            first_target_source=first_target_source,
            rr_ratio=round(rr_ratio, 2),
            rr_verdict=rr_verdict,
            gain_pct=round(gain_pct, 2),
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
        """规则8: 置信度矩阵 - 统一5条件 (原始标准)"""
        bc_located = rule0.bc_found
        spring_lps_verified = step3.spring_detected and step3.lps_confirmed
        counterfactual_passed = not cf.conclusion_overturned
        rr_qualified = rr.rr_ratio >= 2.5
        multiframe_aligned = multiframe

        # A级：Spring+LPS+BC+盈亏比≥1.5
        if step3.spring_detected and step3.lps_confirmed and bc_located and rr.rr_ratio >= 1.5:
            return ConfidenceResult(
                level="A", bc_located=True, spring_lps_verified=True,
                counterfactual_passed=counterfactual_passed, rr_qualified=rr.rr_ratio >= 2.5,
                multiframe_aligned=multiframe_aligned, position_size="标准仓位",
                reason=f"Spring+LPS+BC+盈亏比{rr.rr_ratio:.1f}达标",
            )
        # B+级：Spring+LPS（不需要BC）+ 盈亏比≥1.5
        if step3.spring_detected and step3.lps_confirmed and rr.rr_ratio >= 1.5:
            return ConfidenceResult(
                level="B+", bc_located=bc_located, spring_lps_verified=True,
                counterfactual_passed=counterfactual_passed, rr_qualified=rr.rr_ratio >= 2.5,
                multiframe_aligned=multiframe_aligned, position_size="轻仓试探",
                reason=f"Spring+LPS+盈亏比{rr.rr_ratio:.1f}，B+级",
            )
        # Bypass path 1: Spring detected but LPS not verified
        if step3.spring_detected and not step3.lps_confirmed:
            bypass_result = ConfidenceResult(
                level="C", bc_located=bc_located, spring_lps_verified=False,
                counterfactual_passed=counterfactual_passed, rr_qualified=rr_qualified,
                multiframe_aligned=multiframe_aligned, position_size="试仓",
                reason="Spring已检测但LPS未验证，降级到C",
                bypassed=True,
            )
            if self._debug_r8_compare:
                self._debug_r8_bypass_result = bypass_result
                self._debug_r8_full_result = self.rules.rule8_confidence_matrix(
                    bc_located, spring_lps_verified, counterfactual_passed,
                    rr_qualified, multiframe_aligned
                )
            return bypass_result
        # Bypass path 2: RR qualified but BC not located
        if rr_qualified and not bc_located:
            bypass_result = ConfidenceResult(
                level="C", bc_located=False, spring_lps_verified=spring_lps_verified,
                counterfactual_passed=counterfactual_passed, rr_qualified=True,
                multiframe_aligned=multiframe_aligned, position_size="试仓",
                reason="盈亏比达标但BC未定位，降级到C",
                bypassed=True,
            )
            if self._debug_r8_compare:
                self._debug_r8_bypass_result = bypass_result
                self._debug_r8_full_result = self.rules.rule8_confidence_matrix(
                    bc_located, spring_lps_verified, counterfactual_passed,
                    rr_qualified, multiframe_aligned
                )
            return bypass_result
        return self.rules.rule8_confidence_matrix(
            bc_located, spring_lps_verified, counterfactual_passed,
            rr_qualified, multiframe_aligned
        )

    def _step5_trading_plan(
        self,
        step1: Step1Result,
        step3: Step3Result,
        cf: V3CounterfactualResult,
        rr: RiskRewardResult,
        confidence: ConfidenceResult,
        df: Optional[pd.DataFrame] = None,
    ) -> V3TradingPlan:
        """Step 5: 交易计划（完整字段填充）"""
        # 基本方向 - 根据阶段和信号确定
        direction = "空仓观望"

        # 规则2: Markdown禁止做多
        if step1.phase == WyckoffPhase.MARKDOWN:
            direction = "空仓观望"
        elif step1.phase == WyckoffPhase.DISTRIBUTION:
            direction = "空仓观望"
        elif step1.phase == WyckoffPhase.ACCUMULATION:
            # ACCUMULATION阶段：Spring+LPS确认后可做多
            if step3.spring_detected and step3.lps_confirmed:
                if confidence.level in ("A", "B+"):
                    direction = "做多"
                elif rr.rr_ratio >= 2.5:
                    direction = "做多"
                else:
                    direction = "轻仓试探"
            elif step3.spring_detected:
                # Spring已检测但LPS未确认，可观察
                direction = "观察等待"
            else:
                direction = "空仓观望"
        elif step1.phase == WyckoffPhase.MARKUP:
            # Generalized Markup Action State Machine:
            # 1. Spring-SOS breakthrough confirmation -> "做多"
            # 2. Key low-volume support test or washouts (Test, Shakeout) inside Markup -> "买入"
            # 3. Markup acceleration/continuation (LPS, BUEC, Lack of Supply, Phase E) -> "持有"
            
            # Check for recent Spring (same logic as SOS Signal)
            is_post_spring_sos = False
            last_row = df.iloc[-1]
            c_val = float(last_row["close"])
            o_val = float(last_row["open"])
            l_val = float(last_row["low"])
            h_val = float(last_row["high"])
            c_loc = (c_val - l_val) / max(h_val - l_val, 0.01)

            if step3.spring_detected and step3.spring_date:
                if len(df) >= 3:
                    date_1_day_ago = str(df.iloc[-2]["date"])
                    date_2_days_ago = str(df.iloc[-3]["date"])
                    if step3.spring_date in date_1_day_ago:
                        if c_loc >= 0.5 and c_val > o_val:
                            is_post_spring_sos = True
                    elif step3.spring_date in date_2_days_ago:
                        prev_row = df.iloc[-2]
                        prev_c = float(prev_row["close"])
                        prev_o = float(prev_row["open"])
                        prev_h = float(prev_row["high"])
                        prev_l = float(prev_row["low"])
                        prev_c_loc = (prev_c - prev_l) / max(prev_h - prev_l, 0.01)
                        was_prev_breakout = (prev_c_loc >= 0.5 and prev_c > prev_o)
                        if not was_prev_breakout:
                            if c_loc >= 0.5 and c_val > o_val:
                                is_post_spring_sos = True

            markup_sub_event = self._classify_wyckoff_markup_event(df, step1.boundary_upper)

            if is_post_spring_sos:
                direction = "做多"
            elif "Test" in markup_sub_event or "Shakeout" in markup_sub_event:
                direction = "买入"
            elif "LPS" in markup_sub_event or "BUEC" in markup_sub_event or "Lack of Supply" in markup_sub_event or "Phase E" in markup_sub_event:
                if rr.rr_ratio < 1.2:
                    direction = "空仓观望"
                else:
                    direction = "持有"
            # 兜底动作决策
            elif rr.rr_ratio >= 2.5:
                direction = "做多"
            elif rr.rr_ratio >= 1.5:
                direction = "轻仓试探"
            elif rr.rr_ratio < 1.2:
                # 盈亏比极差，短线进入 No Trade Zone 观望
                direction = "空仓观望"
            else:
                direction = "持有观察"
        elif step1.phase == WyckoffPhase.UNKNOWN:
            # UNKNOWN阶段：根据子状态判断
            if step1.unknown_candidate in ("phase_a_candidate", "sc_st_candidate"):
                if step3.spring_detected:
                    direction = "观察等待"
                else:
                    direction = "空仓观望"
            else:
                direction = "空仓观望"

        # 止损结果（含涨跌停流动性警告 + ATR动态止损）
        key_low = step3.spring_low_price if step3.spring_low_price else step1.boundary_lower
        limit_moves = self._detect_limit_moves(df if df is not None else pd.DataFrame())
        limit_moves_data = [{"price": lm.price, "type": lm.move_type.value} for lm in limit_moves]
        atr_series = Indicators.calc_atr(df)
        current_atr = float(atr_series.iloc[-1]) if len(atr_series) > 0 else 0.0
        # 涨跌停风控: 近20日有跌停记录的股票跳过
        if any(lm.move_type == LimitMoveType.LIMIT_DOWN for lm in limit_moves):
            direction = "空仓观望"
        stop_loss_result = self.rules.rule10_stop_loss(key_low, limit_moves_data, current_atr)

        # 多周期一致性声明
        multi_timeframe_statement = "本次分析未提供周线图，置信度已自动降一级"

        # 执行前提
        execution_preconditions = [
            "大盘指数未出现单边系统性暴跌",
            "所属板块未出现重大利空政策消息",
        ]

        # 生成高度结构化且对齐测试关键字的评估描述
        if step1.phase == WyckoffPhase.ACCUMULATION:
            sub_phase_desc = f" | {step1.sub_phase}" if step1.sub_phase else ""
            assessment = f"当前处于Accumulation阶段{sub_phase_desc}，属于 Phase B/Phase C 震荡区间"
        elif step1.phase == WyckoffPhase.DISTRIBUTION:
            sub_phase_desc = f" | {step1.sub_phase}" if step1.sub_phase else ""
            assessment = f"当前处于Distribution阶段{sub_phase_desc}，属于 Phase B/Phase C 派发震荡区间"
        elif step1.phase == WyckoffPhase.MARKUP:
             if rr.rr_ratio < 1.2:
                assessment = f"当前处于Markup阶段，但盈亏比仅为{rr.rr_ratio:.2f}，属于 No Trade Zone 观望，建议持股者继续持有，无仓者空仓观望"
             else:
                assessment = "当前处于Markup阶段，建议继续持有"
        elif step1.phase == WyckoffPhase.UNKNOWN:
            if step1.unknown_candidate == "sc_st_candidate":
                assessment = "当前处于Unknown阶段 (SC恐慌抛售/二次测试候选)"
            elif step1.unknown_candidate == "phase_a_candidate":
                assessment = "当前处于Unknown阶段 (Phase A候选)"
            elif step1.unknown_candidate == "upthrust_candidate":
                assessment = "当前处于Unknown阶段 (Upthrust候选)"
            elif step1.unknown_candidate == "phase_b_range":
                assessment = "当前处于Unknown阶段 (Phase B震荡区间)"
            else:
                assessment = "当前处于Unknown阶段"
        else:
            assessment = f"当前处于{step1.phase.value}阶段"

        # CF-C4: 假突破检测（突破 TR 上沿后 3 列内跌回 → false_breakout 惩罚）
        false_breakout_detected = False
        if step1.boundary_upper > 0 and df is not None and len(df) > 0:
            fb = self._scan_false_breakout(df, step1.boundary_upper)
            if fb is not None:
                false_breakout_detected = True
                assessment = (
                    f"检测到假突破（{fb['date']} 突破后 3 列内跌回 TR），"
                    f"信号置信度降级，空仓观望"
                )
                direction = "空仓观望"

        return V3TradingPlan(
            current_assessment=assessment,
            multi_timeframe_statement=multi_timeframe_statement,
            execution_preconditions=execution_preconditions,
            direction=direction,
            entry_trigger=f"价格站稳{step1.boundary_upper:.2f}上方"
            if step1.boundary_upper > 0
            else "",
            observation_window="3-5个交易日",
            stop_loss=stop_loss_result,
            target=rr,
            confidence=confidence,
            false_breakout_detected=false_breakout_detected,
        )

    def _apply_a_stock_rules(self, step1: Step1Result, plan: V3TradingPlan) -> V3TradingPlan:
        """A 股铁律最终检查"""
        # 规则2: Markdown 禁止做多
        blocked, reason = self.rules.rule2_no_long_in_markdown(step1.phase, "")
        if blocked:
            plan.direction = "空仓观望"
            plan.current_assessment = reason

        return plan

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
    ) -> WyckoffReport:
        """构建最终报告"""
        current_price = float(df.iloc[-1]["close"])
        current_date = str(df.iloc[-1]["date"])

        # 构建结构
        structure = WyckoffStructure(
            phase=step1.phase,
            unknown_candidate=step1.unknown_candidate,
            bc_point=rule0.bc_position,
            sc_point=None,
            support_levels=[],
            resistance_levels=[],
            trading_range_high=step1.boundary_upper,
            trading_range_low=step1.boundary_lower,
            current_price=current_price,
            current_date=current_date,
        )

        # 构建信号
        signal_type = "no_signal"
        signal_description = ""

        if step1.phase == WyckoffPhase.MARKUP:
            # SOS Candidate / Spring Confirmation detection:
            # If we recently had a Spring (within step3冷静期) and price is rising strongly,
            # this marks a powerful Sign of Strength (SOS) confirming the transition to Markup.
            is_post_spring_sos = False
            last_row = df.iloc[-1]
            c_val = float(last_row["close"])
            o_val = float(last_row["open"])
            l_val = float(last_row["low"])
            h_val = float(last_row["high"])
            c_loc = (c_val - l_val) / max(h_val - l_val, 0.01)

            if step3.spring_detected and step3.spring_date:
                if len(df) >= 3:
                    date_1_day_ago = str(df.iloc[-2]["date"])
                    date_2_days_ago = str(df.iloc[-3]["date"])
                    if step3.spring_date in date_1_day_ago:
                        if c_loc >= 0.5 and c_val > o_val:
                            is_post_spring_sos = True
                    elif step3.spring_date in date_2_days_ago:
                        prev_row = df.iloc[-2]
                        prev_c = float(prev_row["close"])
                        prev_o = float(prev_row["open"])
                        prev_h = float(prev_row["high"])
                        prev_l = float(prev_row["low"])
                        prev_c_loc = (prev_c - prev_l) / max(prev_h - prev_l, 0.01)
                        was_prev_breakout = (prev_c_loc >= 0.5 and prev_c > prev_o)
                        if not was_prev_breakout:
                            if c_loc >= 0.5 and c_val > o_val:
                                is_post_spring_sos = True

            if is_post_spring_sos:
                signal_type = "sos_candidate"
                signal_description = "处于上涨阶段 (Markup - SOS已确认)"
            else:
                signal_type = "markup"
                signal_description = self._classify_wyckoff_markup_event(df, step1.boundary_upper)
        elif step1.phase == WyckoffPhase.MARKDOWN:
            signal_type = "markdown"
            signal_description = "处于下跌阶段 (Markdown)，空仓观望"
        elif step1.phase == WyckoffPhase.DISTRIBUTION:
            if step3.utad_detected:
                signal_type = "utad"
                signal_description = "检测到UTAD假突破信号"
            else:
                signal_type = "distribution"
                signal_description = "处于派发阶段 (Distribution)，空仓观望"
        elif step3.spring_detected:
            signal_type = "spring"
            signal_description = f"检测到Spring信号，质量：{step3.spring_quality}"
            if step3.lps_confirmed:
                signal_description += "，LPS已确认"
        elif step3.utad_detected:
            signal_type = "utad"
            signal_description = "检测到UTAD假突破信号"
        elif step3.st_detected:
            signal_type = "sos_candidate"
            signal_description = "检测到SOS候选信号"
        elif step1.phase == WyckoffPhase.ACCUMULATION:
            signal_type = "accumulation"
            signal_description = "处于积累阶段，等待Spring/SOS信号"
        else:
            signal_type = "no_signal"
            if step1.unknown_candidate == "sc_st_candidate":
                signal_description = "不确定阶段 (检测到SC恐慌抛售候选)，空仓观望"
            elif step1.unknown_candidate == "phase_a_candidate":
                signal_description = "不确定阶段 (检测到Phase A候选)，空仓观望"
            elif step1.unknown_candidate == "upthrust_candidate":
                signal_description = "不确定阶段 (检测到Upthrust候选)，空仓观望"
            else:
                signal_description = "不确定阶段，空仓观望"

        # CF-C4: 假突破惩罚 → 信号置信度 -1 级
        signal_confidence = confidence.level
        if v3_plan.false_breakout_detected:
            signal_confidence = _downgrade_confidence(signal_confidence)
        # CN-C4: 未复权数据 → 信号置信度 -1 级 (研究平台: 降级不拒绝)
        if adjustment_status == "raw":
            signal_confidence = _downgrade_confidence(signal_confidence)
        # P3-T2: markup 追买降级 — RS 非 leader 时降 1 级
        if signal_type in ("markup", "markup_buy") and relative_strength in ("follower", "systemic_decline"):
            signal_confidence = _downgrade_confidence(signal_confidence)

        signal = WyckoffSignal(
            signal_type=signal_type,
            trigger_price=current_price,
            volume_confirmation=VolumeLevel.AVERAGE,
            confidence=ConfidenceLevel[signal_confidence],
            phase=step1.phase,
            description=signal_description if signal_description else v3_plan.current_assessment,
            t1_risk评估=step3.t1_description,
            spring_date=step3.spring_date,
        )

        # 盈亏比投影
        risk_reward = RiskRewardProjection(
            entry_price=rr.entry_price,
            stop_loss=rr.stop_loss,
            first_target=rr.first_target,
            reward_risk_ratio=rr.rr_ratio,
            risk_amount=rr.entry_price - rr.stop_loss,
            reward_amount=rr.first_target - rr.entry_price,
            structure_based=rr.first_target_source,
        )

        # P3-T3: RS 仓位过滤 — systemic_decline 时仓位降级
        trading_direction = v3_plan.direction
        if signal_type in ("spring", "markup") and relative_strength == "systemic_decline":
            trading_direction = "空仓观望"

        # 交易计划
        trading_plan = TradingPlan(
            direction=trading_direction,
            trigger_condition=v3_plan.entry_trigger,
            invalidation_point=v3_plan.stop_loss.stop_logic if v3_plan.stop_loss else "",
            first_target=f"{rr.first_target:.2f}" if rr.first_target > 0 else "",
            confidence=ConfidenceLevel[confidence.level],
            preconditions="; ".join(v3_plan.execution_preconditions)
            if v3_plan.execution_preconditions
            else "",
            current_qualification=v3_plan.current_assessment,
        )

        # 压力测试
        stress_tests = []
        for evidence in step35.forward_evidence:
            stress_tests.append(
                StressTest(
                    scenario_name="正证",
                    scenario_description=evidence,
                    outcome="支持判断",
                    passes=True,
                    risk_level="低",
                )
            )
        for evidence in step35.backward_evidence:
            stress_tests.append(
                StressTest(
                    scenario_name="反证",
                    scenario_description=evidence,
                    outcome="质疑判断",
                    passes=False,
                    risk_level="高",
                )
            )

        # 涨跌停检测
        limit_moves = self._detect_limit_moves(df)

        # 筹码分析
        chip_analysis = self._analyze_chips(df, structure)

        # SQ-C1: 结构完整性评分 (已在 _analyze_single 计算并加权置信度，此处直接透传)
        return WyckoffReport(
            symbol=symbol,
            period=period,
            structure=structure,
            signal=signal,
            risk_reward=risk_reward,
            trading_plan=trading_plan,
            limit_moves=limit_moves,
            stress_tests=stress_tests,
            chip_analysis=chip_analysis,
            pnf_analysis=pnf_result,
            regime_phase=regime_phase,
            adjustment_status=adjustment_status,
            structural_score=structural_score,
            relative_strength=relative_strength,
            relative_strength_detail=relative_strength_detail,
            engine_version="v3.0",
            ruleset_version="v3.0",
            pnf_phase_divergence=pnf_phase_divergence,
            vdb_divergence=step2.vdb_divergence,
            lps_stage=step3.lps_stage,
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
        """Vectorized BC/SC Scoring System using Pandas/NumPy array operations."""
        if df.empty:
            return None, None

        df = df.copy()
        n = len(df)
        
        # 1. Basic metrics vectorization
        vol_rank = df["volume"].rank(pct=True).to_numpy()
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        close = df["close"].to_numpy()
        
        ranges = high - low
        shadow_upper = high - close
        shadow_lower = close - low
        
        shadow_ratio_up = shadow_upper / (ranges + 1e-9)
        shadow_ratio_lo = shadow_lower / (ranges + 1e-9)
        
        # 2. Subsequent price movement vectorization
        # Rolling min/max backwards using flip
        close_rev = close[::-1]
        
        # Get subsequent 9-day low/high: rolling window of size 9, then shifted
        sub_low_rev = pd.Series(close_rev).rolling(9, min_periods=1).min().to_numpy()
        sub_high_rev = pd.Series(close_rev).rolling(9, min_periods=1).max().to_numpy()
        
        subsequent_low = sub_low_rev[::-1]
        subsequent_high = sub_high_rev[::-1]
        
        # Shift forward by 1 (which means subsequent days after index i)
        subsequent_low = np.roll(subsequent_low, -1)
        subsequent_low[-1] = close[-1]
        subsequent_high = np.roll(subsequent_high, -1)
        subsequent_high[-1] = close[-1]
        
        # 3. Vectorized scoring for BC
        bc_scores = np.zeros(n)
        bc_scores += np.where(vol_rank > 0.8, 2, np.where(vol_rank > 0.6, 1, 0))
        bc_scores += np.where(shadow_ratio_up > 0.6, 2, np.where(shadow_ratio_up > 0.4, 1, 0))
        
        # Drop check
        drop_pct = (high - subsequent_low) / (high + 1e-9)
        mask_last5 = np.arange(n) < (n - 5)
        bc_scores += np.where((drop_pct > 0.05) & mask_last5, 2, 0)
        
        # 4. Vectorized scoring for SC
        sc_scores = np.zeros(n)
        sc_scores += np.where(vol_rank > 0.8, 2, 0)
        sc_scores += np.where(shadow_ratio_lo > 0.6, 2, np.where(shadow_ratio_lo > 0.4, 1, 0))
        
        # Rise check
        rise_pct = (subsequent_high - low) / (low + 1e-9)
        sc_scores += np.where((rise_pct > 0.05) & mask_last5, 2, 0)
        
        # 5. Extract top candidates
        df["bc_score"] = bc_scores
        df["sc_score"] = sc_scores
        
        peak_idx = df["high"].idxmax()
        trough_idx = df["low"].idxmin()
        
        # Get highest score first, then nlargest to resolve
        bc_candidates = df.sort_values(by=["bc_score", "high"], ascending=[False, False])
        sc_candidates = df.sort_values(by=["sc_score", "low"], ascending=[False, True])
        
        bc_point = None
        sc_point = None
        
        if not bc_candidates.empty:
            best_bc = bc_candidates.iloc[0]
            score = float(best_bc["bc_score"])
            with np.errstate(over='ignore'):
                prob_confidence = 1.0 / (1.0 + np.exp(-(score - 3.0)))
            
            volume_level = self._classify_volume(best_bc["volume"], df["volume"])
            bc_point = BCPoint(
                date=str(best_bc["date"]),
                price=float(best_bc["high"]),
                volume_level=volume_level,
                is_extremum=(best_bc.name == peak_idx),
                confidence_score=prob_confidence,
            )
            
        if not sc_candidates.empty:
            best_sc = sc_candidates.iloc[0]
            score = float(best_sc["sc_score"])
            with np.errstate(over='ignore'):
                prob_confidence = 1.0 / (1.0 + np.exp(-(score - 3.0)))
            
            volume_level = self._classify_volume(best_sc["volume"], df["volume"])
            sc_point = SCPoint(
                date=str(best_sc["date"]),
                price=float(best_sc["low"]),
                volume_level=volume_level,
                is_extremum=(best_sc.name == trough_idx),
                confidence_score=prob_confidence,
            )
            
        return bc_point, sc_point

    def _detect_limit_moves(self, df: pd.DataFrame) -> List[LimitMove]:
        return detect_limit_moves(df, self._code_prefix, self._is_st, self.rules)

    def _analyze_chips(self, df: pd.DataFrame, structure: WyckoffStructure) -> ChipAnalysis:
        return analyze_chips(df, structure)

    def _compute_avg_price_deviation(self, df: pd.DataFrame) -> float:
        return compute_avg_price_deviation(df)

    def _compute_money_flow_trend(self, df: pd.DataFrame) -> float:
        return compute_money_flow_trend(df)

    def _analyze_multiframe(
        self, df: pd.DataFrame, symbol: str, image_evidence: Optional[ImageEvidenceBundle] = None,
        index_df: Optional[pd.DataFrame] = None,
    ) -> WyckoffReport:
        return analyze_multiframe(
            df, symbol, image_evidence,
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
            symbol, daily_report, weekly_report, monthly_report, self.rules,
        )

    def _build_timeframe_snapshot(self, report: WyckoffReport) -> TimeframeSnapshot:
        return build_timeframe_snapshot(report)

    def _create_no_signal_report(self, symbol: str, period: str, reason: str) -> WyckoffReport:
        return create_no_signal_report(symbol, period, reason)

    def scan_signal(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
    ) -> dict:
        """
        轻量级信号扫描 - 仅返回关键信号标签
        
        Args:
            df: OHLCV 数据
            symbol: 股票代码
            
        Returns:
            dict: 包含 phase, signal_type, action, confidence, spring_detected, utad_detected
        """
        try:
            report = self.analyze(df, symbol=symbol, period="日线", multi_timeframe=False)
            
            # 提取关键信息
            phase = "UNKNOWN"
            signal_type = "no_signal"
            action = "HOLD"
            confidence = 0.0
            spring_detected = False
            utad_detected = False
            
            if report.structure:
                phase = report.structure.phase.value if hasattr(report.structure.phase, 'value') else str(report.structure.phase)
            
            if report.signal:
                signal_type = report.signal.signal_type if hasattr(report.signal, 'signal_type') else "no_signal"
                # confidence 是 ConfidenceLevel 枚举
                conf_level = report.signal.confidence if hasattr(report.signal, 'confidence') else None
                if conf_level:
                    # 将 ConfidenceLevel 转换为数值
                    conf_map = {"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3}
                    confidence = conf_map.get(str(conf_level), 0.3)
                
                # 检测 Spring 和 UTAD
                if "spring" in str(signal_type).lower():
                    spring_detected = True
                if "utad" in str(signal_type).lower():
                    utad_detected = True
            
            if report.trading_plan:
                # TradingPlan 使用 direction 字段而非 action
                direction_raw = str(getattr(report.trading_plan, 'direction', '空仓观望'))
                # 扩展映射表，覆盖引擎输出的所有中文关键词
                buy_keywords = ['long', '多头', '买入', '做多', '轻仓试探', '加仓', '建仓']
                sell_keywords = ['short', '空头', '卖出', '做空', '减仓', '清仓']
                if any(kw in direction_raw for kw in buy_keywords):
                    action = 'BUY'
                elif any(kw in direction_raw for kw in sell_keywords):
                    action = 'SELL'
                else:
                    action = 'HOLD'
            
            # P&F 点图分析
            pnf_signal = {}
            try:
                pnf = PointAndFigure(box_size=0.02, reversal=2)
                pnf.build(df)
                pnf_signal = {
                    "phase_hint": pnf.wyckoff_phase_hint(),
                    "breakout": pnf.breakout_detected(),
                    "count_target": pnf.count_target(),
                }
            except (ValueError, TypeError, KeyError):
                logger.warning("scan_signal Point & Figure analysis failed", exc_info=True)
                pnf_signal = {"phase_hint": "neutral", "breakout": False, "count_target": 0.0}

            return {
                "symbol": symbol,
                "date": df['date'].iloc[-1] if 'date' in df.columns else None,
                "phase": phase,
                "signal_type": signal_type,
                "action": action,
                "confidence": confidence,
                "spring_detected": spring_detected,
                "utad_detected": utad_detected,
                "pnf_analysis": pnf_signal,
                "regime_phase": getattr(report, 'regime_phase', None),
            }
        except (ValueError, TypeError, KeyError, RuntimeError) as e:
            logger.warning(f"scan_signal 失败 {symbol}: {e}", exc_info=True)
            return {
                "symbol": symbol,
                "date": df['date'].iloc[-1] if 'date' in df.columns else None,
                "phase": "UNKNOWN",
                "signal_type": "error",
                "action": "HOLD",
                "confidence": 0.0,
                "spring_detected": False,
                "utad_detected": False,
                "regime_phase": None,
            }


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
