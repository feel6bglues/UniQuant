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


def normalize_stock_data(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """
    标准化股票数据

    Args:
        df: 原始数据
        source_name: 数据源名称

    Returns:
        pd.DataFrame: 标准化后的数据
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    try:
        df = normalize_column_names(df)
        df = _convert_units(df, source_name)
        df = _correct_calculations(df, source_name)
        _validate_data(df, source_name)

        logger.info(f"成功标准化 {source_name} 数据源的数据")

    except Exception as e:
        logger.error(f"标准化数据时出错: {e}")

    return df


def _convert_units(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """
    转换数据单位

    Args:
        df: 原始数据
        source_name: 数据源名称

    Returns:
        pd.DataFrame: 转换单位后的数据
    """
    volume_unit = DataSourceConstants.VOLUME_UNITS.get(source_name, 1)
    amount_unit = DataSourceConstants.AMOUNT_UNITS.get(source_name, 1)

    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        df["volume"] = df["volume"] * volume_unit
        logger.debug(f"{source_name} 成交量单位转换: ×{volume_unit}")

    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
        df["amount"] = df["amount"] * amount_unit
        logger.debug(f"{source_name} 成交额单位转换: ×{amount_unit}")

    return df


def _correct_calculations(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """
    修正计算逻辑

    Args:
        df: 原始数据
        source_name: 数据源名称

    Returns:
        pd.DataFrame: 修正计算逻辑后的数据
    """
    if "close" not in df.columns:
        return df

    numeric_cols = ["open", "high", "low", "close", "preclose"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "preclose" in df.columns and df["preclose"].sum() > 0:
        df["change_rate"] = (
            (df["close"] - df["preclose"]) / df["preclose"] * 100
        ).fillna(0)
    else:
        prev_close = _get_previous_close(df)
        if prev_close > 0:
            df["change_rate"] = ((df["close"] - prev_close) / prev_close * 100).fillna(
                0
            )
        elif "open" in df.columns and df["open"].sum() > 0:
            df["change_rate"] = ((df["close"] - df["open"]) / df["open"] * 100).fillna(
                0
            )
        else:
            df["change_rate"] = 0

    if "high" in df.columns and "low" in df.columns:
        if "preclose" in df.columns and df["preclose"].sum() > 0:
            df["amplitude"] = ((df["high"] - df["low"]) / df["preclose"] * 100).fillna(
                0
            )
        else:
            prev_close = _get_previous_close(df)
            if prev_close > 0:
                df["amplitude"] = ((df["high"] - df["low"]) / prev_close * 100).fillna(
                    0
                )
            elif "open" in df.columns and df["open"].sum() > 0:
                df["amplitude"] = ((df["high"] - df["low"]) / df["open"] * 100).fillna(
                    0
                )
            else:
                df["amplitude"] = 0

    return df


def _get_previous_close(df: pd.DataFrame) -> float:
    """
    获取前一天的收盘价

    Args:
        df: 数据

    Returns:
        float: 前一天的收盘价
    """
    if len(df) < 2:
        return 0

    if "date" in df.columns:
        df = df.sort_values("date")

    return float(df.iloc[-2].get("close", 0))


def _validate_data(df: pd.DataFrame, source_name: str):
    """
    验证数据

    Args:
        df: 数据
        source_name: 数据源名称
    """
    required_cols = ["date", "code", "open", "high", "low", "close", "volume", "amount"]
    for col in required_cols:
        if col not in df.columns:
            logger.warning(f"{source_name} 数据源缺少必要列: {col}")

    if "volume" in df.columns:
        max_volume = df["volume"].max()
        if max_volume > 1e12:
            logger.warning(f"{source_name} 数据源成交量异常大: {max_volume}")

    if "amount" in df.columns:
        max_amount = df["amount"].max()
        if max_amount > 1e15:
            logger.warning(f"{source_name} 数据源成交额异常大: {max_amount}")

    if "close" in df.columns:
        max_close = df["close"].max()
        min_close = df["close"].min()
        if max_close > 10000 or min_close < 0.01:
            logger.warning(f"{source_name} 数据源价格异常: {min_close} - {max_close}")


def normalize_multiple_sources(data_sources: dict) -> dict:
    """
    标准化多个数据源的数据

    Args:
        data_sources: 数据源字典，格式为 {source_name: df}

    Returns:
        dict: 标准化后的数据源字典
    """
    normalized_sources = {}

    for source_name, df in data_sources.items():
        normalized_df = normalize_stock_data(df, source_name)
        normalized_sources[source_name] = normalized_df

    return normalized_sources


def compare_sources(data_sources: dict) -> dict:
    """
    比较不同数据源的数据

    Args:
        data_sources: 数据源字典，格式为 {source_name: df}

    Returns:
        dict: 比较结果
    """
    if not data_sources:
        return {}

    latest_data = {}
    for source_name, df in data_sources.items():
        if not df.empty:
            if "date" in df.columns:
                df = df.sort_values("date")
            latest_data[source_name] = df.iloc[-1]

    comparison = {}
    if latest_data:
        reference_source = (
            "baostock" if "baostock" in latest_data else list(latest_data.keys())[0]
        )
        reference_data = latest_data[reference_source]

        for source_name, data in latest_data.items():
            diffs = {}

            for col in ["close", "volume", "amount", "amplitude", "change_rate"]:
                if col in reference_data and col in data:
                    ref_value = reference_data[col]
                    curr_value = data[col]

                    if ref_value != 0:
                        diff = abs(curr_value - ref_value) / ref_value
                        diffs[col] = {
                            "reference": float(ref_value),
                            "current": float(curr_value),
                            "diff": float(diff),
                        }

            comparison[source_name] = diffs

    return comparison
