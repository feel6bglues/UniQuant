"""P0-1/P0-2: Spring 到交易方向的传导修复 — TDD 验收测试。

背景 (2026-08-07 实证):
  120 只真实 SZ 股实跑, 检测到 3 只 spring, 但 0 只给出做多/买入方向:
  - 000518.SZ phase=unknown conf=A fwd20=+5.8% -> 空仓观望 (UNKNOWN 分支丢弃 spring)
  - 000501.SZ phase=accumulation conf=B fwd20=+3.0% -> 观察等待 (lps 未确认被压到观望)

修复目标:
  P0-1: accumulation + spring + 强置信(>=B+ 或 rr>=1.5) 但 lps 未确认 -> 轻仓试探
  P0-2: UNKNOWN 相位 + spring + 强置信 -> 不再无条件空仓观望, 进入方向判定

守卫(不允许破坏的 A 股铁律):
  - 弱置信 spring (C) 仍保持观望
  - markdown/distribution 禁做多不变

注意 (2026-08-07 红蓝对抗 §六):
  config wyckoff.accumulation_downgrade=true 后, ACCUMULATION 多头方向再降 1 档。
  本文件 `_plan` 默认 pin `_accumulation_downgrade=False`, 专门验证 P0 传导逻辑本身;
  降档行为在 test_accumulation_downgrade.py 单独验收。
"""

import pandas as pd

from uniquant.brain.wyckoff.engine import WyckoffEngine
from uniquant.brain.wyckoff.models import (
    ConfidenceResult,
    RiskRewardResult,
    Step1Result,
    Step3Result,
    V3CounterfactualResult,
    V3TradingPlan,
    WyckoffPhase,
)

STRONG = {"A", "B+"}


def _df() -> pd.DataFrame:
    """温和波动的合成日线，避免触发涨跌停/假突破守卫。"""
    n = 60
    base = pd.Series(10.0 * (1 + 0.005 * pd.Series(range(n)).apply(lambda i: (i % 10) / 10)))
    close = base.values
    open_ = close * 1.0
    high = close * 1.002
    low = close * 0.998
    return pd.DataFrame({
        "date": pd.date_range("2021-01-01", periods=n, freq="D"),
        "open": open_, "high": high, "low": low, "close": close,
        "volume": [1e7] * n,
    })


def _engine() -> WyckoffEngine:
    engine = WyckoffEngine()
    engine._accumulation_downgrade = False  # pin: 本文件只验证 P0 传导逻辑
    return engine


def _plan(
    engine, phase, spring=True, lps=False, conf="B", rr=2.0,
    unknown_candidate="", df=None,
) -> V3TradingPlan:
    engine._code_prefix = "000"
    engine._is_st = False
    step1 = Step1Result(phase=phase, unknown_candidate=unknown_candidate,
                        boundary_upper=10.4, boundary_lower=9.6)
    step3 = Step3Result(spring_detected=spring, lps_confirmed=lps, spring_low_price=9.6)
    cf = V3CounterfactualResult(conclusion_overturned=False)
    rr_res = RiskRewardResult(entry_price=10.2, stop_loss=9.6, first_target=11.0, rr_ratio=rr)
    conf_res = ConfidenceResult(level=conf)
    return engine._step5_trading_plan(step1, step3, cf, rr_res, conf_res, df if df is not None else _df())


def test_p01_accum_spring_strong_conf_lps_unconfirmed_lighten():
    """P0-1: accumulation + Spring + 强置信(B) 但 lps 未确认 -> 轻仓试探。"""
    plan = _plan(_engine(), WyckoffPhase.ACCUMULATION, spring=True, lps=False, conf="B")
    assert plan.direction == "轻仓试探", (
        f"P0-1: 应放开做多方向, got {plan.direction!r}"
    )


def test_p01_accumulation_spring_strong_conf_rr_lighten():
    """P0-1: Spring + 盈亏比>=1.5 (即使置信 C) -> 轻仓试探。"""
    plan = _plan(_engine(), WyckoffPhase.ACCUMULATION, spring=True, lps=False, conf="C", rr=1.8)
    assert plan.direction == "轻仓试探", (
        f"P0-1: rr 达标应轻仓试探, got {plan.direction!r}"
    )


def test_p01_accumulation_spring_strong_conf_alone_lighten():
    """P0-1: Spring + 置信 B (含 B+) 且 RR 不达标(独立置信臂) -> 轻仓试探。

    低 RR (<1.5) 隔离：只有 confidence.level 在 {A,B,B+} 才能触发放行，
    防止测试被 RR >=1.5 分支掩盖。
    """
    plan = _plan(_engine(), WyckoffPhase.ACCUMULATION, spring=True, lps=False, conf="B", rr=1.0)
    assert plan.direction == "轻仓试探", (
        f"P0-1: 置信 B 应单独放行, got {plan.direction!r}"
    )


def test_p01_accumulation_spring_conf_bplus_lighten():
    """P0-1: 引擎内部产生的 B+ 字符串也应被识别为强置信。"""
    plan = _plan(_engine(), WyckoffPhase.ACCUMULATION, spring=True, lps=False, conf="B+", rr=1.0)
    assert plan.direction == "轻仓试探", (
        f"P0-1: B+ 应放行, got {plan.direction!r}"
    )


def test_p02_unknown_spring_strong_conf_not_dropped():
    """P0-2: UNKNOWN + spring + 强置信 -> 不再无条件空仓观望。"""
    plan = _plan(_engine(), WyckoffPhase.UNKNOWN, spring=True, conf="A", rr=1.0, unknown_candidate="other")
    assert plan.direction != "空仓观望", (
        f"P0-2: 强置信 spring 不应被丢弃, got {plan.direction!r}"
    )


def test_p02_unknown_spring_strong_watch_not_drop():
    """P0-2: UNKNOWN (unknown_candidate 未知) + spring + 强置信 -> 至少观察等待。"""
    plan = _plan(_engine(), WyckoffPhase.UNKNOWN, spring=True, conf="B", unknown_candidate="")
    assert plan.direction in ("轻仓试探", "观察等待"), (
        f"P0-2: 应进入方向判定, got {plan.direction!r}"
    )


def test_p01_weak_confidence_spring_still_watch():
    """守卫: accumulation + spring + 弱置信(C) + 低 rr -> 仍观察等待 (不越权做多)。"""
    plan = _plan(_engine(), WyckoffPhase.ACCUMULATION, spring=True, lps=False, conf="C", rr=1.0)
    assert plan.direction == "观察等待", (
        f"守卫: 弱置信应保持观察, got {plan.direction!r}"
    )


def test_p02_unknown_weak_confidence_spring_still_no_trade():
    """守卫: UNKNOWN + spring + 弱置信(D) + 弱盈亏比 -> 仍空仓观望 (无强确认不进入方向)。"""
    plan = _plan(_engine(), WyckoffPhase.UNKNOWN, spring=True, conf="D",
                 rr=1.0, unknown_candidate="")
    assert plan.direction == "空仓观望"