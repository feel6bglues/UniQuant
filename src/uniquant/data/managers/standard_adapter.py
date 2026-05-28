from abc import ABC, abstractmethod
import pandas as pd

from ...shared.logger_factory import get_logger
from ..utils.normalizer import normalize_column_names as _normalize_columns

logger = get_logger(__name__)


class DataSourceAdapter(ABC):
    """数据源适配器接口"""

    @abstractmethod
    def fetch(self, symbol: str, start_date: str) -> pd.DataFrame:
        """获取数据"""
        pass


class StandardAdapter(DataSourceAdapter):
    """标准适配器实现"""

    def __init__(self, data_source):
        self.data_source = data_source

    def fetch(self, symbol: str, start_date: str) -> pd.DataFrame:
        """获取并标准化数据"""
        # 调用具体数据源获取原始数据
        from datetime import datetime

        end_date = datetime.now().strftime("%Y%m%d")

        try:
            raw_data = self.data_source.fetch_daily(symbol, start_date, end_date)
        except AttributeError:
            # 兼容旧版数据源
            if hasattr(self.data_source, "get_data"):
                raw_data = self.data_source.get_data(symbol, start_date)
            else:
                return pd.DataFrame()

        if raw_data.empty:
            return pd.DataFrame()

        # 标准化处理
        df = self._standardize_data(raw_data)

        return df

    def _standardize_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        标准化数据格式
        委托给 normalizer.normalize_column_names 以保持全局一致
        """
        if df.empty:
            return pd.DataFrame()

        # 使用统一的列名标准化（覆盖 20+ 字段映射）
        df = _normalize_columns(df)

        # 确保必要列存在（与 data_validator 保持一致）
        required_columns = ["date", "code", "open", "high", "low", "close", "volume", "amount"]
        for col in required_columns:
            if col not in df.columns:
                if col in ["open", "high", "low"] and "close" in df.columns:
                    df[col] = df["close"]
                elif col == "volume":
                    df["volume"] = 0
                elif col == "amount":
                    df["amount"] = df.get("close", 0) * df.get("volume", 0)
                elif col == "code":
                    # code 可能由上游传入，此处不强制
                    continue
                else:
                    return pd.DataFrame()

        # 处理日期格式
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        # 转换数值类型
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        # 过滤无效数据
        df = df.dropna(subset=["date", "close"])

        # 排序并选择列
        df = df.sort_values("date").reset_index(drop=True)

        final_cols = [c for c in ["date", "code", "open", "high", "low", "close", "volume", "amount"] if c in df.columns]
        return df[final_cols]
