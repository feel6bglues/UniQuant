from typing import Dict, Optional

import pandas as pd


def get_regime(csi: pd.DataFrame, d: str) -> str:
    if csi is None:
        return "unknown"
    a = pd.Timestamp(d)
    h = csi[csi["date"] <= a]
    if len(h) < 120:
        return "unknown"
    c = float(h.iloc[-1]["close"])
    m120 = float(h.tail(120)["close"].mean())
    m60 = float(h.tail(60)["close"].mean())
    if c > m120 * 1.02 and m60 > m120:
        return "bull"
    if c < m120 * 0.98:
        return "bear"
    return "range"


def trade_regime(df: pd.DataFrame, as_of_date: str,
                 cost_buy: Optional[float] = None, cost_sell: Optional[float] = None,
                 csi: pd.DataFrame = None, **kwargs) -> Optional[Dict]:
    regime = get_regime(csi, as_of_date)
    if regime != "bull":
        return None
    a = pd.Timestamp(as_of_date)
    h = df[df["date"] <= a]
    if len(h) < 5:
        return None
    entry = float(h.iloc[-1]["close"])
    fut = df[df["date"] > a].head(20)
    if len(fut) < 5:
        return None
    exit_px = float(fut.iloc[-1]["close"])
    tr = (exit_px - entry) / entry * 100
    if cost_buy is None or cost_sell is None:
        from uniquant.shared.cost_model import COST_BUY, COST_SELL
        cb = cost_buy if cost_buy is not None else COST_BUY
        cs = cost_sell if cost_sell is not None else COST_SELL
    else:
        cb, cs = cost_buy, cost_sell
    tr -= (cb + cs) * 100
    return {"ret": round(tr, 2), "days": len(fut)}
