"""
Shared harness for autonomous alpha mining.
Provides data loading, IC/IR computation, and result logging.
Uses mootdx for local data access — no external API calls.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

# --- paths ---
PROJECT_ROOT = Path(__file__).parents[6]
LOG_FILE = PROJECT_ROOT / "MINING_LOG.md"
GRAVEYARD_FILE = PROJECT_ROOT / "MINING_GRAVEYARD.md"
AUTO_MINED_DIR = Path(__file__).parent

# suppress noisy INFO from data layer
logging.getLogger("uniquant").setLevel(logging.WARNING)
logging.getLogger("TdxSource").setLevel(logging.WARNING)

# --- liquid A-share universe (large-cap, data-rich) ---
UNIVERSE = [
    "000001", "000002", "000858", "000725", "002594",
    "300750", "600000", "600036", "601318", "600519",
    "601166", "601288", "601668", "601888", "600276",
    "600900", "601601", "002415", "600887", "601012",
]

# -------------------------------------------------------
# Data loading
# -------------------------------------------------------

def load_stock_data(symbol: str, years: int = 3) -> Optional[pd.DataFrame]:
    """Load daily OHLCV for symbol from local mootdx files.

    Returns DataFrame indexed by date with columns: open, high, low, close, volume, amount.
    Restricted to the last `years` years of data.
    Returns None on failure.
    """
    try:
        from mootdx.reader import Reader
        tdx_dir = os.path.expanduser("~/.local/share/tdxcfv/drive_c/tc")
        r = Reader.factory(market="std", tdxdir=tdx_dir)
        df = r.daily(symbol=symbol)
        if df is None or len(df) < 100:
            return None
        df.index = pd.to_datetime(df.index)
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
        df = df[df.index >= cutoff].copy()
        df = df.dropna(subset=["close", "open", "high", "low"])
        df = df[df["close"] > 0]
        # normalise column: volume might be in lots — keep as-is
        df["date"] = df.index
        return df
    except Exception as e:
        logging.warning(f"load_stock_data({symbol}): {e}")
        return None


def build_factor_panel(
    factor_func: Callable[[pd.DataFrame], pd.Series],
    symbols: List[str] = UNIVERSE,
    years: int = 3,
) -> Optional[pd.DataFrame]:
    """Build a cross-sectional panel suitable for IC analysis.

    Returns DataFrame with columns: date, code, close, factor_value.
    Rows with NaN factor values are dropped.
    Returns None if fewer than 5 stocks succeeded.
    """
    rows = []
    success = 0
    for sym in symbols:
        df = load_stock_data(sym, years=years)
        if df is None or len(df) < 60:
            continue
        try:
            factor_series = factor_func(df)
        except Exception as e:
            logging.warning(f"factor_func({sym}): {e}")
            continue
        if not isinstance(factor_series, pd.Series) or factor_series.isna().all():
            continue
        tmp = pd.DataFrame({
            "date": df.index,
            "code": sym,
            "close": df["close"].values,
            "factor_value": factor_series.values,
        })
        rows.append(tmp)
        success += 1

    if success < 30:
        return None
    panel = pd.concat(rows, ignore_index=True)
    panel = panel.dropna(subset=["factor_value"])
    return panel


# -------------------------------------------------------
# IC / ICIR computation
# -------------------------------------------------------

def compute_icir(
    panel: pd.DataFrame,
    holding_period: int = 5,
    min_stocks: int = 30,
) -> Dict[str, float]:
    """Compute cross-sectional IC series and ICIR.

    Returns dict with keys: icir, ic_mean, ic_std, ic_pos_ratio, n_periods.
    Forward returns computed from close prices.
    """
    panel = panel.sort_values(["code", "date"]).copy()
    panel["fwd_ret"] = panel.groupby("code")["close"].transform(
        lambda s: s.shift(-holding_period) / s - 1
    )
    panel = panel.dropna(subset=["factor_value", "fwd_ret"])
    # cross-sectional rank IC per date
    ic_series = (
        panel.groupby("date")
        .apply(
            lambda g: (
                stats.spearmanr(g["factor_value"], g["fwd_ret"])[0]
                if len(g) >= min_stocks and g["factor_value"].std() > 1e-12
                else np.nan
            ),
            include_groups=False,
        )
        .dropna()
    )
    if len(ic_series) < 30:
        return {"icir": 0.0, "ic_mean": 0.0, "ic_std": 0.0, "ic_pos_ratio": 0.0, "n_periods": 0}
    ic_std = ic_series.std()
    if ic_std < 1e-12:
        icir = 0.0
    else:
        icir = ic_series.mean() / ic_std
    return {
        "icir": round(float(icir), 4),
        "ic_mean": round(float(ic_series.mean()), 4),
        "ic_std": round(float(ic_std), 4),
        "ic_pos_ratio": round(float((ic_series > 0).mean()), 4),
        "n_periods": int(len(ic_series)),
    }


# -------------------------------------------------------
# Logging helpers
# -------------------------------------------------------

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def log_success(round_num: int, name: str, category: str, metrics: Dict[str, float]) -> None:
    """Append a success entry to MINING_LOG.md."""
    line = (
        f"| {round_num} | {name} | {category} "
        f"| {metrics['icir']:.4f} | {metrics['ic_mean']:.4f} "
        f"| **PASS** | {_today()} |\n"
    )
    detail = (
        f"\n### Round {round_num}: {name} — PASS\n"
        f"- ICIR@5d: **{metrics['icir']:.4f}**  IC_Mean: {metrics['ic_mean']:.4f}  "
        f"IC_Std: {metrics['ic_std']:.4f}  IC>0: {metrics['ic_pos_ratio']*100:.1f}%  "
        f"N_periods: {metrics['n_periods']}\n"
    )
    with open(LOG_FILE, "a") as f:
        f.write(detail)
    # also patch the table row (simple append approach — table was written at init)
    print(f"[PASS] Round {round_num} {name}: ICIR={metrics['icir']:.4f}")


def log_failure(round_num: int, name: str, reason: str, attempts: int) -> None:
    """Append a failure entry to MINING_GRAVEYARD.md."""
    line = f"| {round_num} | {name} | {attempts} | {reason} | {_today()} |\n"
    with open(GRAVEYARD_FILE, "a") as f:
        f.write(line)
    print(f"[FAIL] Round {round_num} {name}: {reason}")


# -------------------------------------------------------
# Circuit-breaker wrapper
# -------------------------------------------------------

MAX_ATTEMPTS = 3
PASS_ICIR_THRESHOLD = 0.4


def run_round(
    round_num: int,
    name: str,
    category: str,
    factor_func: Callable[[pd.DataFrame], pd.Series],
    holding_period: int = 5,
) -> bool:
    """Run a single mining round with circuit breaker.

    Returns True if factor passes the ICIR threshold.
    """
    print(f"\n{'='*60}")
    print(f"Round {round_num}: {name}  [{category}]")
    print(f"{'='*60}")

    last_err = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"  Attempt {attempt}/{MAX_ATTEMPTS}...")
        try:
            panel = build_factor_panel(factor_func)
            if panel is None:
                raise RuntimeError("Fewer than 30 stocks returned valid factor values")
            metrics = compute_icir(panel, holding_period=holding_period)
            print(f"  ICIR={metrics['icir']:.4f}  IC_mean={metrics['ic_mean']:.4f}  "
                  f"IC>0={metrics['ic_pos_ratio']*100:.1f}%  N={metrics['n_periods']}")
            if metrics["icir"] >= PASS_ICIR_THRESHOLD:
                log_success(round_num, name, category, metrics)
                return True
            else:
                log_failure(round_num, name,
                            f"ICIR={metrics['icir']:.4f} < {PASS_ICIR_THRESHOLD}",
                            attempt)
                return False  # no point retrying a deterministic IC calculation
        except Exception as e:
            last_err = str(e)
            print(f"  ERROR attempt {attempt}: {e}")

    log_failure(round_num, name, f"Circuit breaker: {last_err}", MAX_ATTEMPTS)
    return False
