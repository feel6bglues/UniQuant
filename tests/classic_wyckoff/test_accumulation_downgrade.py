"""红蓝对抗 §六 (2026-08-07): ACCUMULATION 多头方向降 1 档 — TDD 验收测试。

依据 WYCKOFF_VERIFICATION_RED_BLUE_20260807.md 双窗口超额收益证据:
  accumulation 超额为负 (-1.87% / -1.37%) → 蓄势不承诺上涨, 多头方向降 1 档。

行为矩阵 (accumulation_downgrade=true):
  做多/买入        → 轻仓试探
  轻仓试探          → 观察等待
  其他 (观察/空仓)  → 不变
非 ACCUMULATION 相位 (markup/unknown) 不受影响。
"""

from unittest.mock import patch

import pandas as pd

from uniquant.brain.wyckoff.engine import _downgrade_direction, WyckoffEngine
from uniquant.brain.wyckoff.models import (
    ConfidenceResult,
    RiskRewardResult,
    Step1Result,
    Step3Result,
    V3CounterfactualResult,
    V3TradingPlan,
    WyckoffPhase,
)


def _df() -> pd.DataFrame:
    n = 60
    base = pd.Series(10.0 * (1 + 0.005 * pd.Series(range(n)).apply(lambda i: (i % 10) / 10)))
    close = base.values
    return pd.DataFrame({
        "date": pd.date_range("2021-01-01", periods=n, freq="D"),
        "open": close * 1.0, "high": close * 1.002,
        "low": close * 0.998, "close": close,
        "volume": [1e7] * n,
    })


def _plan(engine, phase, spring=True, lps=False, conf="B", rr=2.0) -> V3TradingPlan:
    engine._code_prefix = "000"
    engine._is_st = False
    step1 = Step1Result(phase=phase, unknown_candidate="",
                        boundary_upper=10.4, boundary_lower=9.6)
    step3 = Step3Result(spring_detected=spring, lps_confirmed=lps, spring_low_price=9.6)
    cf = V3CounterfactualResult(conclusion_overturned=False)
    rr_res = RiskRewardResult(entry_price=10.2, stop_loss=9.6, first_target=11.0, rr_ratio=rr)
    conf_res = ConfidenceResult(level=conf)
    return engine._step5_trading_plan(step1, step3, cf, rr_res, conf_res, _df())


def _engine(downgrade: bool) -> WyckoffEngine:
    engine = WyckoffEngine()
    engine._accumulation_downgrade = downgrade
    return engine


# ---- 纯函数 _downgrade_direction ----

def test_downgrade_direction_mapping():
    assert _downgrade_direction("做多") == "轻仓试探"
    assert _downgrade_direction("买入") == "轻仓试探"
    assert _downgrade_direction("轻仓试探") == "观察等待"
    assert _downgrade_direction("观察等待") == "观察等待"
    assert _downgrade_direction("空仓观望") == "空仓观望"


# ---- §六: ACCUMULATION 降档行为 ----

def test_accumulation_spring_strong_lighten_downgraded_to_watch():
    """§六: ACCUMULATION + spring + 强置信(B) -> 原本轻仓试探, 降档为观察等待。"""
    plan = _plan(_engine(True), WyckoffPhase.ACCUMULATION, spring=True, lps=False, conf="B", rr=1.0)
    assert plan.direction == "观察等待", (
        f"§六: 蓄势应降档为观察等待, got {plan.direction!r}"
    )


def test_accumulation_lps_confirmed_strong_duo_downgraded_to_lighten():
    """§六: ACCUMULATION + spring + lps + 强置信(A) -> 原本做多, 降档为轻仓试探。"""
    plan = _plan(_engine(True), WyckoffPhase.ACCUMULATION, spring=True, lps=True, conf="A", rr=2.0)
    assert plan.direction == "轻仓试探", (
        f"§六: 做多应降档为轻仓试探, got {plan.direction!r}"
    )


def test_accumulation_weak_conf_spring_unchanged():
    """§六: ACCUMULATION + spring + 弱置信(C) + 低 rr -> 原本观察等待, 降档后仍观察等待。"""
    plan = _plan(_engine(True), WyckoffPhase.ACCUMULATION, spring=True, lps=False, conf="C", rr=1.0)
    assert plan.direction == "观察等待", (
        f"§六: 弱置信保持观察等待, got {plan.direction!r}"
    )


def test_flag_off_keeps_original_p0_behavior():
    """守卫: accumulation_downgrade=false 时, P0 传导逻辑保持不变 (轻仓试探)。"""
    plan = _plan(_engine(False), WyckoffPhase.ACCUMULATION, spring=True, lps=False, conf="B", rr=1.0)
    assert plan.direction == "轻仓试探", (
        f"P0: 关闭降档应保持轻仓试探, got {plan.direction!r}"
    )


def test_unknown_phase_not_affected():
    """§六: UNKNOWN 相位 spring -> 不降档 (仍轻仓试探)。"""
    plan = _plan(_engine(True), WyckoffPhase.UNKNOWN, spring=True, lps=False, conf="B", rr=1.0,
                 )
    assert plan.direction == "轻仓试探", (
        f"§六: UNKNOWN 不应降档, got {plan.direction!r}"
    )


def test_markup_not_affected():
    """§六: MARKUP 相位 -> 降档开关不影响其结果 (flag on/off 方向一致)。"""
    on = _plan(_engine(True), WyckoffPhase.MARKUP, spring=True, lps=False, conf="A", rr=2.0)
    off = _plan(_engine(False), WyckoffPhase.MARKUP, spring=True, lps=False, conf="A", rr=2.0)
    assert on.direction == off.direction, (
        f"§六: MARKUP 不应受降档影响, on={on.direction!r} off={off.direction!r}"
    )
    assert on.direction != "空仓观望", (
        f"MARKUP 不应被误杀为空仓观望, got {on.direction!r}"
    )


def test_config_flag_wired_from_yaml():
    """接线: WyckoffEngine.__init__ 从 config 读取 accumulation_downgrade。"""
    with patch("uniquant.brain.wyckoff.engine.get_config") as mc:
        mc.return_value.get.side_effect = lambda k, d=None: {
            "wyckoff.accumulation_downgrade": True,
        }.get(k, d)
        assert WyckoffEngine()._accumulation_downgrade is True
    with patch("uniquant.brain.wyckoff.engine.get_config") as mc:
        mc.return_value.get.side_effect = lambda k, d=None: {
            "wyckoff.accumulation_downgrade": False,
        }.get(k, d)
        assert WyckoffEngine()._accumulation_downgrade is False
