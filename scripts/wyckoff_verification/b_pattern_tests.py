"""Module B: Individual pattern tests with bootstrap confidence intervals."""

import numpy as np
import pandas as pd
from scipy import stats
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Dict, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from .config import VerifierConfig
from .a_universe import StockRecord, load_data


@dataclass
class EventStudyResult:
    hypothesis: str
    n_events: int
    n_stocks: int
    mean_excess_return: float
    ci_lower: float
    ci_upper: float
    hit_rate: float
    t_stat: float
    p_value: float
    bh_significant: bool
    bootstrap_samples: List[float] = field(default_factory=list)

    @property
    def summary(self) -> str:
        sig = "***" if self.bh_significant else ""
        return (f"  {self.hypothesis:<40} N={self.n_events:<7} "
                f"mean={self.mean_excess_return:>+7.3f}% "
                f"[{self.ci_lower:>+6.3f}, {self.ci_upper:>+6.3f}] "
                f"hit={self.hit_rate:>5.1f}% t={self.t_stat:>+5.2f} {sig}")


def detect_springs(df: pd.DataFrame, config: VerifierConfig) -> List[Dict]:
    """Detect daily-level Springs.
    
    Spring = low makes a new N-day low, then closes back above the low.
    Using N=20 (1 month) as the lookback.
    """
    events = []
    close = df["close"].values
    low = df["low"].values
    high = df["high"].values
    lookback = 20

    for i in range(lookback, len(close)):
        window_low = low[i - lookback : i].min()
        high[i - lookback : i].max()
        is_new_low = low[i] <= window_low * config.patterns.spring_low_factor
        recovered = close[i] >= window_low * config.patterns.spring_close_factor
        if is_new_low and recovered:
            events.append({
                "idx": i,
                "date": str(df["date"].iloc[i].date()),
                "price": float(close[i]),
                "low": float(low[i]),
                "window_low": float(window_low),
                "volume_ratio": float(df["volume"].iloc[i] / max(df["volume"].iloc[i - lookback : i].mean(), 1)),
            })
    return events


def detect_upthrusts(df: pd.DataFrame, config: VerifierConfig) -> List[Dict]:
    """Detect daily-level Upthrusts.
    
    Upthrust = high makes a new N-day high, then closes back below the high.
    Using N=20 lookback.
    """
    events = []
    close = df["close"].values
    low = df["low"].values
    high = df["high"].values
    lookback = 20

    for i in range(lookback, len(close)):
        window_high = high[i - lookback : i].max()
        low[i - lookback : i].min()
        is_new_high = high[i] >= window_high * config.patterns.upthrust_high_factor
        rejected = close[i] <= window_high * config.patterns.upthrust_close_factor
        if is_new_high and rejected:
            events.append({
                "idx": i,
                "date": str(df["date"].iloc[i].date()),
                "price": float(close[i]),
                "high": float(high[i]),
                "window_high": float(window_high),
                "volume_ratio": float(df["volume"].iloc[i] / max(df["volume"].iloc[i - lookback : i].mean(), 1)),
            })
    return events


def detect_volume_climax(df: pd.DataFrame, config: VerifierConfig) -> List[Dict]:
    """Detect volume climax events. 
    
    Climax = volume > 3x 20-day average and price makes significant move.
    """
    events = []
    close = df["close"].values
    volume = df["volume"].values
    lookback = 20
    vol_threshold = 3.0

    for i in range(lookback, len(close)):
        avg_vol = volume[i - lookback : i].mean()
        vol_ratio = volume[i] / avg_vol if avg_vol > 0 else 0
        if vol_ratio >= vol_threshold:
            ret_1d = (close[i] / close[i - 1] - 1) * 100
            events.append({
                "idx": i,
                "date": str(df["date"].iloc[i].date()),
                "price": float(close[i]),
                "vol_ratio": float(vol_ratio),
                "ret_1d_pct": float(ret_1d),
            })
    return events


def forward_returns(df: pd.DataFrame, event_idx: int, horizons: List[int]) -> Dict[int, float]:
    """Compute forward returns for an event at multiple horizons."""
    close = df["close"].values
    price = close[event_idx]
    result = {}
    for h in horizons:
        idx = min(event_idx + h, len(close) - 1)
        if idx > event_idx:
            result[h] = (close[idx] / price - 1) * 100
        else:
            result[h] = 0.0
    return result


def stock_event_study(
    symbol: str, df: pd.DataFrame, config: VerifierConfig
) -> Dict[str, List[float]]:
    """Run all event detections and compute forward returns for one stock."""
    result = defaultdict(list)

    springs = detect_springs(df, config)
    for ev in springs:
        fwd = forward_returns(df, ev["idx"], config.patterns.spring_forward_days)
        for h in config.patterns.spring_forward_days:
            result[f"spring_{h}d"].append(fwd[h])

    upthrusts = detect_upthrusts(df, config)
    for ev in upthrusts:
        fwd = forward_returns(df, ev["idx"], config.patterns.upthrust_forward_days)
        for h in config.patterns.upthrust_forward_days:
            result[f"upthrust_{h}d"].append(fwd[h])

    climaxes = detect_volume_climax(df, config)
    for ev in climaxes:
        fwd = forward_returns(df, ev["idx"], [20])
        result["climax_20d"].append(fwd[20])
        # Classify as buying climax (up) or selling climax (down)
        if ev["ret_1d_pct"] > 0:
            result["buying_climax_20d"].append(fwd[20])
        else:
            result["selling_climax_20d"].append(fwd[20])

    return dict(result)


def bootstrap_ci(data: np.ndarray, n_iter: int = 1000, alpha: float = 0.05) -> Tuple[float, float, float, np.ndarray]:
    """Bootstrap confidence interval for the mean."""
    if len(data) < 3:
        return float(np.mean(data)), 0.0, 0.0, np.array([])
    rng = np.random.default_rng(42)
    boots = np.zeros(n_iter)
    for i in range(n_iter):
        boots[i] = np.mean(rng.choice(data, size=len(data), replace=True))
    ci_low = np.percentile(boots, 100 * alpha / 2)
    ci_high = np.percentile(boots, 100 * (1 - alpha / 2))
    return float(np.mean(data)), float(ci_low), float(ci_high), boots


def run_pattern_tests(
    records: List[StockRecord], config: VerifierConfig
) -> List[EventStudyResult]:
    """Run all pattern tests across stratified universe."""
    print("\n=== Module B: Individual Pattern Tests ===")

    # Collect all events across all stocks (parallel)
    all_events: Dict[str, List[float]] = defaultdict(list)
    stocks_with_events: Dict[str, set] = defaultdict(set)

    n_total = len(records)
    with ProcessPoolExecutor(max_workers=config.n_jobs) as pool:
        fut_map = {}
        for rec in records:
            df = load_data(rec.symbol)
            if df is None:
                continue
            fut = pool.submit(stock_event_study, rec.symbol, df, config)
            fut_map[fut] = rec.symbol

        done = 0
        for fut in as_completed(fut_map):
            done += 1
            sym = fut_map[fut]
            try:
                result = fut.result()
                for key, vals in result.items():
                    all_events[key].extend(vals)
                    stocks_with_events[key].add(sym)
            except Exception:
                pass
            if done % 100 == 0:
                print(f"  Processed {done}/{n_total} stocks")

    # Run bootstrap tests for each hypothesis
    hypotheses = {
        "Spring 5d": "spring_5d",
        "Spring 20d": "spring_20d",
        "Spring 60d": "spring_60d",
        "Upthrust 5d": "upthrust_5d",
        "Upthrust 20d": "upthrust_20d",
        "Upthrust 60d": "upthrust_60d",
        "Volume Climax 20d": "climax_20d",
        "Buying Climax 20d": "buying_climax_20d",
        "Selling Climax 20d": "selling_climax_20d",
    }

    results = []
    p_values = []

    for label, key in hypotheses.items():
        data = np.array(all_events.get(key, []))
        n_stocks = len(stocks_with_events.get(key, set()))
        if len(data) < 10:
            results.append(EventStudyResult(
                hypothesis=label, n_events=len(data), n_stocks=n_stocks,
                mean_excess_return=0, ci_lower=0, ci_upper=0,
                hit_rate=0, t_stat=0, p_value=1.0, bh_significant=False
            ))
            p_values.append(1.0)
            continue

        mean, ci_low, ci_high, boots = bootstrap_ci(
            data, config.patterns.bootstrap_iterations, config.patterns.alpha
        )
        hit_rate = np.mean(data > 0) * 100
        t_stat, p_value = stats.ttest_1samp(data, 0)
        results.append(EventStudyResult(
            hypothesis=label, n_events=len(data), n_stocks=n_stocks,
            mean_excess_return=mean, ci_lower=ci_low, ci_upper=ci_high,
            hit_rate=hit_rate, t_stat=t_stat, p_value=p_value,
            bh_significant=False, bootstrap_samples=boots.tolist() if len(boots) > 0 else []
        ))
        p_values.append(p_value)

    # Benjamini-Hochberg correction
    p_values = np.array(p_values)
    n_tests = len(p_values)
    sorted_idx = np.argsort(p_values)
    ranks = np.arange(1, n_tests + 1)
    bh_thresholds = ranks / n_tests * config.patterns.bh_fdr
    significant = p_values[sorted_idx] <= bh_thresholds
    # Mark significant
    for i, idx in enumerate(sorted_idx):
        if i < len(significant) and significant[i]:
            results[idx].bh_significant = True

    print(f"\n  {''.join(['Event Study Results — BH FDR < ', str(config.patterns.bh_fdr)])}")
    print(f"  {'='*100}")
    for r in results:
        print(r.summary)
    print(f"  {'='*100}")

    return results
