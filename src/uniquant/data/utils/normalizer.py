"""
数据标准化模块
统一处理所有数据源的输出，确保数据格式一致
"""

from typing import List

import pandas as pd

from ...shared.constants import DataSourceConstants
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    标准化列名，将各种别名映射到标准字段名
    
    Args:
        df: 原始数据
        
    Returns:
        pd.DataFrame: 列名标准化后的数据
    """
    if df is None or df.empty:
        return df
    
    df = df.copy()
    column_mapping = {}
    
    def find_standard_col(aliases: List[str], standard_name: str) -> None:
        for alias in aliases:
            if alias in df.columns and standard_name not in df.columns:
                column_mapping[alias] = standard_name
                return
    
    find_standard_col(DataSourceConstants.DATE_COLS, "date")
    find_standard_col(DataSourceConstants.OPEN_COLS, "open")
    find_standard_col(DataSourceConstants.CLOSE_COLS, "close")
    find_standard_col(DataSourceConstants.HIGH_COLS, "high")
    find_standard_col(DataSourceConstants.LOW_COLS, "low")
    find_standard_col(DataSourceConstants.VOLUME_COLS, "volume")
    find_standard_col(DataSourceConstants.AMOUNT_COLS, "amount")
    find_standard_col(DataSourceConstants.CHANGE_RATE_COLS, "change_rate")
    find_standard_col(DataSourceConstants.CHANGE_AMOUNT_COLS, "change_amount")
    find_standard_col(DataSourceConstants.PRECLOSE_COLS, "preclose")
    find_standard_col(DataSourceConstants.QFQ_FACTOR_COLS, "qfq_factor")
    find_standard_col(DataSourceConstants.HFQ_FACTOR_COLS, "hfq_factor")
    find_standard_col(DataSourceConstants.ADJ_FACTOR_COLS, "adj_factor")
    find_standard_col(DataSourceConstants.SECTOR_COLS, "sector")
    find_standard_col(DataSourceConstants.IPO_DATE_COLS, "ipo_date")
    find_standard_col(DataSourceConstants.DELIST_DATE_COLS, "delist_date")
    find_standard_col(DataSourceConstants.STOCK_TYPE_COLS, "stock_type")
    find_standard_col(DataSourceConstants.STOCK_STATUS_COLS, "stock_status")
    find_standard_col(DataSourceConstants.VOL_UNIT_COLS, "vol_unit")
    find_standard_col(DataSourceConstants.DECIMAL_POINT_COLS, "decimal_point")
    find_standard_col(DataSourceConstants.NAME_COLS, "name")
    
    if column_mapping:
        df = df.rename(columns=column_mapping)
        logger.debug(f"列名标准化映射: {column_mapping}")
    
    return df


def normalize_mootdx_columns(df: pd.DataFrame) -> pd.DataFrame:
    """标准化 mootdx 返回的列名 (本地 reader 与在线 quotes 共用)。

    §7.4 #10: 原映射同时含 'volume'→'volume' 与 'vol'→'volume'，当帧里
    两列并存时 rename 会产出重复的 volume 列（落湖即 pyarrow 报错/污染）。
    改为：仅做真正的别名重命名，且目标列已存在时不覆盖；若别名与目标列
    同时存在则保留规范列、丢弃别名，保证成交量列唯一。

    注：mootdx 输出的成交量单位是「手」，手→股换算属消费方归一化职责
    （跨资产系数不一致，见 shared/constants），此处不做硬编码 ÷100。
    """
    if df is None or df.empty:
        return df
    column_mapping = {"datetime": "date", "vol": "volume"}
    rename_map = {
        src: dst
        for src, dst in column_mapping.items()
        if src != dst and src in df.columns and dst not in df.columns
    }
    if rename_map:
        df = df.rename(columns=rename_map)
    if "vol" in df.columns and "volume" in df.columns:
        logger.warning(
            "mootdx 返回同时含 vol/volume 列，丢弃别名 vol 以保持单一成交量列"
        )
        df = df.drop(columns=["vol"])
    return df


__all__ = ["normalize_column_names", "normalize_mootdx_columns"]
