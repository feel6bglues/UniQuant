"""Phase 3 非 P0 — RS-C1 相对强弱四分类 TDD 验收测试。

对应实现方案 docs/analysis/CLASSIC_WYCKOFF_P1_RESEARCH_PLAN_CNC4_SQC1_RSC1.md §4:
- rs_classify(stock_ts, index_ts) 四分类: leader / follower / weak_independent / systemic_decline。
- 对齐规格: "stock > index + low volume → leader (强势独立)"。
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.wyckoff.relative_strength import (
    RelativeStrengthResult,
    rs_classify,
)


def _make_ts(dates, closes, volumes=None):
    """构造含 date/open/high/low/close/volume 的 DataFrame。"""
    closes = np.asarray(closes, dtype=float)
    df = pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": closes * 1.01,
        "low": closes * 0.99,
        "close": closes,
        "volume": np.asarray(volumes, dtype=float)
        if volumes is not None else np.full(len(closes), 1e6),
    })
    return df


def _dates(n=30, start="2025-01-01"):
    return pd.date_range(start, periods=n, freq="B")


# ─────────────────── 四分类 (对齐规格) ───────────────────

def test_rs_leader():
    """个股 20d 涨幅 > 指数且缩量 (vol_ratio < 1) → leader。"""
    dates = _dates()
    stock_close = np.linspace(10.0, 13.0, len(dates))   # 30% 上涨
    index_close = np.linspace(10.0, 11.0, len(dates))   # 10% 上涨
    volumes = np.full(len(dates), 1e6)
    volumes[-3:] = 5e5  # 末尾缩量
    stock = _make_ts(dates, stock_close, volumes)
    index = _make_ts(dates, index_close)

    r = rs_classify(stock, index)
    assert r.classification == "leader"
    assert r.excess_return > 0
    assert r.stock_vol_ratio < 1.0
    assert r.sufficient_data


def test_rs_follower():
    """个股 > 指数但放量 (vol_ratio >= 1) → follower。"""
    dates = _dates()
    stock_close = np.linspace(10.0, 13.0, len(dates))
    index_close = np.linspace(10.0, 11.0, len(dates))
    volumes = np.full(len(dates), 1e6)
    volumes[-3:] = 2e6  # 末尾放量
    stock = _make_ts(dates, stock_close, volumes)
    index = _make_ts(dates, index_close)

    r = rs_classify(stock, index)
    assert r.classification == "follower"
    assert r.stock_vol_ratio >= 1.0


def test_rs_weak_independent():
    """指数涨、个股跌 (逆势走弱) → weak_independent。"""
    dates = _dates()
    stock_close = np.linspace(10.0, 9.0, len(dates))    # -10%
    index_close = np.linspace(10.0, 12.0, len(dates))   # +20%
    stock = _make_ts(dates, stock_close)
    index = _make_ts(dates, index_close)

    r = rs_classify(stock, index)
    assert r.classification == "weak_independent"


def test_rs_systemic_decline():
    """指数跌、个股同步跌无超额 → systemic_decline。"""
    dates = _dates()
    stock_close = np.linspace(10.0, 8.0, len(dates))    # -20%
    index_close = np.linspace(10.0, 8.5, len(dates))    # -15%
    stock = _make_ts(dates, stock_close)
    index = _make_ts(dates, index_close)

    r = rs_classify(stock, index)
    assert r.classification == "systemic_decline"


# ─────────────────── 对齐 / 鲁棒性 ───────────────────

def test_rs_date_alignment():
    """两序列日期错位，inner join 后时间轴一致，无 NaN 泄漏。"""
    stock_dates = _dates(40, start="2025-01-01")
    index_dates = _dates(40, start="2025-01-03")  # 错位 2 天
    stock_close = np.linspace(10.0, 13.0, 40)
    index_close = np.linspace(10.0, 11.0, 40)

    stock = _make_ts(stock_dates, stock_close)
    index = _make_ts(index_dates, index_close)

    r = rs_classify(stock, index)
    # 仍能对齐公共日期并给出分类
    assert r.sufficient_data
    assert r.classification in ("leader", "follower", "weak_independent", "systemic_decline")


def test_rs_insufficient_data():
    """重叠日期 < 2 → unknown + sufficient_data=False。"""
    stock = _make_ts(pd.date_range("2025-01-01", periods=3, freq="D"), [10, 10.5, 11])
    index = _make_ts(pd.date_range("2025-02-01", periods=3, freq="D"), [10, 10.5, 11])
    r = rs_classify(stock, index)
    assert r.classification == "unknown"
    assert not r.sufficient_data


def test_rs_result_dataclass_defaults():
    """RelativeStrengthResult 默认值合法。"""
    r = RelativeStrengthResult()
    assert r.classification == "unknown"
    assert r.sufficient_data


# ─────────────────── 引擎集成 (analyze index_df 可选) ───────────────────

def test_engine_index_df_optional():
    """不传 index_df → relative_strength 为 None，行为与现状一致。"""
    from scripts.wyckoff_fixtures import synthetic_spring
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    report = WyckoffEngine().analyze(synthetic_spring(seed=42), symbol="TEST.SH")
    assert report.relative_strength is None
    assert report.relative_strength_detail is None


def test_engine_index_df_integration():
    """传 index_df → WyckoffReport.relative_strength 有值。"""
    from scripts.wyckoff_fixtures import synthetic_spring
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    stock = synthetic_spring(seed=42)
    stock = stock.copy()
    stock["date"] = pd.to_datetime(stock["date"])
    index_close = np.linspace(10.0, 11.0, len(stock))
    index = _make_ts(stock["date"], index_close)

    report = WyckoffEngine().analyze(stock, symbol="TEST.SH", index_df=index)
    assert report.relative_strength is not None
    assert report.relative_strength in (
        "leader", "follower", "weak_independent", "systemic_decline", "unknown"
    )


def test_output_dict_roundtrip_relative_strength():
    """WyckoffOutput roundtrip 保留 relative_strength。"""
    from uniquant.shared.interfaces import WyckoffOutput

    out = WyckoffOutput(phase="markup", relative_strength="leader")
    d = out.to_dict()
    assert d["relative_strength"] == "leader"
    restored = WyckoffOutput.from_dict(d)
    assert restored.relative_strength == "leader"


# ─────────────────── 真实基准数据对齐 (不依赖具体分类) ───────────────────

def test_csi300_fixture_alignment():
    """data/csi300_index.parquet 可读且能与合成股票对齐。"""
    from pathlib import Path

    p = Path("data/csi300_index.parquet")
    if not p.exists():
        pytest.skip("csi300_index.parquet 不存在")
    index = pd.read_parquet(p)
    assert {"date", "close", "volume"}.issubset(index.columns)
    assert len(index) > 100

    dates = index["date"].tail(60)
    closes = np.linspace(10.0, 12.0, len(dates))
    stock = _make_ts(dates, closes)
    r = rs_classify(stock, index.tail(60))
    assert r.sufficient_data
    assert r.classification in ("leader", "follower", "weak_independent", "systemic_decline", "unknown")
