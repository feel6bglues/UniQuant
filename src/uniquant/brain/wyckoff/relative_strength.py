"""RS-C1: 相对强弱 (Relative Strength) 四分类模块。

研究平台定位: 分类结果作为 WyckoffReport 的增量研究标记，
不改变信号方向，不参与交易决策。

四分类 (对齐 CLASSIC_WYCKOFF_TDD_STANDARD_VERIFICATION_v1.md RS-C1 规格):
- leader:             个股 > 指数 (excess > 0) 且缩量 (vol_ratio < 1) → 强势独立
- follower:           个股 > 指数 (excess > 0) 但放量跟随 (vol_ratio >= 1)
- weak_independent:   指数 > 0 且 个股 < 0 → 逆势走弱
- systemic_decline:   指数 < 0 且 个股 < 0 且无超额 → 同步下跌
- unknown:            数据不足 (窗口不足) 无法分类
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

RS_LOOKBACK_DEFAULT = 20
# excess 收益阈值: |excess| 低于此值视为无显著超额
RS_EXCESS_THRESHOLD = 0.0
# 量比阈值: <1 缩量 (强势独立), >=1 放量 (跟随)
RS_VOL_RATIO_THRESHOLD = 1.0


@dataclass
class RelativeStrengthResult:
    """相对强弱分类结果 (研究标记，不参与交易决策)。"""

    classification: str = "unknown"
    stock_return_20d: float = 0.0
    index_return_20d: float = 0.0
    excess_return: float = 0.0
    stock_vol_ratio: float = 1.0
    sufficient_data: bool = True


def _align_on_date(
    stock_ts: pd.DataFrame, index_ts: pd.DataFrame
) -> Optional[tuple[pd.DataFrame, pd.DataFrame]]:
    """按 date 对齐两时间轴 (inner join)，返回对齐后的 (stock, index)。

    要求两表均含 date 列。日期类型先统一为 datetime64 再合并。
    """
    if stock_ts is None or index_ts is None:
        return None
    if "date" not in stock_ts.columns or "date" not in index_ts.columns:
        return None

    s = stock_ts.copy()
    i = index_ts.copy()
    s["date"] = pd.to_datetime(s["date"])
    i["date"] = pd.to_datetime(i["date"])
    s = s.drop_duplicates(subset=["date"]).set_index("date").sort_index()
    i = i.drop_duplicates(subset=["date"]).set_index("date").sort_index()

    common = s.index.intersection(i.index)
    if len(common) < 2:
        return None
    return s.loc[common], i.loc[common]


def _period_return(series: pd.Series, lookback: int) -> float:
    """取最近 lookback 根的区间收益; 数据不足返回 0.0。"""
    closes = series.astype(float).dropna()
    if len(closes) < 2:
        return 0.0
    window = closes.tail(lookback)
    if len(window) < 2:
        return 0.0
    base = float(window.iloc[0])
    if base <= 0:
        return 0.0
    return float(window.iloc[-1]) / base - 1.0


def rs_classify(
    stock_ts: pd.DataFrame,
    index_ts: pd.DataFrame,
    lookback: int = RS_LOOKBACK_DEFAULT,
) -> RelativeStrengthResult:
    """对齐两时间轴，计算同期收益与量能，输出相对强弱四分类。"""
    aligned = _align_on_date(stock_ts, index_ts)
    if aligned is None:
        return RelativeStrengthResult(
            classification="unknown", sufficient_data=False
        )
    stock_al, index_al = aligned

    if len(stock_al) < 2:
        return RelativeStrengthResult(
            classification="unknown", sufficient_data=False
        )

    stock_ret = _period_return(stock_al["close"], lookback)
    index_ret = _period_return(index_al["close"], lookback)
    excess = stock_ret - index_ret

    vol_ratio = 1.0
    if "volume" in stock_al.columns:
        vol = stock_al["volume"].astype(float).dropna()
        if len(vol) >= 5:
            window_vol = vol.tail(lookback)
            base_vol = float(window_vol.head(max(1, len(window_vol) // 2)).mean())
            latest_vol = float(window_vol.tail(1).iloc[0])
            if base_vol > 0:
                vol_ratio = latest_vol / base_vol

    if stock_ret >= 0 and index_ret >= 0:
        classification = "leader" if (excess > RS_EXCESS_THRESHOLD and vol_ratio < RS_VOL_RATIO_THRESHOLD) else "follower"
    elif stock_ret < 0 and index_ret >= 0:
        classification = "weak_independent"
    elif stock_ret < 0 and index_ret < 0:
        classification = "systemic_decline"
    elif stock_ret >= 0 and index_ret < 0:
        classification = "leader" if vol_ratio < RS_VOL_RATIO_THRESHOLD else "follower"
    else:
        classification = "unknown"

    return RelativeStrengthResult(
        classification=classification,
        stock_return_20d=round(stock_ret, 6),
        index_return_20d=round(index_ret, 6),
        excess_return=round(excess, 6),
        stock_vol_ratio=round(vol_ratio, 6),
        sufficient_data=True,
    )
