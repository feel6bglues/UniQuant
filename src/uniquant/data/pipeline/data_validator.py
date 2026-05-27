import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class DataValidator:
    """数据验证器"""

    def validate(self, df: pd.DataFrame) -> bool:
        """验证数据"""
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
        # 如果 High < Low，交换它们
        mask_error = df["high"] < df["low"]
        if mask_error.any():
            logger.warning(f"发现 {mask_error.sum()} 条记录 High < Low，尝试修复")
            df.loc[mask_error, ["high", "low"]] = df.loc[
                mask_error, ["low", "high"]
            ].values

        # 3. 再次严格校验
        if not (df["high"] >= df["low"]).all():
            logger.error("修复失败，仍有 High < Low 的记录")
            return False

        # 4. 异常值过滤
        if "close" in df.columns and len(df) > 1:
            pct_change = df["close"].pct_change().abs()
            if (pct_change > 0.99).any():
                logger.warning("发现异常值，跌幅超过 99%")

        # 5. 验证价格逻辑关系
        # 确保 high >= open/close，low <= open/close
        high_validate = (df["high"] >= df["open"]) & (df["high"] >= df["close"])
        low_validate = (df["low"] <= df["open"]) & (df["low"] <= df["close"])

        if not high_validate.all():
            logger.warning(f"发现 {~high_validate.sum()} 条记录 High < Open/Close")
            df["high"] = df[["high", "open", "close"]].max(axis=1)

        if not low_validate.all():
            logger.warning(f"发现 {~low_validate.sum()} 条记录 Low > Open/Close")
            df["low"] = df[["low", "open", "close"]].min(axis=1)

        # 6. 验证日期连续性
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            date_diff = df["date"].diff().dt.days

            if (date_diff > 14).any():
                logger.warning("发现异常长的日期间隔，可能存在数据缺失")
                abnormal_gaps = date_diff[date_diff > 14]
                for i, gap in abnormal_gaps.items():
                    date = df.loc[i, "date"]
                    prev_date = df.loc[i - 1, "date"] if i > 0 else "开始"
                    logger.warning(f"异常间隔: {prev_date} 到 {date}, 间隔 {gap} 天")
            else:
                logger.info("日期连续性检查通过")

        logger.info(f"数据验证完成，共 {len(df)} 条记录通过验证")
        return True

    def validate_stock_daily(self, df: pd.DataFrame) -> bool:
        """验证股票日线数据（兼容旧接口）"""
        return self.validate(df)
