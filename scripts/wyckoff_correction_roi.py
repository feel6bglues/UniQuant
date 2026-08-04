#!/usr/bin/env python3
"""
Wyckoff 修正方案 ROI 数据验证脚本.

对 golden_100 分别验证 A/B/C 三方案的预期收益提升.
直接基于 2,400 个滚动窗口快照和 100 stocks × 4.5 年数据计算.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ──────────────────────────────────────────────
#  数据加载 (复用 wyckoff_backtest.py)
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
#  扩展快照: 包含趋势数据用于 B 方案
# ──────────────────────────────────────────────


@dataclass
class ExtendedSnapshot:
    """带趋势数据的 Wyckoff 快照"""
    window_end: int
    date: str
    price: float
    phase: str
    unknown_candidate: str
    direction: str
    conf_level: str
    spring_detected: bool
    rr_ratio: float
    short_trend_pct: float
    prior_trend_pct: float
    boundary_lower: float
    boundary_upper: float
    ma20: float
    ma5: float


def compute_extended_snapshots(
    symbol: str,
    df: pd.DataFrame,
    window_step: int = 40,
    min_window: int = 120,
) -> List[ExtendedSnapshot]:
    """滚动 Wyckoff 分析, 返回扩展快照"""
    from uniquant.brain.wyckoff.engine import WyckoffEngine

    snapshots: List[ExtendedSnapshot] = []
    window_starts = list(range(min_window, len(df), window_step))

    for w_end in window_starts:
        try:
            window_df = df.iloc[: w_end + 1].copy()
            engine = WyckoffEngine(lookback_days=min_window)
            result = engine.analyze(window_df, symbol=symbol, period="日线")

            if not result or not result.structure:
                continue

            phase = result.structure.phase.value if result.structure else "unknown"
            unknown_candidate = result.structure.unknown_candidate if result.structure else ""
            direction = result.trading_plan.direction if result.trading_plan else "空仓观望"
            signal_obj = result.signal
            conf_level = signal_obj.confidence.value if signal_obj and signal_obj.confidence else "D"
            spring_detected = signal_obj.signal_type == "spring" if signal_obj else False
            rr_ratio = result.risk_reward.reward_risk_ratio if result.risk_reward else 0.0

            price = float(window_df.iloc[-1]["close"])

            # 计算趋势
            close_vals = window_df["close"].values
            short_trend = (close_vals[-1] / close_vals[-min(20, len(close_vals))] - 1) * 100
            prior_trend = (close_vals[-1] / close_vals[-min(60, len(close_vals))] - 1) * 100

            # MA
            ma5 = window_df["close"].rolling(5).mean().iloc[-1] if len(window_df) >= 5 else price
            ma20 = window_df["close"].rolling(20).mean().iloc[-1] if len(window_df) >= 20 else price

            bound_low = result.structure.trading_range_low or (price * 0.9)
            bound_high = result.structure.trading_range_high or (price * 1.1)

            snapshots.append(ExtendedSnapshot(
                window_end=w_end,
                date=str(window_df.iloc[-1]["date"]),
                price=price,
                phase=phase,
                unknown_candidate=unknown_candidate,
                direction=direction,
                conf_level=conf_level,
                spring_detected=spring_detected,
                rr_ratio=rr_ratio,
                short_trend_pct=short_trend,
                prior_trend_pct=prior_trend,
                boundary_lower=bound_low,
                boundary_upper=bound_high,
                ma20=ma20,
                ma5=ma5,
            ))
        except Exception:
            pass

    return snapshots


# ──────────────────────────────────────────────
#  策略模拟 + ROI 计算
# ──────────────────────────────────────────────


@dataclass
class SimTrade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    holding_days: int
    variant: str


@dataclass
class SimResult:
    symbol: str
    variant: str
    trades: List[SimTrade]
    final_capital: float
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    win_rate_pct: float
    avg_holding_days: float
    n_trades: int


COMMISSION = 0.0003
STAMP_TAX = 0.001
MIN_COMM = 5.0
SLIPPAGE = 0.001


def simulate(
    symbol: str,
    df: pd.DataFrame,
    snapshots: List[ExtendedSnapshot],
    variant: str,
    initial_capital: float = 100_000.0,
) -> SimResult:
    """单股票 × 单策略模拟。variant 可以是策略名或修正方案代号。"""
    cash = initial_capital
    position = 0
    entry_price = 0.0
    entry_date = ""
    trades: List[SimTrade] = []

    # V3 trailing stop state
    highest_since_entry = 0.0
    trailing_stop = 0.0

    def buy(px: float, dt: str) -> None:
        nonlocal cash, position, entry_price, entry_date, highest_since_entry, trailing_stop
        if position > 0:
            return
        buy_px = px * (1 + SLIPPAGE)
        shares = int(cash / buy_px / 100) * 100
        if shares < 100:
            return
        cost = shares * buy_px
        comm = max(cost * COMMISSION, MIN_COMM)
        total = cost + comm
        if total > cash:
            return
        cash -= total
        position = shares
        entry_price = buy_px
        entry_date = dt
        highest_since_entry = buy_px
        trailing_stop = buy_px * 0.93

    def sell(px: float, dt: str, reason: str = "") -> None:
        nonlocal cash, position, entry_price, entry_date, highest_since_entry, trailing_stop
        if position <= 0:
            return
        sell_px = px * (1 - SLIPPAGE)
        proceeds = position * sell_px
        comm = max(proceeds * COMMISSION, MIN_COMM)
        stamp = proceeds * STAMP_TAX
        net = proceeds - comm - stamp
        cost_basis = position * entry_price
        pnl = net - cost_basis
        pnl_pct = pnl / cost_basis * 100 if cost_basis > 0 else 0.0
        days_held = 0
        if entry_date:
            try:
                days_held = (pd.to_datetime(dt) - pd.to_datetime(entry_date)).days
            except Exception:
                pass
        trades.append(SimTrade(
            entry_date=entry_date, exit_date=dt, entry_price=entry_price,
            exit_price=sell_px, shares=position, pnl=pnl, pnl_pct=pnl_pct,
            holding_days=days_held, variant=variant,
        ))
        cash += net
        position = 0
        entry_price = 0.0
        entry_date = ""
        highest_since_entry = 0.0
        trailing_stop = 0.0

    def get_action(snap: ExtendedSnapshot) -> str:
        p, d, conf, _spring, rr = snap.phase, snap.direction, snap.conf_level, snap.spring_detected, snap.rr_ratio
        st, _uc = snap.short_trend_pct, snap.unknown_candidate

        if variant == "v0_raw":
            if d in ("做多", "买入", "持有", "轻仓试探"):
                return "BUY" if not position else "HOLD"
            return "SELL" if position else "HOLD"

        elif variant == "v1_phase":
            if p in ("accumulation", "markup"):
                return "BUY" if not position else "HOLD"
            return "SELL" if position else "HOLD"

        elif variant == "bh":
            return "BUY" if not position else "HOLD"

        # ══════════════════════════════════════════
        #  方案 A: Step 5 协调 R8 —— 允许 B+ MARKDOWN
        # ══════════════════════════════════════════
        elif variant == "a_corrected":
            # A.3: MARKDOWN + B+ + RR≥2.5 → 专业做多
            if p == "markdown" and conf in ("A", "B") and rr >= 2.5:
                return "BUY" if not position else "HOLD"
            if p == "markdown":
                return "SELL" if position else "HOLD"
            # 其他阶段同 v1_phase
            if p in ("accumulation", "markup"):
                return "BUY" if not position else "HOLD"
            return "SELL" if position else "HOLD"

        # ══════════════════════════════════════════
        #  方案 B: 降低 UNKNOWN —— 根据趋势重分类
        # ══════════════════════════════════════════
        elif variant == "b_corrected":
            # B.1: UNKNOWN 重分类
            if p == "unknown":
                # 下跌趋势中的 UNKNOWN → 维持空仓 (正确)
                if st < -1.0:
                    return "SELL" if position else "HOLD"
                # 上升趋势中的 UNKNOWN (原 MARKUP_CORRECTION) → 买入持有
                if st >= 1.0:
                    return "BUY" if not position else "HOLD"
                # 横盘 UNKNOWN (原 TR_OSCILLATION) → 轻仓
                if abs(st) < 1.0:
                    return "BUY" if not position else "HOLD"
                return "HOLD"
            # 其他阶段同 v1_phase
            if p in ("accumulation", "markup"):
                return "BUY" if not position else "HOLD"
            return "SELL" if position else "HOLD"

        # ══════════════════════════════════════════
        #  方案 B+: UNKNOWN 重分类 + Step 5 协调
        # ══════════════════════════════════════════
        elif variant == "bplus_corrected":
            # UNKNOWN 重分类
            if p == "unknown":
                if st < -1.0:
                    return "SELL" if position else "HOLD"
                if st >= 1.0 or abs(st) < 1.0:
                    return "BUY" if not position else "HOLD"
                return "HOLD"
            # MARKDOWN B+ 覆写
            if p == "markdown" and conf in ("A", "B") and rr >= 2.5:
                return "BUY" if not position else "HOLD"
            if p == "markdown":
                return "SELL" if position else "HOLD"
            if p in ("accumulation", "markup"):
                return "BUY" if not position else "HOLD"
            return "SELL" if position else "HOLD"

        # ══════════════════════════════════════════
        #  方案 C: 模式识别入场
        # ══════════════════════════════════════════
        elif variant == "c_pattern":
            if position > 0:
                # 持仓管理: ATR 止损
                nonlocal highest_since_entry, trailing_stop
                if snap.price > highest_since_entry:
                    highest_since_entry = snap.price
                    trailing_stop = snap.price * 0.93
                if snap.price <= trailing_stop:
                    return "SELL"
                return "HOLD"
            # 模式 1: 量价背离 (MACD底背离 + 缩量)
            div = _detect_divergence(df, snap.window_end)
            # 模式 2: 缩量止跌
            shrink = _detect_shrink_stabilize(df, snap.window_end)
            # 模式 3: 放量突破
            breakout = _detect_breakout(df, snap.window_end, snap.boundary_upper)
            if breakout:
                return "BUY"
            if div and shrink:
                return "BUY"
            if shrink and p in ("accumulation", "unknown") and abs(st) < 2.0:
                return "BUY"
            return "HOLD"

        return "HOLD"

    # 遍历快照
    for snap in snapshots:
        action = get_action(snap)
        if action == "BUY":
            buy(snap.price, snap.date)
        elif action == "SELL" and position > 0:
            sell(snap.price, snap.date)

    # 平仓
    if position > 0 and len(df) > 0:
        sell(float(df.iloc[-1]["close"]), str(df.iloc[-1]["date"]), "close")

    # 指标计算
    total_ret = (cash - initial_capital) / initial_capital if cash > 0 else 0.0
    ann_ret = 0.0
    if snapshots:
        days = (pd.to_datetime(snapshots[-1].date) - pd.to_datetime(snapshots[0].date)).days
        if days > 0:
            ann_ret = (1 + total_ret) ** (365.25 / days) - 1

    mdd = 0.0
    peak = initial_capital
    # 使用最新的权益近似 - 简化
    if trades:
        eq_vals = [initial_capital]
        for t in trades:
            eq_vals.append(eq_vals[-1] + t.pnl)
        for v in eq_vals:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            if dd > mdd:
                mdd = dd

    sharpe = 0.0
    if len(trades) >= 2:
        rets = [t.pnl_pct for t in trades]
        arr = np.array(rets)
        if arr.std() > 0:
            sharpe = float(arr.mean() / arr.std() * np.sqrt(252 / len(rets)))

    win_cnt = sum(1 for t in trades if t.pnl > 0)
    win_rate = win_cnt / len(trades) * 100 if trades else 0.0
    avg_hold = np.mean([t.holding_days for t in trades]) if trades else 0.0

    return SimResult(
        symbol=symbol, variant=variant, trades=trades,
        final_capital=cash, total_return_pct=total_ret * 100,
        annualized_return_pct=ann_ret * 100, max_drawdown_pct=mdd * 100,
        sharpe=sharpe, win_rate_pct=win_rate, avg_holding_days=avg_hold,
        n_trades=len(trades),
    )


# ──────────────────────────────────────────────
#  模式检测 (方案 C 使用)
# ──────────────────────────────────────────────


def _detect_divergence(df: pd.DataFrame, w_end: int) -> bool:
    """MACD 底背离检测 (简化版)"""
    window = df.iloc[:w_end + 1]
    if len(window) < 30:
        return False
    close = window["close"].values
    # 简易 MACD
    ema12 = pd.Series(close).ewm(span=12).mean().values
    ema26 = pd.Series(close).ewm(span=26).mean().values
    macd = ema12 - ema26
    # 检查最近 20 个 bar: 价格新低但 MACD 底部抬高
    recent_close = close[-20:]
    recent_macd = macd[-20:]
    close_low = np.min(recent_close)
    macd_low = np.min(recent_macd)
    close_prev_low = np.min(close[-40:-20]) if len(close) >= 40 else close_low
    macd_prev_low = np.min(macd[-40:-20]) if len(macd) >= 40 else macd_low
    # 底背离: 价格低点更低 + MACD 低点更高
    if close_low <= close_prev_low * 0.995 and macd_low > macd_prev_low * 1.01:
        return True
    return False


def _detect_shrink_stabilize(df: pd.DataFrame, w_end: int) -> bool:
    """缩量止跌检测"""
    window = df.iloc[:w_end + 1]
    if len(window) < 25:
        return False
    vol = window["volume"].values
    low = window["low"].values
    vol_20_avg = np.mean(vol[-20:]) if len(vol) >= 20 else np.mean(vol)
    vol_3_avg = np.mean(vol[-3:])
    shrink = vol_3_avg < vol_20_avg * 0.6 if vol_20_avg > 0 else False
    last_5_low = np.min(low[-5:])
    all_low = np.min(low)
    no_new_low = last_5_low >= all_low * 0.995
    return shrink and no_new_low


def _detect_breakout(df: pd.DataFrame, w_end: int, tr_upper: float) -> bool:
    """放量突破检测"""
    window = df.iloc[:w_end + 1]
    if len(window) < 20:
        return False
    last = window.iloc[-1]
    vol_avg = window["volume"].tail(20).mean()
    vol_ratio = last["volume"] / vol_avg if vol_avg > 0 else 1
    if vol_ratio >= 1.5 and last["close"] > last["open"] and last["close"] > tr_upper:
        return True
    return False


# ──────────────────────────────────────────────
#  股票级作业 (并行)
# ──────────────────────────────────────────────


@dataclass
class StockROI:
    symbol: str
    board: str
    variants: Dict[str, SimResult]
    snapshots: List[ExtendedSnapshot]


def process_one_stock(
    sample: StockSample,
    variants: List[str],
    window_step: int = 40,
    min_window: int = 120,
) -> StockROI:
    snapshots = compute_extended_snapshots(sample.symbol, sample.df, window_step, min_window)
    var_results: Dict[str, SimResult] = {}
    for v in variants:
        try:
            sr = simulate(sample.symbol, sample.df, snapshots, v)
            var_results[v] = sr
        except Exception:
            pass
    return StockROI(symbol=sample.symbol, board=sample.board, variants=var_results, snapshots=snapshots)


# ──────────────────────────────────────────────
#  UNKNOWN 深度分析 (B 方案数据支撑)
# ──────────────────────────────────────────────


def analyze_unknown_forward_returns(samples: List[StockSample], snapshots_cache: Optional[Dict[str, List[ExtendedSnapshot]]] = None, window_step=40, min_window=120) -> Dict:
    """分析 UNKNOWN 快照之后的收益, 用于 B 方案 ROI 估计"""
    all_unknown_fwd = []  # 所有 UNKNOWN 后 N 日收益
    unknown_by_candidate: Dict[str, List[float]] = defaultdict(list)

    for sample in samples:
        if snapshots_cache is not None and sample.symbol in snapshots_cache:
            snapshots = snapshots_cache[sample.symbol]
        else:
            snapshots = compute_extended_snapshots(sample.symbol, sample.df, window_step, min_window)
        df = sample.df
        for snap in snapshots:
            if snap.phase != "unknown":
                continue
            # 计算未来 40 日收益
            curr_idx = snap.window_end
            fwd_idx = min(curr_idx + 40, len(df) - 1)
            if fwd_idx > curr_idx:
                fwd_ret = (float(df.iloc[fwd_idx]["close"]) / snap.price - 1) * 100
                all_unknown_fwd.append(fwd_ret)
                unknown_by_candidate[snap.unknown_candidate or "unknown_range"].append(fwd_ret)

    result = {
        "n_unknown_snapshots": len(all_unknown_fwd),
        "mean_fwd_40d_return_pct": float(np.mean(all_unknown_fwd)) if all_unknown_fwd else 0,
        "median_fwd_40d_return_pct": float(np.median(all_unknown_fwd)) if all_unknown_fwd else 0,
        "positive_fwd_ratio": sum(1 for r in all_unknown_fwd if r > 0) / len(all_unknown_fwd) * 100 if all_unknown_fwd else 0,
        "std_fwd_return_pct": float(np.std(all_unknown_fwd)) if all_unknown_fwd else 0,
    }
    # 按候选类型分组
    by_candidate = {}
    for k, v in unknown_by_candidate.items():
        by_candidate[k] = {
            "count": len(v),
            "mean_fwd_ret_pct": float(np.mean(v)),
            "positive_ratio": sum(1 for r in v if r > 0) / len(v) * 100,
        }
    result["by_candidate"] = by_candidate
    return result


def analyze_markdown_b_signals(samples: List[StockSample], snapshots_cache: Optional[Dict[str, List[ExtendedSnapshot]]] = None, window_step=40, min_window=120) -> Dict:
    """分析 MARKDOWN + B+ 信号, 用于 A 方案 ROI 估计"""
    signals_found = []
    for sample in samples:
        if snapshots_cache is not None and sample.symbol in snapshots_cache:
            snapshots = snapshots_cache[sample.symbol]
        else:
            snapshots = compute_extended_snapshots(sample.symbol, sample.df, window_step, min_window)
        df = sample.df
        for snap in snapshots:
            if snap.phase == "markdown" and snap.conf_level in ("A", "B"):
                # 计算后续 60 日收益
                curr_idx = snap.window_end
                fwd_idx = min(curr_idx + 60, len(df) - 1)
                fwd_ret = 0.0
                if fwd_idx > curr_idx:
                    fwd_ret = (float(df.iloc[fwd_idx]["close"]) / snap.price - 1) * 100
                signals_found.append({
                    "symbol": sample.symbol,
                    "date": snap.date,
                    "price": snap.price,
                    "conf_level": snap.conf_level,
                    "rr_ratio": snap.rr_ratio,
                    "short_trend_pct": snap.short_trend_pct,
                    "fwd_60d_return_pct": round(fwd_ret, 2),
                })
    return {
        "n_signals": len(signals_found),
        "signals": signals_found,
        "mean_fwd_return": float(np.mean([s["fwd_60d_return_pct"] for s in signals_found])) if signals_found else 0,
        "median_fwd_return": float(np.median([s["fwd_60d_return_pct"] for s in signals_found])) if signals_found else 0,
        "positive_ratio": sum(1 for s in signals_found if s["fwd_60d_return_pct"] > 0) / len(signals_found) * 100 if signals_found else 0,
    }


def analyze_spring_lps(samples: List[StockSample], snapshots_cache: Optional[Dict[str, List[ExtendedSnapshot]]] = None, window_step=40, min_window=120) -> Dict:
    """分析 Spring 后收益, 验证 LPS 替代方案"""
    from collections import defaultdict
    fwd_by_horizon: Dict[str, List[float]] = defaultdict(list)
    n_spring = 0
    for sample in samples:
        if snapshots_cache is not None and sample.symbol in snapshots_cache:
            snapshots = snapshots_cache[sample.symbol]
        else:
            snapshots = compute_extended_snapshots(sample.symbol, sample.df, window_step, min_window)
        df = sample.df
        for snap in snapshots:
            if not snap.spring_detected:
                continue
            n_spring += 1
            curr_idx = snap.window_end
            for horizon, label in [(20, "20d"), (40, "40d"), (60, "60d")]:
                fwd_idx = min(curr_idx + horizon, len(df) - 1)
                if fwd_idx > curr_idx:
                    fwd_ret = (float(df.iloc[fwd_idx]["close"]) / snap.price - 1) * 100
                    fwd_by_horizon[label].append(fwd_ret)
    result = {"n_spring_signals": n_spring}
    for label in ["20d", "40d", "60d"]:
        vals = fwd_by_horizon.get(label, [])
        result[f"mean_fwd_{label}"] = float(np.mean(vals)) if vals else 0
        result[f"positive_{label}_ratio"] = sum(1 for r in vals if r > 0) / len(vals) * 100 if vals else 0
    return result


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────


def main():
    t0 = time.time()

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stocks-file", default="tests/benchmark/golden_100.txt")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--output", default="docs/analysis/wyckoff_correction_roi.json")
    args, _ = parser.parse_known_args()

    symbols = load_golden_list(PROJECT_ROOT / args.stocks_file)
    samples = prepare_samples(symbols, start=args.start)
    print(f"Loaded {len(samples)} stocks from {args.stocks_file}")

    # ── 0. 预计算: 一次性计算所有快照 ──
    print("\n═══ 预计算: 所有股票滚动快照 ═══\n")
    all_snapshots: Dict[str, List[ExtendedSnapshot]] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(compute_extended_snapshots, s.symbol, s.df): s.symbol for s in samples}
        done = 0
        for fut in as_completed(futures):
            done += 1
            sym = futures[fut]
            try:
                snaps = fut.result()
                if snaps:
                    all_snapshots[sym] = snaps
            except Exception as exc:
                print(f"  ERROR {sym}: {exc}", file=sys.stderr)
            if done % 50 == 0:
                print(f"  Snapshot progress: {done}/{len(samples)} ({time.time()-t0:.0f}s)")
    print(f"  完成: {len(all_snapshots)} stocks with snapshots in {time.time()-t0:.0f}s")

    # ── 1. 预分析: 用缓存快照 ──
    print("\n═══ 预分析: 修正方案数据支撑 ═══\n")

    print("[A 方案] MARKDOWN + B+ 信号分析 ...")
    md_b_analysis = analyze_markdown_b_signals(samples, all_snapshots)
    print(f"  找到 {md_b_analysis['n_signals']} 个 MARKDOWN+B+ 信号")
    print(f"  未来 60 日平均收益: {md_b_analysis['mean_fwd_return']:.2f}%")
    print(f"  未来 60 日中位收益: {md_b_analysis['median_fwd_return']:.2f}%")
    print(f"  正收益比率: {md_b_analysis['positive_ratio']:.1f}%")
    if md_b_analysis['signals']:
        print("  信号明细(前10):")
        for s in md_b_analysis['signals'][:10]:
            print(f"    {s['symbol']} @ {s['date']} conf={s['conf_level']} rr={s['rr_ratio']:.2f} fwd60d={s['fwd_60d_return_pct']:+.2f}%")

    print("\n[B 方案] UNKNOWN 后 40 日收益分析 ...")
    unknown_analysis = analyze_unknown_forward_returns(samples, all_snapshots)
    print(f"  UNKNOWN 快照数: {unknown_analysis['n_unknown_snapshots']}")
    print(f"  未来 40 日平均收益: {unknown_analysis['mean_fwd_40d_return_pct']:.2f}%")
    print(f"  未来 40 日中位收益: {unknown_analysis['median_fwd_40d_return_pct']:.2f}%")
    print(f"  正收益比率: {unknown_analysis['positive_fwd_ratio']:.1f}%")
    print("  按候选类型:")
    for k, v in unknown_analysis.get("by_candidate", {}).items():
        print(f"    {k}: {v['count']}个, 平均收益 {v['mean_fwd_ret_pct']:.2f}%, 正收益 {v['positive_ratio']:.1f}%")

    print("\n[C 方案] Spring 后收益分析 ...")
    spring_analysis = analyze_spring_lps(samples, all_snapshots)
    print(f"  Spring 信号数: {spring_analysis['n_spring_signals']}")
    print(f"  未来 20 日平均收益: {spring_analysis['mean_fwd_20d']:.2f}%")
    print(f"  未来 40 日平均收益: {spring_analysis['mean_fwd_40d']:.2f}%")
    print(f"  未来 60 日平均收益: {spring_analysis['mean_fwd_60d']:.2f}%")
    print(f"  20 日正收益比率: {spring_analysis['positive_20d_ratio']:.1f}%")

    # ── 2. 全回测: 原始 vs 修正策略 (复用缓存快照) ──
    variants = ["v0_raw", "v1_phase", "bh", "a_corrected", "b_corrected", "bplus_corrected", "c_pattern"]
    print(f"\n═══ 全回测: {len(variants)} 策略 × {len(samples)} 股票 ═══\n")

    all_results: List[StockROI] = []
    for si, sample in enumerate(samples):
        sym = sample.symbol
        snaps = all_snapshots.get(sym, [])
        if not snaps:
            continue
        var_results: Dict[str, SimResult] = {}
        for v in variants:
            try:
                sr = simulate(sym, sample.df, snaps, v)
                var_results[v] = sr
            except Exception:
                pass
        all_results.append(StockROI(symbol=sym, board=sample.board, variants=var_results, snapshots=snaps))
        if (si + 1) % 50 == 0:
            print(f"  Backtest: {si+1}/{len(samples)} ({time.time()-t0:.0f}s)")

    # ── 2. 聚合 ──
    per_variant: Dict[str, List[SimResult]] = defaultdict(list)
    for r in all_results:
        for v, sr in r.variants.items():
            per_variant[v].append(sr)

    # ── 3. 输出结果对比表 ──
    print(f"\n{'='*130}")
    print(f"{f'修正方案 ROI 对比 — {len(all_results)} stocks, 4.5 年':^130}")
    print(f"{'='*130}")
    header = f"{'策略':<18} {'N':<5} {'MeanRet%':<10} {'MedRet%':<10} {'AnnRet%':<10} {'Profit%':<9} {'AvgDD%':<9} {'Sharpe':<9} {'WinRate%':<10} {'Trades':<7}"
    print(header)
    print("-" * 130)
    for v in variants:
        srs = per_variant[v]
        if not srs:
            continue
        rets = [sr.total_return_pct for sr in srs]
        ann_rets = [sr.annualized_return_pct for sr in srs]
        mdds = [sr.max_drawdown_pct for sr in srs]
        sharpes = [sr.sharpe for sr in srs]
        trades = sum(sr.n_trades for sr in srs)
        wins = sum(sum(1 for t in sr.trades if t.pnl > 0) for sr in srs)
        total_t = sum(len(sr.trades) for sr in srs)
        win_rate = wins / total_t * 100 if total_t > 0 else 0
        pos_stocks = sum(1 for r in rets if r > 0)
        sum(1 for r in rets if r < 0)

        label = v
        # 标记修正方案
        if v == "a_corrected":
            label = "A: Step5修复"
        elif v == "b_corrected":
            label = "B: UNKNOWN重分类"
        elif v == "bplus_corrected":
            label = "B+: A+B组合"
        elif v == "c_pattern":
            label = "C: 模式识别"

        print(
            f"{label:<18} {len(srs):<5} {np.mean(rets):<10.2f} {np.median(rets):<10.2f} "
            f"{np.mean(ann_rets):<10.2f} {pos_stocks/len(srs)*100:<9.1f} {np.mean(mdds):<9.2f} "
            f"{np.mean(sharpes):<9.3f} {win_rate:<10.1f} {trades:<7}"
        )

    # ── 4. ROI 计算 ──
    print(f"\n{'='*130}")
    print(f"{'ROI 分析: 修正方案 vs 原始策略':^130}")
    print(f"{'='*130}")

    bh_mean = np.mean([sr.total_return_pct for sr in per_variant["bh"]])
    v0_mean = np.mean([sr.total_return_pct for sr in per_variant["v0_raw"]])
    v1_mean = np.mean([sr.total_return_pct for sr in per_variant["v1_phase"]])

    plan_roi = {}
    for v, label in [("a_corrected", "A"), ("b_corrected", "B"), ("bplus_corrected", "B+"), ("c_pattern", "C")]:
        srs = per_variant[v]
        if not srs:
            continue
        rets = [sr.total_return_pct for sr in srs]
        ann = [sr.annualized_return_pct for sr in srs]

        # 与原始 Wyckoff (v0_raw) 对比
        vs_v0 = np.mean(rets) - v0_mean
        vs_v1 = np.mean(rets) - v1_mean
        vs_bh = np.mean(rets) - bh_mean

        beats_bh = sum(1 for r, bh_r in zip(rets, [sr.total_return_pct for sr in per_variant["bh"]]) if r > bh_r)
        beats_bh_pct = beats_bh / len(rets) * 100
        pos_stocks = sum(1 for r in rets if r > 0) / len(rets) * 100

        plan_roi[label] = {
            "mean_return_pct": f"{np.mean(rets):.2f}",
            "annualized_pct": f"{np.mean(ann):.2f}",
            "vs_v0_raw": f"{vs_v0:+.2f}",
            "vs_v1_phase": f"{vs_v1:+.2f}",
            "vs_bh": f"{vs_bh:+.2f}",
            "vs_bh_improvement_pct": f"{(np.mean(rets)-bh_mean)/bh_mean*100:+.1f}",
            "beat_bh_ratio": f"{beats_bh_pct:.1f}%",
            "profitable_stock_ratio": f"{pos_stocks:.1f}%",
        }

    for plan, roi in plan_roi.items():
        print(f"\n  方案 {plan}:")
        print(f"    平均总收益: {roi['mean_return_pct']}%  (原始 v0_raw={v0_mean:.2f}%)")
        print(f"    年化收益:   {roi['annualized_pct']}%")
        print(f"    较 v0_raw:  {roi['vs_v0_raw']}%   ({roi['vs_v0_raw']} 绝对提升)")
        print(f"    较 v1_phase:{roi['vs_v1_phase']}%")
        print(f"    较 BH:      {roi['vs_bh']}%   ({roi['vs_bh_improvement_pct']} 相对提升)")
        print(f"    跑赢 BH:    {roi['beat_bh_ratio']}")
        print(f"    盈利股票:   {roi['profitable_stock_ratio']}")

    # ── 5. 保存 ──
    output = {
        "pre_analysis": {
            "markdown_b_signals": {
                "n_signals": md_b_analysis["n_signals"],
                "mean_fwd_60d_return_pct": md_b_analysis["mean_fwd_return"],
                "median_fwd_60d_return_pct": md_b_analysis["median_fwd_return"],
                "positive_ratio_pct": md_b_analysis["positive_ratio"],
                "details": md_b_analysis.get("signals", []),
            },
            "unknown_forward_40d": {
                "n_unknown": unknown_analysis["n_unknown_snapshots"],
                "mean_fwd_40d_return_pct": unknown_analysis["mean_fwd_40d_return_pct"],
                "median_fwd_40d_return_pct": unknown_analysis["median_fwd_40d_return_pct"],
                "positive_ratio_pct": unknown_analysis["positive_fwd_ratio"],
                "by_candidate": unknown_analysis.get("by_candidate", {}),
            },
            "spring_forward": {
                "n_spring": spring_analysis["n_spring_signals"],
                "mean_fwd_20d_return_pct": spring_analysis["mean_fwd_20d"],
                "mean_fwd_40d_return_pct": spring_analysis["mean_fwd_40d"],
                "mean_fwd_60d_return_pct": spring_analysis["mean_fwd_60d"],
                "positive_20d_ratio_pct": spring_analysis["positive_20d_ratio"],
            },
        },
        "roi_comparison": plan_roi,
        "full_backtest": {
            v: {
                "mean_return_pct": round(float(np.mean([sr.total_return_pct for sr in srs])), 2),
                "median_return_pct": round(float(np.median([sr.total_return_pct for sr in srs])), 2),
                "mean_annualized_pct": round(float(np.mean([sr.annualized_return_pct for sr in srs])), 2),
                "profitable_stock_pct": round(sum(1 for sr in srs if sr.total_return_pct > 0) / len(srs) * 100, 1),
                "mean_sharpe": round(float(np.mean([sr.sharpe for sr in srs])), 3),
                "mean_max_dd_pct": round(float(np.mean([sr.max_drawdown_pct for sr in srs])), 2),
                "total_trades": sum(sr.n_trades for sr in srs),
            }
            for v, srs in per_variant.items() if srs
        },
        "config": {
            "n_stocks": len(samples),
            "window_step": 40,
            "min_window": 120,
            "elapsed_seconds": round(time.time() - t0, 1),
        },
    }

    out_path = PROJECT_ROOT / args.output
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    print(f"\n结果已保存到: {out_path}")
    print(f"总耗时: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
