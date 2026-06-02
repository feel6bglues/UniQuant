"""
Round 3: Volume-Weighted Momentum Factor (vol_weighted_momentum_20d)

Hypothesis:
    Momentum signals are more reliable when accompanied by volume confirmation.
    High-volume price moves carry more information than low-volume noise.
    This factor weights daily returns by relative volume intensity.

Logic:
    sum(daily_return * (volume / volume_ma_60)) over 20 days
    Volume ratio > 1 amplifies the return, < 1 dampens it

Category: volume_price
Expected IC direction: Negative (reversal effect — high recent momentum predicts reversal)
"""

import numpy as np
import pandas as pd


def compute_vol_weighted_momentum_20d(df: pd.DataFrame) -> pd.Series:
    """
    Volume-Weighted Momentum Factor.

    Args:
        df: DataFrame with columns ['close', 'volume']

    Returns:
        pd.Series: Factor values
    """
    if "close" not in df.columns or "volume" not in df.columns:
        return pd.Series(index=df.index, dtype=float)

    daily_ret = df["close"].pct_change(fill_method=None)
    vol_ma60 = df["volume"].rolling(window=60, min_periods=30).mean()
    vol_ratio = df["volume"] / vol_ma60.replace(0, np.nan)

    # Weight returns by volume intensity
    weighted_ret = daily_ret * vol_ratio

    # Sum over 20 days
    factor = weighted_ret.rolling(window=20, min_periods=10).sum()

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 3: Volume-Weighted Momentum Factor (vol_weighted_momentum_20d)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_vol_weighted_momentum_20d, "vol_weighted_momentum_20d"
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

    print(f"\nAll periods:")
    for p, data in result.get("all_periods", {}).items():
        print(f"  {p}d: IC={data['ic_mean']:.4f}, ICIR={data['icir']:.4f}, IC>0={data['ic_positive_ratio']:.2%}")

    v = verdict(icir, ic_mean, ic_pos)
    print(f"\nVERDICT: {v}")
