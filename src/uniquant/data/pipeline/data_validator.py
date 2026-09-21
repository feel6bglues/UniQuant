import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class DataValidator:
    """数据验证器 (只读门禁断言)

    设计原则 (QTR-OS Blueprint §4.3 / Master Audit R04):
    - 纯只读门禁: 严禁在局部副本上静默修复并虚假返回 True。
    - 发现破损帧 (如 High < Low 或 High < Open/Close) 必须严格返回 False 阻断落盘。
    - 数据的原子清洗与修复职责唯一交由 DataCleaner 负责。
    """

    def validate(self, df: pd.DataFrame) -> bool:
        """验证数据 (纯只读门禁，不修改输入数据)"""
        if df is None or df.empty:
            logger.warning("空DataFrame传入validate方法")
            return False

        logger.info(f"开始验证数据，共 {len(df)} 条记录")

        # 1. 检查必要列
        required_cols = ["date", "code", "open", "high", "low", "close", "volume", "amount"]
        for col in required_cols:
            if col not in df.columns:
                logger.warning(f"缺少必要列: {col}")
                return False

        # 1.5 核心数值非空校验 (FIX-2: 封堵 IEEE 754 下 NaN 比较恒为 False 绕过门禁漏洞)
        core_numeric_cols = ["open", "high", "low", "close", "volume"]
        if df[core_numeric_cols].isna().any().any():
            n_nan = df[core_numeric_cols].isna().sum().to_dict()
            logger.error(f"数据验证失败: 核心行情列存在 NaN 缺失值: {n_nan}")
            return False

        # 2. 价格极值逻辑校验 (只读硬阻断，严禁返回 True 掩盖)
        if (df["high"] < df["low"]).any():
            n_err = (df["high"] < df["low"]).sum()
            logger.error(f"数据验证失败: 发现 {n_err} 条记录 High < Low")
            return False

        # 3. 价格逻辑关系校验 (High >= Open/Close, Low <= Open/Close)
        high_invalid = (df["high"] < df["open"]) | (df["high"] < df["close"])
        if high_invalid.any():
            n_err = high_invalid.sum()
            logger.error(f"数据验证失败: 发现 {n_err} 条记录 High < Open/Close")
            return False

        low_invalid = (df["low"] > df["open"]) | (df["low"] > df["close"])
        if low_invalid.any():
            n_err = low_invalid.sum()
            logger.error(f"数据验证失败: 发现 {n_err} 条记录 Low > Open/Close")
            return False

        # 4. 成交量非负校验
        if (df["volume"] < 0).any():
            logger.error("数据验证失败: 发现成交量 volume < 0")
            return False

        # 5. 成交额基础告警 (不阻断, 仅遥测告警)
        if (df["amount"] <= 0).any():
            n_zero = (df["amount"] <= 0).sum()
            logger.warning(f"发现 {n_zero} 条记录成交额 <= 0")

        # 6. 异常值检测 (单日振幅 > 99%)
        if len(df) > 1:
            pct_change = df["close"].pct_change().abs()
            if (pct_change > 0.99).any():
                logger.warning("发现异常值，涨跌幅超过 99%")

        # 7. 日期连续性检查
        dates = pd.to_datetime(df["date"])
        sorted_dates = dates.sort_values()
        date_diff = sorted_dates.diff().dt.days
        if (date_diff > 14).any():
            logger.warning("发现异常长的日期间隔，可能存在数据缺失")

        # 8. 检查是否为未复权数据
        if "adjustflag" in df.columns:
            if (df["adjustflag"] == 1).any():
                n_unadj = (df["adjustflag"] == 1).sum()
                logger.warning(f"发现 {n_unadj} 条记录 adjustflag=1，数据为未复权数据")
        else:
            logger.warning("缺少 adjustflag 列，无法确认复权状态，可能为未复权数据")

        logger.info(f"数据验证完成，共 {len(df)} 条记录通过只读验证")
        return True

    def validate_stock_daily(self, df: pd.DataFrame) -> bool:
        """验证股票日线数据（兼容旧接口）"""
        return self.validate(df)
