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

        # 1b. 输入列契约 (C1/C2 + vol/volume 双 schema) — 缺列必须显式失败,
        #     禁止静默造列 / 静默忽略, 否则污染下游 illiq_20d 因子。
        self._assert_input_contract(df)

        # 2. 类型转换
        price_cols = {"open", "high", "low", "close"}
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
                if col not in price_cols:
                    df[col] = df[col].fillna(0)

        # 2b. amount 转数值 (契约已保证列存在): NaN 原样保留 + 计数告警,
        #     禁止任何形式的 fill / close*volume 兜底 (会污染 illiq 因子)。
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        n_amount_nan = int(df["amount"].isna().sum())
        if n_amount_nan > 0:
            logger.warning(
                f"amount 存在 {n_amount_nan} 条 NaN, 原样保留 (禁止 fill/兜底, 污染 illiq 因子)"
            )

        # 3. 处理缺失值和重复值
        df = df.dropna(subset=["date", "close"])
        df["date"] = pd.to_datetime(df["date"])

        # 价格列 NaN 防护：仅 ffill (取历史值, 因果方向)。
        # C3 红线: 禁止 bfill — 首段 NaN 回填必来自未来 → 前视偏差。
        for col in ["open", "high", "low"]:
            if col in df.columns:
                df[col] = df[col].ffill()

        df = df.drop_duplicates(subset=["date"], keep="last")

        # 4. 修复 OHLC 一致性: 确保 high >= max(open, close), low <= min(open, close)
        # C4 红线: 修复条数写入 attrs 审计标记, 不加新列。
        repaired = {"high": 0, "low": 0, "open": 0, "close": 0}
        if {"open", "high", "low", "close"}.issubset(df.columns):
            orig_high = df["high"].copy()
            orig_low = df["low"].copy()
            mask_swapped = df["high"] < df["low"]
            if mask_swapped.any():
                df.loc[mask_swapped, ["high", "low"]] = df.loc[
                    mask_swapped, ["low", "high"]
                ].values
            df["high"] = df[["open", "close", "high"]].max(axis=1)
            df["low"] = df[["open", "close", "low"]].min(axis=1)
            n_repaired_high = int((orig_high != df["high"]).sum())
            n_repaired_low = int((orig_low != df["low"]).sum())
            repaired["high"] = n_repaired_high
            repaired["low"] = n_repaired_low
            if n_repaired_high > 0 or n_repaired_low > 0:
                logger.warning(f"修复了 {n_repaired_high} 条 high 异常, {n_repaired_low} 条 low 异常")

        # 5. 排序并重置索引
        df = df.sort_values("date").reset_index(drop=True)

        # 6. 审计标记 (C4): OHLC 修复计数, 供写湖/对账侧可追溯
        df.attrs["cleaner_repaired"] = repaired

        logger.info(f"数据清洗完成，共 {len(df)} 条记录")
        return df

    @staticmethod
    def _assert_input_contract(df: pd.DataFrame) -> None:
        """输入列契约校验 (C1/C2 + vol/volume 双 schema).

        Raises:
            ValueError: 缺必需列时显式失败, 消息含缺失列名与契约标识。
        """
        missing = [col for col in ("date", "close") if col not in df.columns]
        if missing:
            raise ValueError(
                f"cleaner 输入列契约违规: 缺失必需列 {missing}; "
                "cleaner 输入列契约要求日线帧至少含 date 与 close 列"
            )
        if "amount" not in df.columns:
            raise ValueError(
                "amount 缺失禁止 close*volume 兜底，污染 illiq 因子: "
                "cleaner 输入列契约要求上游数据源提供真实 amount 列"
            )
        if "volume" not in df.columns:
            if "vol" in df.columns:
                raise ValueError(
                    "cleaner 输入列契约违规: 检测到 vol/volume 双 schema — "
                    "仅存在 vol 列而无 volume 列, 请上游统一为 volume 命名"
                )
            raise ValueError(
                "cleaner 输入列契约违规: 缺失必需列 ['volume']; "
                "cleaner 输入列契约要求日线帧含 volume 列"
            )

    def clean_stock_daily(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗股票日线数据（兼容旧接口）"""
        return self.clean(df)
