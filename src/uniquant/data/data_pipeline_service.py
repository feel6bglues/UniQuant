import pandas as pd
from typing import Optional

from .pipeline.data_cleaner import DataCleaner
from .pipeline.data_validator import DataValidator
from .pipeline.data_adjuster import DataAdjuster
from .lake.storage_manager import StorageManager
from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


class DataPipelineService:
    def __init__(
        self,
        data_dir: str = "./data",
        storage_manager: Optional[StorageManager] = None,
    ):
        self.storage_manager = (
            storage_manager if storage_manager is not None else StorageManager(data_dir)
        )
        self.cleaner = DataCleaner()
        self.validator = DataValidator()
        self.adjuster = DataAdjuster(self.storage_manager)

    def process(self, df: pd.DataFrame, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
        df = self.cleaner.clean_stock_daily(df)
        if not self.validator.validate(df):
            logger.warning(f"数据验证失败 {symbol}，跳过复权")
            return df
        df = self.adjuster.apply_adjustment(symbol, df, method=adjust)
        return df
