"""
[DEPRECATED] 旧版策略回测 — 请使用 UnifiedResearchPipeline

此文件中的 run_backtest 函数已被 UnifiedResearchPipeline 替代。
新流水线特性:
  - 强类型信号: List[TradingSignal]
  - 全链路贯通: Brain → Adapter → Engine
  - A 股防线: T+1/涨跌停/停牌/资金不透支
"""

import csv
import functools
import math
import random
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from uniquant.data.manager import DataManager
from uniquant.data.tdx_loader import load_tdx_data
from uniquant.hands.strategies.registry import STRATEGY_MAP
from uniquant.shared.backtest_utils import filter_suspended
from uniquant.shared.constants import RANDOM_SEED
from uniquant.shared.logger_factory import get_logger
from uniquant.shared.time_provider import get_time_provider
from uniquant.shared.limits import is_limit_down, is_limit_up
from uniquant.shared.cost_model import (
    COMMISSION_PCT,
    COST_BUY,
    MIN_COMMISSION,
    STAMP_TAX_PCT,
    STAMP_TAX_PCT_OLD,
    TRANSFER_FEE_PCT,
)
from uniquant.shared.parallel import get_optimal_workers, worker_init
from uniquant.shared.risk_constants import RISK_FREE_RATE

warnings.warn(
    "hands.strategies.backtest is deprecated. Use UnifiedResearchPipeline from "
    "uniquant.services.research_pipeline instead.",
    DeprecationWarning,
    stacklevel=2,
)

logger = get_logger("backtest")
TDX_DATA_DIR = Path(__file__).resolve().parents[3] / "data"

# Stamp tax rate change date: 2023-08-28
# Before this date: 0.1% (千1), on/after: 0.05% (万5)
_STAMP_TAX_CUTOFF = "2023-08-28"


def _get_stamp_tax(trade_date: str) -> float:
    """Return stamp tax rate based on trade date.

    2023-08-28 起印花税由千1降为万5。
    """
    if trade_date < _STAMP_TAX_CUTOFF:
        return STAMP_TAX_PCT_OLD  # 0.001
    return STAMP_TAX_PCT  # 0.0005
MC_SIMS = 10000

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STOCK_LIST_PATH = PROJECT_ROOT / "data" / "all_stock_codes.csv"
CSI300_CONST_PATH = PROJECT_ROOT / "data" / "csi300_constituents.csv"


def _load_csi300_history_snapshot(as_of_date: str) -> Optional[set]:
    p = PROJECT_ROOT / "data" / "csi300_history.json"
    if not p.exists():
        return None
    try:
        import json
        history = json.loads(p.read_text())
        candidates = [d for d in sorted(history.keys()) if d <= as_of_date[:10].replace("-", "")]
        if not candidates:
            return None
        return set(c.zfill(6) for c in history[candidates[-1]])
    except Exception:
        logger.warning("Failed to load blacklist from %s", p, exc_info=True)
        return None


def ensure_csi300_history_snapshot() -> None:
    p = PROJECT_ROOT / "data" / "csi300_history.json"
    if p.exists():
        logger.debug("CSI300 history snapshot found at %s", p)
        return
    logger.warning(
        "CSI300 history snapshot not found at %s. "
        "Offline reproducibility requires pre-built snapshot. "
        "Run: python scripts/tools/build_csi300_snapshots.py",
        p,
    )


def _load_csi300_snapshot() -> set:
    if not CSI300_CONST_PATH.exists():
        logger.warning("CSI300 constituents file not found at %s. Falling back to stock_list.csv.", CSI300_CONST_PATH)
        if STOCK_LIST_PATH.exists():
            codes = set()
            try:
                with STOCK_LIST_PATH.open("r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        c = row.get("code", "").strip()
                        if c:
                            codes.add(c.zfill(6))
                logger.warning(
                    "CSI300 constituents file not found. "
                    "Fallback loaded %d codes from stock_list.csv — "
                    "these may NOT all be CSI300 constituents, "
                    "result may include non-CSI300 stocks.", len(codes)
                )
                return codes
            except Exception as e:
                logger.warning("Failed to load fallback codes from stock_list.csv: %s", e)
        return set()
    codes = set()
    with CSI300_CONST_PATH.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            codes.add(row["stock_code"].strip().zfill(6))
    return codes


@functools.lru_cache(maxsize=256)
def load_csi300_constituents(as_of_date: str | None = None) -> set:
    """加载沪深300成分股代码集合

    Parameters
    ----------
    as_of_date : str, optional
        If provided, returns constituents as of this date via akshare.
        Falls back to the local snapshot if the API call fails.
    """
    if as_of_date is not None:
        local = _load_csi300_history_snapshot(as_of_date)
        if local is not None:
            return local
        try:
            import akshare as ak
            df = ak.index_stock_cons(symbol="000300", date=as_of_date)
            codes = set(df["stock_code"].str.strip().str.zfill(6))
            logger.info("Loaded %d CSI300 constituents for %s via akshare", len(codes), as_of_date)
            return codes
        except Exception:
            logger.warning(
                "akshare CSI300 history failed for %s, using local snapshot", as_of_date
            )
    return _load_csi300_snapshot()


def load_stocks(csv_path: Path, limit: int = 99999, index_only: bool = False) -> List[Dict]:
    csi300_codes = load_csi300_constituents() if index_only else set()
    syms = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            c = row.get("code", "").strip()
            m = row.get("market", "").strip().upper()
            n = row.get("name", "").replace("\x00", "").strip()
            if not (c.isdigit() and len(c) == 6 and m in {"SH", "SZ"}):
                continue
            is_st_flag = n.startswith(("*ST", "ST"))
            if c.startswith(("600", "601", "603", "605", "688", "689",
                             "000", "001", "002", "003", "300", "301", "302")):
                if index_only and c not in csi300_codes:
                    continue
                syms.append({"symbol": f"{c}.{m}", "code": c, "market": m, "name": n, "is_st": is_st_flag})
                if len(syms) >= limit:
                    break
    if index_only:
        logger.info("Filtered to %d CSI300 constituent stocks (from %d total)", len(syms),
                     sum(1 for _ in open(csv_path, encoding="utf-8-sig")))
    return syms


def load_csi300() -> Optional[pd.DataFrame]:
    if not TDX_DATA_DIR:
        return None
    p = Path(TDX_DATA_DIR) / "sh" / "lday" / "sh000300.day"
    if not p.exists():
        return None
    df = load_tdx_data(str(p))
    if df is not None and not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    return None


def gen_windows(csi: pd.DataFrame, n: int = 20, min_year: int = 0, max_year: int = 9999,
                seed: int = RANDOM_SEED, method: str = "walk_forward") -> List[str]:
    if csi is None or len(csi) < 200:
        return []
    d = csi["date"].dt.strftime("%Y-%m-%d").tolist()
    d = [x for x in d if int(x[:4]) >= min_year and int(x[:4]) <= max_year]
    if method == "walk_forward":
        seen = {}
        for date_str in sorted(d[:len(d) - 200]):
            month_key = date_str[:7]
            if month_key not in seen:
                seen[month_key] = date_str
        all_months = sorted(seen.values())
        if len(all_months) <= n:
            return all_months
        step = max(1, len(all_months) // n)
        return [all_months[i] for i in range(0, len(all_months), step)][:n]
    else:
        if len(d) < n + 200:
            return []
        random.seed(seed)
        return sorted(random.sample(d[:len(d) - 200], min(n, len(d) - 200)))


def ann_sharpe(rets: np.ndarray, avg_days: float, rf: float = RISK_FREE_RATE) -> float:
    if len(rets) < 5 or np.std(rets) == 0 or avg_days <= 0:
        return 0.0
    rf_per_period = rf * avg_days / 252.0
    excess = np.mean(rets) - rf_per_period
    return float(excess / np.std(rets) * math.sqrt(252.0 / avg_days))


def _block_bootstrap(
    rets: np.ndarray,
    block_size: int = 20,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    n = len(rets)
    n_blocks = int(np.ceil(n / block_size))
    blocks = [rets[i:i+block_size] for i in range(0, n, block_size)]
    rng = rng or np.random.default_rng(RANDOM_SEED)
    sampled = rng.choice(len(blocks), size=n_blocks, replace=True)
    result = np.concatenate([blocks[i] for i in sampled])[:n]
    return result


def compute_stats(sub_df: pd.DataFrame) -> Dict:
    rets = sub_df["ret"].values
    ad = float(np.mean(sub_df["days"]))
    return {
        "n": len(sub_df),
        "mean_ret": round(float(np.mean(rets)), 2),
        "median_ret": round(float(np.median(rets)), 2),
        "std": round(float(np.std(rets)), 2),
        "win_rate": round(float(sum(rets > 0) / len(rets) * 100), 1),
        "avg_days": round(ad, 1),
        "sharpe": round(ann_sharpe(rets, ad), 3),
    }


def process_stock(args: Tuple) -> List[Dict]:
    si, windows, csi, strategies, cost_buy, cost_sell_base, index_only = args
    sym = si["symbol"]
    code = si.get("code", "")
    is_st = si.get("is_st", False)
    code_prefix = code[:3] if code else ""
    trades = []
    error_count = 0
    try:
        dm = DataManager()
        df = dm.get_data(sym)
        if df is None or df.empty or len(df) < 300:
            return trades
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        df = filter_suspended(df)
        if df.empty or len(df) < 300:
            return trades

        # Calculate runtime limit-down ratio for liquidity risk
        try:
            limit_down_count = 0
            for i in range(1, len(df)):
                if is_limit_down({"close": df.iloc[i]["close"]}, df.iloc[i-1]["close"], code_prefix, is_st=is_st):
                    limit_down_count += 1
            limit_down_ratio = limit_down_count / len(df) if len(df) > 0 else 0.0
            if limit_down_ratio > 0.03:
                logger.warning(
                    "LiquidityRisk sym=%s limit_down_ratio=%.2f%% (%d/%d days)",
                    sym, limit_down_ratio * 100, limit_down_count, len(df)
                )
        except Exception:
            logger.debug("limit_down_ratio calc failed for %s", sym)
        first_date = str(df["date"].min().date())
        for w in windows:
            if w < first_date:
                continue
            if index_only and code:
                window_constituents = load_csi300_constituents(as_of_date=w)
                if code not in window_constituents:
                    continue
            # Date-aware stamp tax: 0.1% before 2023-08-28, 0.05% on/after
            cost_sell = cost_sell_base + _get_stamp_tax(w)
            for s_name in strategies:
                func = STRATEGY_MAP.get(s_name)
                if func is None:
                    logger.warning("Unknown strategy '%s' — skipping (valid: %s)",
                                   s_name, list(STRATEGY_MAP.keys()))
                    continue
                try:
                    r = func(df, w, csi=csi, cost_buy=cost_buy, cost_sell=cost_sell, symbol=sym, is_st=is_st)
                    if r:
                        # T+1 constraint: minimum 1-day holding period
                        if r.get("days", 0) < 1:
                            logger.debug("Skip %s %s: T+1 violation (days=%s)", sym, w, r.get("days", 0))
                            continue
                        # Sell-side limit-down check: reject trade if exit price is at limit-down
                        if r.get("exit_price") is not None and code_prefix:
                            exit_price = r["exit_price"]
                            entry_idx = df[df["date"] > pd.Timestamp(w)].index[0] if len(df[df["date"] > pd.Timestamp(w)]) > 0 else None
                            if entry_idx is not None:
                                exit_row_idx = entry_idx + int(r.get("days", 0))
                                if exit_row_idx < len(df):
                                    prev_close = float(df.iloc[exit_row_idx - 1]["close"]) if exit_row_idx > 0 else float(df.iloc[exit_row_idx]["close"])
                                    if is_limit_down({"close": exit_price}, prev_close, code_prefix, is_st=is_st):
                                        logger.debug("Skip %s %s: exit at limit-down", sym, w)
                                        continue
                        window_date = pd.Timestamp(w)
                        entry_date = df[df["date"] > window_date].iloc[0] if len(df[df["date"] > window_date]) > 0 else None
                        if entry_date is not None and code_prefix:
                            exec_price = float(entry_date["open"])
                            prev_idx = df[df["date"] < entry_date["date"]].index[-1]
                            prev_close = float(df.loc[prev_idx, "close"])
                            if exec_price > prev_close and is_limit_up({"close": exec_price}, prev_close, code_prefix, is_st=is_st):
                                logger.debug("Skip %s %s: entry at limit-up", sym, w)
                                continue
                            if exec_price < prev_close and is_limit_down({"close": exec_price}, prev_close, code_prefix, is_st=is_st):
                                logger.debug("Skip %s %s: entry at limit-down", sym, w)
                                continue
                        # Delisted check: stocks with data ending >1yr ago may be delisted
                        # Survivorship bias risk: using today's stock list excludes delisted stocks
                        try:
                            last_date = df["date"].max()
                            is_delisted = last_date < pd.Timestamp(get_time_provider().now()) - pd.DateOffset(years=1)
                        except Exception:
                            is_delisted = False
                        if is_delisted:
                            now = pd.Timestamp(get_time_provider().now())
                            days_since_last = (now - last_date).days
                            if days_since_last > 0:
                                penalty = -0.20 * days_since_last / 365.0
                                r = {**r, "ret": r.get("ret", 0) + penalty, "survivorship_penalty": penalty}
                        trades.append({"strategy": s_name, "symbol": sym, "window": w, "delisted": is_delisted, **r})
                except Exception as e:
                    logger.warning("strategy=%s symbol=%s window=%s error=%s", s_name, sym, w, e)
                    continue
    except Exception as e:
        error_count += 1
        logger.error("symbol=%s error=%s (error_count=%d)", sym, e, error_count)
    return trades


def run_backtest(strategies: List[str], n_windows: int = 20,
                 min_year: int = 0, max_year: int = 9999,
                 with_costs: bool = True, output_dir: str = "",
                 n_stocks_limit: int = 99999, index_only: bool = True) -> Dict:
    """
    Run multi-strategy backtest.

    Args:
        strategies: Strategy names (must be keys in STRATEGY_MAP)
        n_windows: Number of walk-forward windows (monthly sampling)
        min_year: Inclusive start year
        max_year: Inclusive end year
        with_costs: Apply transaction costs
        output_dir: Output directory (reserved, not yet used)
        n_stocks_limit: Maximum number of stocks to include
        index_only: If True, restrict to CSI300 constituents (reduces survivorship bias)

    Returns:
        Dict with strategy performance, correlations, portfolio Sharpe, and Monte Carlo
    """
    np.random.seed(RANDOM_SEED)
    ensure_csi300_history_snapshot()

    if with_costs:
        effective_buy = COST_BUY
        # Sell cost base = commission + transfer_fee; stamp tax added per-window in process_stock
        effective_sell_base = COMMISSION_PCT + TRANSFER_FEE_PCT
    else:
        effective_buy = 0.0
        effective_sell_base = 0.0

    stocks = load_stocks(STOCK_LIST_PATH, n_stocks_limit, index_only)
    logger.info("Running backtest with %s mode (%d stocks)",
                "CSI300 index-only" if index_only else "full universe",
                len(stocks))

    from uniquant.shared.loader import load_strategy_weights
    strategy_weights = load_strategy_weights()
    if strategy_weights:
        logger.info("Loaded strategy weights from config: %s", strategy_weights)
        for s in strategies:
            if s not in strategy_weights:
                logger.warning("Strategy '%s' has no configured weight, using equal weight", s)

    csi = load_csi300()
    windows = gen_windows(csi, n_windows, min_year, max_year, method="walk_forward")

    all_trades = []
    mw = get_optimal_workers()
    bs = mw * 4
    args_list = [(s, windows, csi, strategies, effective_buy, effective_sell_base, index_only) for s in stocks]

    with ProcessPoolExecutor(max_workers=mw, initializer=worker_init) as ex:
        for b in range(0, len(args_list), bs):
            batch = args_list[b:b + bs]
            futures = {ex.submit(process_stock, a): a[0]["symbol"] for a in batch}
            for f in as_completed(futures):
                try:
                    all_trades.extend(f.result(timeout=300))
                except Exception as e:
                    logger.warning("future result error: %s", e)

    if not all_trades:
        return {"config": {"strategies": strategies, "n_trades": 0, "strategy_weights": strategy_weights if strategy_weights else None}}

    df = pd.DataFrame(all_trades)

    results = {}
    for sn in strategies:
        sub = df[df["strategy"] == sn]
        if len(sub) >= 5:
            results[sn] = compute_stats(sub)

    corr_data = {}
    strats = list(results.keys())
    for i, t1 in enumerate(strats):
        for t2 in strats[i + 1:]:
            merged = df[df["strategy"] == t1][["window", "symbol", "ret"]].merge(
                df[df["strategy"] == t2][["window", "symbol", "ret"]],
                on=["window", "symbol"], suffixes=("_1", "_2"))
            if len(merged) >= 5:
                corr_data[f"{t1}_vs_{t2}"] = {
                    "corr": round(float(merged["ret_1"].corr(merged["ret_2"])), 3),
                    "n": len(merged)}

    n_strat = len(strats)
    if n_strat >= 2:
        pivot = df.pivot_table(index=["window", "symbol"],
                               columns="strategy", values="ret")
        pivot = pivot[[s for s in strats if s in pivot.columns]]
        if not pivot.empty and len(pivot.columns) >= 2:
            cov = pivot.cov().values
            w = np.ones(len(pivot.columns)) / len(pivot.columns)
            port_var = w @ cov @ w
            port_mean = pivot.mean().mean()
            avg_days_port = float(np.mean(df["days"])) if "days" in df.columns and len(df) > 0 else 1.0
            if avg_days_port <= 0:
                avg_days_port = 1.0
            combo = (port_mean / np.sqrt(port_var)) * np.sqrt(252 / avg_days_port) if port_var > 0 else 0.0
        else:
            combo = 0.0
    elif n_strat == 1:
        combo = results[strats[0]]["sharpe"]
    else:
        combo = 0

    mc = {}
    for sn in strats:
        sub = df[df["strategy"] == sn]
        if len(sub) < 20:
            continue
        rets = sub["ret"].values
        ad = float(np.mean(sub["days"]))
        rng = np.random.default_rng(RANDOM_SEED)
        sims = [ann_sharpe(_block_bootstrap(rets, rng=rng), ad)
                for _ in range(MC_SIMS)]
        mc[sn] = {
            "mean": round(float(np.mean(sims)), 3),
            "ci_5": round(float(np.percentile(sims, 5)), 3),
            "ci_95": round(float(np.percentile(sims, 95)), 3),
            "p_pos": round(float(sum(s > 0 for s in sims) / len(sims) * 100), 1),
        }

    sb_warning = (
        "universe is today's stock list, not historical; "
        "stocks with data start after window are filtered (reduces but does not eliminate bias)"
    )
    return {
        "config": {
            "n_stocks": len(stocks),
            "n_windows": n_windows,
            "min_year": min_year,
            "max_year": max_year,
            "mc_seed": 42,
            "window_seed": 42,
            "window_method": "walk_forward",
            "with_costs": with_costs,
            "cost_model": {"commission_pct": (COMMISSION_PCT * 100) if with_costs else 0.0,
                           "stamp_tax_pct": (STAMP_TAX_PCT * 100) if with_costs else 0.0,
                           "buy_pct": (effective_buy * 100),
                           "sell_pct": (effective_sell_base * 100),
                           "round_trip_pct": (effective_buy + effective_sell_base) * 100,
                           "min_commission": MIN_COMMISSION if with_costs else 0.0,
                           "note": "min commission applied in investment backtest (src/investment/backtest.py) where position-size context is available"},
            "strategies_used": strategies,
            "index_only": index_only,
            "strategy_weights": strategy_weights if strategy_weights else None,
        },
        "strategies": results,
        "correlations": corr_data,
        "portfolio": {
            "multi_strat_sharpe": round(combo, 3),
            "method": "covariance_matrix",
            "formula": "(w @ mu) / sqrt(w @ Sigma @ w) * sqrt(252)",
            "equal_weight": True,
            "limitation": "基于各策略独立夏普和协方差矩阵估算, 非真实组合净值序列",
        },
        "monte_carlo": mc,
        "survivorship_bias_warning": sb_warning,
        "reproducibility": {
            "mc_seeded": True,
            "mc_seed": 42,
            "window_seeded": True,
            "window_seed": 42,
            "windows": windows,
            "universe_size": len(stocks),
            "universe_source": str(STOCK_LIST_PATH),
            "universe_has_delisted_stocks": False,
            "survivorship_bias_note": sb_warning,
            "universe_mode": "csi300_only" if index_only else "full",
        },
    }
