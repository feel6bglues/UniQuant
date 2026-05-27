"""
数据源基类
"""

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd
import pybreaker
import functools
import threading

_breaker_locks: dict = {}

def with_circuit_breaker(fail_max=5, reset_timeout=30):
    breaker = pybreaker.CircuitBreaker(fail_max=fail_max, reset_timeout=reset_timeout)
    lock = threading.Lock()
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with lock:
                return breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator


class DataSource(ABC):
    """
    数据源基类
    """

    @property
    def name(self) -> str:
        """
        数据源名称
        """
        return self.__class__.__name__.replace("Source", "")

    @abstractmethod
    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取日线数据

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            pd.DataFrame: 日线数据
        """
        pass

    @abstractmethod
    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """
        获取实时数据

        Args:
            symbol: 股票代码，None 表示获取所有

        Returns:
            pd.DataFrame: 实时数据
        """
        pass

    @abstractmethod
    def fetch_market_cap(self, symbol: str) -> float:
        """
        获取市值

        Args:
            symbol: 股票代码

        Returns:
            float: 市值
        """
        pass
