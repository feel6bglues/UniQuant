#!/usr/bin/env python3
"""
Wyckoff 模块滚动回测脚本 — 对 golden_100 执行 5 策略 × 100 股票 × 滚动窗口回测

输出: JSON 报告 (含每只股票逐笔交易 + 聚合统计) + 控制台摘要
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ──────────────────────────────────────────────
#  数据加载
# ──────────────────────────────────────────────


@dataclass
class StockSample:
    symbol: str
    board: str
    df: pd.DataFrame


def load_golden_list(path: Path) -> List[str]:
    symbols = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sym = line.split("#")[0].split()[0].strip()
        if sym:
            symbols.append(sym)
    return symbols


def load_stock_data(symbol: str) -> Optional[pd.DataFrame]:
    path = PROJECT_ROOT / f"data/lake/quotes/daily/{symbol}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None


def get_stock_metadata() -> Dict[str, str]:
    path = PROJECT_ROOT / "data/qualified_universe.csv"
    if not path.exists():
        return {}
    meta: Dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sym = row.get("symbol", "")
            if sym:
                meta[sym] = row.get("board", "SH_Main")
    return meta


def prepare_samples(symbols: List[str], start: str = "2022-01-01") -> List[StockSample]:
    meta = get_stock_metadata()
    samples = []
    for sym in symbols:
        df = load_stock_data(sym)
        if df is None or len(df) < 120:
            continue
        df = df[df["date"] >= start].copy().reset_index(drop=True)
        if len(df) < 120:
            continue
        board = meta.get(sym, "SH_Main")
        samples.append(StockSample(symbol=sym, board=board, df=df))
    return samples


# ──────────────────────────────────────────────
#  分析缓存: (symbol, window_idx) → WyckoffReport
#  所有策略共享同一份预计算分析结果
# ──────────────────────────────────────────────


@dataclass
class WyckoffSnapshot:
    """一帧滚动的 Wyckoff 分析结果"""
    window_end: int
    date: str
    phase: str
    direction: str
    conf_level: str
    spring_detected: bool
    rr_ratio: float
    price: float


def compute_wyckoff_snapshots(
    symbol: str,
    df: pd.DataFrame,
    window_step: int = 40,
    min_window: int = 120,
) -> List[WyckoffSnapshot]:
    """对一只股票执行滚动 Wyckoff 分析，返回所有快照"""
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    snapshots: List[WyckoffSnapshot] = []
    window_starts = list(range(min_window, len(df), window_step))

    for wi, w_end in enumerate(window_starts):
        try:
            window_df = df.iloc[: w_end + 1].copy()
            engine = WyckoffEngine(lookback_days=min_window)
            result = engine.analyze(window_df, symbol=symbol, period="日线")

            phase = result.structure.phase.value if result.structure else "unknown"
            direction = result.trading_plan.direction if result.trading_plan else "空仓观望"
            signal_obj = result.signal
            conf_level = signal_obj.confidence.value if signal_obj and signal_obj.confidence else "D"
            spring_detected = signal_obj.signal_type == "spring" if signal_obj else False
            rr_ratio = result.risk_reward.reward_risk_ratio if result.risk_reward else 0.0
            price = float(window_df.iloc[-1]["close"])

            snapshots.append(WyckoffSnapshot(
                window_end=w_end,
                date=str(window_df.iloc[-1]["date"]),
                phase=phase,
                direction=direction,
                conf_level=conf_level,
                spring_detected=spring_detected,
                rr_ratio=rr_ratio,
                price=price,
            ))
        except Exception as e:
            pass

    return snapshots


# ──────────────────────────────────────────────
#  交易模拟器 (单股票 × 单策略)
# ──────────────────────────────────────────────


@dataclass
class TradeRecord:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    holding_days: int
    reason: str


@dataclass
class SingleEquityCurve:
    dates: List[str]
    values: List[float]


@dataclass
class SingleResult:
    symbol: str
    trades: List[TradeRecord]
    equity_curve: SingleEquityCurve
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    win_rate_pct: float
    avg_holding_days: float

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "trades": [
                {"entry_date": t.entry_date, "exit_date": t.exit_date,
                 "entry_price": round(t.entry_price, 2), "exit_price": round(t.exit_price, 2),
                 "shares": t.shares, "pnl": round(t.pnl, 2), "pnl_pct": round(t.pnl_pct, 2),
                 "holding_days": t.holding_days, "reason": t.reason}
                for t in self.trades
            ],
            "equity_curve": {
                "dates": self.equity_curve.dates,
                "values": [round(v, 2) for v in self.equity_curve.values],
            },
            "total_return_pct": round(self.total_return_pct, 2),
            "annualized_return_pct": round(self.annualized_return_pct, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "sharpe": round(self.sharpe, 3),
            "win_rate_pct": round(self.win_rate_pct, 1),
            "avg_holding_days": round(self.avg_holding_days, 1),
        }


def simulate_variant(
    symbol: str,
    df: pd.DataFrame,
    snapshots: List[WyckoffSnapshot],
    variant: str,
    initial_capital: float = 100_000.0,
    window_step: int = 40,
) -> SingleResult:
    """
    给定预计算快照，对一只股票执行一种策略的交易模拟。

    参数:
      variant: 策略名
        v0_raw        — 完全遵循 Step 5 direction
        v1_phase      — 阶段切换: 仅 ACCUMULATION/MARKUP 做多
        v2_confidence — 置信度 B+ 且非 MARKDOWN/DISTRIBUTION 做多
        v3_spring     — Spring 触发做多 + ATR 止损
        bh            — 买入持有 (基准)
    """
    COMMISSION = 0.0003
    STAMP_TAX = 0.001
    MIN_COMM = 5.0
    SLIPPAGE = 0.001

    cash = initial_capital
    position = 0
    entry_price = 0.0
    entry_date_str = ""
    trades: List[TradeRecord] = []
    equity_values: List[float] = [initial_capital]
    eq_dates: List[str] = [str(df.iloc[0]["date"])]

    # For V3: trailing stop state
    highest_since_entry = 0.0
    trailing_stop = 0.0

    def buy(current_price: float, date_str: str, reason: str) -> None:
        nonlocal cash, position, entry_price, entry_date_str, highest_since_entry, trailing_stop
        if position > 0:
            return
        buy_px = current_price * (1 + SLIPPAGE)
        shares = int(cash / buy_px / 100) * 100
        if shares < 100:
            return
        cost = shares * buy_px
        commission = max(cost * COMMISSION, MIN_COMM)
        total = cost + commission
        if total > cash:
            return
        cash -= total
        position = shares
        entry_price = buy_px
        entry_date_str = date_str
        highest_since_entry = buy_px
        trailing_stop = buy_px * 0.93

    def sell(current_price: float, date_str: str, reason: str) -> None:
        nonlocal cash, position, entry_price, entry_date_str, highest_since_entry, trailing_stop
        if position <= 0:
            return
        sell_px = current_price * (1 - SLIPPAGE)
        proceeds = position * sell_px
        commission = max(proceeds * COMMISSION, MIN_COMM)
        stamp = proceeds * STAMP_TAX
        net = proceeds - commission - stamp
        cost_basis = position * entry_price
        pnl = net - cost_basis
        pnl_pct = pnl / cost_basis * 100 if cost_basis > 0 else 0.0
        days_held = 0
        if entry_date_str:
            try:
                d1 = pd.to_datetime(entry_date_str)
                d2 = pd.to_datetime(date_str)
                days_held = (d2 - d1).days
            except Exception:
                pass
        trades.append(TradeRecord(
            entry_date=entry_date_str, exit_date=date_str,
            entry_price=entry_price, exit_price=sell_px,
            shares=position, pnl=pnl, pnl_pct=pnl_pct,
            holding_days=days_held, reason=reason,
        ))
        cash += net
        position = 0
        entry_price = 0.0
        entry_date_str = ""
        highest_since_entry = 0.0
        trailing_stop = 0.0

    def get_action(
        phase: str, direction: str, conf: str, spring: bool, rr: float,
        in_pos: bool, curr_price: float,
    ) -> str:
        is_bull_phase = phase in ("accumulation", "markup")
        is_bear_phase = phase in ("markdown", "distribution")
        is_bull_dir = direction in ("做多", "买入", "持有")
        is_light_dir = direction in ("轻仓试探",)

        if variant == "v0_raw":
            if is_bull_dir or is_light_dir:
                return "BUY" if not in_pos else "HOLD"
            return "SELL" if in_pos else "HOLD"

        if variant == "v1_phase":
            if is_bull_phase:
                return "BUY" if not in_pos else "HOLD"
            return "SELL" if in_pos else "HOLD"

        if variant == "v2_confidence":
            if conf in ("A", "B") and not is_bear_phase:
                return "BUY" if not in_pos else "HOLD"
            if conf in ("A", "B") and is_bear_phase and rr >= 2.5:
                return "BUY" if not in_pos else "HOLD"
            return "SELL" if in_pos else "HOLD"

        if variant == "v3_spring":
            if spring and not in_pos:
                return "BUY"
            if in_pos:
                nonlocal highest_since_entry, trailing_stop
                if curr_price > highest_since_entry:
                    highest_since_entry = curr_price
                    trailing_stop = curr_price * 0.93
                if curr_price <= trailing_stop:
                    return "SELL"
            return "HOLD"

        if variant == "bh":
            if not in_pos:
                return "BUY"
            return "HOLD"

        return "HOLD"

    # 在每个窗口信号日检查行动
    for snap in snapshots:
        action = get_action(
            snap.phase, snap.direction, snap.conf_level,
            snap.spring_detected, snap.rr_ratio,
            position > 0, snap.price,
        )
        if action == "BUY":
            buy(snap.price, snap.date, f"{variant}_signal")
        elif action == "SELL":
            sell(snap.price, snap.date, f"{variant}_signal")

        # 记录权益曲线
        equity = cash + position * snap.price
        equity_values.append(equity)
        eq_dates.append(snap.date)

    # 在窗口之间也要记录权益 (填充至下一个窗口)
    # 为了更精确的曲线，在每个交易日记录
    last_snap_date = snapshots[-1].date if snapshots else ""
    for i in range(len(df)):
        d = str(df.iloc[i]["date"])
        if d not in eq_dates:  # already have this from snapshot
            # Check if after last snapshot
            if last_snap_date and d <= last_snap_date:
                continue
            # Interpolate: use latest position
            cp = float(df.iloc[i]["close"])
            eq = cash + position * cp
            equity_values.append(eq)
            eq_dates.append(d)

    # 平仓
    if position > 0 and len(df) > 0:
        final_price = float(df.iloc[-1]["close"])
        sell(final_price, str(df.iloc[-1]["date"]), "end_of_data")

    # 计算指标
    total_ret = (equity_values[-1] - initial_capital) / initial_capital if equity_values else 0.0

    ann_ret = 0.0
    if len(eq_dates) >= 2:
        days = (pd.to_datetime(eq_dates[-1]) - pd.to_datetime(eq_dates[0])).days
        if days > 0:
            ann_ret = (1 + total_ret) ** (365.25 / days) - 1

    peak = equity_values[0]
    mdd = 0.0
    for v in equity_values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > mdd:
            mdd = dd

    daily_rets = []
    for i in range(1, len(equity_values)):
        if equity_values[i - 1] > 0:
            daily_rets.append((equity_values[i] - equity_values[i - 1]) / equity_values[i - 1])
    sharpe = 0.0
    if daily_rets:
        arr = np.array(daily_rets)
        if arr.std() > 0:
            sharpe = float(arr.mean() / arr.std() * np.sqrt(252))

    win_rate = 0.0
    if trades:
        win_rate = sum(1 for t in trades if t.pnl > 0) / len(trades)

    avg_hold = 0.0
    if trades:
        avg_hold = sum(t.holding_days for t in trades) / len(trades)

    return SingleResult(
        symbol=symbol,
        trades=trades,
        equity_curve=SingleEquityCurve(dates=eq_dates, values=equity_values),
        total_return_pct=total_ret * 100,
        annualized_return_pct=ann_ret * 100,
        max_drawdown_pct=mdd * 100,
        sharpe=sharpe,
        win_rate_pct=win_rate * 100,
        avg_holding_days=avg_hold,
    )


# ──────────────────────────────────────────────
#  股票级作业 (用于并行处理)
# ──────────────────────────────────────────────


@dataclass
class StockJobResult:
    symbol: str
    board: str
    variants: Dict[str, SingleResult]


def process_one_stock(
    sample: StockSample,
    variants: List[str],
    window_step: int = 40,
    min_window: int = 120,
) -> StockJobResult:
    """预计算快照 → 模拟所有策略"""
    snapshots = compute_wyckoff_snapshots(sample.symbol, sample.df, window_step, min_window)
    if not snapshots:
        return StockJobResult(symbol=sample.symbol, board=sample.board, variants={})

    var_results: Dict[str, SingleResult] = {}
    for v in variants:
        try:
            sr = simulate_variant(sample.symbol, sample.df, snapshots, v, window_step=window_step)
            var_results[v] = sr
        except Exception as exc:
            print(f"  ERROR {sample.symbol} {v}: {exc}", file=sys.stderr)
    return StockJobResult(symbol=sample.symbol, board=sample.board, variants=var_results)


# ──────────────────────────────────────────────
#  聚合统计
# ──────────────────────────────────────────────


@dataclass
class VariantSummary:
    n_stocks: int
    positive_stocks: int
    negative_stocks: int
    mean_return_pct: float
    median_return_pct: float
    std_return_pct: float
    profitable_ratio_pct: float
    mean_annualized_return_pct: float
    mean_max_dd_pct: float
    mean_sharpe: float
    median_sharpe: float
    positive_sharpe_ratio: float
    total_trades: int
    win_rate_pct: float
    avg_holding_days: float

    def to_dict(self) -> Dict:
        return {
            "n_stocks": self.n_stocks,
            "positive_stocks": self.positive_stocks,
            "negative_stocks": self.negative_stocks,
            "mean_return_pct": round(self.mean_return_pct, 2),
            "median_return_pct": round(self.median_return_pct, 2),
            "std_return_pct": round(self.std_return_pct, 2),
            "profitable_ratio_pct": round(self.profitable_ratio_pct, 1),
            "mean_annualized_return_pct": round(self.mean_annualized_return_pct, 2),
            "mean_max_dd_pct": round(self.mean_max_dd_pct, 2),
            "mean_sharpe": round(self.mean_sharpe, 3),
            "median_sharpe": round(self.median_sharpe, 3),
            "positive_sharpe_ratio": round(self.positive_sharpe_ratio, 1),
            "total_trades": self.total_trades,
            "win_rate_pct": round(self.win_rate_pct, 1),
            "avg_holding_days": round(self.avg_holding_days, 1),
        }


def aggregate(results: List[StockJobResult], variants: List[str]) -> Dict[str, VariantSummary]:
    per_variant: Dict[str, List[SingleResult]] = {v: [] for v in variants}
    for r in results:
        for v in variants:
            sr = r.variants.get(v)
            if sr is not None:
                per_variant[v].append(sr)

    summaries: Dict[str, VariantSummary] = {}
    for v in variants:
        srs = per_variant[v]
        if not srs:
            continue
        returns = [sr.total_return_pct for sr in srs]
        ann_rets = [sr.annualized_return_pct for sr in srs]
        mdds = [sr.max_drawdown_pct for sr in srs]
        sharpes = [sr.sharpe for sr in srs]
        all_trades = []
        for sr in srs:
            all_trades.extend(sr.trades)

        pos = sum(1 for r in returns if r > 0)
        neg = sum(1 for r in returns if r < 0)
        trade_wins = sum(1 for t in all_trades if t.pnl > 0) if all_trades else 0
        hold_days = [t.holding_days for t in all_trades] if all_trades else [0]

        summaries[v] = VariantSummary(
            n_stocks=len(srs),
            positive_stocks=pos,
            negative_stocks=neg,
            mean_return_pct=float(np.mean(returns)),
            median_return_pct=float(np.median(returns)),
            std_return_pct=float(np.std(returns)),
            profitable_ratio_pct=pos / len(srs) * 100 if srs else 0,
            mean_annualized_return_pct=float(np.mean(ann_rets)),
            mean_max_dd_pct=float(np.mean(mdds)),
            mean_sharpe=float(np.mean(sharpes)),
            median_sharpe=float(np.median(sharpes)),
            positive_sharpe_ratio=sum(1 for s in sharpes if s > 0) / len(sharpes) * 100 if sharpes else 0,
            total_trades=len(all_trades),
            win_rate_pct=trade_wins / len(all_trades) * 100 if all_trades else 0,
            avg_holding_days=float(np.mean(hold_days)),
        )

    return summaries


# ──────────────────────────────────────────────
#  Wyckoff 阶段跳跃分析 (个股级: 统计窗口间的phase变化)
# ──────────────────────────────────────────────


def compute_signal_statistics(results: List[StockJobResult]) -> Dict:
    """全样本信号统计: phase分布, direction分布, conf分布, spring频率"""
    from collections import Counter
    phase_counter: Counter = Counter()
    direction_counter: Counter = Counter()
    conf_counter: Counter = Counter()
    spring_count = 0
    total_snapshots = 0
    phase_transitions: Dict[str, int] = Counter()

    # 分析 Snapshot 级统计数据 — 需要重新跑快照
    # 用缓存的快照结果: 为每只股票重新跑 compute_wyckoff_snapshots
    samples = []
    # From the results, we lost the original snapshots. Need to regenerate
    # This is computed separately below.

    return {}


def build_snapshot_database(samples: List[StockSample], window_step=40, min_window=120) -> Dict:
    """建立全样本快照数据库用于统计"""
    from collections import Counter
    phase_counter: Counter = Counter()
    direction_counter: Counter = Counter()
    conf_counter: Counter = Counter()
    spring_count = 0
    total = 0
    all_phases: List[str] = []
    prev_phase = ""

    for sample in samples:
        snapshots = compute_wyckoff_snapshots(sample.symbol, sample.df, window_step, min_window)
        for snap in snapshots:
            phase_counter[snap.phase] += 1
            direction_counter[snap.direction] += 1
            conf_counter[snap.conf_level] += 1
            if snap.spring_detected:
                spring_count += 1
            total += 1
            all_phases.append(snap.phase)

    return {
        "total_snapshots": total,
        "phase_distribution": dict(phase_counter.most_common()),
        "direction_distribution": dict(direction_counter.most_common()),
        "confidence_distribution": dict(conf_counter.most_common()),
        "spring_count": spring_count,
        "spring_rate_pct": spring_count / total * 100 if total else 0,
    }


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Wyckoff 滚动回测")
    parser.add_argument("--stocks", default="golden_100", choices=["golden_100", "golden_20"])
    parser.add_argument("--start", default="2022-01-01", help="数据起始日期")
    parser.add_argument("--step", type=int, default=40, help="滚动窗口步长(交易日)")
    parser.add_argument("--min-window", type=int, default=120, help="最小分析窗口")
    parser.add_argument("--workers", type=int, default=4, help="并行进程数")
    parser.add_argument("--output", default="wyckoff_backtest_results.json", help="输出 JSON 路径")
    parser.add_argument("--limit", type=int, default=0, help="限制股票数(调试用)")
    args = parser.parse_args()

    t0 = time.time()

    # 加载股票
    if args.stocks == "golden_100":
        symbols = load_golden_list(PROJECT_ROOT / "tests/benchmark/golden_100.txt")
    else:
        symbols = load_golden_list(PROJECT_ROOT / "tests/benchmark/golden_20.txt")

    samples = prepare_samples(symbols, start=args.start)
    if args.limit > 0:
        samples = samples[: args.limit]
    print(f"Loaded {len(samples)} stocks from {args.stocks}")

    # 策略定义
    variants = ["v0_raw", "v1_phase", "v2_confidence", "v3_spring", "bh"]

    # ── 并行执行 ──
    results: List[StockJobResult] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for sample in samples:
            fut = pool.submit(process_one_stock, sample, variants, args.step, args.min_window)
            futures[fut] = sample.symbol

        done = 0
        for fut in as_completed(futures):
            done += 1
            sym = futures[fut]
            try:
                r = fut.result()
                results.append(r)
            except Exception as exc:
                print(f"ERROR {sym}: {exc}", file=sys.stderr)
            if done % 10 == 0 or done == len(futures):
                print(f"  Progress: {done}/{len(futures)} stocks done ({time.time()-t0:.0f}s)")

    elapsed = time.time() - t0
    print(f"\n分析完成: {len(results)} stocks in {elapsed:.0f}s")

    # ── 聚合 ──
    summaries = aggregate(results, variants)

    # ── 快照统计 ──
    snap_stats = build_snapshot_database(samples, args.step, args.min_window)

    # ── 输出 ──
    print("\n" + "=" * 100)
    print("WYCKOFF 回测结果 — 聚合统计")
    print("=" * 100)
    header = f"{'Strategy':<18} {'N':<5} {'MeanRet%':<9} {'MedRet%':<9} {'AnnRet%':<9} {'Profit%':<8} {'AvgDD%':<8} {'Sharpe':<8} {'WinRate%':<9} {'Trades':<7}"
    print(header)
    print("-" * 100)

    for v in variants:
        s = summaries.get(v)
        if not s:
            continue
        print(
            f"{v:<18} {s.n_stocks:<5} {s.mean_return_pct:<9.2f} {s.median_return_pct:<9.2f} "
            f"{s.mean_annualized_return_pct:<9.2f} {s.profitable_ratio_pct:<8.1f} {s.mean_max_dd_pct:<8.2f} "
            f"{s.mean_sharpe:<8.3f} {s.win_rate_pct:<9.1f} {s.total_trades:<7}"
        )

    # ── 快照统计 ──
    print("\n" + "-" * 100)
    print("WYCKOFF 信号统计 (所有滚动窗口)")
    print("-" * 100)
    print(f"总快照数: {snap_stats['total_snapshots']}")
    print(f"Phase分布: {snap_stats['phase_distribution']}")
    print(f"Direction分布: {snap_stats['direction_distribution']}")
    print(f"Confidence分布: {snap_stats['confidence_distribution']}")
    print(f"Spring检测: {snap_stats['spring_count']} ({snap_stats['spring_rate_pct']:.1f}%)")

    # ── BH vs 策略: 正超额收益股票占比 ──
    print("\n" + "-" * 100)
    print("超额收益分析 (vs Buy & Hold)")
    print("-" * 100)
    bh_returns = {}
    for r in results:
        bh_sr = r.variants.get("bh")
        if bh_sr:
            bh_returns[r.symbol] = bh_sr.total_return_pct

    for v in variants:
        if v == "bh":
            continue
        s = summaries.get(v)
        if not s:
            continue
        beats_bh = 0
        total_comp = 0
        for r in results:
            sr = r.variants.get(v)
            if sr and r.symbol in bh_returns:
                total_comp += 1
                if sr.total_return_pct > bh_returns[r.symbol]:
                    beats_bh += 1
        beat_pct = beats_bh / total_comp * 100 if total_comp else 0
        print(f"{v:<18} beats BH: {beats_bh}/{total_comp} ({beat_pct:.1f}%)")

    # ── 保存 ──
    output_data = {
        "config": {
            "stocks": args.stocks,
            "start_date": args.start,
            "window_step": args.step,
            "min_window": args.min_window,
            "n_samples": len(samples),
            "elapsed_seconds": round(elapsed, 1),
        },
        "signal_statistics": snap_stats,
        "summary": {v: s.to_dict() for v, s in summaries.items()},
        "per_stock": {
            r.symbol: {
                "board": r.board,
                "variants": {v: sr.to_dict() for v, sr in r.variants.items()},
            }
            for r in results
        },
    }

    out_path = PROJECT_ROOT / args.output
    out_path.write_text(json.dumps(output_data, indent=2, ensure_ascii=False, default=str))
    print(f"\n完整结果已保存到: {out_path}")


if __name__ == "__main__":
    main()
