"""
mootdx 在线数据源 - 从行情服务器获取实时数据
"""

from typing import Optional

import pandas as pd

from .base import DataSource
from ...shared.logger_factory import get_logger

logger = get_logger("MootdxOnlineSource")


class MootdxOnlineSource(DataSource):
    """
    mootdx 在线数据源 - 从通达信行情服务器获取数据
    使用 mootdx.quotes.Quotes 连接行情服务器
    """

    def __init__(self):
        self._client = None

    def _get_client(self):
        """延迟初始化 mootdx Quotes 客户端"""
        if self._client is None:
            from mootdx.quotes import Quotes
            self._client = Quotes.factory(market='std', heartbeat=True)
            logger.info("mootdx 在线行情客户端初始化成功")
        return self._client

    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从行情服务器获取日线数据

        Args:
            symbol: 股票代码，如 600000.SH
            start_date: 开始日期，格式 YYYY-MM-DD
            end_date: 结束日期，格式 YYYY-MM-DD

        Returns:
            pd.DataFrame: 日线数据
        """
        try:
            client = self._get_client()
            code = symbol.split('.')[0]
            # frequency=9 为日线，offset=0 从最新开始，count=800 获取足够数据
            df = client.bars(symbol=code, frequency=9, offset=0, count=800)

            if df is None or df.empty:
                logger.warning(f"未获取到 {symbol} 的日线数据")
                return pd.DataFrame()

            df = self._normalize_columns(df)

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

    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """
        获取实时行情数据

        Args:
            symbol: 股票代码，如 600000.SH；None 时获取所有

        Returns:
            pd.DataFrame: 实时行情数据
        """
        try:
            client = self._get_client()

            if symbol:
                symbols = [symbol.split('.')[0]]
            else:
                logger.warning("获取全市场实时数据暂不支持，请指定股票代码")
                return pd.DataFrame()

            df = client.quotes(symbol=symbols)

            if df is None or df.empty:
                logger.warning("未获取到实时数据")
                return pd.DataFrame()

            df = self._normalize_columns(df)
            if symbol:
                df['code'] = symbol

            logger.info(f"成功获取实时数据，共 {len(df)} 条")
            return df

        except Exception as e:
            logger.error(f"获取实时数据失败: {e}")
            return pd.DataFrame()

    def fetch_market_cap(self, symbol: str) -> float:
        """
        获取市值
        注：mootdx 在线源不直接提供市值，返回 0

        Returns:
            float: 0.0
        """
        logger.warning("mootdx 在线数据源暂不支持市值获取")
        return 0.0

    def get_capabilities(self) -> dict:
        """返回数据源能力"""
        return {
            'offline': False,
            'daily': True,
            'minute': True,
            'realtime': True,
            'financial': False,
        }

    def close(self):
        """关闭连接"""
        self._client = None
        logger.info("mootdx 在线行情客户端已关闭")

    @staticmethod
    def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        """标准化 mootdx 返回的列名

        §7.4 #10: 原映射同时含 'volume'→'volume' 与 'vol'→'volume'，当帧里
        两列并存时 rename 会产出**重复的 volume 列**。改为：仅做真正的别名
        重命名，且目标列已存在时不覆盖；若别名与目标列同时存在则保留规范列、
        丢弃别名，保证成交量列唯一。

        注：手→股换算属消费方归一化职责（跨资产系数不一致），此处不做硬编码。
        """
        column_mapping = {'datetime': 'date', 'vol': 'volume'}
        rename_map = {
            src: dst
            for src, dst in column_mapping.items()
            if src != dst and src in df.columns and dst not in df.columns
        }
        if rename_map:
            df = df.rename(columns=rename_map)
        if 'vol' in df.columns and 'volume' in df.columns:
            logger.warning(
                "mootdx 返回同时含 vol/volume 列，丢弃别名 vol 以保持单一成交量列"
            )
            df = df.drop(columns=['vol'])
        return df
