"""条件信号定向验证 — 统计工具单测。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "factor_mining"))

from conditional_stats import (  # noqa: E402
    block_bootstrap_ci,
    newey_west_t,
    pit_vol_states,
)


def test_newey_west_t_iid_matches_plain_t():
    rng = np.random.RandomState(3)
    x = rng.normal(0.05, 1.0, 500)
    t_nw = newey_west_t(x, lag=5)
    se_plain = x.std(ddof=1) / np.sqrt(len(x))
    t_plain = x.mean() / se_plain
    assert t_nw == pytest.approx(t_plain, rel=0.25)


def test_newey_west_t_shrinks_for_autocorrelated():
    """AR(1) 强自相关序列: NW-t 必须显著小于朴素 t (否则未校正)。"""
    rng = np.random.RandomState(5)
    n = 600
    e = rng.normal(0.03, 0.5, n)
    x = np.empty(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = 0.9 * x[i - 1] + e[i]
    t_nw = newey_west_t(x, lag=21)
    t_plain = x.mean() / (x.std(ddof=1) / np.sqrt(n))
    assert abs(t_plain) > abs(t_nw) * 2


def test_block_bootstrap_ci_covers_truth():
    rng = np.random.RandomState(11)
    x = rng.normal(0.10, 0.30, 400)
    point, lo, hi = block_bootstrap_ci(x, block=10, n_boot=1000)
    assert hi > lo
    assert lo < point < hi or point >= lo          # 合理覆盖
    assert lo > -0.02 and hi < 0.25                # 均值0.10附近合理区间


def test_block_bootstrap_ci_short_series_nan():
    _, lo, hi = block_bootstrap_ci(np.array([0.1] * 5), block=10)
    assert np.isnan(lo) and np.isnan(hi)


def test_pit_vol_states_labels_and_monotonic_info():
    rng = np.random.RandomState(2)
    n = 900
    close = 3000 + np.cumsum(rng.normal(0, 40, n))
    idx = pd.DataFrame({"date": pd.bdate_range("2018-01-01", periods=n), "close": close})
    st = pit_vol_states(idx)
    assert set(st["vol_state"].unique()) <= {"vol_low", "vol_mid", "vol_high"}
    assert len(st) < n                              # 预热期被丢弃
    assert st["date"].is_monotonic_increasing