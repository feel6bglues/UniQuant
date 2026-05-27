from typing import Tuple
import pandas as pd
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)

class MarketDataCoordinator:
    """市场数据协调器 - 负责获取指数、ETF、行业、概念等市场级数据"""

    def __init__(self, data_fetcher):
        """
        这里需要传入 DataFetcher 的实例，以便复用基础的 fetch_stock_daily 等方法
        为了打破循环依赖，我们将依赖注入设为弱引用或者使用协议。
        为简单起见，我们直接传入实例并调用它。
        """
        self.data_fetcher = data_fetcher

    def fetch_index_daily(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取指数日线数据
        """
        logger.info(f"获取指数日线数据: {symbol}")
        from ...data.utils.akshare_wrapper import akshare_wrapper
        
        df = akshare_wrapper.fetch_index_daily(symbol)
        if df is not None and not df.empty:
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)].copy()
                
            # 重命名 index API 的特定列以防有不同
            # volume等如果缺失，补齐
            if 'volume' not in df.columns and '成交量' in df.columns:
                df.rename(columns={'成交量': 'volume'}, inplace=True)
            if 'open' not in df.columns and '开盘' in df.columns:
                df.rename(columns={'开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low'}, inplace=True)
                
            return df
            
        return pd.DataFrame()

    def fetch_etf_daily_robust(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        多源ETF数据获取策略
        """
        logger.info(f"获取ETF数据: {symbol}")
        return self.data_fetcher.fetch_stock_daily(symbol, start_date, end_date, adjust="")

    def fetch_industry_concept_data(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        获取行业概念数据
        """
        logger.info("获取行业概念数据")
        return pd.DataFrame(), pd.DataFrame()

    def fetch_sector_daily(
        self, sector_name: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取行业板块指数日线
        """
        logger.info(f"获取行业板块指数: {sector_name}")
        
        sector_map = {
            '金融': '000038.SH',
            '医药': '000037.SH',
            '能源': '000032.SH',
            '材料': '000033.SH',
            '工业': '000034.SH',
            '可选消费': '000035.SH',
            '主要消费': '000036.SH',
            '信息技术': '000039.SH',
            '电信业务': '000040.SH',
            '公用事业': '000041.SH',
            '金融地产': '000038.SH',
            '沪深300金融': '000914.SH',
            '沪深300医药': '000913.SH',
            '沪深300能源': '000908.SH',
            '沪深300材料': '000909.SH',
            '沪深300工业': '000910.SH',
            '沪深300可选消费': '000911.SH',
            '沪深300主要消费': '000912.SH',
            '沪深300信息技术': '000915.SH',
            '沪深300电信业务': '000916.SH',
            '沪深300公用事业': '000917.SH',
        }
        
        sector_code = sector_map.get(sector_name)
        if not sector_code:
            logger.warning(f"未找到行业 {sector_name} 对应的指数代码")
            return pd.DataFrame()
        
        return self.fetch_index_daily(sector_code, start_date, end_date)
