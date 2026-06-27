"""Data synthesis: daily → weekly / monthly OHLCV bars."""

import pandas as pd
import numpy as np
from typing import Tuple, Optional
from pathlib import Path


def synthesize_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Synthesize weekly OHLCV from daily data using ISO week grouping."""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    wk = df["date"].dt.isocalendar()
    df["week_key"] = wk.year.astype(str) + "-W" + wk.week.astype(str).str.zfill(2)

    agg = df.groupby("week_key", sort=False).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        amount=("amount", "sum"),
        n_days=("volume", "count"),
        date=("date", "min"),
    ).reset_index()
    agg = agg.sort_values("date").reset_index(drop=True)
    return agg


def synthesize_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Synthesize monthly OHLCV from daily data using calendar month."""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["month_key"] = df["date"].dt.to_period("M").astype(str)

    agg = df.groupby("month_key", sort=False).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        amount=("amount", "sum"),
        n_days=("volume", "count"),
        date=("date", "min"),
    ).reset_index()
    agg = agg.sort_values("date").reset_index(drop=True)
    return agg


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Unified resample entry point: 'W' for weekly, 'M' for monthly."""
    if rule == "W":
        return synthesize_weekly(df)
    elif rule == "M":
        return synthesize_monthly(df)
    return df


def load_and_synthesize(
    symbol: str, path: Path
) -> Optional[Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    """Load daily data and synthesize weekly/monthly. Returns (daily, weekly, monthly)."""
    fp = path / f"{symbol}.parquet"
    if not fp.exists():
        return None
    try:
        daily = pd.read_parquet(fp)
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.sort_values("date").reset_index(drop=True)
        if len(daily) < 200:
            return None
        weekly = synthesize_weekly(daily)
        monthly = synthesize_monthly(daily)
        return daily, weekly, monthly
    except Exception:
        return None
