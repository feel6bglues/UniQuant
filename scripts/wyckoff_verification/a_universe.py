"""Module A: Universe construction — unbiased, survivor-bias-free A-share universe."""

import pandas as pd
import numpy as np
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional

from .config import VerifierConfig, DATA_LAKE


@dataclass
class StockRecord:
    symbol: str
    n_bars: int
    date_first: str
    date_last: str
    mean_amount: float
    mean_price: float
    ann_vol: float


def scan_all_stocks(config: VerifierConfig) -> List[StockRecord]:
    """Scan every parquet file and extract basic metadata."""
    all_files = list(DATA_LAKE.glob("*.parquet"))
    print(f"  Scanning {len(all_files)} files ...")

    records = []
    for f in all_files:
        try:
            df = pd.read_parquet(f)
            if "date" not in df.columns:
                continue
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            if len(df) < config.universe.min_trading_days:
                continue
            df_train = df[df["date"] <= config.universe.train_end]
            if len(df_train) < config.universe.min_trading_days_contiguous:
                continue
            close = df["close"].values
            vol = df["volume"].values
            mean_amount = float(np.mean(close * vol)) / 1e8
            mean_price = float(np.mean(close))
            ann_vol = float(np.std(np.diff(np.log(close))) * np.sqrt(252))
            records.append(StockRecord(
                symbol=f.stem,
                n_bars=len(df),
                date_first=str(df["date"].iloc[0].date()),
                date_last=str(df["date"].iloc[-1].date()),
                mean_amount=mean_amount,
                mean_price=mean_price,
                ann_vol=ann_vol,
            ))
        except Exception:
            pass

    print(f"  Found {len(records)} stocks meeting criteria")
    return records


def load_data(symbol: str) -> Optional[pd.DataFrame]:
    """Load single stock parquet with OHLCV."""
    path = DATA_LAKE / f"{symbol}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None


def stratified_sample(
    records: List[StockRecord], n_per_stratum: int = 200, seed: int = 42
) -> List[StockRecord]:
    """Stratified sample by trading amount quintile."""
    if not records:
        return []
    rng = np.random.default_rng(seed)
    amounts = np.array([r.mean_amount for r in records])
    # log-transform for better stratification
    log_amounts = np.log10(np.maximum(amounts, 1e-6))
    bins = np.percentile(log_amounts, [20, 40, 60, 80])
    strata = np.digitize(log_amounts, bins)
    sampled = []
    for s in range(5):
        pool = [r for r, si in zip(records, strata) if si == s]
        n = min(n_per_stratum, len(pool))
        chosen = rng.choice(len(pool), size=n, replace=False)
        sampled.extend([pool[i] for i in chosen])
    return sampled


def build_universe(config: VerifierConfig) -> List[StockRecord]:
    print("=== Module A: Universe Construction ===")
    records = scan_all_stocks(config)
    # Stratified by liquidity
    sampled = stratified_sample(records, seed=config.seed)
    print(f"  Stratified sample: {len(sampled)} stocks "
          f"(5 quintiles × up to 200 each)")
    # Report liquidity coverage
    amounts = [r.mean_amount for r in sampled]
    print(f"  Amount range: {min(amounts):.2f}M — {max(amounts):.2f}M, "
          f"median={np.median(amounts):.2f}M")
    return sampled
