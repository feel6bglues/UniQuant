# -*- coding: utf-8 -*-
"""
v3.0 规则执行器 - 10 条规则的独立验证层
基于 Promote_v3.0.md 的规则体系
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from uniquant.brain.wyckoff.models import (
    ConfidenceResult,
    StopLossResult,
    VolumeLevel,
    WyckoffPhase,
)


class V3Rules:
    """v3.0 规则执行器 - 10 条规则的独立验证"""

    def __init__(self) -> None:
        self._vol_ma_30_cache: Dict[int, pd.Series] = {}

    def rule1_relative_volume(self, volume: float, volume_series: pd.Series) -> str:
        """规则1: 相对量能分类（参考基准：近30根K线）

        缓存 30 期滚动均线的计算——管道内的同一次 analyze() 调用中
        volume_series 引用的是同一个 df["volume"] 对象，无需重复计算。
        """
        if volume_series.empty or volume <= 0:
            return VolumeLevel.AVERAGE.value

        vol_id = id(volume_series)
        if vol_id not in self._vol_ma_30_cache:
            self._vol_ma_30_cache[vol_id] = volume_series.rolling(
                window=30, min_periods=10
            ).mean()

        avg_vol = self._vol_ma_30_cache[vol_id].iloc[-1]
        if pd.isna(avg_vol) or avg_vol <= 0:
            return VolumeLevel.AVERAGE.value

        ratio = volume / avg_vol

        if ratio >= 2.0:
            return VolumeLevel.EXTREME_HIGH.value
        elif ratio >= 1.3:
            return VolumeLevel.HIGH.value
        elif ratio >= 0.7:
            return VolumeLevel.AVERAGE.value
        elif ratio >= 0.4:
            return VolumeLevel.LOW.value
        else:
            return VolumeLevel.EXTREME_LOW.value

    @staticmethod
    def rule2_no_long_in_markdown(phase: WyckoffPhase, signal_type: str) -> Tuple[bool, str]:
        """规则2: Markdown/Distribution 禁止做多"""
        if phase == WyckoffPhase.MARKDOWN:
            return True, "Markdown阶段禁止做多"
        if phase == WyckoffPhase.DISTRIBUTION:
            return True, "Distribution阶段禁止做多"
        if signal_type in ("markdown", "downward_thrust"):
            return True, "下跌信号禁止做多"
        return False, ""

    @staticmethod
    def rule3_t1_risk_test(
        entry_price: float, support_low: float, recent_limit_moves: List[Dict] = None,
        atr: Optional[float] = None
    ) -> Dict[str, Any]:
        """规则3: T+1 极限回撤测试（含涨跌停流动性警告 + ATR动态阈值）"""
        if entry_price <= 0 or support_low <= 0:
            return {"verdict": "超限", "pct": 100.0, "desc": "无效价格", "liquidity_warning": ""}

        max_drawdown_pct = (entry_price - support_low) / entry_price * 100

        if atr is not None and atr > 0:
            atr_pct = atr / entry_price * 100
            safe_threshold = atr_pct * 1.0
            limit_threshold = atr_pct * 2.0
        else:
            safe_threshold = 3.0
            limit_threshold = 5.0

        # 检查止损位附近是否有涨跌停记录
        liquidity_warning = ""
        if recent_limit_moves:
            stop_price = support_low * 0.995
            for move in recent_limit_moves:
                move_price = move.get("price", 0)
                if move_price > 0:
                    if abs(move_price - stop_price) / stop_price < 0.03:
                        move_type = move.get("type", "")
                        if move_type in ("涨停", "跌停"):
                            liquidity_warning = f"流动性风险警告：止损位附近有{move_type}记录，止损单可能无法按预期价格成交"
                            break

        if max_drawdown_pct < safe_threshold:
            return {
                "verdict": "安全",
                "pct": round(max_drawdown_pct, 2),
                "desc": f"极限回撤{max_drawdown_pct:.1f}%，安全",
                "liquidity_warning": liquidity_warning,
            }
        elif max_drawdown_pct < limit_threshold:
            return {
                "verdict": "偏薄",
                "pct": round(max_drawdown_pct, 2),
                "desc": f"极限回撤{max_drawdown_pct:.1f}%，偏薄",
                "liquidity_warning": liquidity_warning,
            }
        else:
            return {
                "verdict": "超限",
                "pct": round(max_drawdown_pct, 2),
                "desc": f"极限回撤{max_drawdown_pct:.1f}%，超限",
                "liquidity_warning": liquidity_warning,
            }

    @staticmethod
    def rule4_no_trade_zone(contradictions_count: int, struct_clarity: str) -> bool:
        """规则4: 诚实不作为 - 信号矛盾时强制空仓"""
        if contradictions_count >= 3:
            return True
        if struct_clarity in ("混沌", "unclear", "矛盾"):
            return True
        return False

    @staticmethod
    def rule5_bc_tr_fallback(bc_found: bool, tr_defined: bool) -> Dict[str, Any]:
        """规则5: BC/TR 降级策略"""
        if bc_found and tr_defined:
            return {"validity": "full", "confidence_base": "A", "desc": "BC+TR完整"}
        elif bc_found:
            return {"validity": "partial", "confidence_base": "B", "desc": "BC可见但TR不明"}
        elif tr_defined:
            return {"validity": "tr_fallback", "confidence_base": "C", "desc": "TR明确但BC不可见"}
        else:
            return {"validity": "insufficient", "confidence_base": "D", "desc": "BC和TR均不可见"}

    @staticmethod
    def _find_test_bar(post_spring_df: pd.DataFrame, spring_low: float) -> Optional[int]:
        """找到 spring 后最近一次"回落测试"K线。

        条件：K线 low 接近 spring_low（0.99~1.05 倍区间内），
        且该K线是"回落"性质（open <= spring_low * 1.03，非跳空高开长阳）。
        返回该K线在 post_spring_df 中的位置（最后满足者优先）。
        """
        test_idx: Optional[int] = None
        for i in range(len(post_spring_df)):
            r = post_spring_df.iloc[i]
            if spring_low * 0.99 <= r["low"] <= spring_low * 1.05:
                if r["open"] <= spring_low * 1.03:
                    test_idx = i
        return test_idx

    @staticmethod
    def rule6_spring_validation(
        spring_detected: bool,
        post_spring_df: pd.DataFrame,
        spring_low: float,
        spring_volume: float = 0.0,
        atr: float = 0.0,
    ) -> Dict[str, Any]:
        """规则6: Spring 结构事件验证 — 分层判定（P0-A 重构）

        Args:
            spring_detected: 是否检测到 Spring
            post_spring_df: Spring 后数据
            spring_low: Spring 最低价
            spring_volume: Spring 当日成交量（供给枯竭参照）
            atr: 当前 ATR（冲击容忍阈值）

        Returns:
            Dict 含 lps_confirmed / quality / desc / spring_invalidated（旧字段）
            及 lps_stage / test_low / test_vol_ratio / bounce_bars（新诊断字段）
        """
        base = {
            "lps_stage": "not_test",
            "test_low": None,
            "test_vol_ratio": None,
            "bounce_bars": 0,
        }

        if not spring_detected:
            return {
                **base,
                "lps_confirmed": False,
                "quality": "无",
                "desc": "未检测到Spring",
                "spring_invalidated": False,
            }

        if post_spring_df.empty or len(post_spring_df) < 3:
            return {
                **base,
                "lps_confirmed": False,
                "quality": "二级(需ST验证)",
                "desc": "Spring后数据不足，需ST验证",
                "spring_invalidated": False,
            }

        # 阶段1：作废检查 — 放量再创新低
        spring_invalidated = False
        for row in post_spring_df.itertuples():
            if row.low < spring_low * 0.99:
                avg_vol = post_spring_df["volume"].mean()
                if row.volume > avg_vol * 1.5:
                    spring_invalidated = True
                    break

        if spring_invalidated:
            return {
                **base,
                "lps_stage": "invalidated",
                "lps_confirmed": False,
                "quality": "作废",
                "desc": "Spring后放量再创新低，信号作废，重新进入Step 0评估",
                "spring_invalidated": True,
            }

        # 阶段2：测试K线识别
        test_idx = V3Rules._find_test_bar(post_spring_df, spring_low)
        if test_idx is None:
            return {
                **base,
                "lps_stage": "not_test",
                "lps_confirmed": False,
                "quality": "二级(需ST验证)",
                "desc": "未找到回落测试K线，Spring后数据不足",
                "spring_invalidated": False,
            }

        test_bar = post_spring_df.iloc[test_idx]
        test_bar_low = float(test_bar["low"])
        test_bar_volume = float(test_bar["volume"])

        # 阶段3：硬门槛守位
        tolerance = max(atr * 0.25, spring_low * 0.005)
        price_held = test_bar_low >= spring_low - tolerance
        if not price_held:
            return {
                **base,
                "lps_stage": "not_test",
                "test_low": test_bar_low,
                "lps_confirmed": False,
                "quality": "二级(需ST验证)",
                "desc": f"测试K线低点{test_bar_low:.2f}跌破Spring低点{spring_low:.2f}，守位失败",
                "spring_invalidated": False,
            }

        # 阶段4：确认证据
        # 证据1：量能供给枯竭（参照 spring 当日量）
        if spring_volume > 0:
            test_vol_ratio = test_bar_volume / spring_volume
            supply_dry = test_vol_ratio <= 1.0
        else:
            test_vol_ratio = None
            supply_dry = True

        # 证据2：反弹冲动（多根K线窗口）
        bounce_bars = 0
        test_high = float(test_bar["high"])
        target = test_high + atr * 0.5
        n = 5
        for j in range(test_idx + 1, min(test_idx + 1 + n, len(post_spring_df))):
            if float(post_spring_df.iloc[j]["close"]) >= target:
                bounce_bars = j - test_idx
                break

        bounce = bounce_bars > 0

        # 判定汇总
        vol_ratio_str = f"{test_vol_ratio:.2f}" if test_vol_ratio is not None else "N/A"
        if supply_dry and bounce:
            return {
                "lps_stage": "lps_confirmed",
                "test_low": test_bar_low,
                "test_vol_ratio": test_vol_ratio,
                "bounce_bars": bounce_bars,
                "lps_confirmed": True,
                "quality": "一级(LPS确认)",
                "desc": f"缩量测试(量比{vol_ratio_str})+反弹确认({bounce_bars}根)，LPS确认",
                "spring_invalidated": False,
            }
        elif supply_dry:
            return {
                "lps_stage": "test_held",
                "test_low": test_bar_low,
                "test_vol_ratio": test_vol_ratio,
                "bounce_bars": 0,
                "lps_confirmed": False,
                "quality": "二级(LPS测试中)",
                "desc": f"守位缩量(量比{vol_ratio_str})但反弹未确认，LPS测试中",
                "spring_invalidated": False,
            }
        else:
            return {
                "lps_stage": "test_held",
                "test_low": test_bar_low,
                "test_vol_ratio": test_vol_ratio,
                "bounce_bars": 0,
                "lps_confirmed": False,
                "quality": "二级(需ST验证)",
                "desc": f"守位但测试量放大(量比{vol_ratio_str})，供给未枯竭",
                "spring_invalidated": False,
            }

    @staticmethod
    def rule7_counterfactual(pro_score: float, con_score: float) -> Dict[str, Any]:
        """规则7: 反事实仲裁"""
        if con_score > pro_score:
            return {
                "overturned": True,
                "verdict": "推翻",
                "desc": f"反证({con_score:.1f})>正证({pro_score:.1f})，结论被推翻",
            }
        elif con_score > pro_score * 0.7:
            return {
                "overturned": False,
                "verdict": "降档",
                "desc": f"反证({con_score:.1f})接近正证({pro_score:.1f})，降档处理",
            }
        else:
            return {
                "overturned": False,
                "verdict": "维持",
                "desc": f"正证({pro_score:.1f})占优，维持判断",
            }

    @staticmethod
    def rule8_confidence_matrix(
        bc_located: bool,
        spring_lps_verified: bool,
        counterfactual_passed: bool,
        rr_qualified: bool,
        multiframe_aligned: bool,
    ) -> ConfidenceResult:
        """规则8: 置信度矩阵（5项条件，放宽标准）"""
        conditions = [
            bc_located,
            spring_lps_verified,
            counterfactual_passed,
            rr_qualified,
            multiframe_aligned,
        ]
        met_count = sum(conditions)

        # 放宽标准：A级4项，B级3项，C级2项
        if met_count >= 4:
            level = "A"
            reason = f"{met_count}项条件满足（含BC定位）"
            position_size = "标准仓位"
        elif met_count >= 3:
            level = "B"
            reason = f"{met_count}项条件满足"
            position_size = "轻仓"
        elif met_count >= 2:
            level = "C"
            reason = f"{met_count}项条件满足"
            position_size = "试仓"
        else:
            level = "D"
            reason = f"仅{met_count}项条件满足"
            position_size = "空仓"

        return ConfidenceResult(
            level=level,
            bc_located=bc_located,
            spring_lps_verified=spring_lps_verified,
            counterfactual_passed=counterfactual_passed,
            rr_qualified=rr_qualified,
            multiframe_aligned=multiframe_aligned,
            position_size=position_size,
            reason=reason,
        )

    @staticmethod
    def rule9_multiframe_alignment(
        daily_phase: WyckoffPhase,
        weekly_phase: WyckoffPhase,
        monthly_phase: WyckoffPhase,
        is_single_timeframe: bool = False,
    ) -> Tuple[str, str]:
        """规则9: 多周期一致性（含单周期降级）"""
        # 单周期降级：置信度自动降一级
        if is_single_timeframe:
            return "single_timeframe_degraded", "单周期分析，置信度自动降一级"

        # 月线/周线 Markdown → 覆盖日线，强制空仓
        if monthly_phase == WyckoffPhase.MARKDOWN:
            return "markdown_override", "月线Markdown，强制空仓"
        if weekly_phase == WyckoffPhase.MARKDOWN:
            return "markdown_override", "周线Markdown，强制空仓"

        # 月线/周线 Distribution → 覆盖日线
        if monthly_phase == WyckoffPhase.DISTRIBUTION:
            return "distribution_override", "月线Distribution，降级"
        if weekly_phase == WyckoffPhase.DISTRIBUTION:
            return "distribution_override", "周线Distribution，降级"

        # 三周期共振
        if daily_phase == weekly_phase == monthly_phase:
            return "fully_aligned", f"三周期共振{daily_phase.value}"

        # 月线+周线同时 Markup → 支持日线
        if weekly_phase == WyckoffPhase.MARKUP and monthly_phase == WyckoffPhase.MARKUP:
            return "aligned", "月线+周线Markup支持日线"

        # 周线 Unknown + 日线 Markup → 降级
        if weekly_phase == WyckoffPhase.UNKNOWN and daily_phase == WyckoffPhase.MARKUP:
            return "degraded", "周线Unknown，日线Markup降级"

        return "mixed", "多周期信号混合"

    @staticmethod
    def rule10_stop_loss(key_low: float, recent_limit_moves: List[Dict] = None,
                         atr: Optional[float] = None) -> StopLossResult:
        """规则10: 止损精度（关键低点×0.995，ATR可用时用1倍ATR止损，含流动性警告）"""
        if key_low <= 0:
            return StopLossResult(
                entry_price=0.0,
                stop_loss_price=0.0,
                stop_pct=0.0,
                precision_warning=True,
                liquidity_risk_warning="无效关键低点",
                stop_logic="无法计算止损",
            )

        if atr is not None and atr > 0:
            stop_loss_price = key_low - atr * 1.0
            stop_pct = atr / key_low * 100
            stop_logic = f"关键低点{key_low:.2f}-1倍ATR({atr:.3f})={stop_loss_price:.2f}"
        else:
            stop_loss_price = key_low * 0.995
            stop_pct = 0.5
            stop_logic = f"关键低点{key_low:.2f}×0.995={stop_loss_price:.2f}"

        precision_warning = stop_pct < 1.5

        # 检查止损位附近是否有涨跌停记录
        liquidity_warning = ""
        if recent_limit_moves:
            for move in recent_limit_moves:
                move_price = move.get("price", 0)
                if move_price > 0:
                    if abs(move_price - stop_loss_price) / stop_loss_price < 0.03:
                        move_type = move.get("type", "")
                        if move_type in ("涨停", "跌停"):
                            liquidity_warning = f"流动性风险警告：止损位附近有{move_type}记录，止损单可能无法按预期价格成交"
                            break

        if not liquidity_warning and precision_warning:
            liquidity_warning = "止损区间窄，注意流动性"

        return StopLossResult(
            entry_price=key_low,
            stop_loss_price=round(stop_loss_price, 3),
            stop_pct=round(stop_pct, 2),
            precision_warning=precision_warning,
            liquidity_risk_warning=liquidity_warning,
            stop_logic=stop_logic,
        )
