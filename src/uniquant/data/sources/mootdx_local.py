"""
mootdx 离线数据源 - 从本地 TDX 文件读取
"""

from typing import Optional

import pandas as pd

from .base import DataSource
from ...shared.logger_factory import get_logger

logger = get_logger("MootdxLocalSource")


class MootdxLocalSource(DataSource):
    """
    mootdx 离线数据源 - 从本地通达信文件读取数据
    使用 mootdx.reader.Reader 读取本地 TDX 数据目录
    """

    def __init__(self, tdx_dir: Optional[str] = None):
        """
        初始化 mootdx 离线数据源

        Args:
            tdx_dir: 通达信数据目录路径，为 None 时从配置读取
        """
        if tdx_dir:
            self.tdx_dir = tdx_dir
        else:
            from ...shared.config_loader import get_config
            config = get_config()
            self.tdx_dir = config.get("base.tdx.path", None)
            if self.tdx_dir:
                logger.info(f"从配置文件读取通达信路径: {self.tdx_dir}")

        if not self.tdx_dir:
            logger.warning("未设置通达信数据目录，离线数据源将不可用")

        self._reader = None

    def _get_reader(self):
        """延迟初始化 mootdx Reader"""
        if self._reader is None:
            if not self.tdx_dir:
                raise RuntimeError("通达信数据目录未设置，无法初始化 Reader")
            from mootdx.reader import Reader
            self._reader = Reader.factory(market='std', tdxdir=self.tdx_dir)
            logger.info(f"mootdx Reader 初始化成功，目录: {self.tdx_dir}")
        return self._reader

    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从本地 TDX 文件获取日线数据

        Args:
            symbol: 股票代码，如 600000.SH
            start_date: 开始日期，格式 YYYY-MM-DD
            end_date: 结束日期，格式 YYYY-MM-DD

        Returns:
            pd.DataFrame: 日线数据
        """
        try:
            reader = self._get_reader()
            code = symbol.split('.')[0]
            df = reader.daily(symbol=code)

            if df is None or df.empty:
                logger.warning(f"未获取到 {symbol} 的日线数据")
                return pd.DataFrame()

            # 标准化列名
            df = self._normalize_columns(df)

            # mootdx reader 返回 DatetimeIndex（列中无 'date'），须先重置为列再过滤
            df = self._ensure_date_column(df)

            # 筛选日期范围
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                start = pd.to_datetime(start_date)
                end = pd.to_datetime(end_date)
                df = df[(df['date'] >= start) & (df['date'] <= end)]

            df['code'] = symbol
            logger.info(f"成功获取 {symbol} 日线数据，共 {len(df)} 条")
            return df

        except Exception as e:
            logger.error(f"获取 {symbol} 日线数据失败: {e}")
            return pd.DataFrame()

    def fetch_minute(self, symbol: str, freq: int = 5) -> pd.DataFrame:
        """
        从本地 TDX 文件获取分钟线数据

        Args:
            symbol: 股票代码，如 600000.SH
            freq: 分钟级别，默认 5 分钟

        Returns:
            pd.DataFrame: 分钟线数据
        """
        try:
            reader = self._get_reader()
            code = symbol.split('.')[0]
            df = reader.minute(symbol=code, suffix=freq)

            if df is None or df.empty:
                logger.warning(f"未获取到 {symbol} 的 {freq} 分钟数据")
                return pd.DataFrame()

            df = self._normalize_columns(df)
            # mootdx reader 返回 DatetimeIndex，统一重置出 date 列
            df = self._ensure_date_column(df)
            df['code'] = symbol
            logger.info(f"成功获取 {symbol} {freq}分钟数据，共 {len(df)} 条")
            return df

        except Exception as e:
            logger.error(f"获取 {symbol} 分钟数据失败: {e}")
            return pd.DataFrame()

    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """
        mootdx 离线数据源不支持实时数据

        Returns:
            pd.DataFrame: 空 DataFrame
        """
        logger.warning("mootdx 离线数据源不支持实时数据，请使用 MootdxOnlineSource")
        return pd.DataFrame()

    def fetch_market_cap(self, symbol: str) -> float:
        """
        mootdx 离线数据源不支持市值数据

        Returns:
            float: 0.0
        """
        logger.warning("mootdx 离线数据源不支持市值获取")
        return 0.0

    def get_capabilities(self) -> dict:
        """返回数据源能力"""
        return {
            'offline': True,
            'daily': True,
            'minute': True,
            'realtime': False,
            'financial': False,
        }

    @staticmethod
    def _ensure_date_column(df: pd.DataFrame) -> pd.DataFrame:
        """确保 DataFrame 含有 'date' 列。

        mootdx reader.daily()/minute() 返回的 DataFrame 以 DatetimeIndex 为索引
        （index.name 为 'date' 或 'datetime'），列中无 'date' -> 重置为普通列并
        统一命名为 'date'。已含 'date' 列的输入原样返回（不重复 reset）。
        """
        if 'date' in df.columns:
            return df

        idx = df.index
        is_named_time_index = idx.name in ('date', 'datetime')
        is_datetime_index = isinstance(idx, pd.DatetimeIndex)
        if not (is_named_time_index or is_datetime_index):
            return df

        df = df.reset_index()
        # index 列名可能是 'date'/'datetime'，统一重命名为 'date'
        if 'date' not in df.columns and 'datetime' in df.columns:
            df = df.rename(columns={'datetime': 'date'})
        return df

    @staticmethod
    def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        """标准化 mootdx 返回的列名"""
        column_mapping = {
            'datetime': 'date',
            'open': 'open',
            'close': 'close',
            'high': 'high',
            'low': 'low',
            'volume': 'volume',
            'amount': 'amount',
            'vol': 'volume',
        }
        rename_map = {k: v for k, v in column_mapping.items() if k in df.columns}
        if rename_map:
            df = df.rename(columns=rename_map)
        return df
