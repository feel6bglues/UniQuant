import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class DataValidator:
    """数据验证器"""

    def validate(self, df: pd.DataFrame) -> bool:
        """验证数据"""
        df = df.copy()
        if df.empty:
            logger.warning("空DataFrame传入validate方法")
            return False

        logger.info(f"开始验证数据，共 {len(df)} 条记录")

        # 1. 检查必要列
        required_cols = ["date", "code", "open", "high", "low", "close", "volume", "amount"]
        for col in required_cols:
            if col not in df.columns:
                logger.warning(f"缺少必要列: {col}")
                return False

        # 2. 智能修复逻辑
        mask_error = df["high"] < df["low"]
        if mask_error.any():
            logger.warning(f"发现 {mask_error.sum()} 条记录 High < Low，尝试修复")
            df.loc[mask_error, ["high", "low"]] = df.loc[
                mask_error, ["low", "high"]
            ].values

        if not (df["high"] >= df["low"]).all():
            logger.error("修复失败，仍有 High < Low 的记录")
            return False

        # 3. 价格逻辑关系 + 自动修复
        high_ok = (df["high"] >= df["open"]) & (df["high"] >= df["close"])
        low_ok = (df["low"] <= df["open"]) & (df["low"] <= df["close"])

        if not high_ok.all():
            n = len(df) - high_ok.sum()
            logger.warning(f"发现 {n} 条记录 High < Open/Close，自动修复")
            df["high"] = df[["high", "open", "close"]].max(axis=1)

        if not low_ok.all():
            n = len(df) - low_ok.sum()
            logger.warning(f"发现 {n} 条记录 Low > Open/Close，自动修复")
            df["low"] = df[["low", "open", "close"]].min(axis=1)

        # 4. 成交额基础校验
        if "amount" in df.columns and (df["amount"] <= 0).any():
            n_zero = (df["amount"] <= 0).sum()
            logger.warning(f"发现 {n_zero} 条记录成交额 <= 0")

        # 5. 异常值检测
        if "close" in df.columns and len(df) > 1:
            pct_change = df["close"].pct_change().abs()
            if (pct_change > 0.99).any():
                logger.warning("发现异常值，跌幅超过 99%")

        # 6. 日期连续性检查
        if "date" in df.columns:
            dates = pd.to_datetime(df["date"])
            sorted_dates = dates.sort_values()
            date_diff = sorted_dates.diff().dt.days

            if (date_diff > 14).any():
                logger.warning("发现异常长的日期间隔，可能存在数据缺失")

        # 7. 检查是否为未复权数据
        if "adjustflag" in df.columns:
            if (df["adjustflag"] == 1).any():
                n_unadj = (df["adjustflag"] == 1).sum()
                logger.warning(f"发现 {n_unadj} 条记录 adjustflag=1，数据为未复权数据")
        else:
            logger.warning("缺少 adjustflag 列，无法确认复权状态，可能为未复权数据")

        logger.info(f"数据验证完成，共 {len(df)} 条记录通过验证")
        return True

    def validate_stock_daily(self, df: pd.DataFrame) -> bool:
        """验证股票日线数据（兼容旧接口）"""
        return self.validate(df)
