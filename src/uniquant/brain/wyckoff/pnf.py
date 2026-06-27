from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import pandas as pd


@dataclass
class PnFBox:
    price_level: float
    column_index: int
    is_x: bool


class PointAndFigure:
    """Point & Figure chart engine using the standard 3-box reversal method."""

    def __init__(self, box_size: float = 0.01, reversal: int = 3):
        self.box_size = box_size
        self.reversal = reversal
        self._boxes: List[PnFBox] = []
        self._step: float = 0.0

    def _fixed_step(self, ohlc: pd.DataFrame) -> float:
        median_price = float(np.median(ohlc[["high", "low"]].values))
        return max(median_price * self.box_size, 0.01)

    def _round_up(self, price: float, step: float) -> float:
        return float(np.ceil(price / step) * step)

    def _round_down(self, price: float, step: float) -> float:
        return float(np.floor(price / step) * step)

    def _column_stats(self) -> tuple[list[float], list[float]]:
        if not self._boxes:
            return [], []
        n_cols = max(b.column_index for b in self._boxes) + 1
        highs = [-1e9] * n_cols
        lows = [1e9] * n_cols
        for b in self._boxes:
            i = b.column_index
            if b.price_level > highs[i]:
                highs[i] = b.price_level
            if b.price_level < lows[i]:
                lows[i] = b.price_level
        return highs, lows

    def build(self, ohlc: pd.DataFrame) -> List[PnFBox]:
        high = ohlc["high"].values.astype(float)
        low = ohlc["low"].values.astype(float)
        n = len(high)
        if n == 0:
            return []

        self._boxes = []
        step = self._fixed_step(ohlc)
        self._step = step

        has_open = "open" in ohlc.columns
        if has_open:
            is_x = ohlc["close"].iloc[0] >= ohlc["open"].iloc[0]
        else:
            is_x = high[0] >= low[0]

        current = self._round_up(high[0], step) if is_x else self._round_down(low[0], step)
        col = 0
        self._boxes.append(PnFBox(current, col, is_x))

        for i in range(1, n):
            hi, lo = float(high[i]), float(low[i])

            if is_x:
                if hi >= current + step:
                    target = self._round_down(hi, step)
                    while current < target:
                        current += step
                        self._boxes.append(PnFBox(current, col, True))
                elif lo <= current - self.reversal * step:
                    target = self._round_up(lo, step)
                    if current - target >= step:
                        is_x = False
                        col += 1
                        while current > target:
                            current -= step
                            self._boxes.append(PnFBox(current, col, False))
            else:
                if lo <= current - step:
                    target = self._round_up(lo, step)
                    while current > target:
                        current -= step
                        self._boxes.append(PnFBox(current, col, False))
                elif hi >= current + self.reversal * step:
                    target = self._round_down(hi, step)
                    if target - current >= step:
                        is_x = True
                        col += 1
                        while current < target:
                            current += step
                            self._boxes.append(PnFBox(current, col, True))

        return self._boxes

    def count_target(self) -> float:
        if len(self._boxes) < 10 or self._step <= 0:
            return 0.0

        highs, lows = self._column_stats()
        n_cols = len(highs)
        if n_cols < 5:
            return 0.0

        best_count = 0
        breakout_level = 0.0
        is_up = True

        for start in range(n_cols - 2):
            zh, zl = highs[start], lows[start]
            count = 1
            end = start + 1
            while end < n_cols:
                if highs[end] >= zl and lows[end] <= zh:
                    zh = max(zh, highs[end])
                    zl = min(zl, lows[end])
                    count += 1
                    end += 1
                else:
                    break
            if count > best_count:
                best_count = count
                if end < n_cols and highs[end] > zh:
                    is_up = True
                    breakout_level = zh
                elif end < n_cols and lows[end] < zl:
                    is_up = False
                    breakout_level = zl
                else:
                    is_up = highs[-1] > highs[0]
                    breakout_level = zh if is_up else zl

        if best_count < 3:
            return 0.0

        extension = best_count * self._step
        return breakout_level + extension if is_up else breakout_level - extension

    def breakout_detected(self) -> Tuple[bool, str]:
        highs, lows = self._column_stats()
        n = len(highs)
        if n < 12 or self._step <= 0:
            return False, "none"

        tol = self._step * 0.3
        min_gap = 3
        last_n = min(n, 15)
        search_start = n - last_n

        for i in range(search_start, n - min_gap - 1):
            for j in range(i + min_gap, n - 1):
                if abs(highs[i] - highs[j]) <= tol:
                    top_level = max(highs[i], highs[j])
                    for k in range(j + 1, n):
                        if (highs[k] > top_level + self._step * 2.0
                                and k >= n - 4):
                            return True, "double_top_buy"

        for i in range(search_start, n - min_gap - 1):
            for j in range(i + min_gap, n - 1):
                if abs(lows[i] - lows[j]) <= tol:
                    bottom_level = min(lows[i], lows[j])
                    for k in range(j + 1, n):
                        if (lows[k] < bottom_level - self._step * 2.0
                                and k >= n - 4):
                            return True, "double_bottom_sell"

        return False, "none"

    def wyckoff_phase_hint(self) -> str:
        highs, lows = self._column_stats()
        n = len(highs)
        if n < 8:
            return "unknown"

        recent = slice(n // 2, n)
        first_half = slice(0, n // 2)

        rising_lows_ratio = sum(1 for i in range(1, n) if lows[i] > lows[i - 1]) / (n - 1)
        falling_highs_ratio = sum(1 for i in range(1, n) if highs[i] < highs[i - 1]) / (n - 1)
        recent_rising_lows = sum(1 for i in range(n // 2, n) if lows[i] > lows[i - 1]) / max(1, n - n // 2 - 1)

        ranges = [highs[i] - lows[i] for i in range(n)]
        recent_ranges = ranges[n // 2:]
        early_ranges = ranges[:n // 2]
        avg_recent = np.mean(recent_ranges) if recent_ranges else 0
        avg_early = np.mean(early_ranges) if early_ranges else 1

        if avg_early == 0:
            avg_early = 1
        range_contraction = avg_recent / avg_early

        if (rising_lows_ratio > 0.5 and range_contraction < 0.85
                and recent_rising_lows > 0.4 and avg_recent < avg_early * 0.9):
            return "accumulation"

        up_columns = sum(1 for i in range(1, n) if highs[i] > highs[i - 1])
        down_ratio = 1 - up_columns / max(1, n - 1)

        if (falling_highs_ratio > 0.3 and range_contraction > 1.2
                and down_ratio > 0.5 and avg_recent > avg_early * 1.1):
            return "distribution"

        return "unknown"
