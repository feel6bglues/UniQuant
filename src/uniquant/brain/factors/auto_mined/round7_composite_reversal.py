"""
Round 7: Composite Reversal Factor (composite_reversal_20d)

Hypothesis:
    Combining volume-weighted momentum (ICIR=-0.29) and smart money flow (ICIR=-0.26)
    may produce a stronger signal through diversification of noise. The two factors
    capture different aspects of the same reversal phenomenon.

Logic:
    1. vol_weighted_momentum: sum(return * vol_ratio) over 20d
    2. smart_money_flow: sum(intraday_ret * vol_weight) over 20d
    3. Composite: z-score(vol_momentum) + z-score(smart_money) / 2
    Cross-sectional z-score normalization per date

Category: composite
Expected IC direction: Negative (reversal)
"""

import numpy as np
import pandas as pd


def compute_composite_reversal_20d(df: pd.DataFrame) -> pd.Series:
    """
    Composite Reversal Factor.

    Args:
        df: DataFrame with columns ['close', 'open', 'volume']

    Returns:
        pd.Series: Factor values
    """
    required = {"close", "volume"}
    if not required.issubset(df.columns):
        return pd.Series(index=df.index, dtype=float)

    # Component 1: Volume-weighted momentum
    daily_ret = df["close"].pct_change(fill_method=None)
    vol_ma60 = df["volume"].rolling(window=60, min_periods=30).mean()
    vol_ratio = df["volume"] / vol_ma60.replace(0, np.nan)
    vol_momentum = (daily_ret * vol_ratio).rolling(window=20, min_periods=10).sum()

    # Component 2: Smart money flow (requires open)
    if "open" in df.columns:
        intraday_ret = (df["close"] - df["open"]) / df["open"].replace(0, np.nan)
        vol_ma20 = df["volume"].rolling(window=20, min_periods=10).mean()
        vol_weight = df["volume"] / vol_ma20.replace(0, np.nan)
        smart_flow = (intraday_ret * vol_weight).rolling(window=20, min_periods=10).sum()
    else:
        smart_flow = vol_momentum * 0  # fallback

    # Composite: equal-weighted (no z-score here, do it cross-sectionally in harness)
    factor = (vol_momentum + smart_flow) / 2.0

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 7: Composite Reversal Factor (composite_reversal_20d)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_composite_reversal_20d, "composite_reversal_20d"
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
