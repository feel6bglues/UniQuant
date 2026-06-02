"""
Round 2: Intraday Intensity Factor (intraday_intensity_20d)

Hypothesis:
    The position of the close within the day's range indicates buying/selling pressure.
    A close near the high with high volume suggests institutional buying.
    Averaged over 20 days, this captures persistent directional pressure.

Logic:
    ((close - low) / (high - low) * 2 - 1).rolling(20).mean()
    Normalized to [-1, 1]: +1 = always closing at high, -1 = always at low

Category: volume_price
Expected IC direction: Positive (high factor = future positive returns)
"""

import numpy as np
import pandas as pd


def compute_intraday_intensity_20d(df: pd.DataFrame) -> pd.Series:
    """
    Intraday Intensity Factor (20-day average).

    Args:
        df: DataFrame with columns ['close', 'high', 'low']

    Returns:
        pd.Series: Factor values in [-1, 1]
    """
    required = {"close", "high", "low"}
    if not required.issubset(df.columns):
        return pd.Series(index=df.index, dtype=float)

    day_range = (df["high"] - df["low"]).replace(0, np.nan)
    # Normalize to [-1, 1]: close at high = +1, close at low = -1
    intraday_pos = (df["close"] - df["low"]) / day_range * 2 - 1

    # 20-day rolling mean
    factor = intraday_pos.rolling(window=20, min_periods=10).mean()

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 2: Intraday Intensity Factor (intraday_intensity_20d)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_intraday_intensity_20d, "intraday_intensity_20d"
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
