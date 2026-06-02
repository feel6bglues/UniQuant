"""
Round 10: Abnormal Volume Factor (abnormal_volume_20d)

Hypothesis:
    Unusual volume spikes signal information events (earnings, news, institutional
    activity). Stocks with sustained abnormal volume tend to experience price
    continuation or reversal depending on the price action accompanying the volume.

Logic:
    vol_ratio = volume / volume_ma_60
    abnormal_vol = std(vol_ratio, 20) — measures dispersion of volume shocks
    Combined with price direction for directional signal

Category: volume_price
Expected IC direction: Negative (abnormal volume + up = distribution, predicts reversal)
"""

import numpy as np
import pandas as pd


def compute_abnormal_volume_20d(df: pd.DataFrame) -> pd.Series:
    """
    Abnormal Volume Factor.

    Args:
        df: DataFrame with columns ['close', 'volume']

    Returns:
        pd.Series: Factor values
    """
    if "close" not in df.columns or "volume" not in df.columns:
        return pd.Series(index=df.index, dtype=float)

    # Volume relative to 60-day average
    vol_ma60 = df["volume"].rolling(window=60, min_periods=30).mean()
    vol_ratio = df["volume"] / vol_ma60.replace(0, np.nan)

    # Abnormal volume: rolling std of volume ratio (measures volume shock frequency)
    vol_std = vol_ratio.rolling(window=20, min_periods=10).std()

    # Price direction: cumulative return over same period
    price_ret = df["close"].pct_change(20, fill_method=None)

    # Factor: abnormal volume * price direction
    # High positive = abnormal volume on up-moves (distribution signal)
    factor = vol_std * np.sign(price_ret)

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 10: Abnormal Volume Factor (abnormal_volume_20d)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_abnormal_volume_20d, "abnormal_volume_20d"
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
