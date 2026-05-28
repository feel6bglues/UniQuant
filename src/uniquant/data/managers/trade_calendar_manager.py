import datetime
import os
from typing import Set

import pandas as pd

from ...data.sources.baostock import BaostockSource
from ...shared.constants import DateConstants
from ...shared.logger_factory import get_logger

logger = get_logger("TradeCalendarManager")

_CN_HOLIDAYS: Set[str] = {
    "2024-01-01",
    "2024-02-09", "2024-02-10", "2024-02-11", "2024-02-12",
    "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16", "2024-02-17",
    "2024-04-04", "2024-04-05", "2024-04-06",
    "2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-05",
    "2024-06-08", "2024-06-09", "2024-06-10",
    "2024-09-15", "2024-09-16", "2024-09-17",
    "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04",
    "2024-10-05", "2024-10-06", "2024-10-07",
    "2025-01-01",
    "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
    "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",
    "2025-04-04", "2025-04-05", "2025-04-06",
    "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
    "2025-05-31", "2025-06-01", "2025-06-02",
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04",
    "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
    "2026-01-01",
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-09-26", "2026-09-27", "2026-09-28",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07",
}

_CN_SPECIAL_WORKDAYS: Set[str] = {
    "2024-02-04",
    "2024-02-18",
    "2024-04-07",
    "2024-09-29",
    "2024-10-12",
    "2025-01-26",
    "2025-02-08",
    "2025-09-28",
    "2025-10-11",
}

class TradeCalendarManager:
    """交易日历管理器"""

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = data_dir

    def create_trade_calendar(self):
        """
        使用 Baostock 获取完整的交易日历并保存到本地
        """
        logger.info("开始使用 Baostock 获取完整的交易日历")
        baostock = BaostockSource()
        
        try:
            logger.info("1. 登录 Baostock...")
            if not baostock._login():
                logger.error("登录 Baostock 失败")
                return
            
            start_date = DateConstants.DEFAULT_START_DATE
            end_date = datetime.datetime.now().strftime("%Y-%m-%d")
            
            calendar = baostock.fetch_calendar(start_date=start_date, end_date=end_date)
            
            if not calendar.empty:
                output_path = os.path.join(self.data_dir, "trade_calendar.csv")
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                calendar.to_csv(output_path, index=False, encoding='utf-8-sig')
                logger.info(f"保存成功，文件大小: {os.path.getsize(output_path) / 1024:.2f} KB")
            else:
                logger.error("获取交易日历失败，返回空数据")
                
        except Exception as e:
            logger.error(f"操作失败: {e}", exc_info=True)
        finally:
            baostock._logout()

    def generate_trade_calendar(self, year: int, force_update: bool = False) -> pd.DataFrame:
        calendar_file = os.path.join(self.data_dir, f"trade_calendar_{year}.csv")
        if not force_update and os.path.exists(calendar_file):
            try:
                df = pd.read_csv(calendar_file, encoding='utf-8-sig')
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date'])
                return df
            except Exception as e:
                logger.warning(f"加载本地交易日历失败: {e}")
        return pd.DataFrame()

    def is_trading_day(self, date: datetime.date) -> bool:
        try:
            year = date.year
            calendar_file = os.path.join(self.data_dir, f"trade_calendar_{year}.csv")
            if os.path.exists(calendar_file):
                try:
                    calendar = pd.read_csv(calendar_file, encoding='utf-8-sig')
                    if 'trade_date' in calendar.columns:
                        calendar['trade_date'] = pd.to_datetime(calendar['trade_date'])
                        date_str = date.strftime("%Y-%m-%d")
                        return date_str in calendar['trade_date'].dt.strftime("%Y-%m-%d").values
                except Exception as e:
                    logger.warning(f"加载本地交易日历失败: {e}")
            iso = date.isoformat()
            if iso in _CN_SPECIAL_WORKDAYS:
                return True
            if date.weekday() >= 5:
                return False
            return iso not in _CN_HOLIDAYS
        except Exception as e:
            logger.error(f"检查交易日失败: {e}")
            return False

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            years = range(start_dt.year, end_dt.year + 1)
            
            all_dates = []
            for year in years:
                calendar = self.generate_trade_calendar(year)
                if not calendar.empty:
                    all_dates.append(calendar)
            
            if all_dates:
                combined_calendar = pd.concat(all_dates)
                combined_calendar['trade_date'] = pd.to_datetime(combined_calendar['trade_date'])
                filtered_calendar = combined_calendar[
                    (combined_calendar['trade_date'] >= start_dt) & 
                    (combined_calendar['trade_date'] <= end_dt)
                ]
                filtered_calendar = filtered_calendar.sort_values('trade_date').reset_index(drop=True)
                return filtered_calendar
                
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取交易日历失败: {e}")
            return pd.DataFrame()

def main():
    manager = TradeCalendarManager()
    manager.create_trade_calendar()

if __name__ == "__main__":
    main()
