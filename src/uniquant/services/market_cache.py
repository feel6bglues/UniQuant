"""
市场级缓存 — 从 AnalysisService 中抽离的市场共享状态
====================================================

职责: 管理全市场共享的计算结果 (Regime, NTF, Benchmark)
线程安全: 所有读写操作通过锁保护
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Any, Dict, Optional

import pandas as pd

from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


class MarketLevelCache:
    """市场级缓存 — 全市场共享的计算结果

    Regime 和 NTF 信号是全市场共享的，每只股票分析时只需计算一次。
    此类封装了这个缓存逻辑，线程安全。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._date: Optional[str] = None
        self._regime: Optional[str] = None
        self._regime_details: Optional[Dict[str, Any]] = None
        self._ntf_signals: Optional[Dict[str, Any]] = None
        self._benchmark: Optional[pd.DataFrame] = None

    @property
    def date(self) -> Optional[str]:
        with self._lock:
            return self._date

    def get_regime(self) -> Optional[str]:
        with self._lock:
            if self._date == self._today():
                return self._regime
        return None

    def get_regime_details(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self._date == self._today():
                return self._regime_details
        return None

    def set_regime(self, regime: str, details: Dict[str, Any]) -> None:
        with self._lock:
            self._regime = regime
            self._regime_details = details
            self._date = self._today()
        logger.debug(f"Market regime cached: {regime}")

    def get_ntf(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self._date == self._today():
                return self._ntf_signals
        return None

    def set_ntf(self, signals: Dict[str, Any]) -> None:
        with self._lock:
            self._ntf_signals = signals
            if self._date is None:
                self._date = self._today()
        logger.debug(f"NTF signals cached: {signals.get('side', 'NONE')}")

    def get_benchmark(self) -> Optional[pd.DataFrame]:
        with self._lock:
            return self._benchmark

    def set_benchmark(self, df: pd.DataFrame) -> None:
        with self._lock:
            self._benchmark = df

    def clear(self) -> None:
        with self._lock:
            self._date = None
            self._regime = None
            self._regime_details = None
            self._ntf_signals = None
            self._benchmark = None
        logger.info("Market-level cache cleared")

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "date": self._date,
                "has_regime": self._regime is not None,
                "has_ntf": self._ntf_signals is not None,
                "has_benchmark": self._benchmark is not None,
            }

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()
