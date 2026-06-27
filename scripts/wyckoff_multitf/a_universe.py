"""Universe construction: stratified sample of A-shares."""

import pandas as pd
import numpy as np
from typing import List
from dataclasses import dataclass

from .config import VerifierConfig, DATA_LAKE


@dataclass
class StockRecord:
    symbol: str
    n_bars: int
    mean_amount: float


def scan_universe(config: VerifierConfig) -> List[StockRecord]:
    all_files = list(DATA_LAKE.glob("*.parquet"))
    records = []
    for f in all_files:
        try:
            df = pd.read_parquet(f)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            if len(df) < config.min_listing_days:
                continue
            close = df["close"].values
            vol = df["volume"].values
            mean_amount = float(np.mean(close * vol)) / 1e8
            records.append(StockRecord(f.stem, len(df), mean_amount))
        except Exception:
            pass
    return records


def stratified_sample(records: List[StockRecord], n_per: int = 200, seed: int = 42) -> List[StockRecord]:
    rng = np.random.default_rng(seed)
    amounts = np.array([r.mean_amount for r in records])
    log_a = np.log10(np.maximum(amounts, 1e-6))
    bins = np.percentile(log_a, [20, 40, 60, 80])
    strata = np.digitize(log_a, bins)
    sampled = []
    for s in range(5):
        pool = [r for r, si in zip(records, strata) if si == s]
        n = min(n_per, len(pool))
        chosen = rng.choice(len(pool), size=n, replace=False)
        sampled.extend([pool[i] for i in chosen])
    return sampled


def build_universe(config: VerifierConfig) -> List[StockRecord]:
    print("=== Universe Construction ===")
    records = scan_universe(config)
    print(f"  Valid stocks: {len(records)}")
    sampled = stratified_sample(records, seed=config.seed)[:config.max_stocks]
    amounts = [r.mean_amount for r in sampled]
    print(f"  Stratified: {len(sampled)} stocks")
    print(f"  Amount: median={np.median(amounts):.2f}M, range=[{min(amounts):.2f}, {max(amounts):.2f}]M")
    return sampled