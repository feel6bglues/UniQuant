"""Phase 1 P&F 先行 — PF-C1 / PF-C3 / PF-C2 TDD 验收测试。

对应 TDD 标准 docs/analysis/CLASSIC_WYCKOFF_TDD_STANDARD_VERIFICATION_v1.md
Phase 1 (PF-C1 → PF-C3 → PF-C2)：
- PF-C1: P&F phase_hint 驱动 Step1 phase 判定
- PF-C3: TR 边界来自 P&F 水平密集区的列顶/列底
- PF-C2: V3TradingPlan.target 在 PNF count_target > 0 时优先使用 PNF target
"""

import numpy as np
import pandas as pd

from scripts.wyckoff_fixtures import (
    synthetic_accumulation,
    synthetic_spring,
)
from uniquant.brain.wyckoff.engine import WyckoffEngine
from uniquant.brain.wyckoff.models import WyckoffPhase
from uniquant.brain.wyckoff.pnf import PointAndFigure


# ───────────────────────── PF-C1: P&F 驱动 Phase ─────────────────────────

def test_pnf_drives_phase_decision(monkeypatch):
    """已知 Accumulation 数据，mock P&F hint 为 accumulation/distribution，
    验证 engine.analyze().structure.phase 跟随 P&F 提示变化。"""
    df = synthetic_accumulation(seed=42)
    engine = WyckoffEngine()

    monkeypatch.setattr(
        PointAndFigure, "wyckoff_phase_hint", lambda self: "accumulation"
    )
    report = engine.analyze(df, symbol="TEST.SH")
    assert report.structure.phase == WyckoffPhase.ACCUMULATION

    monkeypatch.setattr(
        PointAndFigure, "wyckoff_phase_hint", lambda self: "distribution"
    )
    report = engine.analyze(df, symbol="TEST.SH")
    assert report.structure.phase == WyckoffPhase.DISTRIBUTION


# ───────────────────────── PF-C3: TR 边界来自 P&F ─────────────────────────

def _make_tr_df(low_bound=10.0, high_bound=12.0, length=120, spike=False):
    """构造水平密集区 [low, high] 的合成 OHLCV。

    交替上/下 K 线使 P&F 列稳定重叠在 [low, high]；可选单日尖峰，
    60 日裸 H/L 会覆盖它，但 P&F 密集区不应被其拖离。"""
    rng = np.random.default_rng(7)
    rows = []
    for i in range(length):
        if i % 2 == 0:
            o = high_bound - 0.1
            c = high_bound - 0.05
            h = high_bound
            lo = high_bound - 1.2
        else:
            o = low_bound + 0.1
            c = low_bound + 0.05
            h = low_bound + 1.2
            lo = low_bound
        if spike and i == length - 1:
            h = high_bound + 0.5
            lo = low_bound - 0.5
            c = low_bound - 0.3
            o = low_bound + 0.1
        v = int(1e7 * (1 + rng.normal(0, 0.1)))
        rows.append({
            "date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=i),
            "open": o, "high": h, "low": lo, "close": c, "volume": v,
        })
    return pd.DataFrame(rows)


def test_tr_boundary_from_pnf():
    """水平密集区在 [10, 12] 的合成数据，engine 输出的 TR 上下界
    应落在 P&F 密集区附近（偏差 < 1 box_size 有效步长）。"""
    df = _make_tr_df()
    engine = WyckoffEngine()

    pnf = PointAndFigure(box_size=0.02, reversal=2)
    pnf.build(df)
    zone_lower, zone_upper = pnf.congestion_zone()
    assert zone_lower > 0 and zone_upper > zone_lower, "密集区应可识别"
    box = pnf._step

    report = engine.analyze(df, symbol="TEST.SH")
    upper = report.structure.trading_range_high
    lower = report.structure.trading_range_low
    assert upper is not None and lower is not None
    assert abs(upper - zone_upper) <= box, f"上界 {upper} vs P&F {zone_upper}"
    assert abs(lower - zone_lower) <= box, f"下界 {lower} vs P&F {zone_lower}"
    assert abs(upper - 12.0) < box, f"上界应接近 12.0, got {upper}"
    assert abs(lower - 10.0) < box, f"下界应接近 10.0, got {lower}"


def test_tr_boundary_resists_single_spike():
    """单日尖峰（12.5/9.5）不应把 TR 边界拖离 P&F 密集区。

    裸 60 日 H/L 会输出 12.5/9.5，而 P&F 密集区应保持 ~[10, 12]。
    断言 engine 边界跟随 P&F 密集区，且不被尖峰带偏。"""
    df = _make_tr_df(spike=True)
    engine = WyckoffEngine()

    pnf = PointAndFigure(box_size=0.02, reversal=2)
    pnf.build(df)
    zone_lower, zone_upper = pnf.congestion_zone()
    assert zone_lower > 0 and zone_upper > zone_lower, "密集区应可识别"
    box = pnf._step
    # 裸 H/L 极值必须落在密集区之外，否则测试无判别力
    assert 12.5 > zone_upper + box and 9.5 < zone_lower - box

    report = engine.analyze(df, symbol="TEST.SH")
    upper = report.structure.trading_range_high
    lower = report.structure.trading_range_low
    assert upper is not None and lower is not None
    assert abs(upper - zone_upper) <= box, f"上界 {upper} vs P&F {zone_upper}"
    assert abs(lower - zone_lower) <= box, f"下界 {lower} vs P&F {zone_lower}"
    # 不被尖峰带偏：边界必须远离裸 H/L 极值
    assert upper < 12.5 - box, f"上界不应是尖峰极值, got {upper}"
    assert lower > 9.5 + box, f"下界不应是尖峰极值, got {lower}"


# ───────────────────────── PF-C2: Count Target 进交易计划 ─────────────────────────

def test_count_target_in_trading_plan():
    """当 P&F count_target > 0 时，trading_plan.target.first_target
    应参考 PNF target（偏差 < box_size × 3）。"""
    df = synthetic_spring(seed=42)
    engine = WyckoffEngine()

    pnf = PointAndFigure(box_size=0.02, reversal=2)
    pnf.build(df)
    count_target = pnf.count_target()
    box = pnf._step

    report = engine.analyze(df, symbol="TEST.SH")
    plan_target = report.risk_reward.first_target

    if count_target > 0:
        assert abs(plan_target - count_target) <= box * 3, (
            f"target {plan_target} 应参考 PNF count_target {count_target}"
        )
