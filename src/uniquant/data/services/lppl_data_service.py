from datetime import timedelta

from ...shared.time_provider import get_time_provider

import pandas as pd

from ..data_fetcher import DataFetcher
from ..lake.storage_manager import StorageManager
from ...shared.logger_factory import get_logger

# Configure logging
logger = get_logger("LPPLDataService")


class LPPLDataService:
    """
    专门为LPPL引擎提供数据服务的类
    统一管理数据的抓取、清洗和存储
    """

    def __init__(self):
        self.data_fetcher = DataFetcher()
        self.storage_manager = StorageManager()
        self.index_codes = {
            "sh000001": "上证综指",
            "sz399001": "深证成指",
            "sz399006": "创业板指",
            "sh000016": "上证50",
            "sh000300": "沪深300",
            "sh000905": "中证500",
            "sh000852": "中证1000",
        }
        # 兼容性：设置 data_lake 属性
        self.data_lake = self.storage_manager

    def get_index_data(self, symbol: str, days: int = 350) -> pd.DataFrame:
        """
        获取指数数据，优先从数据湖读取，若不存在则从数据源获取并存储

        Args:
            symbol: 指数代码
            days: 获取的天数

        Returns:
            指数数据DataFrame
        """
        end_date = get_time_provider().now().strftime("%Y-%m-%d")
        start_date = (get_time_provider().now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # 优先从数据湖读取
        df = self.data_lake.read_data(symbol, data_type="index", market="cn")

        if not df.empty:
            # 检查数据是否足够新
            last_date = df.index.max() if hasattr(df.index, "max") else None
            if last_date:
                days_since_last_update = (
                    get_time_provider().now() - pd.to_datetime(last_date)
                ).days
                if days_since_last_update <= 1:
                    logger.info(f"从数据湖读取指数 {symbol} 数据，共 {len(df)} 条记录")
                    return df.tail(days)

        # 从数据源获取数据
        logger.info(f"从数据源获取指数 {symbol} 数据")

        # 尝试使用data_fetcher获取数据
        df = self.data_fetcher.fetch_index_daily(symbol, start_date, end_date)

        # 如果data_fetcher失败，尝试使用akshare直接获取
        if df.empty:
            logger.info(f"尝试使用akshare直接获取指数 {symbol} 数据")
            try:
                import akshare as ak

                df = ak.stock_zh_index_daily(symbol=symbol)
                logger.info(
                    f"使用akshare成功获取指数 {symbol} 数据，共 {len(df)} 条记录"
                )
            except Exception as e:
                logger.warning(f"使用akshare获取指数 {symbol} 数据失败: {e}")

        if not df.empty:
            # 数据清洗
            df = self._clean_data(df)

            # 存储到数据湖
            self.data_lake.write_data(
                symbol=symbol, df=df, data_type="index", market="cn", overwrite=True
            )
            logger.info(f"指数 {symbol} 数据已存储到数据湖")
        else:
            logger.warning(f"获取指数 {symbol} 数据失败")

        return df

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        数据清洗

        Args:
            df: 原始数据DataFrame

        Returns:
            清洗后的数据DataFrame
        """
        if df.empty:
            logger.warning("空DataFrame提供给_clean_data")
            return df

        logger.info(f"开始清洗LPPL数据，原始数据共 {len(df)} 条记录")

        # 确保日期列存在且格式正确
        if "date" in df.columns:
            logger.info("发现'date'列，开始处理")
            try:
                df["date"] = pd.to_datetime(df["date"])
                logger.info("日期列格式转换成功")
            except Exception as e:
                logger.error(f"日期列格式转换失败: {e}")
                return pd.DataFrame()
        else:
            # 尝试从其他可能的列名映射
            date_columns = ["Date", "datetime", "time", "日期"]
            found_date_col = None
            for col in date_columns:
                if col in df.columns:
                    found_date_col = col
                    break

            if found_date_col:
                logger.info(f"将 '{found_date_col}' 列重命名为 'date'")
                df = df.rename(columns={found_date_col: "date"})
                try:
                    df["date"] = pd.to_datetime(df["date"])
                    logger.info("日期列格式转换成功")
                except Exception as e:
                    logger.error(f"日期列格式转换失败: {e}")
                    return pd.DataFrame()
            else:
                logger.error("数据中缺少日期列")
                return pd.DataFrame()

        # 确保收盘价列存在
        if "close" not in df.columns:
            # 尝试从其他可能的列名映射
            close_columns = ["Close", "CLOSE", "收", "收盘价"]
            found_close_col = None
            for col in close_columns:
                if col in df.columns:
                    found_close_col = col
                    break

            if found_close_col:
                logger.info(f"将 '{found_close_col}' 列重命名为 'close'")
                df = df.rename(columns={found_close_col: "close"})
            else:
                logger.warning("数据中缺少收盘价列")
                return pd.DataFrame()

        # 保留'date'作为普通列，同时设置为索引
        df["date_col"] = df["date"]
        df.set_index("date", inplace=True)
        logger.info("保留'date'作为普通列'date_col'，同时设置为索引")

        # 去除重复数据
        df = df[~df.index.duplicated(keep="last")]
        logger.info(f"去重后剩余 {len(df)} 条记录")

        # 按日期排序
        df = df.sort_index()
        logger.info("按日期排序完成")

        # 确保数值类型正确
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        logger.info(f"LPPL数据清洗完成，最终剩余 {len(df)} 条记录")
        return df
