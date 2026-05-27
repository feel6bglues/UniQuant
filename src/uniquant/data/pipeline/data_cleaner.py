import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class DataCleaner:
    """数据清洗器"""

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗数据"""
        if df.empty:
            logger.warning("空DataFrame传入clean方法")
            return df

        logger.info(f"开始清洗数据，原始数据共 {len(df)} 条记录")

        # 1. 标准化列名（小写）
        df.columns = [col.lower() for col in df.columns]

        # 2. 类型转换
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        # 3. 处理停牌逻辑
        if "volume" in df.columns:
            df["volume"] = df["volume"].fillna(0)

        # 4. 处理缺失值和重复值
        df = df.dropna(subset=["date", "close"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates(subset=["date"], keep="last")

        # 5. 确保成交额列存在
        if "amount" not in df.columns:
            df["amount"] = df.get("close", 0) * df.get("volume", 0)
        else:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)

        # 6. 排序并重置索引
        df = df.sort_values("date").reset_index(drop=True)

        logger.info(f"数据清洗完成，共 {len(df)} 条记录")
        return df

    def clean_stock_daily(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗股票日线数据（兼容旧接口）"""
        return self.clean(df)
