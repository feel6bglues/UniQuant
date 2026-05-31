import numpy as np
import pandas as pd


def calc_atr(s: pd.DataFrame, p: int = 20) -> float:
    if len(s) < p + 1:
        return 0.0
    hi = s["high"].values[-p - 1:]
    lo = s["low"].values[-p - 1:]
    cl = s["close"].values[-p - 1:]
    tr = np.maximum(hi[1:] - lo[1:],
                    np.maximum(np.abs(hi[1:] - cl[:-1]),
                               np.abs(lo[1:] - cl[:-1])))
    return float(np.mean(tr))
