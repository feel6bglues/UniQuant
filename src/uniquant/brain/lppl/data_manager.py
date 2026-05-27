import logging
import os
from typing import Optional

import pandas as pd

from ...shared.error_handling import handle_errors
from ...shared.exceptions import DataError, DataFetchError
from ...shared.logger_factory import get_logger

try:
    from ...data.services.lppl_data_service import LPPLDataService
except ImportError:
    LPPLDataService = None

logger = get_logger(__name__)


class LPPLDataManager:
    """
    LPPL数据管理器
    负责数据获取、验证和清洗
    """

    def __init__(self, data_dir: str = "data"):
        """
        初始化LPPL数据管理器

        Args:
            data_dir: 数据存储目录
        """
        if LPPLDataService is None:
            raise ImportError(
                "LPPLDataService not available. data/ layer not yet migrated."
            )
        self.data_service = LPPLDataService()
        self.data_dir = data_dir

        # 创建数据目录
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            logger.info(f"Created data directory: {self.data_dir}")

    @handle_errors(
        DataFetchError, DataError, default_return=None, log_level=logging.ERROR
    )
    def fetch_data(self, symbol: str, name: str) -> Optional[pd.DataFrame]:
        """
        获取数据，支持增量更新

        Args:
            symbol: 证券代码
            name: 证券名称

        Returns:
            数据DataFrame或None
        """
        file_path = os.path.join(self.data_dir, f"{symbol}.csv")

        try:
            # 1. 尝试加载本地数据
            if os.path.exists(file_path):
                df = pd.read_csv(file_path, parse_dates=["date"])
                last_date = df["date"].iloc[-1].date()
            else:
                df = pd.DataFrame()
                last_date = None

            # 2. 更新数据
            logger.info(f"更新 {name} ({symbol})...")

            # 3. 区分股票和指数
            from ...data.data_fetcher import DataFetcher

            fetcher = DataFetcher()

            # 使用DataFetcher获取股票数据
            end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
            start_date = (pd.Timestamp.now() - pd.Timedelta(days=365)).strftime(
                "%Y-%m-%d"
            )

            new_df = fetcher.fetch_stock_daily(
                symbol, start_date, end_date, adjust="qfq"
            )

            if not new_df.empty:
                new_df["date"] = pd.to_datetime(new_df["date"])
            else:
                logger.warning(f"获取 {symbol} 数据失败")
                return None

            if last_date:
                # 数据合并
                latest_new = new_df["date"].iloc[-1].date()
                if latest_new > last_date:
                    df = pd.concat(
                        [df, new_df[new_df["date"] > pd.Timestamp(last_date)]]
                    )
                    df = (
                        df.drop_duplicates(subset=["date"])
                        .sort_values("date")
                        .reset_index(drop=True)
                    )
                    df.to_csv(file_path, index=False)
                    logger.info(f"  更新至 {latest_new}")
                else:
                    logger.info(f"  数据最新 ({last_date})")
            else:
                # 首次完整下载
                df = new_df
                df.to_csv(file_path, index=False)
                logger.info(f"  首次下载完成")

            return df
        except Exception as e:
            logger.error(f"  错误: {e}")
            return None

    @handle_errors(
        ValueError, TypeError, DataError, default_return=False, log_level=logging.ERROR
    )
    def validate_data(self, df: pd.DataFrame) -> bool:
        """
        验证数据有效性

        Args:
            df: 待验证的数据

        Returns:
            是否有效
        """
        if df is None:
            logger.error("DataFrame is None")
            return False

        if df.empty:
            logger.error("DataFrame is empty")
            return False

        required_columns = ["date", "close"]
        for col in required_columns:
            if col not in df.columns:
                logger.error(f"Missing required column: {col}")
                return False

        if len(df) < 60:  # 至少需要60个数据点
            logger.warning(f"Insufficient data points: {len(df)}")
            return False

        return True

    @handle_errors(
        ValueError,
        TypeError,
        DataError,
        default_return=pd.DataFrame(),
        log_level=logging.ERROR,
    )
    def clean_data(self, df: pd.DataFrame, column: str = "close") -> pd.DataFrame:
        """
        清洗数据

        Args:
            df: 待清洗的数据
            column: 价格列名

        Returns:
            清洗后的数据
        """
        if not self.validate_data(df):
            return pd.DataFrame()

        # 检查数据类型
        if not pd.api.types.is_numeric_dtype(df[column]):
            logger.warning(f"'{column}' column is not numeric, trying to convert")
            df[column] = pd.to_numeric(df[column], errors="coerce")
            # 填充NaN值
            df[column] = df[column].fillna(0.0)

        # 检查是否有足够的有效数据
        valid_data_count = df[column].replace(0, pd.NA).count()
        if valid_data_count < 60:
            logger.warning(f"Insufficient valid data points: {valid_data_count}")
            return pd.DataFrame()

        return df

    def get_clean_data(
        self, symbol: str, name: str, column: str = "close"
    ) -> pd.DataFrame:
        """
        获取并清洗数据的便捷方法

        Args:
            symbol: 证券代码
            name: 证券名称
            column: 价格列名

        Returns:
            清洗后的数据
        """
        df = self.fetch_data(symbol, name)
        if df is None:
            return pd.DataFrame()
        return self.clean_data(df, column)
