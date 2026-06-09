# -*- coding: utf-8 -*-
import pandas as pd

from ...shared.logger_factory import get_logger
from ..managers.trade_calendar_manager import TradeCalendarManager
from ..managers.stock_metadata_manager import StockMetadataManager

logger = get_logger(__name__)

class DataAligner:
    """Aligns daily/intraday bars with trading calendar to handle suspensions and delisting."""

    def __init__(self, data_dir: str = "./data"):
        self.calendar_manager = TradeCalendarManager(data_dir=data_dir)
        self.metadata_manager = StockMetadataManager(data_dir=data_dir)
        self.metadata_manager.load()

    def align_stock_data(self, symbol: str, df: pd.DataFrame) -> pd.DataFrame:
        """
        Aligns the raw bar DataFrame with the official trading calendar.
        Suspended days are forward-filled for prices and zero-filled for volume/amount.
        Does not generate data prior to IPO or post Delisting.
        """
        if df.empty:
            return df

        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        clean_symbol = symbol.split(".")[0].replace("sh", "").replace("sz", "").replace("bj", "").upper()
        meta = self.metadata_manager.get_stock_info(clean_symbol)

        # Determine alignment window boundary
        start_date = df["date"].min()
        end_date = df["date"].max()

        if meta:
            if meta.ipo_date:
                try:
                    ipo_dt = pd.to_datetime(meta.ipo_date)
                    if ipo_dt > start_date:
                        start_date = ipo_dt
                except Exception as e:
                    logger.warning(f"Invalid IPO date {meta.ipo_date} for {symbol}: {e}")

            if meta.delist_date and meta.delist_date not in ("None", "0", ""):
                try:
                    delist_dt = pd.to_datetime(meta.delist_date)
                    if delist_dt < end_date:
                        end_date = delist_dt
                except Exception as e:
                    logger.warning(f"Invalid delist date {meta.delist_date} for {symbol}: {e}")

        # Fetch trade calendar dates within limits
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        calendar_df = self.calendar_manager.get_trade_calendar(start_str, end_str)

        if calendar_df.empty:
            return df[(df["date"] >= start_date) & (df["date"] <= end_date)].reset_index(drop=True)

        calendar_dates = pd.DataFrame({"date": pd.to_datetime(calendar_df["trade_date"])})

        # Keep original data in bounds
        df_bounded = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()

        # Merge with trade calendar to expose gaps (suspensions)
        merged = pd.merge(calendar_dates, df_bounded, on="date", how="left")

        # Fill identifier metadata
        if "code" in merged.columns:
            merged["code"] = merged["code"].fillna(symbol)
        else:
            merged["code"] = symbol

        # Suspensions pricing fill logic: only ffill from previous bars.
        # Do not bfill leading gaps; that would leak future prices into earlier
        # suspended days when the requested window starts during a suspension.
        price_cols = ["open", "high", "low", "close"]
        for col in price_cols:
            if col in merged.columns:
                merged[col] = merged[col].ffill()

        # Suspensions volume/amount fill logic: set to zero
        vol_cols = ["volume", "amount"]
        for col in vol_cols:
            if col in merged.columns:
                merged[col] = merged[col].fillna(0.0)

        # Fill any custom columns with ffill
        all_cols = merged.columns.tolist()
        exclude = ["date", "code"] + price_cols + vol_cols
        for col in all_cols:
            if col not in exclude:
                merged[col] = merged[col].ffill()

        return merged.sort_values("date").reset_index(drop=True)
