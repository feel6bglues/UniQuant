from typing import Optional
import pandas as pd
import numpy as np

_CACHE: Optional[pd.DataFrame] = None

def get_industry_dummies() -> pd.DataFrame:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    import akshare as ak
    df = ak.stock_board_industry_name_em()
    dummies = pd.get_dummies(df.set_index("symbol")["board_name"])
    _CACHE = dummies
    return dummies


def get_log_market_cap(symbols, price_df: pd.DataFrame, shares_outstanding: pd.Series) -> pd.Series:
    cap = price_df["close"] * shares_outstanding
    return np.log(cap.replace(0, np.nan))
