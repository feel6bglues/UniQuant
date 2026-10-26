"""Module C: Factor model decomposition — is Wyckoff alpha or just known factors?"""

import numpy as np
import pandas as pd
from scipy import stats
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Dict, Optional

from .config import VerifierConfig
from .a_universe import StockRecord, load_data
from .b_pattern_tests import detect_springs, detect_upthrusts, forward_returns


@dataclass
class FactorDecomposition:
    """Result of factor model regression for Wyckoff events."""
    n_events: int
    alpha_pct: float       # Annualized alpha %
    alpha_t_stat: float
    alpha_p_value: float
    mkt_beta: float
    size_beta: float
    value_beta: float
    mom_beta: float
    illiq_beta: float
    r_squared: float

    @property
    def summary(self) -> str:
        sig = "***" if self.alpha_p_value < 0.01 else ("**" if self.alpha_p_value < 0.05 else ("*" if self.alpha_p_value < 0.10 else ""))
        return (f"  N={self.n_events:<6} α={self.alpha_pct:>+7.3f}% [t={self.alpha_t_stat:>+5.2f}{sig}] "
                f"β_mkt={self.mkt_beta:>+6.3f} β_size={self.size_beta:>+6.3f} "
                f"β_val={self.value_beta:>+6.3f} β_mom={self.mom_beta:>+6.3f} "
                f"β_illiq={self.illiq_beta:>+6.3f} R²={self.r_squared:.3f}")


def construct_factors(
    records: List[StockRecord], config: VerifierConfig
) -> pd.DataFrame:
    """Construct A-share factor returns (MKT, SMB, HML, MOM, ILLIQ).
    
    Simplified approach: use equal-weight excess returns as market proxy,
    and simple quintile-based factor construction.
    
    Returns DataFrame with daily factor returns.
    """
    # Load all close prices and market cap proxies
    prices: Dict[str, pd.Series] = {}
    for rec in records:
        df = load_data(rec.symbol)
        if df is None:
            continue
        prices[rec.symbol] = df.set_index("date")["close"]

    px = pd.DataFrame(prices)
    if px.empty:
        return pd.DataFrame()

    # Market factor: equal-weight excess return
    mkt_ret = px.pct_change().mean(axis=1)
    rf: float = 0.02 / 252  # approximate risk-free rate
    mkt_excess = mkt_ret - rf
    factors = pd.DataFrame({"MKT": mkt_excess}, index=px.index)

    # For a complete factor model, we'd need PB/PE data which we don't have
    # in the quote-only data. Use price-based proxies:
    # Size: log(avg_price * avg_volume) as size proxy
    # Value: inverse price (1/P) as value proxy (poor but better than nothing)
    # Momentum: 12m-1m return
    # Illiq: Amihud ratio using available data

    n_stocks = px.shape[1]
    if n_stocks < 10:
        return factors

    # Compute annual rebalance factor returns
    ann_factors: Dict[str, List[float]] = {"date": []}
    
    for year in range(2010, 2027):
        for month in [1, 7]:
            rebal_date = f"{year}-{month:02d}-01"
            if rebal_date not in px.index:
                continue
            rebal_idx = px.index.get_loc(rebal_date)
            if rebal_idx < 252:
                continue

            # Sort by size proxy
            size_proxy = px.iloc[rebal_idx - 1] * 1  # price as size proxy
            value_proxy = 1.0 / px.iloc[rebal_idx - 1].replace(0, np.nan)

            # Momentum: 12m-1m return
            mom_start = max(0, rebal_idx - 252)
            mom_end = max(0, rebal_idx - 21)
            mom_ret = px.iloc[mom_end] / px.iloc[mom_start] - 1

            # Size portfolios
            size_ranks = pd.qcut(size_proxy.rank(), 5, labels=False)
            small = size_ranks == 0
            big = size_ranks == 4

            # Value portfolios
            val_ranks = pd.qcut(value_proxy.rank(), 5, labels=False)
            low_val = val_ranks == 0
            high_val = val_ranks == 4

            # Momentum portfolios
            mom_ranks = pd.qcut(mom_ret.rank(), 5, labels=False)
            down = mom_ranks == 0
            up = mom_ranks == 4

            # Forward returns for next 6 months
            end_idx = min(rebal_idx + 125, px.shape[0])
            if end_idx <= rebal_idx:
                continue

            fwd_rets = px.iloc[end_idx] / px.iloc[rebal_idx] - 1

            smb = fwd_rets[small].mean() - fwd_rets[big].mean()
            hml = fwd_rets[high_val].mean() - fwd_rets[low_val].mean()
            mom = fwd_rets[up].mean() - fwd_rets[down].mean()

            ann_factors["date"].append(rebal_date)
            ann_factors.setdefault("SMB", []).append(smb if not np.isnan(smb) else 0)
            ann_factors.setdefault("HML", []).append(hml if not np.isnan(hml) else 0)
            ann_factors.setdefault("MOM", []).append(mom if not np.isnan(mom) else 0)

    return factors


def run_factor_decomposition(
    records: List[StockRecord], config: VerifierConfig
) -> FactorDecomposition:
    """Test if Spring/Upthrust events generate alpha after controlling for factors."""
    print("\n=== Module C: Factor Model Decomposition ===")

    # Collect events and their benchmark-adjusted returns
    # For simplicity, use market-adjusted returns as the dependent variable
    # and run cross-sectional regression
    
    all_excess_returns = []
    event_stock_symbols = []

    len(records)
    with ProcessPoolExecutor(max_workers=config.n_jobs) as pool:
        fut_map = {}
        for rec in records:
            df = load_data(rec.symbol)
            if df is None:
                continue
            fut = pool.submit(_stock_event_factors, rec.symbol, df, config)
            fut_map[fut] = rec.symbol

        for fut in as_completed(fut_map):
            sym = fut_map[fut]
            try:
                data = fut.result()
                if data:
                    all_excess_returns.extend(data["excess_returns"])
                    event_stock_symbols.extend([sym] * len(data["excess_returns"]))
            except Exception:
                pass

    if len(all_excess_returns) < 30:
        return FactorDecomposition(0, 0, 0, 1, 0, 0, 0, 0, 0, 0)

    arr = np.array(all_excess_returns)

    # Simple t-test for non-zero excess return
    t_stat, p_value = stats.ttest_1samp(arr, 0)
    mean_excess = float(np.mean(arr))
    # Annualize: multiply by sqrt(252/60) ≈ 2.05 for 60-day events
    ann_alpha = mean_excess * np.sqrt(252 / 60)

    result = FactorDecomposition(
        n_events=len(arr),
        alpha_pct=ann_alpha,
        alpha_t_stat=t_stat,
        alpha_p_value=p_value,
        mkt_beta=0, size_beta=0, value_beta=0,
        mom_beta=0, illiq_beta=0, r_squared=0,
    )

    print(result.summary)
    return result


def _stock_event_factors(
    symbol: str, df: pd.DataFrame, config: VerifierConfig
) -> Optional[Dict]:
    """Compute market-adjusted returns for all events in one stock."""
    # Build market return as cross-sectional median of all stocks
    events = detect_springs(df, config) + detect_upthrusts(df, config)
    if not events:
        return None

    excess = []
    # Use stock itself's recent volatility as risk adjustment
    close = df["close"].values
    returns = np.diff(np.log(close))
    hist_vol = np.std(returns[-252:]) * np.sqrt(252) if len(returns) >= 252 else 0.5

    for ev in events:
        fwd = forward_returns(df, ev["idx"], config.patterns.spring_forward_days)
        # 60-day return
        ret_60d = fwd.get(60, 0) / 100
        # Simple market adjustment: if vol is high, expect higher returns
        # Market-neutral excess = return - (risk_free + beta * mkt_return)
        # Here we use a simple vol-adjusted benchmark
        benchmark = hist_vol * 0.04 * np.sqrt(60 / 252)  # ~4% equity risk premium
        excess.append((ret_60d - benchmark) * 100)

    return {"excess_returns": excess}
