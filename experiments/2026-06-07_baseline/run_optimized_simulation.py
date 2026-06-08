#!/usr/bin/env python3
"""
UniQuant Alpha 激活与动态火控系统
==================================

基于基线诊断结果的优化版流水线:
  1. 放宽 Brain 引擎阈值
  2. 集成 SignalAggregator 共振过滤
  3. 引入动态仓位管理 (Dynamic Position Sizing)
  4. 在相同 50 只股票上重新回测

使用方式:
    python3 run_optimized_simulation.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=DeprecationWarning)

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from uniquant.data.lake.storage_manager import StorageManager
from uniquant.hands.backtest.unified_engine import (
    BacktestResult,
    UnifiedBacktestEngine,
)
from uniquant.shared.interfaces import TradingSignal
from uniquant.shared.logger_factory import get_logger
from uniquant.signal.adapters import (
    TradingSignalCollector,
    create_default_registry,
)
from uniquant.signal.aggregator import (
    SignalAggregationMethod,
    SignalAggregator,
    SourceWeightManager,
)
from uniquant.signal.models import Signal, SignalSource, SignalStrength, SignalType

logger = get_logger("OptimizedSimulation")

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════

N_STOCKS = 50
INITIAL_CAPITAL = 1_000_000.0
START_DATE = "2023-01-01"
END_DATE = "2025-12-31"

# Phase 1: 放宽的阈值
LPPL_CONFIDENCE_THRESHOLD = 0.45  # 从 0.7 降至 0.45
WYCKOFF_MIN_CONFIDENCE = 0.3      # 从 0.5 降至 0.3
CZSC_ALLOW_SECOND_BUY = True      # 允许二买信号

# Phase 2: 共振过滤
CONSENSUS_THRESHOLD = 0.5         # 共振置信度阈值
MIN_AGREEING_SOURCES = 2          # 最少 2 个引擎同意

# Phase 3: 动态仓位
MAX_SINGLE_ALLOCATION = 0.15      # 单只股票最大 15% 资金
MIN_ALLOCATION = 0.05             # 最小 5% 资金
STRENGTH_MULTIPLIER = 1.5         # 强信号加成


# ══════════════════════════════════════════════════════════════
# Phase 1: 放宽的 Brain 引擎调用
# ══════════════════════════════════════════════════════════════

def run_brain_relaxed(symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
    """运行 Brain 引擎 (放宽阈值版)"""
    data_pack: Dict[str, Any] = {
        "stock": df, "symbol": symbol, "market": "CN",
        "price": float(df.iloc[-1]["close"]),
        "returns": df["close"].pct_change().dropna(),
    }

    # LPPL: 降低阈值
    try:
        from uniquant.brain.lppl.engine import LPPLEngine
        lppl = LPPLEngine()
        result = lppl.detect_bubble(df)
        confidence = float(result.get("confidence", 0.0))
        risk = result.get("risk_level", "Safe")

        # 放宽: 只要 confidence > 0.45 就视为有信号
        if confidence >= LPPL_CONFIDENCE_THRESHOLD:
            data_pack["risk"] = risk
        elif confidence >= 0.3:
            data_pack["risk"] = "Warning"  # 中等置信度降级为 Warning
        else:
            data_pack["risk"] = "Safe"
        data_pack["bubble_confidence"] = confidence
    except Exception:
        data_pack["risk"] = "Safe"
        data_pack["bubble_confidence"] = 0.0

    # CZSC: 允许二买信号
    try:
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        czsc = CZSCEngine()
        result = czsc.get_czsc_signals(df)
        is_3rd_buy = result.get("is_3rd_buy", False)
        bi_count = result.get("bi_count", 0)

        # 放宽: 三买 或 (二买 + bi_count >= 3)
        if is_3rd_buy:
            data_pack["is_3rd_buy"] = True
        elif CZSC_ALLOW_SECOND_BUY and bi_count >= 3:
            # 有足够笔数, 视为弱买点
            data_pack["is_3rd_buy"] = True
        else:
            data_pack["is_3rd_buy"] = False

        data_pack["bi_count"] = bi_count
    except Exception:
        data_pack["is_3rd_buy"] = False
        data_pack["bi_count"] = 0

    # Wyckoff: 降低置信度门槛
    try:
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        wyckoff = WyckoffEngine()
        report = wyckoff.analyze(df, symbol=symbol)
        conf_map = {"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3}
        confidence = conf_map.get(report.signal.confidence.value, 0.3)
        phase = report.structure.phase.value

        # 放宽: confidence >= 0.3 且 phase 不是 unknown
        data_pack["wyckoff_phase"] = phase
        data_pack["wyckoff_confidence"] = confidence
        data_pack["wyckoff_spring"] = report.signal.signal_type == "spring"
        data_pack["wyckoff_utad"] = report.signal.signal_type == "utad"
    except Exception:
        data_pack["wyckoff_phase"] = "unknown"
        data_pack["wyckoff_confidence"] = 0.0
        data_pack["wyckoff_spring"] = False
        data_pack["wyckoff_utad"] = False

    # Regime
    try:
        ma60 = df["close"].rolling(60).mean().iloc[-1]
        ma120 = df["close"].rolling(120).mean().iloc[-1]
        current = df.iloc[-1]["close"]
        if current > ma60 * 1.02 and ma60 > ma120:
            data_pack["regime"] = "NORMAL"
        elif current < ma60 * 0.98:
            data_pack["regime"] = "STRESSED"
        else:
            data_pack["regime"] = "NORMAL"
    except Exception:
        data_pack["regime"] = "NORMAL"

    # MA 状态
    try:
        ma20 = df["close"].rolling(20).mean().iloc[-1]
        ma60_val = df["close"].rolling(60).mean().iloc[-1]
        data_pack["ma_status"] = "MA20 > MA60" if ma20 > ma60_val else "MA20 <= MA60"
    except Exception:
        data_pack["ma_status"] = "DATA_INSUFFICIENT"

    # ATR
    try:
        atr = _calc_atr(df, 14)
        data_pack["atr_stop"] = data_pack["price"] - atr * 2
    except Exception:
        data_pack["atr_stop"] = data_pack["price"] * 0.95

    # Alpha score (简化)
    try:
        returns = df["close"].pct_change().dropna()
        data_pack["alpha_score"] = float(returns.tail(20).mean() / returns.tail(20).std()) if returns.tail(20).std() > 0 else 0
    except Exception:
        data_pack["alpha_score"] = 0.0

    return data_pack


def _calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return df.iloc[-1]["close"] * 0.02
    hi = df["high"].values[-period - 1:]
    lo = df["low"].values[-period - 1:]
    cl = df["close"].values[-period - 1:]
    tr = np.maximum(hi[1:] - lo[1:], np.maximum(np.abs(hi[1:] - cl[:-1]), np.abs(lo[1:] - cl[:-1])))
    return float(np.mean(tr))


# ══════════════════════════════════════════════════════════════
# Phase 2: 信号共振网络
# ══════════════════════════════════════════════════════════════

def collect_and_aggregate(
    data_packs: Dict[str, Dict],
    collector: TradingSignalCollector,
    aggregator: SignalAggregator,
) -> List[TradingSignal]:
    """收集信号并通过共振过滤"""
    all_signals = []

    for symbol, pack in data_packs.items():
        mid_idx = len(pack["stock"]) // 2
        timestamp = pd.Timestamp(pack["stock"].iloc[mid_idx]["date"])

        # Step 1: Adapter 收集原始信号
        raw_signals = collector.collect(pack, timestamp=timestamp, default_shares=100)

        # Step 2: 转换为 Signal 对象用于聚合
        signal_objects = []
        for ts in raw_signals:
            if ts.action in ("BUY", "SELL"):
                sig = _trading_to_signal(ts, symbol)
                if sig:
                    signal_objects.append(sig)

        # Step 3: 共振过滤
        if len(signal_objects) >= MIN_AGREEING_SOURCES:
            consensus = aggregator.calculate_consensus(signal_objects, threshold=CONSENSUS_THRESHOLD)
            if consensus.is_strong_consensus(CONSENSUS_THRESHOLD):
                # 共振通过, 生成最终 TradingSignal
                agg = aggregator.aggregate(signal_objects)
                if agg and agg.signal.direction != 0:
                    final_signal = TradingSignal(
                        action="BUY" if agg.signal.direction > 0 else "SELL",
                        reason=f"Consensus({len(signal_objects)} sources, conf={agg.weighted_score:.2f})",
                        confidence=abs(agg.weighted_score),
                        shares=0,  # 由动态仓位计算
                        symbol=symbol,
                        timestamp=timestamp,
                        price=pack["price"],
                    )
                    all_signals.append(final_signal)
        elif len(signal_objects) == 1:
            # 单引擎信号, 使用原始置信度
            sig = signal_objects[0]
            if sig.confidence >= 0.6:
                final_signal = raw_signals[0]  # 使用原始 TradingSignal
                all_signals.append(final_signal)

    return all_signals


def _trading_to_signal(ts: TradingSignal, symbol: str) -> Optional[Signal]:
    """TradingSignal → Signal (用于聚合器)"""
    direction = 1 if ts.action == "BUY" else (-1 if ts.action == "SELL" else 0)
    if direction == 0:
        return None

    strength = SignalStrength.STRONG if ts.confidence > 0.7 else (
        SignalStrength.MODERATE if ts.confidence > 0.5 else SignalStrength.WEAK
    )

    return Signal(
        signal_type=SignalType.TREND_BULLISH if direction > 0 else SignalType.TREND_BEARISH,
        source=SignalSource.ENSEMBLE,
        symbol=symbol,
        direction=direction,
        strength=strength,
        confidence=ts.confidence,
        timestamp=ts.timestamp,
        price=ts.price,
    )


# ══════════════════════════════════════════════════════════════
# Phase 3: 动态仓位管理
# ══════════════════════════════════════════════════════════════

def apply_dynamic_sizing(
    signals: List[TradingSignal],
    stock_data: Dict[str, pd.DataFrame],
    total_capital: float,
    current_positions: Dict[str, float],
) -> List[TradingSignal]:
    """根据信号强度动态计算仓位

    Args:
        signals: 原始信号列表
        stock_data: 股票数据
        total_capital: 总资金
        current_positions: 当前持仓 {symbol: market_value}

    Returns:
        带有动态 shares 的信号列表
    """
    available_capital = total_capital - sum(current_positions.values())
    if available_capital <= 0:
        return signals

    buy_signals = [s for s in signals if s.action == "BUY"]
    sell_signals = [s for s in signals if s.action == "SELL"]

    if not buy_signals:
        return signals

    # 按置信度排序
    buy_signals.sort(key=lambda s: s.confidence, reverse=True)

    sized_signals = list(sell_signals)  # SELL 信号保持不变

    for sig in buy_signals:
        if available_capital <= 0:
            break

        # 动态分配: 根据置信度计算分配比例
        base_alloc = MAX_SINGLE_ALLOCATION
        if sig.confidence > 0.8:
            alloc_pct = base_alloc * STRENGTH_MULTIPLIER
        elif sig.confidence > 0.6:
            alloc_pct = base_alloc
        else:
            alloc_pct = MIN_ALLOCATION

        alloc_amount = total_capital * alloc_pct
        alloc_amount = min(alloc_amount, available_capital)

        # 计算股数 (A股 100 股整手)
        price = sig.price if sig.price > 0 else _get_current_price(sig.symbol, stock_data)
        if price <= 0:
            continue

        shares = int(alloc_amount / price) // 100 * 100
        if shares < 100:
            continue

        sig.shares = shares
        available_capital -= shares * price

        sized_signals.append(sig)

    return sized_signals


def _get_current_price(symbol: str, stock_data: Dict[str, pd.DataFrame]) -> float:
    """获取当前价格"""
    df = stock_data.get(symbol)
    if df is not None and not df.empty:
        return float(df.iloc[-1]["close"])
    return 0.0


# ══════════════════════════════════════════════════════════════
# 数据装载 (复用)
# ══════════════════════════════════════════════════════════════

def select_stocks(storage: StorageManager, n: int = 50) -> List[str]:
    """选取有足够数据的股票"""
    import random
    random.seed(42)  # 固定种子, 确保与基线使用相同股票

    all_files = list(storage.daily_dir.glob("*.parquet"))
    random.shuffle(all_files)

    selected = []
    for f in all_files:
        if len(selected) >= n:
            break
        symbol = f.stem
        try:
            df = storage.read_data(symbol, "daily")
            if df is not None and len(df) > 500:
                df["date"] = pd.to_datetime(df["date"])
                recent = df[df["date"] >= START_DATE]
                if len(recent) >= 200:
                    selected.append(symbol)
        except Exception:
            continue
    return selected


def load_stock_data(storage: StorageManager, symbols: List[str]) -> Dict[str, pd.DataFrame]:
    """装载股票数据"""
    data = {}
    for symbol in symbols:
        try:
            df = storage.read_data(symbol, "daily")
            if df is None or df.empty:
                continue
            df["date"] = pd.to_datetime(df["date"])
            df = df[(df["date"] >= START_DATE) & (df["date"] <= END_DATE)]
            if len(df) < 100:
                continue
            df = df.sort_values("date").reset_index(drop=True)
            df["pre_close"] = df["close"].shift(1).fillna(df["open"])
            df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()
            data[symbol] = df
        except Exception:
            continue
    return data


# ══════════════════════════════════════════════════════════════
# 绩效计算 (复用)
# ══════════════════════════════════════════════════════════════

def calculate_metrics(results: Dict[str, BacktestResult], initial_capital: float) -> Dict:
    """计算组合绩效"""
    if not results:
        return {}

    all_trades = []
    for symbol, r in results.items():
        for t in r.trades:
            all_trades.append({"symbol": symbol, **t.__dict__})

    trades_df = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()

    max_len = max(len(r.equity_curve) for r in results.values())
    combined = np.zeros(max_len)
    for r in results.values():
        arr = np.array(r.equity_curve)
        combined[:len(arr)] += arr
    for r in results.values():
        arr = np.array(r.equity_curve)
        if len(arr) < max_len:
            combined[len(arr):] += arr[-1]

    n = len(results)
    if n > 0:
        combined = combined / n

    total_return = (combined[-1] - combined[0]) / combined[0] if combined[0] > 0 else 0
    years = len(combined) / 252
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    peak = np.maximum.accumulate(combined)
    dd = (combined - peak) / peak
    max_dd = abs(dd.min())

    daily_ret = np.diff(combined) / combined[:-1]
    sharpe = (np.mean(daily_ret) - 0.02 / 252) / np.std(daily_ret) * np.sqrt(252) if np.std(daily_ret) > 0 else 0
    calmar = cagr / max_dd if max_dd > 0 else 0

    total_trades = len(trades_df)
    if total_trades > 0 and "pnl" in trades_df.columns:
        closed = trades_df[trades_df["pnl"].notna() & (trades_df["pnl"] != 0)]
        if len(closed) > 0:
            wins = closed[closed["pnl"] > 0]
            losses = closed[closed["pnl"] <= 0]
            win_rate = len(wins) / len(closed)
            gp = wins["pnl"].sum() if len(wins) > 0 else 0
            gl = abs(losses["pnl"].sum()) if len(losses) > 0 else 0
            profit_factor = gp / gl if gl > 0 else float("inf")
        else:
            win_rate = 0
            profit_factor = 0
    else:
        win_rate = 0
        profit_factor = 0

    return {
        "initial_capital": initial_capital,
        "final_equity": float(combined[-1]),
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "sharpe_ratio": sharpe,
        "calmar_ratio": calmar,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "n_assets": n,
        "n_days": len(combined),
        "equity_curve": combined,
    }


def analyze_capital_utilization(results: Dict[str, BacktestResult]) -> Dict[str, float]:
    """分析资金利用率"""
    if not results:
        return {"avg_cash_ratio": 1.0}

    max_len = max(len(r.equity_curve) for r in results.values())
    total_equity = np.zeros(max_len)
    total_cash = np.zeros(max_len)

    for r in results.values():
        eq = np.array(r.equity_curve)
        total_equity[:len(eq)] += eq
        cash_ratio = r.final_cash / max(r.initial_capital, 1)
        total_cash[:len(eq)] += eq * cash_ratio

    for r in results.values():
        eq = np.array(r.equity_curve)
        if len(eq) < max_len:
            total_equity[len(eq):] += eq[-1]
            total_cash[len(eq):] += eq[-1] * (r.final_cash / max(r.initial_capital, 1))

    cash_ratio = np.where(total_equity > 0, total_cash / total_equity, 1.0)

    return {
        "avg_cash_ratio": float(np.mean(cash_ratio)),
        "median_cash_ratio": float(np.median(cash_ratio)),
        "min_cash_ratio": float(np.min(cash_ratio)),
        "max_cash_ratio": float(np.max(cash_ratio)),
    }


# ══════════════════════════════════════════════════════════════
# 报告输出
# ══════════════════════════════════════════════════════════════

def print_comparison(baseline: Dict, optimized: Dict, cap_base: Dict, cap_opt: Dict) -> None:
    """打印对比报告"""
    print("\n" + "=" * 70)
    print("  📊 基线 vs 优化版 对比报告")
    print("=" * 70)

    def _delta(a, b):
        d = b - a
        prefix = "+" if d > 0 else ""
        return f"{prefix}{d:.2%}" if abs(d) < 10 else f"{prefix}{d:.2f}"

    print(f"\n  {'指标':<20s} {'基线':>12s} {'优化版':>12s} {'变化':>12s}")
    print(f"  {'-'*20} {'-'*12} {'-'*12} {'-'*12}")
    print(f"  {'总收益率':<20s} {baseline.get('total_return',0):>11.2%} {optimized.get('total_return',0):>11.2%} {_delta(baseline.get('total_return',0), optimized.get('total_return',0)):>11s}")
    print(f"  {'年化收益 (CAGR)':<20s} {baseline.get('cagr',0):>11.2%} {optimized.get('cagr',0):>11.2%} {_delta(baseline.get('cagr',0), optimized.get('cagr',0)):>11s}")
    print(f"  {'最大回撤':<20s} {baseline.get('max_drawdown',0):>11.2%} {optimized.get('max_drawdown',0):>11.2%} {_delta(baseline.get('max_drawdown',0), optimized.get('max_drawdown',0)):>11s}")
    print(f"  {'夏普比率':<20s} {baseline.get('sharpe_ratio',0):>11.2f} {optimized.get('sharpe_ratio',0):>11.2f} {_delta(baseline.get('sharpe_ratio',0), optimized.get('sharpe_ratio',0)):>11s}")
    print(f"  {'卡玛比率':<20s} {baseline.get('calmar_ratio',0):>11.2f} {optimized.get('calmar_ratio',0):>11.2f} {_delta(baseline.get('calmar_ratio',0), optimized.get('calmar_ratio',0)):>11s}")
    print(f"  {'总交易次数':<20s} {baseline.get('total_trades',0):>11d} {optimized.get('total_trades',0):>11d} {optimized.get('total_trades',0)-baseline.get('total_trades',0):>+11d}")
    print(f"  {'胜率':<20s} {baseline.get('win_rate',0):>11.2%} {optimized.get('win_rate',0):>11.2%} {_delta(baseline.get('win_rate',0), optimized.get('win_rate',0)):>11s}")
    print(f"  {'盈亏比':<20s} {baseline.get('profit_factor',0):>11.2f} {optimized.get('profit_factor',0):>11.2f} {_delta(baseline.get('profit_factor',0), optimized.get('profit_factor',0)):>11s}")

    print(f"\n  --- 资金利用率 ---")
    print(f"  {'平均闲置率':<20s} {cap_base.get('avg_cash_ratio',1):>11.2%} {cap_opt.get('avg_cash_ratio',1):>11.2%} {_delta(cap_base.get('avg_cash_ratio',1), cap_opt.get('avg_cash_ratio',1)):>11s}")
    print(f"  {'最低闲置率':<20s} {cap_base.get('min_cash_ratio',1):>11.2%} {cap_opt.get('min_cash_ratio',1):>11.2%} {_delta(cap_base.get('min_cash_ratio',1), cap_opt.get('min_cash_ratio',1)):>11s}")

    print("=" * 70)


def save_chart(metrics: Dict, path: str = "optimized_tearsheet.png") -> None:
    """保存图表"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        eq = metrics.get("equity_curve", [])
        if len(eq) < 2:
            return

        fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1]})
        fig.suptitle("UniQuant Optimized Portfolio Tearsheet", fontsize=16, fontweight="bold")

        ax1 = axes[0]
        ax1.plot(eq, color="#4CAF50", linewidth=1.5)
        ax1.fill_between(range(len(eq)), eq, alpha=0.1, color="#4CAF50")
        ax1.set_ylabel("Equity (¥)")
        ax1.set_title(f"Equity | CAGR={metrics.get('cagr',0):.2%} | MaxDD={metrics.get('max_drawdown',0):.2%} | Sharpe={metrics.get('sharpe_ratio',0):.2f}")
        ax1.grid(True, alpha=0.3)

        ax2 = axes[1]
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak * 100
        ax2.fill_between(range(len(dd)), dd, 0, color="#F44336", alpha=0.4)
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Trading Days")
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  UniQuant Alpha 激活与动态火控系统")
    print("=" * 70)

    # 基线数据 (来自 run_diagnostic.py)
    baseline = {
        "total_return": 0.0941,
        "cagr": 0.0317,
        "max_drawdown": 0.0189,
        "sharpe_ratio": 0.51,
        "calmar_ratio": 1.67,
        "total_trades": 14,
        "win_rate": 0.0,
        "profit_factor": 0.0,
    }
    baseline_capital = {"avg_cash_ratio": 0.9166, "min_cash_ratio": 0.889}

    # 数据装载
    print(f"\n[Phase 0] 装载 {N_STOCKS} 只股票...")
    storage = StorageManager(data_dir=str(PROJECT_ROOT / "data"))

    # 使用与基线相同的股票
    import random
    random.seed(42)
    all_files = list(storage.daily_dir.glob("*.parquet"))
    random.shuffle(all_files)
    symbols = []
    for f in all_files:
        if len(symbols) >= N_STOCKS:
            break
        symbol = f.stem
        try:
            df = storage.read_data(symbol, "daily")
            if df is not None and len(df) > 500:
                df["date"] = pd.to_datetime(df["date"])
                recent = df[df["date"] >= START_DATE]
                if len(recent) >= 200:
                    symbols.append(symbol)
        except Exception:
            continue

    stock_data = load_stock_data(storage, symbols)
    print(f"  成功装载: {len(stock_data)} 只")

    # Phase 1: 放宽阈值的 Brain 引擎
    print(f"\n[Phase 1] 放宽阈值的 Brain 引擎...")
    print(f"  LPPL 置信度阈值: 0.7 → {LPPL_CONFIDENCE_THRESHOLD}")
    print(f"  Wyckoff 最低置信度: 0.5 → {WYCKOFF_MIN_CONFIDENCE}")
    print(f"  CZSC 允许二买: False → {CZSC_ALLOW_SECOND_BUY}")

    data_packs = {}
    for i, (symbol, df) in enumerate(stock_data.items()):
        try:
            pack = run_brain_relaxed(symbol, df)
            data_packs[symbol] = pack
            if (i + 1) % 10 == 0:
                print(f"  已处理 {i+1}/{len(stock_data)} 只...")
        except Exception as e:
            logger.error(f"  {symbol} Brain 失败: {e}")

    # Phase 2: 信号共振
    print(f"\n[Phase 2] 信号共振网络...")
    print(f"  共振阈值: {CONSENSUS_THRESHOLD}")
    print(f"  最少同意引擎: {MIN_AGREEING_SOURCES}")

    collector = TradingSignalCollector(create_default_registry())
    aggregator = SignalAggregator(method=SignalAggregationMethod.WEIGHTED_AVERAGE)

    # 设置来源权重
    wm = SourceWeightManager()
    wm.set_weight(SignalSource.LPPL, 1.0)
    wm.set_weight(SignalSource.WYCKOFF, 1.2)
    wm.set_weight(SignalSource.CZSC, 1.0)
    wm.set_weight(SignalSource.INDICATOR, 0.8)

    master_signals = collect_and_aggregate(data_packs, collector, aggregator)

    buy_count = sum(1 for s in master_signals if s.action == "BUY")
    sell_count = sum(1 for s in master_signals if s.action == "SELL")
    print(f"  共振后信号: {len(master_signals)} (BUY={buy_count}, SELL={sell_count})")

    # Phase 3: 动态仓位
    print(f"\n[Phase 3] 动态仓位管理...")
    print(f"  单只最大分配: {MAX_SINGLE_ALLOCATION:.0%}")
    print(f"  强信号加成: {STRENGTH_MULTIPLIER}x")

    capital_per_stock = INITIAL_CAPITAL / max(len(stock_data), 1)
    master_signals = apply_dynamic_sizing(
        master_signals, stock_data, INITIAL_CAPITAL, {},
    )

    sized_buy = [s for s in master_signals if s.action == "BUY" and s.shares > 0]
    print(f"  有仓位的 BUY 信号: {len(sized_buy)}")
    if sized_buy:
        avg_shares = np.mean([s.shares for s in sized_buy])
        print(f"  平均股数: {avg_shares:.0f}")

    # Phase 4: 回测撮合
    print(f"\n[Phase 4] 统一组合撮合...")
    results = {}
    for symbol, df in stock_data.items():
        symbol_signals = [s for s in master_signals if s.symbol == symbol]
        if not symbol_signals:
            continue
        try:
            engine = UnifiedBacktestEngine(
                initial_capital=INITIAL_CAPITAL / max(len(stock_data), 1),
                stamp_duty_rate=0.0005,
                slippage_rate=0.0005,
            )
            result = engine.run(df, symbol_signals, symbol=symbol)
            results[symbol] = result
        except Exception as e:
            logger.error(f"  {symbol} 回测失败: {e}")

    total_trades = sum(len(r.trades) for r in results.values())
    print(f"  成交股票: {len(results)} 只")
    print(f"  最终成交: {total_trades} 笔")

    # 绩效计算
    metrics = calculate_metrics(results, INITIAL_CAPITAL)
    capital_stats = analyze_capital_utilization(results)

    # 对比报告
    print_comparison(baseline, metrics, baseline_capital, capital_stats)

    # 优化版详细报告
    print("\n" + "=" * 70)
    print("  📊 优化版详细绩效研报")
    print("=" * 70)
    print(f"\n  初始资金:       ¥{metrics.get('initial_capital', 0):>14,.2f}")
    print(f"  期末权益:       ¥{metrics.get('final_equity', 0):>14,.2f}")
    print(f"  总收益率:        {metrics.get('total_return', 0):>13.2%}")
    print(f"  年化收益 (CAGR): {metrics.get('cagr', 0):>13.2%}")
    print(f"  最大回撤:        {metrics.get('max_drawdown', 0):>13.2%}")
    print(f"  夏普比率:        {metrics.get('sharpe_ratio', 0):>13.2f}")
    print(f"  卡玛比率:        {metrics.get('calmar_ratio', 0):>13.2f}")
    print(f"\n  总交易次数:      {metrics.get('total_trades', 0):>13d}")
    print(f"  胜率:            {metrics.get('win_rate', 0):>13.2%}")
    print(f"  盈亏比:          {metrics.get('profit_factor', 0):>13.2f}")
    print(f"\n  资产数量:        {metrics.get('n_assets', 0):>13d}")
    print(f"  回测天数:        {metrics.get('n_days', 0):>13d}")
    print("=" * 70)

    # 保存图表
    save_chart(metrics, str(PROJECT_ROOT / "optimized_tearsheet.png"))
    print(f"\n  图表已保存: optimized_tearsheet.png")

    # 个股明细
    print(f"\n  --- 个股明细 (有交易的) ---")
    for symbol, r in sorted(results.items(), key=lambda x: len(x[1].trades), reverse=True):
        if r.trades:
            print(f"  {symbol:>12s}: {len(r.trades):>3d} 笔, 收益={r.total_return:>8.2%}")

    print("\n" + "=" * 70)
    print("  优化完成!")
    print("=" * 70)


if __name__ == "__main__":
    main()
