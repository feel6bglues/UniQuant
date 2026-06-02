"""
Round 6: Rank-Normalized Volume-Weighted Momentum (rank_vol_momentum_20d)

Hypothesis:
    Volume-weighted momentum has moderate reversal power (ICIR=-0.29 in raw form).
    Cross-sectional rank normalization can improve signal-to-noise by removing
    outlier effects and making the factor comparable across different market cap segments.

Logic:
    1. Compute vol-weighted momentum per stock
    2. Cross-sectional rank normalization per date (percentile rank)
    3. This removes distribution skew and focuses on relative ordering

Category: volume_price
Expected IC direction: Negative (reversal)
"""

import numpy as np
import pandas as pd


def compute_rank_vol_momentum_20d(df: pd.DataFrame) -> pd.Series:
    """
    Rank-Normalized Volume-Weighted Momentum Factor.

    Args:
        df: DataFrame with columns ['close', 'volume']

    Returns:
        pd.Series: Factor values (rank-normalized per date)
    """
    if "close" not in df.columns or "volume" not in df.columns:
        return pd.Series(index=df.index, dtype=float)

    daily_ret = df["close"].pct_change(fill_method=None)
    vol_ma60 = df["volume"].rolling(window=60, min_periods=30).mean()
    vol_ratio = df["volume"] / vol_ma60.replace(0, np.nan)

    weighted_ret = daily_ret * vol_ratio
    factor = weighted_ret.rolling(window=20, min_periods=10).sum()

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, verdict

    print("=" * 60)
    print("ROUND 6: Rank-Normalized Volume-Weighted Momentum")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)

    # Cross-sectional rank normalization per date
    factor_list = []
    for code, group in df.groupby("code"):
        group = group.sort_values("date").copy()
        group["rank_vol_momentum_20d"] = compute_rank_vol_momentum_20d(group)
        factor_list.append(group)

    df2 = pd.concat(factor_list, ignore_index=True)
    df2 = df2.dropna(subset=["rank_vol_momentum_20d"])

    # Cross-sectional rank normalization per date
    df2["rank_vol_momentum_20d"] = df2.groupby("date")["rank_vol_momentum_20d"].rank(pct=True)

    from uniquant.brain.factors.analyzer import FactorAnalyzer

    analyzer = FactorAnalyzer()
    results = analyzer.compute_ic_ir(
        df=df2,
        factor_cols=["rank_vol_momentum_20d"],
        holding_periods=[1, 5, 20],
        date_col="date",
        code_col="code",
        price_col="close",
    )

    best_period = None
    best_score = -1.0
    best_result = None
    for factor_col, period_results in results.items():
        for period, result in period_results.items():
            if result is not None and abs(result.icir) > best_score:
                best_score = abs(result.icir)
                best_period = period
                best_result = result

    if best_result is None:
        print("ERROR: No results")
        sys.exit(1)

    icir = best_result.icir
    ic_mean = best_result.ic_mean
    ic_pos = best_result.ic_positive_ratio

    print(f"\nBest holding period: {best_period}d")
    print(f"IC Mean:   {ic_mean:.4f}")
    print(f"IC Std:    {best_result.ic_std:.4f}")
    print(f"ICIR:      {icir:.4f}")
    print(f"IC>0:      {ic_pos:.2%}")
    print(f"t-stat:    {best_result.ic_t_stat:.2f}")
    print(f"Periods:   {best_result.n_periods}")

    print("\nAll periods:")
    for p, r in period_results.items():
        print(f"  {p}d: IC={r.ic_mean:.4f}, ICIR={r.icir:.4f}, IC>0={r.ic_positive_ratio:.2%}")

    v = verdict(icir, ic_mean, ic_pos)
    print(f"\nVERDICT: {v}")
