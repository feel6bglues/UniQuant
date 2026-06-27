"""A-share market constraint wrappers for Wyckoff research pipeline.

Reuses existing production code from src/uniquant/:
- shared/limit_checker.py: limit up/down detection
- shared/market_rules.py: lot size, board detection
- risk/sizer.py: stop-loss logic

Usage:
    constraints = AShareConstraints()
    is_tradeable = constraints.can_trade("000001.SZ", "2024-01-15", daily_df)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _get_limit_pct(symbol: str) -> float:
    """Determine price limit percentage based on stock exchange and board.

    Rules:
    - Shanghai: 688xxx = 20% (STAR), others = 10%
    - Shenzhen: 300xxx = 20% (ChiNext), 00xxxx = 10%
    - Beijing (8xxxxx): 30%
    - ST stocks (*ST, ST): 5% (override board rule)
    """
    is_st = any(kw in symbol.upper() for kw in ['ST', '*ST', 'ＳＴ', '＊ＳＴ'])
    if is_st:
        return 0.05

    code = symbol.split('.')[0]

    if symbol.upper().endswith('.SH'):
        if code.startswith('688'):
            return 0.20
        return 0.10

    if symbol.upper().endswith('.SZ'):
        if code.startswith('300'):
            return 0.20
        return 0.10

    if symbol.upper().endswith('.BJ'):
        return 0.30

    if code.startswith('8'):
        return 0.30

    if len(code) >= 6 and code.startswith('688'):
        return 0.20

    if len(code) >= 6 and code.startswith('300'):
        return 0.20

    return 0.10


class AShareConstraints:
    """Gate wrapper for A-share trading constraints in research pipeline.

    Each method returns (passes: bool, reason: str).
    """

    @staticmethod
    def can_trade(symbol: str, date: str, daily: pd.DataFrame) -> tuple[bool, str]:
        """Check if a stock can be traded on a given date.

        Rejects if: suspended (volume=0), limit-up (can't buy), limit-down (can't sell).
        """
        try:
            row = daily[daily['date'] <= pd.Timestamp(date)].iloc[-1]
        except (IndexError, KeyError):
            return False, "no_data"

        if row['volume'] == 0 or row['close'] == 0:
            return False, "suspended"

        limit_pct = _get_limit_pct(symbol)
        limit_up = row['close'] >= row['close'] * (1 + limit_pct * 0.97) if row['close'] > 0 else False
        limit_down = row['close'] <= row['close'] * (1 - limit_pct * 0.97) if row['close'] > 0 else False

        # Simplified limit check using last close
        prev_rows = daily[daily['date'] < pd.Timestamp(date)]
        if len(prev_rows) > 0:
            prev_close = prev_rows['close'].iloc[-1]
            if prev_close > 0:
                pct = (row['close'] / prev_close - 1) * 100
                threshold = limit_pct * 100 * 0.94
                if pct > threshold:
                    return False, "limit_up"
                if pct < -threshold:
                    return False, "limit_down"

        return True, "ok"

    @staticmethod
    def get_limit_pct(symbol: str) -> float:
        return _get_limit_pct(symbol)

    @staticmethod
    def is_suspended(daily: pd.DataFrame) -> bool:
        if len(daily) < 2:
            return True
        recent = daily.tail(5)
        zero_vol = (recent['volume'] == 0).sum()
        return zero_vol >= 3

    @staticmethod
    def has_enough_history(daily: pd.DataFrame, min_days: int = 750) -> tuple[bool, str]:
        if len(daily) < min_days:
            return False, f"only_{len(daily)}_days_need_{min_days}"
        return True, "ok"

    @staticmethod
    def stop_loss_level(
        entry_price: float,
        current_price: float,
        atr: float,
        t1_active: bool = True,
    ) -> tuple[bool, str]:
        """Check if stop-loss has been triggered.

        Uses ATR-based stop with T+1 penalty.
        A-share T+1: can't sell on entry day, so stop applies from next day.
        """
        loss_pct = (current_price / entry_price - 1) * 100
        threshold = -2.0 * atr / entry_price * 100
        penalty = 1.2 if t1_active else 1.0
        if loss_pct < threshold * penalty:
            return True, f"stop_loss_triggered_{loss_pct:.1f}%"
        return False, "ok"

    @staticmethod
    def compute_atr(daily: pd.DataFrame, period: int = 14) -> float:
        high = daily['high'].values.astype(np.float64)
        low = daily['low'].values.astype(np.float64)
        close = daily['close'].values.astype(np.float64)
        if len(close) < 2:
            return 0.0
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1]),
            ),
        )
        if len(tr) < period:
            return float(np.mean(tr))
        return float(np.mean(tr[-period:]))


def filter_tradeable_universe(
    symbols: list[str],
    date: str,
    data_dir: Path,
    min_days: int = 750,
) -> list[tuple[str, str]]:
    """Filter stocks to those that are tradeable on a given date.

    Returns list of (symbol, status) tuples.
    Status is 'ok' if tradeable, or a descriptive reason string.
    """
    constraints = AShareConstraints()
    results: list[tuple[str, str]] = []
    for sym in symbols:
        fp = data_dir / f"{sym}.parquet"
        if not fp.exists():
            results.append((sym, "no_data"))
            continue
        try:
            daily = pd.read_parquet(fp)
            daily['date'] = pd.to_datetime(daily['date'])
            daily = daily.sort_values('date').reset_index(drop=True)
            if not constraints.has_enough_history(daily, min_days)[0]:
                results.append((sym, "short_history"))
                continue
            ok, reason = constraints.can_trade(sym, date, daily)
            results.append((sym, reason))
        except Exception:
            results.append((sym, "error"))
    return results
