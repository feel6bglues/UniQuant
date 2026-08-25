"""向量化 compute_ic_ir 与逐日 spearmanr 参考实现的等价性回归。"""

import numpy as np
import pandas as pd
from scipy import stats

from src.uniquant.brain.factors.analyzer import AnalysisMode, FactorAnalyzer


def _ref_daily_ic(df, fwd_col, factor_col):
    """旧实现：按日期分组逐日 spearmanr。"""
    def calc(group):
        factor_vals = group[factor_col]
        ret_vals = group[fwd_col]
        valid = ~(factor_vals.isna() | ret_vals.isna())
        if valid.sum() < 5:
            return np.nan
        fv = factor_vals[valid]
        rv = ret_vals[valid]
        if fv.nunique() < 2 or rv.nunique() < 2:
            return np.nan
        ic, _ = stats.spearmanr(fv, rv)
        return ic if not np.isnan(ic) else 0.0

    return df.groupby("date", group_keys=False)[[factor_col, fwd_col]].apply(calc)


def _make_df(n_stocks=20, n_days=80, seed=3):
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2020-01-02", periods=n_days)
    rows = []
    for i in range(n_stocks):
        close = 10 + rng.randn(n_days).cumsum() * 0.5
        factor = rng.randn(n_days)
        volume = rng.randint(10000, 100000, n_days).astype(float)
        for d, c, f, v in zip(dates, close, factor, volume):
            rows.append({"date": d, "code": f"600{i:03d}.SH", "close": c,
                         "factor_a": f, "volume": v})
    return pd.DataFrame(rows)


def test_compute_ic_ir_vectorized_equals_reference():
    df = _make_df()
    df["ret_1"] = df.groupby("code")["close"].shift(-1) / df["close"] - 1

    analyzer = FactorAnalyzer()
    icr = analyzer.compute_ic_ir(
        df, factor_cols=["factor_a"], holding_periods=[1],
        date_col="date", code_col="code", price_col="close",
        mode=AnalysisMode.BACKTEST,
    )

    ref = _ref_daily_ic(df, "ret_1", "factor_a").dropna()
    assert len(ref) == icr["factor_a"][1].n_periods
    assert np.isclose(icr["factor_a"][1].ic_mean, float(ref.mean()), rtol=1e-8)
    assert np.isclose(icr["factor_a"][1].ic_std, float(ref.std(ddof=0)), rtol=1e-8)
    assert np.isclose(icr["factor_a"][1].ic_positive_ratio,
                      float((ref > 0).mean()), rtol=1e-8)


def test_compute_ic_ir_vectorized_all_periods():
    df = _make_df()
    analyzer = FactorAnalyzer()
    icr = analyzer.compute_ic_ir(
        df, factor_cols=["factor_a"], holding_periods=[1, 5, 20],
        date_col="date", code_col="code", price_col="close",
        mode=AnalysisMode.BACKTEST,
    )
    assert set(icr["factor_a"].keys()) == {1, 5, 20}
    for r in icr["factor_a"].values():
        assert r.n_periods > 0
        assert np.isfinite(r.ic_mean)


def test_compute_ic_ir_handles_dates_with_few_stocks():
    """单只股票的日期不应导致 NaN 传播 (向量化必须逐日独立)。"""
    rng = np.random.RandomState(9)
    dates = pd.bdate_range("2020-01-02", periods=60)
    rows = []
    for i in range(8):
        for d in dates:
            rows.append({"date": d, "code": f"600{i:03d}.SH",
                         "close": 10 + rng.randn(), "factor_a": rng.randn(),
                         "volume": 10000.0})
    sub = pd.DataFrame(rows)
    # 前 5 天只保留 3 只股票 (valid<5 → 这些天应被排除但不污染其它天)
    first = sub["date"].unique()[:5]
    drop_codes = [c for i, c in enumerate(
        sorted(sub["code"].unique())) if i >= 3]
    mask = sub["date"].isin(first) & sub["code"].isin(drop_codes)
    sub = sub[~mask]
    analyzer = FactorAnalyzer()
    icr = analyzer.compute_ic_ir(
        sub, factor_cols=["factor_a"], holding_periods=[1],
        date_col="date", code_col="code", price_col="close",
        mode=AnalysisMode.BACKTEST,
    )
    # 有数据的日期仍应产出结果（不抛异常、不全是 NaN）
    assert icr["factor_a"][1].n_periods > 0
    assert np.isfinite(icr["factor_a"][1].ic_mean)