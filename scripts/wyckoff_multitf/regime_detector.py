"""Market regime detector (bull/bear/neutral) using CSI 300 index.

Reuses existing CSI 300 parquet data at data/lake/quotes/daily/000300.SH.parquet
or data/csi300_index.parquet.

Usage:
    detector = MarketRegimeDetector()
    df = detector.load_index_data()
    regime = detector.classify('2023-06-01')  # 'bull', 'bear', 'neutral'
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDEX_PATHS = [
    PROJECT_ROOT / "data" / "lake" / "quotes" / "daily" / "000300.SH.parquet",
    PROJECT_ROOT / "data" / "csi300_index.parquet",
    PROJECT_ROOT / "data" / "lake" / "index" / "sh000300.parquet",
]


class MarketRegimeDetector:
    """Classify A-share market regime as bull/bear/neutral using CSI 300.

    Uses 5-month MA50/MA200 crossover logic + trailing 3-month return to
    distinguish bull (trending up) from bear (trending down).
    """

    def __init__(self, df: Optional[pd.DataFrame] = None):
        self._df: Optional[pd.DataFrame] = None
        self._ma50: Optional[np.ndarray] = None
        self._ma200: Optional[np.ndarray] = None
        if df is not None:
            self.fit(df)

    def load_index_data(self) -> pd.DataFrame:
        for p in INDEX_PATHS:
            if p.exists():
                df = pd.read_parquet(p)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                self.fit(df)
                return df
        raise FileNotFoundError(
            f"CSI 300 index not found at any of: {INDEX_PATHS}"
        )

    def fit(self, df: pd.DataFrame) -> None:
        close = df['close'].values.astype(np.float64)
        self._df = df
        self._ma50 = pd.Series(close).rolling(50).mean().values
        self._ma200 = pd.Series(close).rolling(200).mean().values

    def classify(self, date: str) -> str:
        if self._df is None:
            raise ValueError("Call load_index_data() or fit() first")
        dates = self._df['date'].values
        idx = int(np.searchsorted(dates, np.datetime64(date), side='right')) - 1
        if idx < 0:
            idx = 0
        if idx >= len(self._ma50) or np.isnan(self._ma50[idx]):
            return 'neutral'

        ma50 = float(self._ma50[idx])
        ma200 = float(self._ma200[idx])
        close = float(self._df['close'].values[idx])

        # Trailing 90-day return
        idx_90 = max(0, idx - 60)
        ret_90d = (close / float(self._df['close'].values[idx_90]) - 1) * 100

        ma_bull = ma50 > ma200 * 1.02
        ma_bear = ma50 < ma200 * 0.98

        if ma_bull and ret_90d > -5:
            return 'bull'
        if ma_bear and ret_90d < 5:
            return 'bear'
        return 'neutral'

    def regime_series(self, dates: list[str]) -> list[str]:
        return [self.classify(d) for d in dates]


def load_dates_from_results(results_path: str) -> list[str]:
    """Extract all unique cutoff dates from runner_v4 output."""
    import json
    with open(results_path) as f:
        data = json.load(f)
    dates = sorted(set(o['c'] for o in data['data']))
    return dates
