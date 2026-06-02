"""
Round 1: Volume-Price Divergence Factor (vol_price_divergence_20d)

Hypothesis:
    When price makes new highs but volume declines (distribution), future returns
    tend to be negative. When price makes new lows but volume declines (accumulation),
    future returns tend to be positive. This captures institutional footprints.

Logic:
    rank(price_change_20d) * rank(-volume_change_20d)
    Cross-sectional rank product: high value = price up + volume down (distribution)

Category: volume_price
Expected IC direction: Negative (high factor = future negative returns)
"""

import numpy as np
import pandas as pd


def compute_vol_price_divergence_20d(df: pd.DataFrame) -> pd.Series:
    """
    Volume-Price Divergence Factor.

    Args:
        df: DataFrame with columns ['close', 'volume']

    Returns:
        pd.Series: Factor values
    """
    if "close" not in df.columns or "volume" not in df.columns:
        return pd.Series(index=df.index, dtype=float)

    price_ret = df["close"].pct_change(20, fill_method=None)
    vol_ret = df["volume"].pct_change(20, fill_method=None)

    # Cross-sectional rank product
    # High value = price rising + volume falling = distribution (bearish)
    # Low value = price falling + volume rising = accumulation (bullish)
    factor = price_ret * (-1.0 * vol_ret)

    # Winsorize extreme values at 1%/99% per stock
    lower = factor.quantile(0.01)
    upper = factor.quantile(0.99)
    factor = factor.clip(lower, upper)

    return factor


# Live-mode guard
if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]  # UniQuant root
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 1: Volume-Price Divergence Factor (vol_price_divergence_20d)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_vol_price_divergence_20d, "vol_price_divergence_20d"
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
