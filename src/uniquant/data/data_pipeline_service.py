import pandas as pd
from typing import Optional

from .pipeline.data_cleaner import DataCleaner
from .pipeline.data_validator import DataValidator
from .corporate_action import CorporateActionAdjuster
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
        # Step4 S4a: data_adjuster 薄壳已删，复权单轨 CorporateActionAdjuster
        self.adjuster = CorporateActionAdjuster()

    def process(self, df: pd.DataFrame, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
        df = self.cleaner.clean_stock_daily(df)
        if not self.validator.validate(df):
            logger.warning(f"数据验证失败 {symbol}，跳过复权")
            return df
        # Step4 S4a: 直调新轨 (qfq/hfq)；其它值原样返回 (旧契约)
        if adjust not in ("qfq", "hfq"):
            logger.warning(f"无效的复权参数: {adjust}，返回原始数据")
            return df
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        df = self.adjuster.adjust(df, symbol, adjust_type=adjust)
        return df
