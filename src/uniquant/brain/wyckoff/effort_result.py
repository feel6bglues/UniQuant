"""P1-B: VDB 量价背离 (Volume Divergence) 检测模块。

研究平台定位: 检测结果作为 Step2Result 的增量研究标记(vdb_divergence)，
不改变现有 evidence 累加逻辑，不参与交易决策。

检测逻辑:
- bullish_divergence:  价跌量缩(price_change < -0.03, volume_trend < 0.8) → 供给枯竭吸筹背离
- bearish_divergence: 价升量缩(price_change > 0.03, volume_trend < 0.8) → 需求不足派发背离
- none:               不满足上述条件
"""

from __future__ import annotations

import pandas as pd


def detect_effort_result_divergence(
    df: pd.DataFrame, lookback: int = 30
) -> str:
    """检测量价背离 (VDB)。

    Args:
        df: OHLCV DataFrame, 需含 close 和 volume 列。
        lookback: 分析窗口大小(默认 30)。

    Returns:
        "bullish_divergence" | "bearish_divergence" | "none"
    """
    if len(df) < lookback:
        return "none"

    window = df.tail(lookback)

    price_change = (
        window["close"].iloc[-1] - window["close"].iloc[0]
    ) / window["close"].iloc[0]

    vol_ma10 = window["volume"].tail(10).mean()
    vol_ma20 = window["volume"].head(20).mean()

    volume_trend = vol_ma10 / vol_ma20 if vol_ma20 > 0 else 1.0

    if price_change < -0.03 and volume_trend < 0.8:
        return "bullish_divergence"

    if price_change > 0.03 and volume_trend < 0.8:
        return "bearish_divergence"

    return "none"