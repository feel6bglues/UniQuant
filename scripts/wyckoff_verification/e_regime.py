"""Module E: Regime decomposition — market regime dependent Wyckoff efficacy."""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from .config import VerifierConfig


@dataclass
class RegimeResult:
    regime_name: str
    n_days: int
    pct_of_period: float
    n_stocks_active: int
    mean_return_pct: float
    strategy_sharpe: float


def compute_sh_index_returns(config: VerifierConfig) -> Optional[pd.DataFrame]:
    """Compute SH-Index daily returns for regime detection."""
    try:
        from .a_universe import load_data
        df = load_data("000001.SH")
        if df is None:
            return None
        df["ret"] = df["close"].pct_change()
        return df[["date", "ret"]].dropna()
    except Exception:
        return None


def simple_regime_classification(config: VerifierConfig) -> Dict[str, Tuple[str, str]]:
    """Simple rule-based regime classification for A-share market periods.
    
    Returns dict of date_range -> regime_name
    """
    regimes = {
        # Bear → Bull transitions
        ("2015-01-01", "2015-06-15"): "bull",
        ("2015-06-15", "2016-02-29"): "bear",  # Crash
        ("2016-03-01", "2018-01-31"): "bull",  # Recovery
        ("2018-02-01", "2019-01-31"): "bear",  # Trade war
        ("2019-02-01", "2021-02-19"): "bull",  # Post-trade war + COVID recovery
        ("2021-02-20", "2022-10-31"): "bear",  # Regulatory crackdown
        ("2022-11-01", "2023-04-30"): "bull",  # Reopening rally
        ("2023-05-01", "2024-09-30"): "sideways",  # Range-bound
        ("2024-10-01", "2025-06-30"): "bull",  # Stimulus rally
        ("2025-07-01", "2026-06-18"): "sideways",  # Current
    }
    return regimes


def get_regime_for_date(date_str: str, regimes: Dict) -> str:
    """Classify a single date into a regime."""
    from datetime import datetime
    d = datetime.strptime(str(date_str).split()[0], "%Y-%m-%d")
    for (start, end), regime in regimes.items():
        sd = datetime.strptime(start, "%Y-%m-%d")
        ed = datetime.strptime(end, "%Y-%m-%d")
        if sd <= d <= ed:
            return regime
    return "unknown"


def run_regime_analysis(
    strategy_results: List, config: VerifierConfig
) -> Dict[str, RegimeResult]:
    """Decompose strategy performance by market regime."""
    print("\n=== Module E: Regime Decomposition ===")

    regimes = simple_regime_classification(config)
    
    # Aggregate all trades by regime
    regime_trades: Dict[str, List[float]] = defaultdict(list)
    regime_stocks: Dict[str, set] = defaultdict(set)

    for r in strategy_results:
        for t in r.trades:
            regime = get_regime_for_date(t.entry_date, regimes)
            regime_trades[regime].append(t.pnl_pct)
            regime_stocks[regime].add(r.symbol)

    print(f"\n  Regime Analysis:")
    print(f"  {'Regime':<12} {'Trades':<8} {'Stocks':<8} {'Mean PnL%':<12} {'Win Rate':<10}")
    print(f"  {'-'*50}")
    
    results = {}
    for regime in ["bull", "bear", "sideways", "unknown"]:
        trades = regime_trades.get(regime, [])
        if not trades:
            continue
        n_stocks = len(regime_stocks.get(regime, set()))
        mean_pnl = float(np.mean(trades))
        win_rate = sum(1 for t in trades if t > 0) / len(trades) * 100
        print(f"  {regime:<12} {len(trades):<8} {n_stocks:<8} {mean_pnl:<+12.2f} {win_rate:<10.1f}%")
        results[regime] = RegimeResult(
            regime_name=regime,
            n_days=0,
            pct_of_period=0,
            n_stocks_active=n_stocks,
            mean_return_pct=mean_pnl,
            strategy_sharpe=0,
        )

    return results
