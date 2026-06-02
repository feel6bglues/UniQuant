"""
Round 4: Range Compression Breakout Factor (range_compression_breakout)

Hypothesis:
    Stocks with contracting trading ranges (decreasing ATR) followed by expansion
    tend to continue in the breakout direction. This captures the "coiling spring"
    effect seen in A-share markets.

Logic:
    atr_ratio = atr_5 / atr_20  (low = compressed)
    direction = sign(close - ma_20)  (+1 = above MA, -1 = below)
    factor = direction * (1 - atr_ratio)
    High positive = bullish compression (price above MA, range narrowing)

Category: technical
Expected IC direction: Positive (compression breakouts tend to continue)
"""

import numpy as np
import pandas as pd


def compute_range_compression_breakout(df: pd.DataFrame) -> pd.Series:
    """
    Range Compression Breakout Factor.

    Args:
        df: DataFrame with columns ['close', 'high', 'low']

    Returns:
        pd.Series: Factor values
    """
    required = {"close", "high", "low"}
    if not required.issubset(df.columns):
        return pd.Series(index=df.index, dtype=float)

    # True Range
    tr = pd.DataFrame(
        {
            "hl": df["high"] - df["low"],
            "hc": (df["high"] - df["close"].shift(1)).abs(),
            "lc": (df["low"] - df["close"].shift(1)).abs(),
        }
    ).max(axis=1)

    atr_5 = tr.rolling(window=5, min_periods=3).mean()
    atr_20 = tr.rolling(window=20, min_periods=10).mean()

    # Compression ratio (low = compressed)
    atr_ratio = atr_5 / atr_20.replace(0, np.nan)

    # Direction: +1 if above 20-day MA, -1 if below
    ma_20 = df["close"].rolling(window=20, min_periods=10).mean()
    direction = np.sign(df["close"] - ma_20)

    # Factor: direction * compression magnitude
    factor = direction * (1 - atr_ratio)

    return factor


if __name__ == "__main__":
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(project_root / "src"))
    sys.path.insert(0, str(project_root))

    from mining_harness import load_universe, run_factor_ic_analysis, verdict

    print("=" * 60)
    print("ROUND 4: Range Compression Breakout Factor (range_compression_breakout)")
    print("=" * 60)

    df = load_universe(max_stocks=50, min_rows=500)
    result = run_factor_ic_analysis(
        df, compute_range_compression_breakout, "range_compression_breakout"
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
