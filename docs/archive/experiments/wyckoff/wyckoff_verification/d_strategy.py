"""Module D: Context-dependent Wyckoff strategy — threshold-based entry/exit."""

import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List
from enum import Enum

from .config import VerifierConfig
from .a_universe import StockRecord, load_data


class Position(Enum):
    FLAT = 0
    LONG = 1


@dataclass
class Trade:
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    direction: str  # "long"
    pnl_pct: float
    pnl_amount: float
    holding_days: int
    reason: str = ""


@dataclass
class StrategyResult:
    symbol: str
    total_return_pct: float
    annualized_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    n_trades: int
    win_rate: float
    avg_hold_days: float
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (f"ret={self.total_return_pct:>+7.2f}% ann={self.annualized_return_pct:>+7.2f}% "
                f"sharpe={self.sharpe:>+6.3f} mdd={self.max_drawdown_pct:>6.2f}% "
                f"trades={self.n_trades:<4} win={self.win_rate:>5.1f}%")


def detect_accumulation(df_slice: pd.DataFrame) -> float:
    """Score accumulation phase signals. Returns 0-1 score.
    
    Signals: price in lower half of range, volume contracting, 
    multiple tests of support without breaking.
    """
    close = df_slice["close"].values
    low = df_slice["low"].values
    high = df_slice["high"].values
    volume = df_slice["volume"].values
    n = len(close)

    score = 0.0

    # 1. Price in lower 40% of range
    price_range = np.max(high) - np.min(low)
    if price_range > 0:
        price_pos = (close[-1] - np.min(low)) / price_range
        score += 0.3 * (1 - price_pos)  # lower = more accumulation

    # 2. Volume declining
    vol_ma_short = np.mean(volume[-10:])
    vol_ma_long = np.mean(volume[-min(40, n):])
    if vol_ma_long > 0 and vol_ma_short < vol_ma_long * 0.9:
        score += 0.2

    # 3. Multiple support tests
    support_level = np.percentile(low, 20)
    tests = np.sum(low[-20:] <= support_level * 1.02)
    if tests >= 3:
        score += 0.3

    # 4. Tight closing range (absorption)
    recent_range = (high[-5:].max() - low[-5:].min()) / close[-1]
    if recent_range < 0.05:
        score += 0.2

    return min(score, 1.0)


def detect_distribution(df_slice: pd.DataFrame) -> float:
    """Score distribution phase signals. Returns 0-1 score."""
    close = df_slice["close"].values
    low = df_slice["low"].values
    high = df_slice["high"].values
    volume = df_slice["volume"].values
    len(close)

    score = 0.0

    # 1. Price in upper 40% of range
    price_range = np.max(high) - np.min(low)
    if price_range > 0:
        price_pos = (close[-1] - np.min(low)) / price_range
        score += 0.3 * price_pos

    # 2. Volume expanding on up-days
    up_days = close[-10:] > np.roll(close, 1)[-10:]
    vol_up = np.mean(volume[-10:][up_days]) if np.any(up_days) else 0
    vol_down = np.mean(volume[-10:][~up_days]) if np.any(~up_days) else 0
    if vol_down > 0 and vol_up > vol_down * 1.2:
        score += 0.2

    # 3. Wide price swings (volatility increasing)
    recent_atr = np.mean(np.abs(close[-10:] - np.roll(close, 1)[-10:]))
    older_atr = np.mean(np.abs(close[-20:-10] - np.roll(close, 1)[-20:-10]))
    if older_atr > 0 and recent_atr > older_atr * 1.3:
        score += 0.3

    # 4. Upthrusts detected
    for i in range(-5, 0):
        window_high = np.max(high[i - 20:i])
        if high[i] >= window_high * 0.99 and close[i] <= window_high * 1.0:
            score += 0.2
            break

    return min(score, 1.0)


def simulate_wyckoff_strategy(
    df: pd.DataFrame, config: VerifierConfig, symbol: str = ""
) -> StrategyResult:
    """Simulate Wyckoff context-dependent strategy on one stock.
    
    Rules:
    - Accumulation score > 0.6 AND Spring detected → BUY
    - Distribution score > 0.6 AND Upthrust detected → SELL (or exit)
    - Exit: phase change, stop loss (2× ATR), or take profit (3:1 or 5:1)
    """
    close = df["close"].values
    low = df["low"].values
    high = df["high"].values
    df["volume"].values
    dates_pd = df["date"]
    
    # ATR
    atr_window = config.strategy.atr_period
    true_ranges = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )
    atr = np.zeros(len(close))
    atr[atr_window] = np.mean(true_ranges[:atr_window])
    for i in range(atr_window + 1, len(close)):
        atr[i] = (atr[i - 1] * (atr_window - 1) + true_ranges[i - 1]) / atr_window

    position = Position.FLAT
    trades: List[Trade] = []
    equity = [1.0]
    entry_price = 0.0
    entry_idx = 0
    stop_loss = 0.0
    take_partial = 0.0
    take_full = 0.0

    # Cost model
    commission = config.strategy.commission_pct
    stamp_duty = config.strategy.stamp_duty_pct
    slippage = config.strategy.slippage_pct
    min_comm = config.strategy.min_commission

    lookback = 60  # window for phase detection

    for i in range(lookback, len(close)):
        # Check exit conditions if in position
        if position == Position.LONG:
            # Stop loss
            if close[i] <= stop_loss:
                exit_price = close[i] * (1 - slippage)
                pnl_pct = (exit_price / entry_price - 1) * 100
                pnl_amount = pnl_pct  # as percentage of capital
                cost_out = exit_price * (commission + stamp_duty) + min_comm / 10000
                trades.append(Trade(
                    entry_date=str(dates_pd.iloc[entry_idx]),
                    entry_price=float(entry_price),
                    exit_date=str(dates_pd.iloc[i]),
                    exit_price=float(exit_price),
                    direction="long", pnl_pct=float(pnl_pct - cost_out),
                    pnl_amount=float(pnl_amount - cost_out),
                    holding_days=i - entry_idx, reason="stop_loss",
                ))
                equity.append(equity[-1] * (1 + (pnl_pct - cost_out) / 100))
                position = Position.FLAT
                continue

            # Take full profit
            if close[i] >= take_full:
                exit_price = close[i] * (1 - slippage)
                pnl_pct = (exit_price / entry_price - 1) * 100
                cost_out = exit_price * (commission + stamp_duty) + min_comm / 10000
                trades.append(Trade(
                    entry_date=str(dates_pd.iloc[entry_idx]),
                    entry_price=float(entry_price),
                    exit_date=str(dates_pd.iloc[i]),
                    exit_price=float(exit_price),
                    direction="long", pnl_pct=float(pnl_pct - cost_out),
                    pnl_amount=float(pnl_pct - cost_out),
                    holding_days=i - entry_idx, reason="take_full_profit",
                ))
                equity.append(equity[-1] * (1 + (pnl_pct - cost_out) / 100))
                position = Position.FLAT
                continue

            # Take partial profit
            if close[i] >= take_partial:
                pass  # In a simple version, just hold for full target

            # Phase change to distribution → exit
            dist_score = detect_distribution(df.iloc[i - min(60, i) : i])
            if dist_score > 0.6:
                exit_price = close[i] * (1 - slippage)
                pnl_pct = (exit_price / entry_price - 1) * 100
                cost_out = exit_price * (commission + stamp_duty) + min_comm / 10000
                trades.append(Trade(
                    entry_date=str(dates_pd.iloc[entry_idx]),
                    entry_price=float(entry_price),
                    exit_date=str(dates_pd.iloc[i]),
                    exit_price=float(exit_price),
                    direction="long", pnl_pct=float(pnl_pct - cost_out),
                    pnl_amount=float(pnl_pct - cost_out),
                    holding_days=i - entry_idx, reason="distribution_detected",
                ))
                equity.append(equity[-1] * (1 + (pnl_pct - cost_out) / 100))
                position = Position.FLAT
                continue

            # Normal mark continuation
            equity.append(equity[-1] * (1 + (close[i] / close[i - 1] - 1)))

        # Check entry conditions if flat
        if position == Position.FLAT:
            window = df.iloc[i - min(lookback, i) : i]
            acc_score = detect_accumulation(window)
            dist_score = detect_distribution(window)

            # Spring detection
            is_spring = False
            if i >= 20:
                w_low = np.min(low[i - 20 : i])
                if low[i] <= w_low * 1.01 and close[i] >= w_low * 1.0:
                    is_spring = True

            # Entry: accumulation + spring
            if acc_score > 0.5 and is_spring:
                entry_price = close[i] * (1 + slippage)
                cost_in = entry_price * commission + min_comm / 10000
                position = Position.LONG
                entry_idx = i
                stop_loss = entry_price * (1 - config.strategy.atr_stop_multiple * atr[i] / close[i])
                take_partial = entry_price * (1 + config.strategy.rr_take_partial * atr[i] / close[i])
                take_full = entry_price * (1 + config.strategy.rr_take_full * atr[i] / close[i])
                # Deduct entry cost from equity
                equity[-1] = equity[-1] * (1 - cost_in / 10000)

    # Close any remaining position at end
    if position == Position.LONG:
        exit_price = close[-1] * (1 - slippage)
        pnl_pct = (exit_price / entry_price - 1) * 100
        cost_out = exit_price * (commission + stamp_duty) + min_comm / 10000
        trades.append(Trade(
            entry_date=str(dates_pd.iloc[entry_idx]),
            entry_price=float(entry_price),
            exit_date=str(dates_pd.iloc[-1]),
            exit_price=float(exit_price),
            direction="long", pnl_pct=float(pnl_pct - cost_out),
            pnl_amount=float(pnl_pct - cost_out),
            holding_days=len(close) - 1 - entry_idx, reason="end_of_data",
        ))
        equity.append(equity[-1] * (1 + (pnl_pct - cost_out) / 100))

    # Compute metrics
    equity_arr = np.array(equity)
    total_ret = (equity_arr[-1] - 1) * 100
    n_years = len(close) / 252
    ann_ret = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0

    # Sharpe
    daily_returns = np.diff(equity_arr) / equity_arr[:-1]
    sharpe = 0.0
    if len(daily_returns) > 1 and np.std(daily_returns) > 1e-10:
        sharpe = float(np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252))

    # Max drawdown
    cummax = np.maximum.accumulate(equity_arr)
    drawdown = (equity_arr / cummax - 1) * 100
    mdd = float(np.min(drawdown))

    # Win rate
    wins = sum(1 for t in trades if t.pnl_pct > 0)
    win_rate = wins / len(trades) * 100 if trades else 0
    avg_hold = np.mean([t.holding_days for t in trades]) if trades else 0

    return StrategyResult(
        symbol=symbol,
        total_return_pct=total_ret,
        annualized_return_pct=ann_ret,
        sharpe=sharpe,
        max_drawdown_pct=mdd,
        n_trades=len(trades),
        win_rate=win_rate,
        avg_hold_days=avg_hold,
        trades=trades,
        equity_curve=equity_arr.tolist(),
    )


def run_strategy(
    records: List[StockRecord], config: VerifierConfig
) -> List[StrategyResult]:
    """Run context-dependent Wyckoff strategy across all stocks."""
    print("\n=== Module D: Context-Dependent Wyckoff Strategy ===")

    results: List[StrategyResult] = []
    n_total = len(records)

    with ThreadPoolExecutor(max_workers=config.n_jobs) as pool:
        fut_map = {}
        for rec in records:
            df = load_data(rec.symbol)
            if df is None:
                continue
            fut = pool.submit(simulate_wyckoff_strategy, df, config, rec.symbol)
            fut_map[fut] = rec.symbol

        done = 0
        for fut in as_completed(fut_map):
            done += 1
            try:
                res = fut.result()
                if res is not None:
                    results.append(res)
            except Exception:
                pass
            if done % 100 == 0:
                print(f"  Processed {done}/{n_total} stocks")

    # Aggregate
    if not results:
        print("\n  Wyckoff Strategy Results (0 stocks) — no trades generated")
        return results

    rets = [r.total_return_pct for r in results]
    anns = [r.annualized_return_pct for r in results]
    sharpes = [r.sharpe for r in results]
    trades_total = sum(r.n_trades for r in results)
    wins_total = sum(sum(1 for t in r.trades if t.pnl_pct > 0) for r in results)
    total_t = sum(len(r.trades) for r in results)
    win_rate = wins_total / total_t * 100 if total_t > 0 else 0
    n_profitable = sum(1 for r in rets if r > 0)

    print(f"\n  Wyckoff Strategy Results ({len(results)} stocks)")
    print(f"  {'='*80}")
    print(f"  Mean total return: {np.mean(rets):>+7.2f}%  "
          f"Median: {np.median(rets):>+7.2f}%")
    print(f"  Mean annualized:  {np.mean(anns):>+7.2f}%  "
          f"Median: {np.median(anns):>+7.2f}%")
    print(f"  Mean Sharpe:      {np.mean(sharpes):>+7.3f}")
    print(f"  Profitable stocks: {n_profitable}/{len(results)} "
          f"({n_profitable/len(results)*100:.1f}%)")
    print(f"  Win rate (trades): {win_rate:.1f}% "
          f"({wins_total}/{total_t})")
    print(f"  Total trades: {trades_total}")
    print(f"  Avg hold days: {np.mean([r.avg_hold_days for r in results if r.n_trades > 0]):.0f}")

    return results
