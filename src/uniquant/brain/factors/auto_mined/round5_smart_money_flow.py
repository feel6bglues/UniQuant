"""
Round 5: Smart Money Flow Factor (smart_money_flow_20d)

Hypothesis:
    Intraday returns (close vs open) on high-volume days carry more information
    than overnight returns (open vs prev close). Smart money acts during trading
    hours; retail reacts overnight. This factor isolates the "smart money" component.

Logic:
    intraday_ret = (close - open) / open
    vol_weight = volume / volume_ma_20
    factor = sum(intraday_ret * vol_weight) over 20 days

Category: volume_price
Expected IC direction: Negative (high smart money flow predicts reversal)
"""

import numpy as np
import pandas as pd


def compute_smart_money_flow_20d(df: pd.DataFrame) -> pd.Series:
    """
    Smart Money Flow Factor.

    Args:
        df: DataFrame with columns ['close', 'open', 'volume']

    Returns:
        pd.Series: Factor values
    """
    required = {"close", "open", "volume"}
    if not required.issubset(df.columns):
        return pd.Series(index=df.index, dtype=float)

    # Intraday return (close vs open)
    intraday_ret = (df["close"] - df["open"]) / df["open"].replace(0, np.nan)

    # Volume weight: relative to 20-day average
    vol_ma20 = df["volume"].rolling(window=20, min_periods=10).mean()
    vol_weight = df["volume"] / vol_ma20.replace(0, np.nan)

    # Smart money flow: intraday return weighted by volume
    smart_flow = intraday_ret * vol_weight

    # Sum over 20 days
    factor = smart_flow.rolling(window=20, min_periods=10).sum()

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 5: Smart Money Flow Factor (smart_money_flow_20d)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_smart_money_flow_20d, "smart_money_flow_20d"
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
