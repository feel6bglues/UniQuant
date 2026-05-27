from typing import Optional
import pandas as pd
from .pipeline.data_cleaner import DataCleaner
from .pipeline.data_validator import DataValidator
from .pipeline.data_adjuster import DataAdjuster
from .lake.storage_manager import StorageManager
from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


class DataPipelineService:
    def __init__(self, data_dir: str = "./data"):
        self.cleaner = DataCleaner()
        self.validator = DataValidator()
        self.adjuster = DataAdjuster(StorageManager(data_dir))

    def process(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        df = self.cleaner.clean_stock_daily(df)
        df = self.validator.validate(df)
        df = self.adjuster.adjust(df, symbol)
        return df
