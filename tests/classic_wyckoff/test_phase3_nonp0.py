"""Phase 3 非 P0 — CN-C4 预复权校验 TDD 验收测试。

对应实现方案 docs/analysis/CLASSIC_WYCKOFF_P1_RESEARCH_PLAN_CNC4_SQC1_RSC1.md §2:
- CN-C4: 引擎入口探测未复权数据 → 标记 adjustment_status=raw + 信号降级。
- 研究平台定位: 降级不拒绝；启发式排除连续涨停结构。
"""

import pandas as pd

from scripts.wyckoff_fixtures import synthetic_spring, synthetic_accumulation
from uniquant.brain.wyckoff.engine import WyckoffEngine, _detect_adjustment_status
from uniquant.brain.wyckoff.models import ConfidenceLevel


# ─────────────────── 单元: _detect_adjustment_status ───────────────────

def test_detect_adjustment_status_pre_adjusted():
    """正常连续波动数据 → pre_adjusted。"""
    close = pd.Series([10.0, 10.2, 10.1, 10.5, 10.3, 10.6, 10.4, 10.7, 10.8])
    assert _detect_adjustment_status(close) == "pre_adjusted"


def test_detect_adjustment_status_raw():
    """单日 >20% 跳空且前日未涨停 → raw (除权除息跳空)。"""
    close = pd.Series([10.0, 10.2, 10.1, 8.0, 8.2, 8.1, 8.3, 8.2, 8.4])
    assert _detect_adjustment_status(close) == "raw"


def test_detect_adjustment_status_limit_up_continuation():
    """连续涨停 (前一日已涨停 +20%) 不应误判 raw。"""
    close = pd.Series([10.0, 12.0, 14.4, 17.28, 20.74, 24.89, 22.0, 22.5])
    assert _detect_adjustment_status(close) == "pre_adjusted"


def test_detect_adjustment_status_volatile_but_bounded():
    """±20% 内波动不触发 (A 股正常涨跌停范围)。"""
    close = pd.Series([10.0, 11.9, 10.0, 11.9, 10.0, 11.9, 10.0, 11.9, 10.0])
    assert _detect_adjustment_status(close) == "pre_adjusted"


# ─────────────────── 端到端: 报告标记 + 降级 ───────────────────

def _inject_ex_div_jump(df: pd.DataFrame) -> pd.DataFrame:
    """在 120 行 fixture 中段注入一个除权式 >20% 收盘跳空 (无放量)。"""
    out = df.copy()
    close = out["close"].astype(float)
    idx = len(out) // 2
    out.loc[idx, "close"] = close.iloc[idx - 1] * 0.75
    out.loc[idx, "open"] = close.iloc[idx - 1] * 0.76
    out.loc[idx, "high"] = close.iloc[idx - 1] * 0.80
    out.loc[idx, "low"] = close.iloc[idx - 1] * 0.74
    return out


def test_report_marks_raw_adjustment():
    """raw 数据端到端 analyze() → adjustment_status == "raw" 且信号置信度 ≤ 对照。"""
    df = synthetic_spring(seed=42)
    raw_df = _inject_ex_div_jump(df)

    engine = WyckoffEngine()
    report = engine.analyze(raw_df, symbol="TEST.SH")
    assert report.adjustment_status == "raw"

    # 对照: 未注入跳空 → pre_adjusted
    baseline = engine.analyze(df, symbol="TEST.SH")
    assert baseline.adjustment_status == "pre_adjusted"

    # raw 数据信号置信度不高于对照
    order = {"A": 0, "B": 1, "C": 2, "D": 3}
    raw_conf = report.signal.confidence
    base_conf = baseline.signal.confidence
    raw_level = raw_conf.value if hasattr(raw_conf, "value") else str(raw_conf)
    base_level = base_conf.value if hasattr(base_conf, "value") else str(base_conf)
    assert order.get(raw_level, 3) >= order.get(base_level, 3)


def test_report_pre_adjusted_passthrough():
    """既有 fixture (accumulation) 得 pre_adjusted，回归不破坏。"""
    df = synthetic_accumulation(seed=42)
    report = WyckoffEngine().analyze(df, symbol="TEST.SH")
    assert report.adjustment_status == "pre_adjusted"


def test_output_dict_roundtrip_adjustment_status():
    """WyckoffOutput roundtrip 保留 adjustment_status。"""
    from uniquant.shared.interfaces import WyckoffOutput

    out = WyckoffOutput(phase="accumulation", adjustment_status="raw")
    d = out.to_dict()
    assert d["adjustment_status"] == "raw"
    restored = WyckoffOutput.from_dict(d)
    assert restored.adjustment_status == "raw"


def test_confidence_level_enum_present():
    """确保 ConfidenceLevel 枚举可映射 (降级链路依赖)。"""
    assert ConfidenceLevel.A.value < ConfidenceLevel.D.value
