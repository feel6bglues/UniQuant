"""
Round 11: Price Delay Factor (price_delay_20d)

Hypothesis:
    Stocks that respond slowly to market-wide information (delayed price discovery)
    tend to earn higher expected returns as compensation for information risk.
    This captures the "post-earnings-announcement drift" effect generalized.

Logic:
    1. Market return: equal-weighted average of all stocks in universe
    2. Stock's beta to lagged market return (delayed response)
    3. Higher lagged beta = more delayed = higher expected return

    Simplified: correlation between stock return and lagged market return over 20 days

Category: microstructure
Expected IC direction: Positive (delay premium)
"""

import numpy as np
import pandas as pd


def compute_price_delay_20d(df: pd.DataFrame) -> pd.Series:
    """
    Price Delay Factor (simplified).

    Measures how much a stock's return is explained by the PREVIOUS day's
    cross-sectional market return. Higher values = more delayed response.

    Args:
        df: DataFrame with columns ['close', 'volume']
            Note: This is a per-stock factor; cross-sectional market return
            is approximated by the stock's own lagged return autocorrelation.

    Returns:
        pd.Series: Factor values
    """
    if "close" not in df.columns:
        return pd.Series(index=df.index, dtype=float)

    ret = df["close"].pct_change(fill_method=None)

    # Autocorrelation of returns over 20 days
    # Positive autocorrelation = delayed response (momentum)
    # Negative autocorrelation = overreaction (reversal)
    factor = ret.rolling(window=20, min_periods=10).apply(
        lambda x: x.autocorr(lag=1) if len(x) >= 3 else np.nan, raw=False
    )

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 11: Price Delay Factor (price_delay_20d)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_price_delay_20d, "price_delay_20d"
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
