"""Phase 3 — P3-T2 markup 追买降级 + P3-T3 RS 仓位过滤 TDD 验收测试。

对应:
- P3-T2: markup 信号 + RS∈{follower, systemic_decline} → 置信度降 1 级
- P3-T3: spring/markup + RS=systemic_decline → 仓位降级
"""

from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts.wyckoff_fixtures import synthetic_accumulation, synthetic_trading_range
from uniquant.brain.wyckoff.engine import WyckoffEngine


class MockRSResult:
    """模拟 rs_classify 返回值。"""
    def __init__(self, classification: str):
        self.classification = classification
        self.stock_return_20d = 5.0
        self.index_return_20d = 2.0
        self.excess_return = 3.0
        self.stock_vol_ratio = 0.8
        self.sufficient_data = True


def synthetic_markup(seed: int = 42) -> pd.DataFrame:
    """在 accumulation 基础上追加 15 根强上涨柱 → 触发 MARKUP 相位。"""
    df = synthetic_accumulation(seed=seed).copy()
    close = df["close"].values.astype(float)
    n = len(close)
    for i in range(15):
        close[n - 15 + i] = close[n - 16] * (1 + 0.02 * (i + 1))
    df["close"] = close
    rng = np.random.default_rng(seed)
    df["open"] = close * (1 + rng.uniform(-0.005, 0.005, n))
    df["high"] = np.maximum(df["close"], df["open"]) * 1.02
    df["low"] = np.minimum(df["close"], df["open"]) * 0.98
    df["volume"] = df["volume"] * 2.0
    return df


def _conf_level(conf) -> str:
    return conf.value if hasattr(conf, "value") else str(conf)


# ─────────────────── P3-T2: markup 置信度降级 ───────────────────

def test_markup_leader_no_downgrade():
    """T1: markup + RS=leader → 不降级。"""
    df = synthetic_markup(seed=42)
    engine = WyckoffEngine()
    with patch("uniquant.brain.wyckoff.engine.rs_classify", return_value=MockRSResult("leader")):
        report = engine.analyze(df, symbol="TEST.SH", index_df=df)
    assert report.structure.phase.name == "MARKUP"
    assert report.signal.signal_type == "markup"
    assert report.relative_strength == "leader"
    assert _conf_level(report.signal.confidence) == "B"


def test_markup_follower_downgrade():
    """T2: markup + RS=follower → 降 1 级 (B→C)。"""
    df = synthetic_markup(seed=42)
    engine = WyckoffEngine()
    with patch("uniquant.brain.wyckoff.engine.rs_classify", return_value=MockRSResult("follower")):
        report = engine.analyze(df, symbol="TEST.SH", index_df=df)
    assert report.structure.phase.name == "MARKUP"
    assert report.relative_strength == "follower"
    assert _conf_level(report.signal.confidence) == "C"


def test_markup_systemic_decline_downgrade():
    """T3: markup + RS=systemic_decline → 降 1 级 (B→C)。"""
    df = synthetic_markup(seed=42)
    engine = WyckoffEngine()
    with patch("uniquant.brain.wyckoff.engine.rs_classify", return_value=MockRSResult("systemic_decline")):
        report = engine.analyze(df, symbol="TEST.SH", index_df=df)
    assert report.structure.phase.name == "MARKUP"
    assert report.relative_strength == "systemic_decline"
    assert _conf_level(report.signal.confidence) == "C"


# ─────────────────── P3-T3: RS 仓位过滤 ───────────────────

def test_spring_systemic_decline_position_downgrade():
    """T4: spring + RS=systemic_decline → 仓位降级为'空仓观望'。"""
    df = synthetic_trading_range(seed=42)
    engine = WyckoffEngine()
    with patch("uniquant.brain.wyckoff.engine.rs_classify", return_value=MockRSResult("systemic_decline")):
        report = engine.analyze(df, symbol="TEST.SH", index_df=df)
    assert report.signal.signal_type == "spring"
    assert report.relative_strength == "systemic_decline"
    assert report.trading_plan.direction == "空仓观望"


def test_spring_leader_position_unchanged():
    """T5: spring + RS=leader → 仓位不变(与基准对照一致)。"""
    df = synthetic_trading_range(seed=42)
    engine = WyckoffEngine()
    with patch("uniquant.brain.wyckoff.engine.rs_classify", return_value=MockRSResult("leader")):
        report = engine.analyze(df, symbol="TEST.SH", index_df=df)
    assert report.signal.signal_type == "spring"
    assert report.relative_strength == "leader"
    assert report.trading_plan.direction == "空仓观望"


# ─────────────────── 边界情况 ───────────────────

def test_non_markup_signal_unaffected():
    """T6: 非 markup/spring 信号(如 sos_candidate) + RS 不受影响。"""
    df = synthetic_accumulation(seed=42)
    engine = WyckoffEngine()
    with patch("uniquant.brain.wyckoff.engine.rs_classify", return_value=MockRSResult("follower")):
        report = engine.analyze(df, symbol="TEST.SH", index_df=df)
    assert report.signal.signal_type == "sos_candidate"
    assert report.relative_strength == "follower"
    assert _conf_level(report.signal.confidence) == "A"


def test_downgrade_chain_stacking():
    """T7: CF-C4 假突破 + P3 markup+follower → 降 2 级 (B→D)。

    构造一个同时满足 CF-C4 (false_breakout) 和 markup 的场景。
    """
    df = synthetic_markup(seed=42)
    engine = WyckoffEngine()
    with patch("uniquant.brain.wyckoff.engine.rs_classify", return_value=MockRSResult("follower")):
        with patch.object(engine, "_scan_false_breakout", return_value={"date": "2025-01-15", "close_high": 13.5}):
            report = engine.analyze(df, symbol="TEST.SH", index_df=df)
    assert report.signal.signal_type == "markup"
    assert report.relative_strength == "follower"
    assert _conf_level(report.signal.confidence) == "D"