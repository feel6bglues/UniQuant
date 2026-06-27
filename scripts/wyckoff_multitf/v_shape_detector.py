#!/usr/bin/env python3
"""V-Shaped Reversal Detector for Wyckoff regime analysis.

Detects extreme V-shaped reversals (like 2020 COVID) where traditional
Wyckoff sell signals fail because the recovery is faster than the normal
distribution→markdown cycle.

Usage:
    from scripts.wyckoff_multitf.v_shape_detector import VShapedReversalDetector
    detector = VShapedReversalDetector()
    result = detector.detect(index_df)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class VShapeResult:
    """Detection result for one V-shape event"""
    date: str
    v_type: str  # 'v_bottom' (恐慌→反弹) | 'v_top' (暴涨→暴跌)
    severity: str  # 'high' | 'medium' | 'low'
    decline_pct: float
    recovery_pct: float
    decline_days: int
    recovery_days: int
    in_progress: bool = False  # True if still recovering/dropping


class VShapedReversalDetector:
    """
    Detect V-shaped reversal patterns in market index data.
    
    A V-bottom: sharp decline > 15% followed by > 50% recovery within 10 days
    A V-top: sharp rally > 15% followed by > 50% retracement within 10 days
    
    When V-top is detected, Wyckoff sell signals should be treated with 
    reduced confidence (they typically fail in these windows).
    """

    def __init__(self, 
                 decline_threshold: float = 0.15,
                 recovery_ratio: float = 0.50,
                 recovery_window: int = 10,
                 lookback: int = 120):
        self.decline_threshold = decline_threshold
        self.recovery_ratio = recovery_ratio
        self.recovery_window = recovery_window
        self.lookback = lookback

    def detect(self, index_df: pd.DataFrame) -> List[VShapeResult]:
        """
        Scan index DataFrame for V-shape patterns.
        
        Args:
            index_df: DataFrame with 'close' column (e.g., CSI 300 index)
            
        Returns:
            List of VShapeResult for each detected event
        """
        df = index_df.copy()
        close = df['close'].values
        results = []

        for i in range(self.lookback, len(close)):
            window = close[i - self.lookback : i + 1]
            
            v_bottom = self._check_v_bottom(window, i, close, df)
            if v_bottom:
                results.append(v_bottom)
            
            v_top = self._check_v_top(window, i, close, df)
            if v_top:
                results.append(v_top)

        return results

    def _check_v_bottom(self, window: np.ndarray, idx: int,
                        close: np.ndarray,
                        df: pd.DataFrame) -> Optional[VShapeResult]:
        """Check for V-bottom at current position"""
        peak = np.max(window[:len(window)//3])
        trough = np.min(window)
        trough_idx = np.argmin(window)
        
        decline = (peak - trough) / peak
        if decline < self.decline_threshold:
            return None
        
        recovery_start = trough_idx
        recovery_end = min(recovery_start + self.recovery_window, len(window))
        if recovery_end > recovery_start:
            recovery_high = np.max(window[recovery_start:recovery_end])
            recovery = (recovery_high - trough) / (peak - trough)
            
            if recovery >= self.recovery_ratio:
                severity = 'high' if decline > 0.25 else 'medium' if decline > 0.20 else 'low'
                return VShapeResult(
                    date=str(df.index[idx]) if isinstance(df.index, pd.DatetimeIndex) else str(df.iloc[idx].get('date', idx)),
                    v_type='v_bottom',
                    severity=severity,
                    decline_pct=round(decline * 100, 2),
                    recovery_pct=round(recovery * 100, 2),
                    decline_days=int(trough_idx),
                    recovery_days=int(recovery_end - recovery_start),
                )

        if idx == len(close) - 1:
            recent = close[-self.recovery_window:]
            recent_trough = np.min(recent)
            if recent_trough > 0:
                recent_recovery = (close[-1] - recent_trough) / recent_trough
                if recent_recovery > 0.3 and decline > self.decline_threshold:
                    return VShapeResult(
                        date=str(df.index[idx]) if isinstance(df.index, pd.DatetimeIndex) else str(df.iloc[idx].get('date', idx)),
                        v_type='v_bottom',
                        severity='medium',
                        decline_pct=round(decline * 100, 2),
                        recovery_pct=round(recent_recovery * 100, 2),
                        decline_days=int(trough_idx),
                        recovery_days=0,
                        in_progress=True,
                    )
        return None

    def _check_v_top(self, window: np.ndarray, idx: int,
                     close: np.ndarray,
                     df: pd.DataFrame) -> Optional[VShapeResult]:
        """Check for V-top at current position (mirrors v-bottom logic)"""
        trough = np.min(window[:len(window)//3])
        peak = np.max(window)
        peak_idx = np.argmax(window)
        
        rally = (peak - trough) / trough
        if rally < self.decline_threshold:
            return None
        
        retrace_start = peak_idx
        retrace_end = min(retrace_start + self.recovery_window, len(window))
        if retrace_end > retrace_start:
            retrace_low = np.min(window[retrace_start:retrace_end])
            retracement = (peak - retrace_low) / (peak - trough)
            
            if retracement >= self.recovery_ratio:
                severity = 'high' if rally > 0.25 else 'medium' if rally > 0.20 else 'low'
                return VShapeResult(
                    date=str(df.index[idx]) if isinstance(df.index, pd.DatetimeIndex) else str(df.iloc[idx].get('date', idx)),
                    v_type='v_top',
                    severity=severity,
                    decline_pct=round(rally * 100, 2),
                    recovery_pct=round(retracement * 100, 2),
                    decline_days=int(peak_idx),
                    recovery_days=int(retrace_end - retrace_start),
                )
        return None

    def classify_date(self, date: str, index_df: pd.DataFrame) -> Dict:
        """
        Convenience method: classify a specific date
        
        Returns dict with v_shape signal for the given date
        """
        results = self.detect(index_df)
        for r in results:
            if r.date == date:
                return {
                    "v_shape_detected": True,
                    "v_type": r.v_type,
                    "severity": r.severity,
                    "decline_pct": r.decline_pct,
                }
        return {
            "v_shape_detected": False,
            "v_type": "none",
            "severity": "none",
            "decline_pct": 0.0,
        }


def load_index_data(path: str, date_col: str = "date") -> Optional[pd.DataFrame]:
    """Load index parquet data for V-shape detection"""
    fp = Path(path)
    if not fp.exists():
        return None
    df = pd.read_parquet(fp)
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.sort_values(date_col).reset_index(drop=True)
        df.set_index(date_col, inplace=True)
    return df
