"""条件信号定向验证 — 统计工具函数。

预注册见 docs/analysis/CONDITIONAL_VALIDATION_PREREGISTRATION.md:
Newey-West t / 移动块自助 CI / 点时(PIT)波动状态。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def newey_west_t(x: np.ndarray | pd.Series, lag: int) -> float:
    """Newey-West HAC t 统计量 (均值=0 检验)。"""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 20:
        return float("nan")
    e = x - x.mean()
    g0 = float(np.dot(e, e)) / n
    s = g0
    for lag_i in range(1, min(lag, n - 1) + 1):
        w = 1.0 - lag_i / (lag + 1.0)
        gl = float(np.dot(e[lag_i:], e[:-lag_i])) / n
        s += 2.0 * w * gl
    var_over_n = s / n
    se = np.sqrt(var_over_n) if var_over_n > 0 else np.nan
    mean = float(x.mean())
    if se is None or (isinstance(se, float) and (np.isnan(se) or se < 1e-12)):
        return float("nan")
    return mean / se


def block_bootstrap_ci(
    x: np.ndarray | pd.Series,
    block: int = 10,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float, float]:
    """移动块自助均值的百分位 CI。返回 (point, lo, hi)。"""
    rng = np.random.default_rng(seed)
    arr = np.asarray(x, dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n < block * 3:
        return (float(arr.mean()) if n else float("nan"), float("nan"), float("nan"))
    nb = int(np.ceil(n / block))
    means = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n - block + 1, size=nb)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n]
        means[b] = arr[idx].mean()
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return (float(arr.mean()), float(lo), float(hi))


def pit_vol_states(index_df: pd.DataFrame, window: int = 750, min_periods: int = 250) -> pd.DataFrame:
    """点时(PIT)波动三分位状态: 阈值仅用截至当日的滚动窗口分位。

    返回 date → vol_state {vol_low/vol_mid/vol_high}。
    已知特性: 窗口不足 min_periods 时无标签(丢弃)。
    """
    idx = index_df.sort_values("date").copy()
    idx["date"] = pd.to_datetime(idx["date"])
    ret = idx["close"].pct_change(fill_method=None)
    vol20 = ret.rolling(20).std()
    q33 = vol20.rolling(window, min_periods=min_periods).quantile(0.33)
    q67 = vol20.rolling(window, min_periods=min_periods).quantile(0.67)
    state = np.where(vol20.isna() | q33.isna(), "",
              np.where(vol20 <= q33, "vol_low",
                np.where(vol20 <= q67, "vol_mid", "vol_high")))
    out = pd.DataFrame({"date": idx["date"], "vol_state": state})
    return out[out["vol_state"] != ""]