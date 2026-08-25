"""CANSLIM 成长因子构造器 — 单元测试。

覆盖红蓝对抗修正案 A3 边界规则:
R-BASE-NEG / R-BASE-TINY / R-MIN-HIST / R-YOUNG / R-FIN / 年边界单季差分 / 公告日对齐。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "canslim"))

from growth_factors import (  # noqa: E402
    TINY_BASE,
    annual_metrics,
    normalize_announcement_int,
    single_quarter_diff,
    ttm_and_yoy,
)


# ── 单季差分: 年边界重置 ────────────────────────────────────────────────


def test_single_quarter_year_reset():
    dates = [20170331, 20170630, 20170930, 20171231, 20180331]
    cum = [20.0, 45.0, 60.0, 80.0, 24.0]
    sq = single_quarter_diff(pd.Series(cum), pd.Series(dates))
    assert sq.tolist() == pytest.approx([20.0, 25.0, 15.0, 20.0, 24.0])


def test_single_quarter_first_row_is_itself():
    sq = single_quarter_diff(pd.Series([7.0]), pd.Series([20200101]))
    assert sq.iloc[0] == pytest.approx(7.0)


# ── TTM 与同比: 基数规则 ────────────────────────────────────────────────


def _yoy_frame(sq_vals):
    """8 季单季序列, 返回 ttm 与 yoy。"""
    return ttm_and_yoy(pd.Series(sq_vals, dtype=float))


def test_ttm_requires_full_window():
    big = 1e8                            # 真实量级, 避开 R-BASE-TINY
    ttm, yoy = _yoy_frame([big] * 8)
    assert np.isnan(ttm.iloc[2])          # 未满 4 季 → NaN (R-MIN-HIST)
    assert ttm.iloc[3] == pytest.approx(4 * 1e8)
    assert np.isnan(yoy.iloc[3])          # 无去年同期 TTM → NaN
    assert yoy.iloc[7] == pytest.approx(0.0)


def test_yoy_negative_base_nan():
    # 去年同期 TTM 为负 → 增速 NaN (R-BASE-NEG)
    sq = [-10.0] * 4 + [5.0] * 4         # 前四季TTM=-40, 后四季TTM=20
    ttm, yoy = _yoy_frame(sq)
    assert np.isnan(yoy.iloc[7])


def test_yoy_tiny_base_nan():
    # 基数绝对值 < TINY_BASE → NaN (R-BASE-TINY)
    tiny = TINY_BASE / 4 / 10            # 单季值使 TTM = TINY_BASE/10 < TINY_BASE
    sq = [tiny] * 4 + [tiny * 50] * 4
    _, yoy = _yoy_frame(sq)
    assert np.isnan(yoy.iloc[7])


# ── 年度指标: CAGR 与年轻标记 ───────────────────────────────────────────


def test_annual_cagr_and_consec():
    rows = []
    eps_map = {2016: 1.0, 2017: 1.3, 2018: 1.69, 2019: 2.197}   # 30% 复合
    for y, e in eps_map.items():
        rows.append({"report_date": y * 10000 + 1231, "effective_date": pd.Timestamp(f"{y+1}-04-01"), "eps": e})
    df = pd.DataFrame(rows)
    out = annual_metrics(df)
    last = out[out["report_date"] == 20191231].iloc[0]
    assert last["a_cagr3"] == pytest.approx(0.30, rel=1e-3)
    assert bool(last["a_consec_growth"]) is True


def test_annual_young_flag_needs_four_fy():
    rows = [
        {"report_date": 20171231, "effective_date": pd.Timestamp("2018-03-20"), "eps": 1.0},
        {"report_date": 20181231, "effective_date": pd.Timestamp("2019-03-20"), "eps": 1.2},
        {"report_date": 20191231, "effective_date": pd.Timestamp("2020-03-20"), "eps": 1.5},
    ]
    out = annual_metrics(pd.DataFrame(rows))
    assert (out["is_young"]).all()       # 不足 4 个年报 → 全部 young (R-YOUNG)


def test_annual_negative_eps_cagr_nan():
    rows = [
        {"report_date": 20171231, "effective_date": pd.Timestamp("2018-03-20"), "eps": -1.0},
        {"report_date": 20181231, "effective_date": pd.Timestamp("2019-03-20"), "eps": 1.0},
        {"report_date": 20191231, "effective_date": pd.Timestamp("2020-03-20"), "eps": 2.0},
        {"report_date": 20201231, "effective_date": pd.Timestamp("2021-03-20"), "eps": 3.0},
    ]
    out = annual_metrics(pd.DataFrame(rows))
    last = out[out["report_date"] == 20201231].iloc[0]
    assert not last["is_young"]
    assert np.isnan(last["a_cagr3"])     # 起点 EPS ≤ 0 → NaN


# ── 公告日归一化 ────────────────────────────────────────────────────────


def test_normalize_announcement_int():
    assert normalize_announcement_int(250419.0) == 20250419
    assert normalize_announcement_int(np.nan) != normalize_announcement_int(np.nan)  # NaN 保持 NaN
    assert normalize_announcement_int(0.0) != normalize_announcement_int(0.0)