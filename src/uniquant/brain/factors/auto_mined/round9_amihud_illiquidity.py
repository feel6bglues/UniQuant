"""
Round 9: Amihud Illiquidity Factor (amihud_illiquidity_20d)

Hypothesis:
    Illiquid stocks earn a premium (Amihud, 2002). Stocks with high price impact
    per unit of volume tend to have higher expected returns. This is one of the
    most robust cross-sectional factors in academic finance.

Logic:
    amihud = mean(|daily_return| / daily_dollar_volume) over 20 days
    High value = illiquid (large price moves per dollar traded)

Category: liquidity
Expected IC direction: Positive (illiquidity premium)
"""

import numpy as np
import pandas as pd


def compute_amihud_illiquidity_20d(df: pd.DataFrame) -> pd.Series:
    """
    Amihud Illiquidity Factor (20-day average).

    Args:
        df: DataFrame with columns ['close', 'volume', 'amount']
            If 'amount' is missing, approximates with close * volume

    Returns:
        pd.Series: Factor values (higher = more illiquid)
    """
    if "close" not in df.columns or "volume" not in df.columns:
        return pd.Series(index=df.index, dtype=float)

    daily_ret = df["close"].pct_change(fill_method=None).abs()

    # Dollar volume
    if "amount" in df.columns:
        dollar_vol = df["amount"].abs()
    else:
        dollar_vol = (df["close"] * df["volume"]).abs()

    # Price impact per dollar traded
    price_impact = daily_ret / dollar_vol.replace(0, np.nan)

    # 20-day average
    factor = price_impact.rolling(window=20, min_periods=10).mean()

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 9: Amihud Illiquidity Factor (amihud_illiquidity_20d)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_amihud_illiquidity_20d, "amihud_illiquidity_20d"
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
