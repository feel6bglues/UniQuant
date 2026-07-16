"""
数据源基类
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict

import pandas as pd
import pybreaker
import requests
import requests.adapters
import functools
import threading

from ...shared.constants import NetworkConstants
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)

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

    def close(self) -> None:
        """关闭会话资源"""
        if hasattr(self, 'session') and self.session is not None:
            try:
                self.session.close()
            except Exception as e:
                logger.debug(f"Error closing session: {e}")
            self.session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

    def _create_session(self, retry_total: int = 5, backoff_factor: float = 1.0) -> requests.Session:
        """创建请求会话"""
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(
                total=retry_total,
                backoff_factor=backoff_factor,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS"],
            )
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.timeout = NetworkConstants.LONG_TIMEOUT
        return session

    # ── Shared column utilities ──────────────────────────────────────────

    _CANONICAL_COLUMNS: List[str] = [
        "date", "code", "open", "high", "low",
        "close", "volume", "amount", "amplitude", "change_rate",
    ]

    @staticmethod
    def _shared_column_mapping() -> Dict[str, str]:
        """返回常用的 TDX / source 到 canonical 列名的映射。"""
        return {
            "date": "date",
            "trade_date": "date",
            "day": "date",
            "时间": "date",
            "日期": "date",
            "交易日期": "date",
            "开盘": "open",
            "开盘价": "open",
            "open": "open",
            "最高": "high",
            "最高价": "high",
            "high": "high",
            "最低": "low",
            "最低价": "low",
            "low": "low",
            "收盘": "close",
            "收盘价": "close",
            "close": "close",
            "成交量": "volume",
            "volume": "volume",
            "成交额": "amount",
            "amount": "amount",
            "振幅": "amplitude",
            "涨跌幅": "change_rate",
            "代码": "symbol",
            "名称": "name",
            "最新价": "price",
            "涨跌额": "change",
        }

    _DATE_COLUMN_NAMES: List[str] = [
        "date", "日期", "trade_date", "交易日期", "时间", "time",
    ]

    def _parse_date_column(self, df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
        """将 date_col 统一转换为 datetime.date 格式。"""
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.date
        return df

    def _normalize_date_column(self, df: pd.DataFrame) -> pd.DataFrame:
        """检测并标准化日期列。"""
        date_col = None
        for possible_col in self._DATE_COLUMN_NAMES:
            if possible_col in df.columns:
                date_col = possible_col
                break

        if date_col is None:
            if df.index.name in self._DATE_COLUMN_NAMES:
                df = df.reset_index()
                date_col = df.index.name
            elif isinstance(df.index, pd.DatetimeIndex):
                df["date"] = df.index.date
                date_col = "date"
            else:
                raise ValueError(f"找不到日期列. 列名: {df.columns.tolist()}")

        if date_col != "date":
            df = df.rename(columns={date_col: "date"})

        try:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        except (ValueError, TypeError) as e:
            logger.warning(f"处理日期列时出错: {e}")
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        return df

    def _filter_by_date_range(
        self, df: pd.DataFrame, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """按日期范围过滤。"""
        start = pd.to_datetime(start_date).date()
        end = pd.to_datetime(end_date).date()
        df = df[(df["date"] >= start) & (df["date"] <= end)]

        if df.empty:
            raise ValueError("日期范围内无数据")
        return df

    def _ensure_required_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """确保标准 OHLCV 列存在。"""
        required_cols = ["date", "open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col not in df.columns:
                if col in ["open", "high", "low"] and "close" in df.columns:
                    df[col] = df["close"]
                elif col == "volume":
                    df["volume"] = 0
                else:
                    df[col] = 0

        if "amount" not in df.columns:
            df["amount"] = df.get("close", 0) * df.get("volume", 0)

        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df

    def _calculate_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算振幅和涨跌幅。"""
        if "close" in df.columns and "high" in df.columns and "low" in df.columns:
            if "preclose" in df.columns:
                df["amplitude"] = (
                    (df["high"] - df["low"]) / df["preclose"] * 100
                ).fillna(0)
            elif "open" in df.columns:
                df["amplitude"] = (
                    (df["high"] - df["low"]) / df["open"] * 100
                ).fillna(0)
            else:
                df["amplitude"] = 0
        else:
            df["amplitude"] = 0

        if "close" in df.columns:
            if "preclose" in df.columns:
                df["change_rate"] = (
                    (df["close"] - df["preclose"]) / df["preclose"] * 100
                ).fillna(0)
            elif "open" in df.columns:
                df["change_rate"] = (
                    (df["close"] - df["open"]) / df["open"] * 100
                ).fillna(0)
            else:
                df["change_rate"] = 0
        else:
            df["change_rate"] = 0
        return df

    def _finalize_dataframe(
        self, df: pd.DataFrame, clean_symbol: str, source_name: str = ""
    ) -> pd.DataFrame:
        """最终处理和标准化。"""
        if "code" not in df.columns:
            df["code"] = clean_symbol

        df = df.sort_values("date").reset_index(drop=True)

        if source_name:
            from ..utils.normalizer import normalize_stock_data
            df = normalize_stock_data(df, source_name)

        for col in self._CANONICAL_COLUMNS:
            if col not in df.columns:
                df[col] = 0
                logger.warning(f"添加缺失列 {col}，值设为 0")
        return df[self._CANONICAL_COLUMNS]

    def _standardize_columns(
        self, df: pd.DataFrame, column_mapping: Optional[Dict[str, str]] = None
    ) -> pd.DataFrame:
        """重命名列并使用 canonical order。"""
        mapping = column_mapping or self._shared_column_mapping()
        available = {k: v for k, v in mapping.items() if k in df.columns}
        df = df.rename(columns=available)
        for col in self._CANONICAL_COLUMNS:
            if col not in df.columns:
                df[col] = 0
        return df[[c for c in self._CANONICAL_COLUMNS if c in df.columns]]

    # ── Abstract methods ─────────────────────────────────────────────────

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
