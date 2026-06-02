"""
Round 12: Turnover-Adjusted Reversal (turnover_adj_reversal_60d)

Hypothesis:
    In A-share markets, high-turnover stocks experience stronger reversal because
    retail-dominated trading creates overreaction. Adjusting momentum by turnover
    amplifies the reversal signal for liquid, retail-heavy stocks.

Logic:
    1. 60-day momentum (longer horizon captures more persistent reversal)
    2. 60-day average turnover rate
    3. factor = -momentum * turnover (negative because we expect reversal)
    High positive = high momentum + high turnover = strongest reversal candidate

Category: volume_price
Expected IC direction: Positive (high factor = strong reversal = positive future returns)
"""

import numpy as np
import pandas as pd


def compute_turnover_adj_reversal_60d(df: pd.DataFrame) -> pd.Series:
    """
    Turnover-Adjusted Reversal Factor.

    Args:
        df: DataFrame with columns ['close', 'volume']

    Returns:
        pd.Series: Factor values
    """
    if "close" not in df.columns or "volume" not in df.columns:
        return pd.Series(index=df.index, dtype=float)

    # 60-day momentum
    momentum_60d = df["close"].pct_change(60, fill_method=None)

    # Turnover proxy: volume / 250-day average volume
    vol_ma250 = df["volume"].rolling(window=250, min_periods=60).mean()
    turnover = df["volume"] / vol_ma250.replace(0, np.nan)
    turnover_60d = turnover.rolling(window=60, min_periods=30).mean()

    # Negative momentum * turnover = reversal signal
    # Stocks that went up a lot AND have high turnover = most overbought
    factor = (-momentum_60d) * turnover_60d

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 12: Turnover-Adjusted Reversal (turnover_adj_reversal_60d)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_turnover_adj_reversal_60d, "turnover_adj_reversal_60d"
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
