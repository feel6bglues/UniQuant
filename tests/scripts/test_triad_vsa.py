"""TRIAD-VSA 极限用例 — 评估器对抗测试.

覆盖: 因果前缀不变性 (未来函数捕手) / 常量价 / 稳态趋势 / 涨停棒 /
一字板 / 零量 / NaN 量 / 除权跳空鲁棒性 / 熵退化 / TE 可解 / 正交性 /
无方向契约 / 融合共识 / 预注册门骨架。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.wyckoff_experiments.triad_vsa import (
    TriadResult,
    _fusion,
    _limit_pct,
    _rank_sum_p,
    audit_no_direction,
    compute_triad,
    summarize_window,
)


# ── 工具: 造帧 ────────────────────────────────────────────────────────────


def _frame(
    closes: list[float] | np.ndarray,
    volumes: list[float] | np.ndarray | None = None,
    spread: float = 0.005,
) -> pd.DataFrame:
    c = np.asarray(closes, dtype=float)
    n = len(c)
    o = c.copy()
    h = np.maximum(o, c) * (1.0 + spread)
    lo = np.minimum(o, c) * (1.0 - spread)
    v = np.full(n, 1e6, dtype=float) if volumes is None else np.asarray(volumes, float)
    return pd.DataFrame(
        {"open": o, "high": h, "low": lo, "close": c, "volume": v}
    )


def _rand_series(
    n: int,
    seed: int = 7,
    trend_up: int = 40,
    churn: int = 40,
    trend_down: int = 40,
) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    prices: list[float] = []
    vols: list[float] = []
    prev = 100.0
    for i in range(n):
        if i < trend_up:
            r = 0.005
        elif i < trend_up + churn:
            r = rng.normal(0.0, 0.002)
        elif i < trend_up + churn + trend_down:
            r = -0.005
        else:
            r = rng.normal(0.0, 0.004)
        prev *= 1.0 + r
        prices.append(prev)
        vols.append(5e6 if trend_up <= i < trend_up + churn else 1e6)
    return _frame(prices, vols)


_CMP_FIELDS = ("A_stag", "B_abs", "C_abs", "B_liq", "te", "triad_abs", "triad_liq")


def _assert_finite_bounded(res: TriadResult) -> None:
    for f in ("A_stag", "B_abs", "C_abs", "B_liq", "te", "triad_abs", "triad_liq"):
        arr = getattr(res, f)
        v = arr[np.isfinite(arr)]
        assert len(v) == 0 or (v >= -1e-9).all(), f
        assert len(v) == 0 or (v <= 1.0 + 1e-9).all(), f
        assert (np.abs(arr[~np.isnan(arr)]) < np.inf).all()


# ── 1. 因果前缀不变性 (未来函数捕手) ─────────────────────────────────────


def test_causality_prefix_invariance() -> None:
    """前 150 棒特征与在 160 棒序列上重算的前 150 棒必须逐位一致."""
    full = _rand_series(220, seed=7)
    pref = full.iloc[:150].reset_index(drop=True)
    full_trim = full.iloc[:160].reset_index(drop=True)
    r_pref = compute_triad(pref)
    r_full = compute_triad(full_trim)
    for f in _CMP_FIELDS:
        a = getattr(r_pref, f)[:150]
        b = getattr(r_full, f)[:150]
        np.testing.assert_allclose(a, b, equal_nan=True, err_msg=f)


def test_causality_structural_field_invariance() -> None:
    full = _rand_series(220, seed=11)
    pref = full.iloc[:150].reset_index(drop=True)
    full_trim = full.iloc[:160].reset_index(drop=True)
    rp, rf = compute_triad(pref), compute_triad(full_trim)
    np.testing.assert_array_equal(rp.structural[:150], rf.structural[:150])
    np.testing.assert_array_equal(rp.organic[:150], rf.organic[:150])


# ── 2. 常量价 / 稳态趋势 / 熵退化 ────────────────────────────────────────


def test_constant_price_all_flat() -> None:
    df = pd.DataFrame(
        {
            "open": [100.0] * 250,
            "high": [100.0] * 250,
            "low": [100.0] * 250,
            "close": [100.0] * 250,
            "volume": np.linspace(5e5, 5e6, 250),
        }
    )
    res = compute_triad(df)
    _assert_finite_bounded(res)
    assert res.triad_abs[-1] == pytest.approx(0.0, abs=1e-9)
    assert res.triad_liq[-1] == pytest.approx(0.0, abs=1e-9)
    assert res.A_stag[-1] == pytest.approx(0.0, abs=1e-9)


def test_steady_trend_no_absorption() -> None:
    closes = [100.0]
    for _ in range(219):
        closes.append(closes[-1] * 1.01)
    res = compute_triad(_frame(closes, [1e6] * 220))
    _assert_finite_bounded(res)
    assert res.triad_abs[-1] < 0.05
    assert res.A_stag[-1] < 0.05


# ── 3. A 股铁律 censoring ───────────────────────────────────────────────


def test_limit_up_day_censored() -> None:
    """单涨停日 (量大) 在通道有效区间内必须被 censoring 完全吸收."""
    closes = [100.0] * 200 + [110.0] * 100
    vols = [1e6] * 200 + [5e7] + [1e6] * 99
    res = compute_triad(_frame(closes, vols), symbol="600000.SH")
    assert res.structural[200]
    assert not res.organic[200]
    assert res.A_stag[200] == pytest.approx(res.A_stag[199], abs=1e-9)
    assert res.triad_liq[200] < 1e-9
    baseline = compute_triad(_frame([100.0] * 300, [1e6] * 300), symbol="600000.SH")
    np.testing.assert_allclose(res.triad_liq[200], baseline.triad_liq[200], atol=1e-9)
    np.testing.assert_allclose(res.triad_abs[200], baseline.triad_abs[200], atol=1e-9)


def test_limit_down_day_censored() -> None:
    closes = [100.0] * 200 + [90.0] * 100
    vols = [1e6] * 200 + [5e7] + [1e6] * 99
    res = compute_triad(_frame(closes, vols), symbol="000001.SZ")
    assert res.structural[200]
    assert res.triad_liq[200] < 1e-9


def test_one_price_board_structural() -> None:
    """一字板 = 开盘即涨/跌停价且 open=high=low=close → structural."""
    opens = [100.0] * 60 + [110.0] * 60
    closes = opens.copy()
    df = pd.DataFrame(
        {
            "open": opens,
            "high": opens,
            "low": opens,
            "close": closes,
            "volume": [2e6] * 120,
        }
    )
    res = compute_triad(df, symbol="600000.SH")
    assert res.structural[60]
    assert not res.organic[60]
    assert res.organic[59]
    _assert_finite_bounded(res)


# ── 4. 数据质量: 零量 / NaN / 除权跳空 / 畸形 ───────────────────────────


def test_zero_volume_bar_excluded() -> None:
    full = _rand_series(240, seed=13)
    df = full.copy()
    df.loc[50, "volume"] = 0.0
    res = compute_triad(df)
    assert not res.organic[50]
    _assert_finite_bounded(res)
    assert np.isfinite(res.A_stag[-1])


def test_nan_volume_robust() -> None:
    full = _rand_series(240, seed=17)
    df = full.copy()
    df.loc[50, "volume"] = np.nan
    res = compute_triad(df)
    assert not res.organic[50]
    _assert_finite_bounded(res)


def test_adjustment_gap_robust() -> None:
    closes = [100.0] * 100 + [70.0] * 60
    res = compute_triad(_frame(closes, [1e6] * 160), symbol="600000.SH")
    _assert_finite_bounded(res)
    assert np.isfinite(res.triad_liq[-1])
    assert res.triad_liq[-1] >= 0.0 and res.triad_liq[-1] <= 1.0


def test_malformed_zero_close_finite() -> None:
    closes = [100.0] * 40 + [0.0] + [100.0] * 120
    res = compute_triad(_frame(closes, [1e6] * 161), symbol="000001.SZ")
    _assert_finite_bounded(res)


def test_short_series_no_crash() -> None:
    res = compute_triad(_frame([100.0] * 20, [1e6] * 20), symbol="600000.SH")
    assert np.isnan(res.triad_abs).all()
    assert np.isnan(res.B_abs).all()
    _assert_finite_bounded(res)


def test_warmup_nan_region() -> None:
    full = _rand_series(260, seed=19)
    res = compute_triad(full)
    assert np.isnan(res.triad_abs[:30]).all()
    assert np.isfinite(res.triad_abs[-1])


# ── 5. 传递熵可解性 ─────────────────────────────────────────────────────


def test_transfer_entropy_structured_positive() -> None:
    rng = np.random.RandomState(0)
    n = 300
    vbits = rng.randint(0, 2, n)
    vols = np.where(vbits == 1, 2e6, 5e5)
    ret = np.where(np.roll(vbits, 1) == 1, 0.01, -0.01)
    ret[0] = 0.0
    closes = 100.0 * np.exp(np.cumsum(np.log1p(ret)))
    res = compute_triad(_frame(closes, vols), symbol="600000.SH")
    assert res.te[-1] > 0.2


def test_transfer_entropy_random_near_zero() -> None:
    rng = np.random.RandomState(5)
    n = 300
    ret = rng.normal(0.0, 0.01, n)
    ret[0] = 0.0
    closes = 100.0 * np.exp(np.cumsum(ret))
    vols = rng.randint(5, 20, n) * 1e5
    res = compute_triad(_frame(closes, vols), symbol="600000.SH")
    assert res.te[-1] < 0.15


# ── 6. 正交性 / 融合共识 / 契约 ─────────────────────────────────────────


def test_orthogonality_correlation() -> None:
    rng = np.random.RandomState(23)
    n = 420
    prices: list[float] = []
    vols: list[float] = []
    prev = 100.0
    for i in range(n):
        if i < 130:
            r = 0.005
        elif i < 250:
            r = rng.normal(0.0, 0.002)
        elif i < 320:
            r = -0.005
        else:
            r = rng.normal(0.0, 0.004)
        prev *= 1.0 + r
        prices.append(prev)
        vols.append(5e6 if 130 <= i < 250 else 1e6)
    res = compute_triad(_frame(prices, vols))
    _assert_finite_bounded(res)
    valid = np.isfinite(res.A_stag) & np.isfinite(res.B_abs) & np.isfinite(res.C_abs)
    idx = np.where(valid)[0]
    assert len(idx) > 30
    a = res.A_stag[idx]
    b = res.B_abs[idx]
    c = res.C_abs[idx]
    for x, y in ((a, b), (a, c), (b, c)):
        rho = np.corrcoef(x, y)[0, 1]
        assert abs(rho) < 0.9, f"通道相关过高: rho={rho:.3f}"


def test_fusion_requires_agreement() -> None:
    t1, a1 = _fusion(
        np.array([0.9]), np.array([0.1]), np.array([0.9]), gate=0.6
    )
    assert t1[0] == pytest.approx((0.9 * 0.1 * 0.9) ** (1 / 3))
    assert a1[0] == 1.0
    t2, a2 = _fusion(
        np.array([0.9]), np.array([0.1]), np.array([0.1]), gate=0.6
    )
    assert a2[0] == 0.0
    assert t2[0] < 0.9


def test_audit_no_direction_contract() -> None:
    full = _rand_series(240, seed=29)
    res = compute_triad(full)
    audit_no_direction(res)
    frame = res.to_frame(full)
    banned = ("buy", "sell", "direction", "signal")
    cols = "|".join(frame.columns)
    assert not any(b in cols.lower() for b in banned)


# ── 7. 工具 / 预注册门骨架 ──────────────────────────────────────────────


def test_limit_pct_prefixes() -> None:
    assert _limit_pct("600519.SH") == 0.10
    assert _limit_pct("000001.SZ") == 0.10
    assert _limit_pct("002415.SZ") == 0.10
    assert _limit_pct("300750.SZ") == 0.20
    assert _limit_pct("688981.SH") == 0.20
    assert _limit_pct("430047.BJ") == 0.30
    assert _limit_pct("159915.SZ") is None
    assert _limit_pct("510300.SH") is None
    assert _limit_pct(None) is None
    assert _limit_pct("AB12") is None


def test_rank_sum_p_sanity() -> None:
    rng = np.random.RandomState(0)
    x = rng.normal(0.0, 1.0, 100)
    y = rng.normal(3.0, 1.0, 100)
    assert _rank_sum_p(x, y) < 0.001
    z = rng.normal(0.0, 1.0, 100)
    w = rng.normal(0.0, 1.0, 100)
    assert _rank_sum_p(z, w) > 0.05


def test_summarize_window_gate() -> None:
    rng = np.random.RandomState(1)
    triad = rng.rand(200)
    fwd = 0.05 * (triad > 0.85) + rng.normal(0.0, 0.01, 200)
    relmom = rng.normal(0.0, 1.0, 200)
    out = summarize_window(triad, fwd, relmom)
    assert out["n"] == 200
    assert out["raw_excess"] > 0.0
    assert out["r3_p"] < 0.05
    assert np.isfinite(out["m2_resid"])