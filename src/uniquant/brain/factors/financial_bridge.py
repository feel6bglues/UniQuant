"""
财务因子桥接器
将财务 Parquet 的中文字段映射为标准因子，并计算 PE_TTM / PB
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Any

import numpy as np
import pandas as pd

from ...shared.error_handling import handle_errors
from ...shared.logger_factory import get_logger

logger = get_logger("FinancialFactorBridge")


@dataclass
class FieldMapping:
    """字段映射配置"""
    chinese_name: str
    standard_name: str
    data_type: str = "float"


FINANCIAL_FIELD_MAPPINGS: List[FieldMapping] = [
    FieldMapping("基本每股收益", "eps", "float"),
    FieldMapping("扣除非经常性损益每股收益", "eps_deducted", "float"),
    FieldMapping("每股未分配利润", "retained_eps", "float"),
    FieldMapping("每股净资产", "bps", "float"),
    FieldMapping("每股资本公积金", "capital_reserve_ps", "float"),
    FieldMapping("净资产收益率", "roe", "float"),
    FieldMapping("每股经营现金流量", "ocf_ps", "float"),
    FieldMapping("货币资金", "cash", "float"),
    FieldMapping("营业收入", "revenue", "float"),
    FieldMapping("营业利润", "operating_profit", "float"),
    FieldMapping("利润总额", "total_profit", "float"),
    FieldMapping("净利润", "net_profit", "float"),
    FieldMapping("扣除非经常性损益净利润", "net_profit_deducted", "float"),
    FieldMapping("归属母公司所有者的净利润", "net_profit_parent", "float"),
    FieldMapping("销售毛利率", "gross_margin", "float"),
    FieldMapping("销售净利率", "net_margin", "float"),
    FieldMapping("资产负债率", "debt_ratio", "float"),
    FieldMapping("流动比率", "current_ratio", "float"),
    FieldMapping("速动比率", "quick_ratio", "float"),
    FieldMapping("总资产", "total_assets", "float"),
    FieldMapping("总负债", "total_liabilities", "float"),
    FieldMapping("股东权益", "equity", "float"),
    FieldMapping("经营活动产生的现金流量净额", "ocf", "float"),
    FieldMapping("投资活动产生的现金流量净额", "icf", "float"),
    FieldMapping("筹资活动产生的现金流量净额", "fcf", "float"),
]

FIELD_MAPPING_DICT: Dict[str, str] = {m.chinese_name: m.standard_name for m in FINANCIAL_FIELD_MAPPINGS}

FINANCIAL_FIELD_ALIASES: Dict[str, List[str]] = {
    "total_assets": ["总资产", "资产总计"],
    "total_liabilities": ["总负债", "负债合计"],
    "equity": ["股东权益", "所有者权益（或股东权益）合计", "归属于母公司股东权益(资产负债表)"],
    "net_profit_parent": ["归属母公司所有者的净利润", "归属于母公司所有者的净利润", "归属于母公司所有者的净利润.1"],
    "total_profit": ["利润总额", "四、利润总额"],
    "debt_ratio": ["资产负债率", "资产负债率(%)"],
    "current_ratio": ["流动比率", "流动比率(非金融类指标)"],
    "quick_ratio": ["速动比率", "速动比率(非金融类指标)"],
    "gross_margin": ["销售毛利率", "销售毛利率(%)(非金融类指标)"],
    "net_margin": ["销售净利率", "销售净利率(%)", "净利润率(非金融类指标)"],
    "net_profit_deducted": ["扣除非经常性损益净利润", "扣除非经常性损益后的净利润", "扣除非经常性损益后的净利润.1"],
}

ANNOUNCEMENT_DATE_COLS = [
    "财报公告日期",
    "业绩快报公告日期",
    "业绩预告公告日期 ",
    "业绩预告公告日期",
]

MARKET_SUFFIX_MAP = {
    "60": "SH",
    "68": "SH",
    "00": "SZ",
    "30": "SZ",
    "43": "BJ",
    "83": "BJ",
    "87": "BJ",
}



def _report_year_series(s: pd.Series) -> pd.Series:
    """报告期序列 → 年份整数序列 (datetime / int YYYYMMDD / str 均可)。"""
    if pd.api.types.is_datetime64_any_dtype(s):
        return s.dt.year.astype(int)
    if pd.api.types.is_numeric_dtype(s):
        return s.astype("int64") // 10000
    return s.astype(str).str.slice(0, 4).astype(int)


class FinancialFactorBridge:
    """
    财务因子桥接器
    
    功能:
    1. 中文字段映射为标准英文字段
    2. TTM 滚动计算 (最近4个季度累加)
    3. PE_TTM / PB 计算
    4. 日频 merge_asof 合并
    """
    
    EPS_TTM_WINDOW = 4
    MERGE_TOLERANCE_DAYS = "7D"
    
    def __init__(self):
        self.field_mapping = FIELD_MAPPING_DICT.copy()
        self.alias_to_standard = self._build_alias_mapping()
        logger.info(f"FinancialFactorBridge initialized with {len(self.field_mapping)} field mappings")

    def _build_alias_mapping(self) -> Dict[str, str]:
        alias_mapping = FIELD_MAPPING_DICT.copy()
        for standard_name, aliases in FINANCIAL_FIELD_ALIASES.items():
            for alias in aliases:
                alias_mapping[alias] = standard_name
        return alias_mapping

    def _normalize_code(self, code: Any) -> Any:
        if pd.isna(code):
            return code

        code_str = str(code).strip().upper()
        if not code_str:
            return code

        if "." in code_str:
            left, right = code_str.split(".", 1)
            if right in {"SH", "SZ", "BJ"} and left.isdigit():
                return f"{left.zfill(6)}.{right}"
            if left in {"SH", "SZ", "BJ"} and right.isdigit():
                return f"{right.zfill(6)}.{left}"

        digits = "".join(ch for ch in code_str if ch.isdigit())
        if len(digits) > 6:
            digits = digits[-6:]
        digits = digits.zfill(6)

        suffix = None
        for prefix, market in MARKET_SUFFIX_MAP.items():
            if digits.startswith(prefix):
                suffix = market
                break

        return f"{digits}.{suffix}" if suffix else digits

    def _normalize_codes(self, df: pd.DataFrame) -> pd.DataFrame:
        if "code" in df.columns:
            df["code"] = df["code"].map(self._normalize_code)
        return df

    def _normalize_date_series(self, series: pd.Series) -> pd.Series:
        as_str = series.astype(str).str.strip()
        parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")

        len8_mask = as_str.str.fullmatch(r"\d{8}")
        if len8_mask.any():
            parsed.loc[len8_mask] = pd.to_datetime(as_str.loc[len8_mask], format="%Y%m%d", errors="coerce")

        len6_mask = parsed.isna() & as_str.str.fullmatch(r"\d{6}")
        if len6_mask.any():
            parsed.loc[len6_mask] = pd.to_datetime(as_str.loc[len6_mask], format="%y%m%d", errors="coerce")

        fallback_mask = parsed.isna()
        if fallback_mask.any():
            parsed.loc[fallback_mask] = pd.to_datetime(series.loc[fallback_mask], errors="coerce")

        return parsed

    def _resolve_price_col(self, daily_df: pd.DataFrame, price_col: str) -> str:
        if price_col in daily_df.columns:
            return price_col

        fallback_cols = ["qfq_close", "close"]
        for fallback in fallback_cols:
            if fallback in daily_df.columns:
                logger.info(f"Price column {price_col} missing, fallback to {fallback}")
                return fallback

        raise ValueError(f"daily_df must contain one of {fallback_cols}")

    @staticmethod
    def _apply_report_date_offset(date_series: pd.Series) -> pd.Series:
        month = date_series.dt.month
        result = date_series.copy()
        result.loc[month == 3] = date_series.loc[month == 3] + pd.DateOffset(months=3)
        result.loc[month == 6] = date_series.loc[month == 6] + pd.DateOffset(months=2)
        result.loc[month == 9] = date_series.loc[month == 9] + pd.DateOffset(months=3)
        result.loc[month == 12] = date_series.loc[month == 12] + pd.DateOffset(months=4)
        return result

    def _get_effective_date_col(self, financial_df: pd.DataFrame) -> str:
        for col in ANNOUNCEMENT_DATE_COLS:
            if col in financial_df.columns:
                effective_col = "__effective_date"
                financial_df[effective_col] = self._normalize_date_series(financial_df[col])
                nan_mask = financial_df[effective_col].isna()
                financial_df.loc[nan_mask, effective_col] = self._apply_report_date_offset(
                    financial_df.loc[nan_mask, "report_date"]
                )
                earlier_than_report = financial_df[effective_col] < financial_df["report_date"]
                financial_df.loc[earlier_than_report, effective_col] = financial_df.loc[earlier_than_report, "report_date"]
                return effective_col

        effective_col = "__effective_date"
        financial_df[effective_col] = self._apply_report_date_offset(financial_df["report_date"])
        return effective_col
    
    def map_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        映射中文字段名为标准英文名
        
        Args:
            df: 原始财务数据 DataFrame
            
        Returns:
            映射后的 DataFrame
        """
        if df.empty:
            return df
        
        df = df.copy()
        rename_cols = {}
        
        for col in df.columns:
            if col in self.alias_to_standard:
                rename_cols[col] = self.alias_to_standard[col]
        
        if rename_cols:
            df = df.rename(columns=rename_cols)
            logger.debug(f"Mapped {len(rename_cols)} columns: {rename_cols}")

        df = self._normalize_codes(df)
        
        return df
    
    def calculate_eps_ttm(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 TTM EPS (最近4个季度累加)
        
        Args:
            df: 财务数据 DataFrame，需包含 eps, report_date, code
            
        Returns:
            添加 eps_ttm 列的 DataFrame
        """
        if df.empty or "eps" not in df.columns:
            return df

        df = df.copy()
        df = df.sort_values(["code", "report_date"])

        # 财报行为同年累计值(YTD, TDX/东财口径实测确认):
        # 先按年边界差分为单季, 再滚动 4 季求和。跨年 Q1 为新累计起点, 直接保留。
        years = _report_year_series(df["report_date"])
        prev_same_code_same_year = (
            df["code"].eq(df["code"].shift(1)) & years.eq(years.shift(1))
        )
        single_quarter = df["eps"].where(
            ~prev_same_code_same_year, df["eps"] - df["eps"].shift(1)
        )
        df["eps_ttm"] = single_quarter.groupby(df["code"]).transform(
            lambda x: x.rolling(window=self.EPS_TTM_WINDOW, min_periods=1).sum()
        )

        logger.debug(f"Calculated eps_ttm for {len(df)} records")
        return df
    
    def calculate_pe_pb(
        self,
        daily_df: pd.DataFrame,
        financial_df: pd.DataFrame,
        price_col: str = "qfq_close"
    ) -> pd.DataFrame:
        """
        计算 PE_TTM 和 PB
        
        Args:
            daily_df: 日线数据 DataFrame，需包含 date, code, qfq_close
            financial_df: 财务数据 DataFrame，需包含 report_date, code, eps_ttm, bps
            price_col: 价格列名
            
        Returns:
            合并后的 DataFrame，包含 pe_ttm, pb 列
        """
        if daily_df.empty:
            logger.warning("Daily DataFrame is empty")
            return pd.DataFrame()
        
        if financial_df.empty:
            logger.warning("Financial DataFrame is empty")
            return daily_df.copy()
        
        daily_df = daily_df.copy()
        financial_df = financial_df.copy()
        
        if "date" not in daily_df.columns:
            raise ValueError("daily_df must contain 'date' column")
        price_col = self._resolve_price_col(daily_df, price_col)
        
        daily_df["date"] = pd.to_datetime(daily_df["date"])
        
        if "report_date" in financial_df.columns:
            financial_df["report_date"] = self._normalize_date_series(financial_df["report_date"])
        else:
            raise ValueError("financial_df must contain 'report_date' column")
        
        required_fin_cols = ["code", "report_date"]
        for col in required_fin_cols:
            if col not in financial_df.columns:
                raise ValueError(f"financial_df missing required column: {col}")

        daily_df = self._normalize_codes(daily_df)
        financial_df = self._normalize_codes(financial_df)
        effective_date_col = self._get_effective_date_col(financial_df)
        
        fin_cols = ["code", "report_date"]
        if effective_date_col != "report_date":
            fin_cols.append(effective_date_col)
        if "eps_ttm" in financial_df.columns:
            fin_cols.append("eps_ttm")
        if "bps" in financial_df.columns:
            fin_cols.append("bps")
        
        fin_subset = financial_df[fin_cols].drop_duplicates(subset=["code", "report_date"])
        fin_subset = fin_subset.sort_values(effective_date_col)
        
        result_frames = []
        
        for code in daily_df["code"].unique():
            daily_code = daily_df[daily_df["code"] == code].copy()
            daily_code = daily_code.sort_values("date")
            
            fin_code = fin_subset[fin_subset["code"] == code].copy()
            
            if fin_code.empty:
                daily_code["pe_ttm"] = np.nan
                daily_code["pb"] = np.nan
                result_frames.append(daily_code)
                continue
            
            try:
                merged = pd.merge_asof(
                    daily_code,
                    fin_code,
                    left_on="date",
                    right_on=effective_date_col,
                    by="code",
                    direction="backward",
                )
                
                if "eps_ttm" in merged.columns and price_col in merged.columns:
                    eps_ttm = merged["eps_ttm"].replace(0, np.nan)
                    merged["pe_ttm"] = merged[price_col] / eps_ttm
                    merged.loc[eps_ttm <= 0, "pe_ttm"] = np.nan
                
                if "bps" in merged.columns and price_col in merged.columns:
                    bps = merged["bps"].replace(0, np.nan)
                    merged["pb"] = merged[price_col] / bps
                    merged.loc[bps <= 0, "pb"] = np.nan

                if effective_date_col in merged.columns and effective_date_col != "report_date":
                    merged = merged.drop(columns=[effective_date_col])
                
                result_frames.append(merged)
                
            except Exception as e:
                logger.warning(f"merge_asof failed for {code}: {e}")
                daily_code["pe_ttm"] = np.nan
                daily_code["pb"] = np.nan
                result_frames.append(daily_code)
        
        if not result_frames:
            return pd.DataFrame()
        
        result = pd.concat(result_frames, ignore_index=True)
        logger.info(f"Calculated PE_TTM/PB for {len(result)} records")
        
        return result
    
    def process(
        self,
        daily_df: pd.DataFrame,
        financial_df: pd.DataFrame,
        price_col: str = "qfq_close"
    ) -> pd.DataFrame:
        """
        完整处理流程: 字段映射 → TTM计算 → PE/PB计算 → 合并
        
        Args:
            daily_df: 日线数据 DataFrame
            financial_df: 财务数据 DataFrame
            price_col: 价格列名
            
        Returns:
            合并后的 DataFrame
        """
        financial_mapped = self.map_fields(financial_df)
        
        financial_with_ttm = self.calculate_eps_ttm(financial_mapped)
        
        result = self.calculate_pe_pb(daily_df, financial_with_ttm, price_col)
        
        return result
    
    @handle_errors(ValueError, KeyError, TypeError, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def get_latest_factors(self, financial_df: pd.DataFrame) -> pd.DataFrame:
        """
        获取每只股票最新的财务因子
        
        Args:
            financial_df: 财务数据 DataFrame
            
        Returns:
            最新财务因子 DataFrame (每个 code 一行)
        """
        if financial_df.empty:
            return pd.DataFrame()
        
        df = self.map_fields(financial_df)
        
        if "report_date" not in df.columns or "code" not in df.columns:
            logger.warning("Missing report_date or code column")
            return pd.DataFrame()
        
        df = df.sort_values("report_date")
        
        factor_cols = [m.standard_name for m in FINANCIAL_FIELD_MAPPINGS]
        available_cols = [c for c in factor_cols if c in df.columns]
        
        result = df.groupby("code").last()[available_cols].reset_index()
        
        logger.info(f"Got latest factors for {len(result)} stocks")
        return result
