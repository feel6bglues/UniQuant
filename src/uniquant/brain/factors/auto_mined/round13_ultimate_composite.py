"""
Round 13: Ultimate Composite Reversal (ultimate_composite_60d)

Hypothesis:
    Combining all moderate reversal signals with ICIR-weighted averaging should
    produce a stronger composite. Uses the best 3 components:
    - Volume-weighted momentum (ICIR=-0.29)
    - Smart money flow (ICIR=-0.26)
    - Composite reversal (ICIR=-0.30)

    Weighted by |ICIR|: 0.29/0.85, 0.26/0.85, 0.30/0.85

Logic:
    60-day lookback for all components (longer = more stable)
    ICIR-weighted average of z-scored components per stock

Category: composite
Expected IC direction: Negative (reversal)
"""

import numpy as np
import pandas as pd


def compute_ultimate_composite_60d(df: pd.DataFrame) -> pd.Series:
    """
    Ultimate Composite Reversal Factor (60-day).

    Args:
        df: DataFrame with columns ['close', 'open', 'volume']

    Returns:
        pd.Series: Factor values
    """
    required = {"close", "volume"}
    if not required.issubset(df.columns):
        return pd.Series(index=df.index, dtype=float)

    # Component 1: Volume-weighted momentum (60d)
    daily_ret = df["close"].pct_change(fill_method=None)
    vol_ma120 = df["volume"].rolling(window=120, min_periods=60).mean()
    vol_ratio = df["volume"] / vol_ma120.replace(0, np.nan)
    c1 = (daily_ret * vol_ratio).rolling(window=60, min_periods=30).sum()

    # Component 2: Smart money flow (60d)
    if "open" in df.columns:
        intraday_ret = (df["close"] - df["open"]) / df["open"].replace(0, np.nan)
        vol_ma60 = df["volume"].rolling(window=60, min_periods=30).mean()
        vol_weight = df["volume"] / vol_ma60.replace(0, np.nan)
        c2 = (intraday_ret * vol_weight).rolling(window=60, min_periods=30).sum()
    else:
        c2 = c1 * 0

    # Component 3: Raw momentum reversal (60d)
    c3 = df["close"].pct_change(60, fill_method=None)

    # Normalize each component to z-score per stock (time-series)
    def zscore(s, window=60):
        m = s.rolling(window, min_periods=30).mean()
        s_std = s.rolling(window, min_periods=30).std()
        return (s - m) / s_std.replace(0, np.nan)

    z1 = zscore(c1)
    z2 = zscore(c2)
    z3 = zscore(c3)

    # ICIR-weighted average (weights proportional to |ICIR|)
    w1, w2, w3 = 0.29, 0.26, 0.30
    w_total = w1 + w2 + w3
    factor = (w1 * z1 + w2 * z2 + w3 * z3) / w_total

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 13: Ultimate Composite Reversal (ultimate_composite_60d)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_ultimate_composite_60d, "ultimate_composite_60d"
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
