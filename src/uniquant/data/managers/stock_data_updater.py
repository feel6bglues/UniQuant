import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import pandas as pd

from ...shared.constants import DateConstants
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)

class StockDataUpdater:
    """股票数据更新器 - 负责增量更新、脏数据清洗、并行更新"""

    def __init__(self, data_fetcher):
        """
        传入 orchestrator (DataFetcher) 以便复用核心方法
        """
        self.data_fetcher = data_fetcher
        self.storage_manager = data_fetcher.storage_manager
        self.source_router = data_fetcher.source_router
        self.data_cleaner = data_fetcher.data_cleaner
        self.data_validator = data_fetcher.data_validator
        self.data_adjuster = data_fetcher.data_adjuster

    def needs_update(self, df: pd.DataFrame) -> bool:
        """
        判断是否需要更新 (智能版)
        """
        if not self.data_validator.validate(df):
            logger.info("数据未能通过基础验证，需要更新")
            return True

        try:
            last_date_val = df["date"].iloc[-1]
            last_date = pd.to_datetime(last_date_val)
            if pd.isna(last_date):
                logger.error("最后一条记录的日期是无效值")
                return True
            last_date = last_date.date()
        except Exception as e:
            logger.error(f"解析日期失败: {e}")
            return True

        now = datetime.now()
        today = now.date()

        if last_date >= today:
            logger.info("数据已是最新，不需要更新")
            return False

        if last_date == (today - timedelta(days=1)):
            if now.time() < datetime.strptime("16:00", "%H:%M").time():
                logger.info("盘中保护：16:00前不更新当天数据")
                return False

        if not self.data_fetcher.is_trading_day(datetime.now()):
            logger.info("非交易日保护：非交易日不更新数据")
            return False

        logger.info("需要更新数据")
        return True

    def update_stock(self, symbol: str, df_old: pd.DataFrame) -> pd.DataFrame:
        """
        执行：抓取行情 -> 抓取因子 -> 清洗 -> 验证 -> 落盘
        """
        logger.info(f"开始更新 {symbol} 数据")

        try:
            start_date = DateConstants.DEFAULT_START_DATE_COMPACT
            if not df_old.empty and "date" in df_old.columns:
                try:
                    last_dt = pd.to_datetime(df_old["date"].iloc[-1])
                    if not pd.isna(last_dt):
                        start_date = (last_dt + timedelta(days=1)).strftime("%Y%m%d")
                except Exception as e:
                    logger.error(f"计算开始日期失败: {e}")
                    start_date = DateConstants.DEFAULT_START_DATE_COMPACT

            df_new = self.source_router.fetch_data(symbol, start_date)
            
            if df_new.empty:
                logger.warning(f"未抓取到 {symbol} 的新数据")
                return df_old

            try:
                self.data_adjuster.update_factors(symbol)
            except Exception as e:
                logger.warning(f"更新复权因子失败: {e}")

            df_new = self.data_cleaner.clean(df_new)
            
            if not self.data_validator.validate(df_new):
                logger.error(f"数据验证失败 {symbol}，放弃更新")
                return df_old

            if not df_new.empty:
                try:
                    start_date_str = df_new['date'].min()
                    end_date_str = df_new['date'].max()
                    trade_calendar = self.data_fetcher.get_trade_calendar(start_date_str, end_date_str)
                    
                    if not trade_calendar.empty:
                        df_new['date'] = pd.to_datetime(df_new['date'])
                        trade_dates = pd.to_datetime(trade_calendar['trade_date'])
                        df_new = df_new[df_new['date'].isin(trade_dates)]
                        
                        if df_new.empty:
                            logger.warning(f"过滤后未找到 {symbol} 的交易日数据")
                            return df_old
                except Exception as e:
                    logger.warning(f"过滤非交易日数据失败: {e}")

            if not df_old.empty:
                df_final = pd.concat([df_old, df_new]).drop_duplicates(
                    subset=["date"], keep="last"
                )
            else:
                df_final = df_new

            df_final = df_final.sort_values("date").reset_index(drop=True)

            self.storage_manager.save_data(symbol, df_final)
            logger.info(f"成功更新 {symbol} 数据，共 {len(df_final)} 条记录")

            return df_final
        except Exception as e:
            logger.error(f"更新股票数据失败: {e}", exc_info=True)
            return df_old

    def update_all(self, symbols: list):
        """
        多线程批量更新
        """
        logger.info(f"开始批量更新 {len(symbols)} 只股票")

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda s: self.data_fetcher.get_price(s), symbols))

        logger.info(f"批量更新完成，共 {len(symbols)} 只股票")

    def clean_data(self, symbol):
        """
        清理并重建数据
        """
        logger.info(f"清理并重建 {symbol} 的数据")
        self.storage_manager.clean_data(symbol)
        return self.data_fetcher.get_price(symbol)
