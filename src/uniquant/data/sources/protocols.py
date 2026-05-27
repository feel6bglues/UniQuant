"""
数据源能力协议
使用能力模式定义数据源的可选能力
"""

from typing import Protocol, Optional
import pandas as pd


class HasBasicInfo(Protocol):
    """
    具有获取基本信息能力的数据源协议
    """

    def fetch_basic_info(self, symbol: str) -> pd.DataFrame:
        """
        获取股票基本信息

        Args:
            symbol: 股票代码

        Returns:
            pd.DataFrame: 基本信息数据
        """
        ...


class HasFundFlow(Protocol):
    """
    具有获取资金流能力的数据源协议
    """

    def fetch_fund_flow(self, symbol: str) -> pd.DataFrame:
        """
        获取资金流数据

        Args:
            symbol: 股票代码

        Returns:
            pd.DataFrame: 资金流数据
        """
        ...


class HasIndustryList(Protocol):
    """
    具有获取行业列表能力的数据源协议
    """

    def fetch_industry_list(self) -> pd.DataFrame:
        """
        获取行业列表

        Returns:
            pd.DataFrame: 行业列表数据
        """
        ...


class HasConceptList(Protocol):
    """
    具有获取概念列表能力的数据源协议
    """

    def fetch_concept_list(self) -> pd.DataFrame:
        """
        获取概念列表

        Returns:
            pd.DataFrame: 概念列表数据
        """
        ...


class HasSectorFundFlow(Protocol):
    """
    具有获取板块资金流能力的数据源协议
    """

    def fetch_sector_fund_flow(self) -> pd.DataFrame:
        """
        获取板块资金流数据

        Returns:
            pd.DataFrame: 板块资金流数据
        """
        ...


class HasHotRanking(Protocol):
    """
    具有获取热门排名能力的数据源协议
    """

    def fetch_hot_ranking(self) -> pd.DataFrame:
        """
        获取热门排名数据

        Returns:
            pd.DataFrame: 热门排名数据
        """
        ...


class HasMinuteData(Protocol):
    """
    具有获取分钟级K线数据能力的数据源协议
    """

    def fetch_minute_data(
        self,
        symbol: str,
        period: str,
        start_date: str,
        end_date: str,
        adjust: Optional[str] = "qfq",
    ) -> pd.DataFrame:
        """
        获取分钟级K线数据

        Args:
            symbol: 股票代码
            period: K线周期('1','5','15','30','60')
            start_date: 开始日期
            end_date: 结束日期
            adjust: 复权方式(可选)

        Returns:
            pd.DataFrame: 分钟K线数据
        """
        ...


class HasDragonTiger(Protocol):
    """
    具有获取龙虎榜数据能力的数据源协议
    """

    def fetch_dragon_tiger_list(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取龙虎榜数据

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            pd.DataFrame: 龙虎榜数据
        """
        ...


class HasTickData(Protocol):
    """
    具有获取逐笔成交数据能力的数据源协议
    """

    def fetch_tick_data(self, symbol: str) -> pd.DataFrame:
        """
        获取逐笔成交数据

        Args:
            symbol: 股票代码

        Returns:
            pd.DataFrame: 逐笔成交数据
        """
        ...
