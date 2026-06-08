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

        df = df.copy()  # 防止原地修改调用方数据

        logger.info(f"开始清洗数据，原始数据共 {len(df)} 条记录")

        # 1. 标准化列名（小写）
        df.columns = [col.lower() for col in df.columns]

        # 2. 类型转换
        price_cols = {"open", "high", "low", "close"}
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
                if col not in price_cols:
                    df[col] = df[col].fillna(0)

        # 3. 修复 OHLC 一致性: 确保 high >= max(open, close), low <= min(open, close)
        if {"open", "high", "low", "close"}.issubset(df.columns):
            orig_high = df["high"].copy()
            orig_low = df["low"].copy()
            df["high"] = df[["open", "close", "high"]].max(axis=1)
            df["low"] = df[["open", "close", "low"]].min(axis=1)
            n_repaired_high = (orig_high != df["high"]).sum()
            n_repaired_low = (orig_low != df["low"]).sum()
            if n_repaired_high > 0 or n_repaired_low > 0:
                logger.warning(f"修复了 {n_repaired_high} 条 high 异常, {n_repaired_low} 条 low 异常")

        # 4. 处理缺失值和重复值
        df = df.dropna(subset=["date", "close"])
        df["date"] = pd.to_datetime(df["date"])
        
        # 价格列 NaN 防护：ffill + bfill 兜底
        for col in ["open", "high", "low"]:
            if col in df.columns:
                df[col] = df[col].ffill().bfill()
        
        df = df.drop_duplicates(subset=["date"], keep="last")

        # 5. 确保成交额列存在
        if "amount" not in df.columns:
            df["amount"] = df.get("close", 0) * df.get("volume", 0)
        else:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

        # 6. 排序并重置索引
        df = df.sort_values("date").reset_index(drop=True)

        logger.info(f"数据清洗完成，共 {len(df)} 条记录")
        return df

    def clean_stock_daily(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗股票日线数据（兼容旧接口）"""
        return self.clean(df)
