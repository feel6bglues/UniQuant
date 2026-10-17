"""第九轮（2026-10-17）覆盖率补测：``brain/wyckoff/events.py``。

覆盖项：

* ``_vol_ma20`` 的**短序列**分支（:41）；
* 三个 ``@njit`` 事件打分内核 ``_score_ps_numba`` / ``_score_sc_numba`` /
  ``_score_sos_numba``（:68-187）——经 ``.py_func`` 覆盖等价纯 Python 逻辑
  （``@njit`` 原生码对 coverage tracer 不可见，口径同
  ``tests/brain/lppl/test_lppl_numba_optimizer_coverage.py``）；
* ``detect_st`` / ``detect_lps`` 中 "参考事件日期不在 df 内 ⇒ 返回空"
  的分支（:318 / :398）。

**不覆盖项（不可达防御守卫，不写"强行命中"的测试）**：``_score_sc_numba:124``
（``i < 5``：循环起点 ``max(n-60,5) >= 5`` 恒不成立）、``_score_sos_numba:165``
（``i < 2``：起点 ``max(n-30,5) >= 5``）、``detect_st:323``（``i >= n``：循环上界即 ``n``）、
``detect_lps:405``（同上）、``detect_jac:450``（``i < 20``：起点 ``max(n-20,20) >= 20``）。

不触网、不读数据湖、不依赖 czsc/backtrader。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.wyckoff.events import (
    _score_ps_numba,
    _score_sc_numba,
    _score_sos_numba,
    _vol_ma20,
    detect_lps,
    detect_st,
    WyckoffEvent,
)

N = 60
VOL_MA20 = 1.0e6


def _base_arrays() -> dict:
    """单调下行 + 受控逐 bar 覆写的合成 OHLCV（n=60）。"""
    close = np.linspace(10.0, 5.0, N)
    open_prices = close + 0.02
    high = close * 1.02
    low = close * 0.98
    volume = np.full(N, VOL_MA20)
    return {
        "close": close,
        "open": open_prices,
        "high": high,
        "low": low,
        "volume": volume,
    }


# --------------------------------------------------------------------------
# _vol_ma20
# --------------------------------------------------------------------------
def test_vol_ma20_uses_trailing_20_window() -> None:
    v = np.arange(1.0, 61.0)
    assert _vol_ma20(v) == float(np.mean(v[-20:]))


def test_vol_ma20_short_series_falls_back_to_full_mean() -> None:
    """len < 20 ⇒ 全序列均值（源码 :41）。"""
    v = np.array([1.0, 2.0, 3.0])
    assert _vol_ma20(v) == float(np.mean(v))


# --------------------------------------------------------------------------
# _score_ps_numba
# --------------------------------------------------------------------------
def test_score_ps_kernel_covers_all_branches() -> None:
    a = _base_arrays()
    close, open_p, high, low, volume = (
        a["close"], a["open"], a["high"], a["low"], a["volume"],
    )

    # i = 58/59：i >= n-2 ⇒ continue（:77）
    # i = 50：tr_prior > -5 ⇒ continue（:80）—— close[30] 基准上抬
    close[50] = close[30] * 0.99
    # i = 41：vol_ratio < 1.2 ⇒ continue（:83）
    volume[41] = VOL_MA20 * 0.5
    # i = 42：body < 0.01 ⇒ continue（:89）
    volume[42] = VOL_MA20 * 2.0
    open_p[42] = close[42]
    # i = 43：close_pos < 0.4 ⇒ continue（:92）
    volume[43] = VOL_MA20 * 2.0
    open_p[43] = close[43] + 0.05
    high[43] = close[43] + 1.0
    low[43] = close[43] - 0.01
    # i = 44：amp < 0.015 ⇒ continue（:94）
    volume[44] = VOL_MA20 * 2.0
    low[44] = close[44] * 0.999
    high[44] = close[44] * 1.001
    open_p[44] = close[44] - 0.05
    # i = 45：hero —— 全部通过，score >= 3（:101-108）
    volume[45] = VOL_MA20 * 2.0
    open_p[45] = close[45] - 0.05
    low[45] = close[45] - 0.20
    high[45] = close[45] + 0.10
    close[46] = close[45] + 0.10  # confirm = True

    valid, scores, vol_ratios, wick_ratios, close_poses, confirms, close_vals = (
        _score_ps_numba.py_func(close, high, low, open_p, volume, VOL_MA20, N)
    )

    assert valid[45] is np.True_ or bool(valid[45]) is True
    assert scores[45] >= 3
    assert wick_ratios[45] > 2
    assert close_poses[45] > 0.6
    assert bool(confirms[45]) is True
    assert close_vals[45] == close[45]
    assert vol_ratios[45] == volume[45] / VOL_MA20


def test_score_ps_kernel_zero_vol_ma20_guard() -> None:
    """``vol_ma20 <= 0`` ⇒ vol_ratio 回退 1（不走除零）。"""
    a = _base_arrays()
    out = _score_ps_numba.py_func(
        a["close"], a["high"], a["low"], a["open"], a["volume"], 0.0, N
    )
    # 无有效信号，但函数正常返回（覆盖 vol_ma20 == 0 的 else 分支）
    assert len(out) == 7
    assert not out[0].any()


# --------------------------------------------------------------------------
# _score_sc_numba
# --------------------------------------------------------------------------
def test_score_sc_kernel_covers_all_branches() -> None:
    a = _base_arrays()
    close, open_p, high, low, volume = (
        a["close"], a["open"], a["high"], a["low"], a["volume"],
    )
    vol_rank = np.zeros(N)

    # i = 20：tr_prior > -8 ⇒ continue（:127）
    close[20] = close[0] * 0.99
    # i = 30：body <= 0.01 ⇒ wick_ratio = 10（:131 else 分支）
    open_p[30] = close[30]
    # i = 40：hero —— 全部通过，score >= 3（:142-150）
    open_p[40] = close[40] - 0.05
    low[40] = 1.0            # 成为 low[20:41] 的最小值 ⇒ new_20d_low
    high[40] = 1.10          # amp = 0.10 > 0.04
    volume[40] = VOL_MA20 * 3.0   # vol_ratio = 3 > 2
    vol_rank[40] = 0.9            # vol_rank > 0.8
    subsequent_high = high * 1.0
    subsequent_high[40] = low[40] * 1.05   # rebound = 0.05 > 0.01

    out = _score_sc_numba.py_func(
        close, high, low, open_p, volume, VOL_MA20, vol_rank, subsequent_high, N
    )
    valid, scores, vol_ratios, wick_ratios, amps, new_lows, rebounds, low_vals = out

    assert bool(valid[40]) is True
    assert scores[40] >= 3
    assert wick_ratios[40] > 2
    assert amps[40] == pytest.approx(0.1)
    assert bool(new_lows[40]) is True
    assert rebounds[40] == pytest.approx(0.05)
    assert low_vals[40] == 1.0
    assert vol_ratios[40] == 3.0
    # i=30 的 body≈0 ⇒ wick_ratio 记为 10（未入选 valid 时不写出，但函数已走该分支）
    assert len(out) == 8


def test_score_sc_kernel_zero_vol_ma20_guard() -> None:
    a = _base_arrays()
    vol_rank = np.zeros(N)
    out = _score_sc_numba.py_func(
        a["close"], a["high"], a["low"], a["open"], a["volume"],
        0.0, vol_rank, a["high"], N,
    )
    assert len(out) == 8


# --------------------------------------------------------------------------
# _score_sos_numba
# --------------------------------------------------------------------------
def test_score_sos_kernel_covers_all_branches() -> None:
    a = _base_arrays()
    close, high, low, volume = a["close"], a["high"], a["low"], a["volume"]

    # i = 35：gain < 0.03 ⇒ continue（:168）—— 基线单调下行天然满足
    # i = 38：gain >= 0.03 但 vol_ratio < 1.3 ⇒ continue（:171）
    close[38] = close[37] * 1.05
    volume[38] = VOL_MA20 * 0.5
    # i = 40：hero —— gain > 0.05, vol_ratio > 2, close_pos > 0.75, new_high
    close[40] = close[39] * 1.06
    volume[40] = VOL_MA20 * 3.0
    # high[40] 必须超过窗口 [20,40] 内最大 high（≈ high[20] = close[20]*1.02）
    high[40] = 9.0
    # low 取足够低，使 close_pos = (close-low)/(high-low) > 0.75
    low[40] = 1.0

    valid, scores, vol_ratios, close_poses, new_highs, gains, close_vals = (
        _score_sos_numba.py_func(close, high, low, volume, VOL_MA20, N)
    )

    assert bool(valid[40]) is True
    assert scores[40] >= 4
    assert vol_ratios[40] == 3.0
    assert close_poses[40] > 0.75
    assert bool(new_highs[40]) is True
    assert gains[40] == pytest.approx(0.06)
    assert close_vals[40] == close[40]


def test_score_sos_kernel_zero_vol_ma20_guard() -> None:
    a = _base_arrays()
    out = _score_sos_numba.py_func(
        a["close"], a["high"], a["low"], a["volume"], 0.0, N
    )
    assert len(out) == 7


# --------------------------------------------------------------------------
# detect_st / detect_lps：参考事件日期不在 df 内
# --------------------------------------------------------------------------
def _df() -> pd.DataFrame:
    a = _base_arrays()
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=N, freq="D"),
            "open": a["open"],
            "high": a["high"],
            "low": a["low"],
            "close": a["close"],
            "volume": a["volume"],
        }
    )


def test_detect_st_returns_empty_when_reference_date_absent() -> None:
    """参考事件日期不在 df 内 ⇒ ``ref_idx < 0`` ⇒ 返回空（源码 :318）。"""
    ref = WyckoffEvent(
        event_type="SC",
        date="1999-01-01",
        price=1.0,
        confidence=0.5,
        volume_ratio=1.0,
    )
    assert detect_st(_df(), [ref]) == []


def test_detect_lps_returns_empty_when_sos_date_absent() -> None:
    """SOS 事件日期不在 df 内 ⇒ ``sos_idx < 0`` ⇒ 返回空（源码 :398）。"""
    sos = WyckoffEvent(
        event_type="SOS",
        date="1999-01-01",
        price=1.0,
        confidence=0.5,
        volume_ratio=1.0,
    )
    assert detect_lps(_df(), [sos]) == []


def test_detect_st_and_lps_empty_reference_short_circuit() -> None:
    """空参考事件列表 ⇒ 早退返回空（正对照，防守卫依赖）。"""
    assert detect_st(_df(), []) == []
    assert detect_lps(_df(), []) == []
