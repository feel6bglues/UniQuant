"""Regime 条件化诊断 — 核心函数单测。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "factor_mining"))

from run_regime_conditional_ic import (  # noqa: E402
    daily_ic,
    find_highlights,
    index_states,
    summarize,
)


def test_daily_ic_matches_scipy():
    rng = np.random.RandomState(7)
    rows = []
    for d in range(3):
        n = 60
        f = rng.normal(size=n)
        r = 0.5 * f + rng.normal(scale=0.8, size=n)   # 强单调关系
        rows += [(pd.Timestamp(f"2024-01-{d+1:02d}"), f[i], r[i]) for i in range(n)]
    panel = pd.DataFrame(rows, columns=["date", "f", "r"])
    got = daily_ic(panel, "f", "r")
    assert len(got) == 3
    expected = spearmanr(
        panel[panel["date"] == panel["date"].iloc[0]]["f"],
        panel[panel["date"] == panel["date"].iloc[0]]["r"],
    ).statistic
    assert got.iloc[0] == pytest.approx(expected, abs=1e-10)


def test_daily_ic_small_cross_section_skipped():
    rows = [(pd.Timestamp("2024-01-01"), i * 1.0, i * 1.0) for i in range(10)]
    panel = pd.DataFrame(rows, columns=["date", "f", "r"])
    assert daily_ic(panel, "f", "r").empty          # <20 只 → 跳过


def _fake_index(n: int = 500) -> pd.DataFrame:
    rng = np.random.RandomState(0)
    close = 3000 + np.cumsum(rng.normal(0, 30, n))
    return pd.DataFrame({
        "date": pd.bdate_range("2020-01-01", periods=n),
        "close": close,
    })


def test_index_states_columns_and_values():
    st = index_states(_fake_index())
    assert set(st.columns) == {"date", "trend", "vol_state"}
    assert set(st["trend"].unique()) <= {"trend_on", "trend_off"}
    assert set(st["vol_state"].unique()) <= {"vol_low", "vol_mid", "vol_high"}
    # 语义断言: 首行处于 MA200 预热期 → off; 无残留 nan 状态标签
    assert st["trend"].iloc[0] == "trend_off"
    assert not st["vol_state"].isin(["nan", "", "None"]).any()


def test_summarize_splits_by_state():
    dates = pd.bdate_range("2022-01-03", periods=400)
    ic = pd.Series(np.linspace(-0.1, 0.1, 400), index=pd.DatetimeIndex(dates), name="x")
    states = pd.DataFrame({
        "date": dates,
        "trend": ["trend_on"] * 200 + ["trend_off"] * 200,
        "vol_state": ["vol_low"] * 400,
    })
    out = summarize(ic, states)
    assert "trend_on|vol_low" in out and "trend_off|vol_low" in out
    assert out["trend_on|vol_low"]["mean_ic"] < out["trend_off|vol_low"]["mean_ic"]
    assert "_overall" in out


def test_find_highlights_thresholds():
    rep = {
        "a|low": {"n_days": 150, "mean_ic": 0.05, "t": 3.5},
        "b|low": {"n_days": 150, "mean_ic": -0.04, "t": -3.2},
        "c|low": {"n_days": 50, "mean_ic": 0.20, "t": 5.0},      # n 不足不入选
        "d|low": {"n_days": 150, "mean_ic": 0.01, "t": 1.0},     # t 不足
        "_overall": {},
    }
    hits = find_highlights(rep)
    assert any("a|low" in h for h in hits)
    assert any("FLIP" in h and "b|low" in h for h in hits)
    assert not any("c|low" in h for h in hits)
    assert not any("d|low:" in h for h in hits)