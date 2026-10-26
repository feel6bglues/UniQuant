"""
行情周期重采样合成器 (QuoteResampler)
=============================================================================
核心职责:
1. 从日线数据聚合合成规范的周线 (Weekly) 序列；
2. 从日线数据聚合合成规范的月线 (Monthly) 序列；
3. 遵循 OHLCV 金融聚合守卫契约，保证原子写回数据湖。
=============================================================================
"""

from typing import TYPE_CHECKING
import pandas as pd

from ...shared.logger_factory import get_logger

if TYPE_CHECKING:
    from .storage_manager import StorageManager

logger = get_logger("QuoteResampler")


class QuoteResampler:
    """
    行情周期重采样合成器
    从底层日线行情合成高阶周期（周线、月线）并持久化到对应湖目录
    """

    def __init__(self, storage_manager: "StorageManager"):
        self.storage_manager = storage_manager

    def synthesize_weekly(self, symbol: str) -> pd.DataFrame:
        """从日线数据合成周线

        规则:
        - open: 同一周第一个交易日的 open
        - high: 同一周最高价
        - low: 同一周最低价
        - close: 同一周最后一个交易日的 close
        - volume: 同一周成交量合计
        - amount: 同一周成交额合计

        Args:
            symbol: 股票代码

        Returns:
            合成后的周线 DataFrame
        """
        daily = self.storage_manager.read_data(symbol=symbol, data_type="daily")
        if daily is None or daily.empty:
            logger.warning(f"无日线数据可供合成周线: {symbol}")
            return pd.DataFrame()

        if "date" not in daily.columns:
            logger.warning(f"日线数据缺少 date 列: {symbol}")
            return pd.DataFrame()

        daily = daily.copy()
        daily["date"] = pd.to_datetime(daily["date"])
        daily["_year"] = daily["date"].dt.isocalendar().year.astype(int)
        daily["_week"] = daily["date"].dt.isocalendar().week.astype(int)

        agg_dict = {}
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in daily.columns:
                if col == "open":
                    agg_dict[col] = "first"
                elif col == "high":
                    agg_dict[col] = "max"
                elif col == "low":
                    agg_dict[col] = "min"
                elif col == "close":
                    agg_dict[col] = "last"
                else:
                    agg_dict[col] = "sum"

        if not agg_dict:
            logger.warning(f"日线数据无可聚合列: {symbol}")
            return pd.DataFrame()

        weekly = daily.groupby(["_year", "_week"]).agg(agg_dict).reset_index()
        weekly = weekly.rename(columns={"_year": "year", "_week": "week"})

        self.storage_manager.write_data(symbol=symbol, df=weekly, data_type="weekly")
        logger.info(f"合成周线完成: {symbol}, 共 {len(weekly)} 条")
        return weekly

    def synthesize_monthly(self, symbol: str) -> pd.DataFrame:
        """从日线数据合成月线

        规则:
        - open: 同月第一个交易日的 open
        - high: 同月最高价
        - low: 同月最低价
        - close: 同月最后一个交易日的 close
        - volume: 同月成交量合计
        - amount: 同月成交额合计

        Args:
            symbol: 股票代码

        Returns:
            合成后的月线 DataFrame
        """
        daily = self.storage_manager.read_data(symbol=symbol, data_type="daily")
        if daily is None or daily.empty:
            logger.warning(f"无日线数据可供合成月线: {symbol}")
            return pd.DataFrame()

        if "date" not in daily.columns:
            logger.warning(f"日线数据缺少 date 列: {symbol}")
            return pd.DataFrame()

        daily = daily.copy()
        daily["date"] = pd.to_datetime(daily["date"])
        daily["_year"] = daily["date"].dt.year
        daily["_month"] = daily["date"].dt.month

        agg_dict = {}
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in daily.columns:
                if col == "open":
                    agg_dict[col] = "first"
                elif col == "high":
                    agg_dict[col] = "max"
                elif col == "low":
                    agg_dict[col] = "min"
                elif col == "close":
                    agg_dict[col] = "last"
                else:
                    agg_dict[col] = "sum"

        if not agg_dict:
            logger.warning(f"日线数据无可聚合列: {symbol}")
            return pd.DataFrame()

        monthly = daily.groupby(["_year", "_month"]).agg(agg_dict).reset_index()
        monthly = monthly.rename(columns={"_year": "year", "_month": "month"})

        self.storage_manager.write_data(symbol=symbol, df=monthly, data_type="monthly")
        logger.info(f"合成月线完成: {symbol}, 共 {len(monthly)} 条")
        return monthly
