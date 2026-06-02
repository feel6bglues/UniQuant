"""
Round 8: Volatility-Adjusted Momentum (vol_adj_momentum_20d)

Hypothesis:
    Raw momentum is noisy because stocks have different volatility levels.
    Normalizing returns by their rolling volatility makes the momentum signal
    comparable across stocks and reduces the impact of high-volatility outliers.
    This is essentially a 20-day Sharpe ratio.

Logic:
    daily_ret = close.pct_change()
    factor = mean(daily_ret, 20) / std(daily_ret, 20) * sqrt(252)
    This is the annualized Sharpe ratio over 20 days

Category: technical
Expected IC direction: Negative (reversal — high recent Sharpe predicts mean reversion)
"""

import numpy as np
import pandas as pd


def compute_vol_adj_momentum_20d(df: pd.DataFrame) -> pd.Series:
    """
    Volatility-Adjusted Momentum Factor (20-day rolling Sharpe).

    Args:
        df: DataFrame with columns ['close']

    Returns:
        pd.Series: Factor values (annualized Sharpe-like ratio)
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)

    daily_ret = df["close"].pct_change(fill_method=None)

    ret_mean = daily_ret.rolling(window=20, min_periods=10).mean()
    ret_std = daily_ret.rolling(window=20, min_periods=10).std()

    # Annualized Sharpe-like ratio
    factor = ret_mean / ret_std.replace(0, np.nan) * np.sqrt(252)

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 8: Volatility-Adjusted Momentum (vol_adj_momentum_20d)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_vol_adj_momentum_20d, "vol_adj_momentum_20d"
    )

    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)

    icir = result["icir"]
    ic_mean = result["ic_mean"]
    ic_pos = result["ic_positive_ratio"]
    best_p = result["best_period"]
    n = result["n_periods"]

    print(f"\nBest holding period: {best_p}d")
    print(f"IC Mean:   {ic_mean:.4f}")
    print(f"IC Std:    {result['ic_std']:.4f}")
    print(f"ICIR:      {icir:.4f}")
    print(f"IC>0:      {ic_pos:.2%}")
    print(f"t-stat:    {result['ic_t_stat']:.2f}")
    print(f"Periods:   {n}")

    print("\nAll periods:")
    for p, data in result.get("all_periods", {}).items():
        print(f"  {p}d: IC={data['ic_mean']:.4f}, ICIR={data['icir']:.4f}, IC>0={data['ic_positive_ratio']:.2%}")

    v = verdict(icir, ic_mean, ic_pos)
    print(f"\nVERDICT: {v}")
