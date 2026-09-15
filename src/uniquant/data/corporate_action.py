"""动态复权引擎 (CorporateActionAdjuster)。

基于 data/fq/gbbq.parquet (通达信股本变迁，含分红、送转股、配股) 与
SmartFactorCalculatorV15 交易所级算法，实现高频与日线行情的动态前复权 (QFQ) / 后复权 (HFQ)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Literal, Optional

import numpy as np
import pandas as pd

from uniquant.data.utils.smart_factor_calculator import (
    GBBQProcessorV15,
    SmartFactorCalculatorV15,
)
from uniquant.shared.logger_factory import get_logger

logger = get_logger(__name__)

AdjustType = Literal["qfq", "hfq", "none"]


class CorporateActionAdjuster:
    """企业行为动态复权调整器。

    支持对单股日线数据进行实时的前复权 (QFQ) 与后复权 (HFQ) 调整。
    具备缓存与预聚合索引，支持高并发无锁只读访问。
    """

    def __init__(self, gbbq_path: Optional[str | Path] = None) -> None:
        if gbbq_path is None:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            gbbq_path = project_root / "data" / "fq" / "gbbq.parquet"
        self.gbbq_path = Path(gbbq_path)
        self.calculator = SmartFactorCalculatorV15()
        self._events_by_code: Dict[str, pd.DataFrame] = {}
        self._is_loaded = False

    def load_events(self) -> None:
        """预加载并清洗 GBBQ 数据库，按 6 位代码建立索引。"""
        if self._is_loaded:
            return

        if not self.gbbq_path.exists():
            logger.warning(f"GBBQ 文件不存在: {self.gbbq_path}，复权引擎将回退为单位矩阵。")
            self._is_loaded = True
            return

        df_clean = GBBQProcessorV15.load_and_clean(str(self.gbbq_path))
        if df_clean.empty:
            self._is_loaded = True
            return

        # 向量化单次聚合所有股票与除权日期 (0.05s 极速处理)
        agg_rules = {"cash": "sum", "split": "sum", "rights": "sum", "r_price": "max"}
        df_agg = (
            df_clean.groupby(["code", "date"])[list(agg_rules.keys())]
            .agg(agg_rules)
            .reset_index()
            .sort_values(["code", "date"])
        )
        df_agg["code"] = df_agg["code"].astype(str).str.zfill(6)

        # 转换为 code -> DataFrame 映射
        self._events_by_code = {
            code: group.reset_index(drop=True)
            for code, group in df_agg.groupby("code")
        }
        self._is_loaded = True
        logger.info(f"CorporateActionAdjuster 已加载 {len(self._events_by_code)} 只股票的除权除息底座。")

    def get_stock_events(self, symbol: str) -> pd.DataFrame:
        """获取指定股票的已清洗除权事件。"""
        if not self._is_loaded:
            self.load_events()
        code6 = symbol.split(".")[0].zfill(6)
        return self._events_by_code.get(code6, pd.DataFrame())

    def compute_factors(self, df_daily: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """计算指定股票在日线序列上的累积复权因子。

        Args:
            df_daily: 包含 date, close, open 等列的日线数据。
            symbol: 股票代码，如 '000001.SZ' 或 '000001'。

        Returns:
            DataFrame: columns=['date', 'factor', 'qfq_ratio', 'hfq_ratio']
        """
        if df_daily.empty:
            return pd.DataFrame(columns=["date", "factor", "qfq_ratio", "hfq_ratio"])

        events = self.get_stock_events(symbol)
        calc_res = self.calculator.calculate(df_daily, events)
        if calc_res.empty:
            factors = np.ones(len(df_daily), dtype=np.float64)
            dates = df_daily["date"]
        else:
            factors = calc_res["factor"].to_numpy(dtype=np.float64)
            dates = calc_res["date"]

        latest_factor = factors[-1] if len(factors) > 0 and factors[-1] > 0 else 1.0
        qfq_ratio = factors / latest_factor
        hfq_ratio = factors

        return pd.DataFrame({
            "date": dates,
            "factor": factors,
            "qfq_ratio": qfq_ratio,
            "hfq_ratio": hfq_ratio,
        })

    def adjust(
        self,
        df: pd.DataFrame,
        symbol: str,
        adjust_type: AdjustType = "qfq",
        price_cols: tuple[str, ...] = ("open", "high", "low", "close"),
    ) -> pd.DataFrame:
        """对日线行情 DataFrame 执行前复权或后复权调整。

        Args:
            df: 包含 price_cols 与 date 的 DataFrame。
            symbol: 股票代码。
            adjust_type: "qfq" (前复权), "hfq" (后复权), 或 "none" (不调整)。
            price_cols: 需要调整的价格列名元组。

        Returns:
            调整后的 DataFrame 拷贝，新增 'adj_factor' 列。
        """
        if df.empty or adjust_type in (None, "none"):
            return df

        adj_df = df.copy()
        factors_df = self.compute_factors(adj_df, symbol)
        if factors_df.empty:
            adj_df["adj_factor"] = 1.0
            return adj_df

        ratio_col = "qfq_ratio" if adjust_type == "qfq" else "hfq_ratio"
        ratio = factors_df[ratio_col].to_numpy()

        for col in price_cols:
            if col in adj_df.columns:
                adj_df[col] = adj_df[col].astype(np.float64) * ratio

        adj_df["adj_factor"] = ratio
        return adj_df


# 模块级全局单例
_GLOBAL_ADJUSTER: Optional[CorporateActionAdjuster] = None


def get_corporate_action_adjuster() -> CorporateActionAdjuster:
    """获取全局共享的 CorporateActionAdjuster 单例。"""
    global _GLOBAL_ADJUSTER
    if _GLOBAL_ADJUSTER is None:
        _GLOBAL_ADJUSTER = CorporateActionAdjuster()
        _GLOBAL_ADJUSTER.load_events()
    return _GLOBAL_ADJUSTER
