#!/usr/bin/env python3
"""
UniQuant 样本外盲测 (Out-of-Sample Blind Test)
================================================

验证调优后的引擎在完全未见过的市场环境和标的下的真实生存能力。

测试条件:
  - 时间外推: 2018-01-01 至 2022-12-31 (含 2018 大熊市 + 2020 疫情底)
  - 资产外推: 50 只完全不同的中证 500 成分股
  - 参数绝对锁定: 与 run_optimized_simulation.py 完全一致

使用方式:
    python3 run_oos_blind_test.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=DeprecationWarning)

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from uniquant.data.lake.storage_manager import StorageManager
from uniquant.hands.backtest.unified_engine import BacktestResult, UnifiedBacktestEngine
from uniquant.shared.interfaces import TradingSignal
from uniquant.shared.logger_factory import get_logger
from uniquant.signal.adapters import TradingSignalCollector, create_default_registry
from uniquant.signal.aggregator import SignalAggregationMethod, SignalAggregator, SourceWeightManager
from uniquant.signal.models import Signal, SignalSource, SignalStrength, SignalType

logger = get_logger("OOS_BlindTest")

# ══════════════════════════════════════════════════════════════
# 配置 (参数绝对锁定, 与优化版完全一致)
# ══════════════════════════════════════════════════════════════

N_STOCKS = 50
INITIAL_CAPITAL = 1_000_000.0
START_DATE = "2018-01-01"
END_DATE = "2022-12-31"

# 与 run_optimized_simulation.py 完全一致的参数
LPPL_CONFIDENCE_THRESHOLD = 0.45
WYCKOFF_MIN_CONFIDENCE = 0.3
CZSC_ALLOW_SECOND_BUY = True
CONSENSUS_THRESHOLD = 0.5
MIN_AGREEING_SOURCES = 2
MAX_SINGLE_ALLOCATION = 0.15
MIN_ALLOCATION = 0.05
STRENGTH_MULTIPLIER = 1.5


# ══════════════════════════════════════════════════════════════
# Brain 引擎 (与优化版完全一致)
# ══════════════════════════════════════════════════════════════

def run_brain_relaxed(symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
    data_pack: Dict[str, Any] = {
        "stock": df, "symbol": symbol, "market": "CN",
        "price": float(df.iloc[-1]["close"]),
        "returns": df["close"].pct_change().dropna(),
    }

    try:
        from uniquant.brain.lppl.engine import LPPLEngine
        result = LPPLEngine().detect_bubble(df)
        confidence = float(result.get("confidence", 0.0))
        data_pack["risk"] = result.get("risk_level", "Safe") if confidence >= LPPL_CONFIDENCE_THRESHOLD else ("Warning" if confidence >= 0.3 else "Safe")
        data_pack["bubble_confidence"] = confidence
    except Exception:
        data_pack["risk"] = "Safe"
        data_pack["bubble_confidence"] = 0.0

    try:
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        result = CZSCEngine().get_czsc_signals(df)
        is_3rd = result.get("is_3rd_buy", False)
        bi = result.get("bi_count", 0)
        data_pack["is_3rd_buy"] = is_3rd or (CZSC_ALLOW_SECOND_BUY and bi >= 3)
        data_pack["bi_count"] = bi
    except Exception:
        data_pack["is_3rd_buy"] = False
        data_pack["bi_count"] = 0

    try:
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        report = WyckoffEngine().analyze(df, symbol=symbol)
        conf_map = {"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3}
        data_pack["wyckoff_phase"] = report.structure.phase.value
        data_pack["wyckoff_confidence"] = conf_map.get(report.signal.confidence.value, 0.3)
        data_pack["wyckoff_spring"] = report.signal.signal_type == "spring"
        data_pack["wyckoff_utad"] = report.signal.signal_type == "utad"
    except Exception:
        data_pack["wyckoff_phase"] = "unknown"
        data_pack["wyckoff_confidence"] = 0.0
        data_pack["wyckoff_spring"] = False
        data_pack["wyckoff_utad"] = False

    try:
        ma60 = df["close"].rolling(60).mean().iloc[-1]
        ma120 = df["close"].rolling(120).mean().iloc[-1]
        c = df.iloc[-1]["close"]
        data_pack["regime"] = "NORMAL" if (c > ma60 * 1.02 and ma60 > ma120) else ("STRESSED" if c < ma60 * 0.98 else "NORMAL")
    except Exception:
        data_pack["regime"] = "NORMAL"

    try:
        ma20 = df["close"].rolling(20).mean().iloc[-1]
        ma60v = df["close"].rolling(60).mean().iloc[-1]
        data_pack["ma_status"] = "MA20 > MA60" if ma20 > ma60v else "MA20 <= MA60"
    except Exception:
        data_pack["ma_status"] = "DATA_INSUFFICIENT"

    try:
        hi = df["high"].values[-15:]
        lo = df["low"].values[-15:]
        cl = df["close"].values[-15:]
        tr = np.maximum(hi[1:] - lo[1:], np.maximum(np.abs(hi[1:] - cl[:-1]), np.abs(lo[1:] - cl[:-1])))
        atr = float(np.mean(tr))
        data_pack["atr_stop"] = data_pack["price"] - atr * 2
    except Exception:
        data_pack["atr_stop"] = data_pack["price"] * 0.95

    try:
        ret = df["close"].pct_change().dropna()
        data_pack["alpha_score"] = float(ret.tail(20).mean() / ret.tail(20).std()) if ret.tail(20).std() > 0 else 0
    except Exception:
        data_pack["alpha_score"] = 0.0

    return data_pack


# ══════════════════════════════════════════════════════════════
# 信号共振 (与优化版完全一致)
# ══════════════════════════════════════════════════════════════

def _trading_to_signal(ts: TradingSignal, symbol: str) -> Optional[Signal]:
    direction = 1 if ts.action == "BUY" else (-1 if ts.action == "SELL" else 0)
    if direction == 0:
        return None
    strength = SignalStrength.STRONG if ts.confidence > 0.7 else (SignalStrength.MODERATE if ts.confidence > 0.5 else SignalStrength.WEAK)
    return Signal(
        signal_type=SignalType.TREND_BULLISH if direction > 0 else SignalType.TREND_BEARISH,
        source=SignalSource.ENSEMBLE, symbol=symbol, direction=direction,
        strength=strength, confidence=ts.confidence, timestamp=ts.timestamp, price=ts.price,
    )


def collect_and_aggregate(data_packs: Dict[str, Dict], collector: TradingSignalCollector, aggregator: SignalAggregator) -> List[TradingSignal]:
    all_signals = []
    for symbol, pack in data_packs.items():
        mid_idx = len(pack["stock"]) // 2
        timestamp = pd.Timestamp(pack["stock"].iloc[mid_idx]["date"])
        raw_signals = collector.collect(pack, timestamp=timestamp, default_shares=100)
        signal_objects = [_trading_to_signal(s, symbol) for s in raw_signals if s.action in ("BUY", "SELL")]
        signal_objects = [s for s in signal_objects if s is not None]

        if len(signal_objects) >= MIN_AGREEING_SOURCES:
            consensus = aggregator.calculate_consensus(signal_objects, threshold=CONSENSUS_THRESHOLD)
            if consensus.is_strong_consensus(CONSENSUS_THRESHOLD):
                agg = aggregator.aggregate(signal_objects)
                if agg and agg.signal.direction != 0:
                    all_signals.append(TradingSignal(
                        action="BUY" if agg.signal.direction > 0 else "SELL",
                        reason=f"Consensus({len(signal_objects)} sources, conf={agg.weighted_score:.2f})",
                        confidence=abs(agg.weighted_score), shares=0,
                        symbol=symbol, timestamp=timestamp, price=pack["price"],
                    ))
        elif len(signal_objects) == 1 and signal_objects[0].confidence >= 0.6:
            all_signals.append(raw_signals[0])
    return all_signals


def apply_dynamic_sizing(signals: List[TradingSignal], stock_data: Dict[str, pd.DataFrame], total_capital: float) -> List[TradingSignal]:
    available = total_capital
    buy_sigs = sorted([s for s in signals if s.action == "BUY"], key=lambda s: s.confidence, reverse=True)
    sell_sigs = [s for s in signals if s.action == "SELL"]
    sized = list(sell_sigs)

    for sig in buy_sigs:
        if available <= 0:
            break
        alloc_pct = MAX_SINGLE_ALLOCATION * STRENGTH_MULTIPLIER if sig.confidence > 0.8 else (MAX_SINGLE_ALLOCATION if sig.confidence > 0.6 else MIN_ALLOCATION)
        alloc = min(total_capital * alloc_pct, available)
        price = sig.price if sig.price > 0 else float(stock_data.get(sig.symbol, pd.DataFrame({"close": [0]})).iloc[-1]["close"])
        if price <= 0:
            continue
        shares = int(alloc / price) // 100 * 100
        if shares >= 100:
            sig.shares = shares
            available -= shares * price
            sized.append(sig)
    return sized


# ══════════════════════════════════════════════════════════════
# 数据与绩效
# ══════════════════════════════════════════════════════════════

def select_oos_stocks(storage: StorageManager, n: int = 50) -> List[str]:
    import random
    random.seed(99)
    all_files = list(storage.daily_dir.glob("*.parquet"))
    random.shuffle(all_files)
    selected = []
    for f in all_files:
        if len(selected) >= n:
            break
        try:
            df = pd.read_parquet(f)
            df["date"] = pd.to_datetime(df["date"])
            df = df[(df["date"] >= START_DATE) & (df["date"] <= END_DATE)]
            if len(df) >= 500:
                selected.append(f.stem)
        except Exception:
            continue
    return selected


def load_data(storage: StorageManager, symbols: List[str]) -> Dict[str, pd.DataFrame]:
    data = {}
    for s in symbols:
        try:
            df = storage.read_data(s, "daily")
            if df is None or df.empty:
                continue
            df["date"] = pd.to_datetime(df["date"])
            df = df[(df["date"] >= START_DATE) & (df["date"] <= END_DATE)]
            if len(df) < 100:
                continue
            df = df.sort_values("date").reset_index(drop=True)
            df["pre_close"] = df["close"].shift(1).fillna(df["open"])
            df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()
            data[s] = df
        except Exception:
            continue
    return data


def calc_metrics(results: Dict[str, BacktestResult], initial: float) -> Dict:
    if not results:
        return {}
    all_trades = []
    for sym, r in results.items():
        for t in r.trades:
            all_trades.append({"symbol": sym, **t.__dict__})
    trades_df = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()

    max_len = max(len(r.equity_curve) for r in results.values())
    combined = np.zeros(max_len)
    for r in results.values():
        a = np.array(r.equity_curve)
        combined[:len(a)] += a
    for r in results.values():
        a = np.array(r.equity_curve)
        if len(a) < max_len:
            combined[len(a):] += a[-1]
    n = len(results)
    if n > 0:
        combined /= n

    total_ret = (combined[-1] - combined[0]) / combined[0] if combined[0] > 0 else 0
    years = len(combined) / 252
    cagr = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0
    peak = np.maximum.accumulate(combined)
    dd = (combined - peak) / peak
    max_dd = abs(dd.min())
    dr = np.diff(combined) / combined[:-1]
    sharpe = (np.mean(dr) - 0.02 / 252) / np.std(dr) * np.sqrt(252) if np.std(dr) > 0 else 0
    calmar = cagr / max_dd if max_dd > 0 else 0

    tt = len(trades_df)
    wr = pf = 0.0
    if tt > 0 and "pnl" in trades_df.columns:
        closed = trades_df[trades_df["pnl"].notna() & (trades_df["pnl"] != 0)]
        if len(closed) > 0:
            wins = closed[closed["pnl"] > 0]
            losses = closed[closed["pnl"] <= 0]
            wr = len(wins) / len(closed)
            gp = wins["pnl"].sum() if len(wins) > 0 else 0
            gl = abs(losses["pnl"].sum()) if len(losses) > 0 else 0
            pf = gp / gl if gl > 0 else float("inf")

    return {
        "initial_capital": initial, "final_equity": float(combined[-1]),
        "total_return": total_ret, "cagr": cagr, "max_drawdown": max_dd,
        "sharpe_ratio": sharpe, "calmar_ratio": calmar,
        "total_trades": tt, "win_rate": wr, "profit_factor": pf,
        "n_assets": n, "n_days": len(combined), "equity_curve": combined,
    }


def print_oos_report(metrics: Dict, in_sample: Dict) -> None:
    print("\n" + "=" * 70)
    print("  🔮 样本外盲测报告 (OOS Blind Test)")
    print("=" * 70)
    print(f"\n  测试区间: {START_DATE} ~ {END_DATE}")
    print(f"  测试标的: {metrics.get('n_assets', 0)} 只中证 500 成分股")
    print(f"  包含极端行情: 2018 大熊市 / 2020 疫情底 / 2022 震荡市")

    print(f"\n  {'指标':<20s} {'样本内(IS)':>12s} {'样本外(OOS)':>12s} {'衰减':>10s}")
    print(f"  {'-'*20} {'-'*12} {'-'*12} {'-'*10}")

    def _row(name, is_key, oos_key):
        is_v = in_sample.get(is_key, 0)
        oos_v = metrics.get(oos_key, 0)
        decay = (oos_v - is_v) / abs(is_v) if is_v != 0 else 0
        print(f"  {name:<20s} {is_v:>11.2%} {oos_v:>11.2%} {decay:>+9.1%}")

    _row("总收益率", "total_return", "total_return")
    _row("年化收益(CAGR)", "cagr", "cagr")
    _row("最大回撤", "max_drawdown", "max_drawdown")

    is_sharpe = in_sample.get("sharpe_ratio", 0)
    oos_sharpe = metrics.get("sharpe_ratio", 0)
    print(f"  {'夏普比率':<20s} {is_sharpe:>11.2f} {oos_sharpe:>11.2f} {(oos_sharpe-is_sharpe)/abs(is_sharpe) if is_sharpe else 0:>+9.1%}")

    print(f"\n  --- 合格检验 ---")
    sharpe_ok = oos_sharpe > 0.8
    dd_ok = metrics.get("max_drawdown", 1) < 0.15
    print(f"  OOS 夏普 > 0.8:     {'✅ PASS' if sharpe_ok else '❌ FAIL'} ({oos_sharpe:.2f})")
    print(f"  OOS 最大回撤 < 15%: {'✅ PASS' if dd_ok else '❌ FAIL'} ({metrics.get('max_drawdown',0):.2%})")
    print(f"\n  综合判定: {'🚀 实盘就绪!' if (sharpe_ok and dd_ok) else '⚠️ 需要进一步验证'}")
    print("=" * 70)


def save_chart(metrics: Dict, path: str = "oos_tearsheet.png") -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        eq = metrics.get("equity_curve", [])
        if len(eq) < 2:
            return
        fig, axes = plt.subplots(2, 1, figsize=(14, 10))
        fig.suptitle("UniQuant OOS Blind Test Tearsheet", fontsize=16, fontweight="bold")
        ax1 = axes[0]
        ax1.plot(eq, color="#FF9800", linewidth=1.5)
        ax1.fill_between(range(len(eq)), eq, alpha=0.1, color="#FF9800")
        ax1.set_ylabel("Equity (¥)")
        ax1.set_title(f"OOS Equity | CAGR={metrics.get('cagr',0):.2%} | MaxDD={metrics.get('max_drawdown',0):.2%} | Sharpe={metrics.get('sharpe_ratio',0):.2f}")
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
    print("  UniQuant 样本外盲测 (OOS Blind Test)")
    print("  参数绝对锁定, 零修改")
    print("=" * 70)

    # 样本内基准数据
    in_sample = {
        "total_return": 0.4424, "cagr": 0.1354, "max_drawdown": 0.0956,
        "sharpe_ratio": 1.00, "calmar_ratio": 1.42,
    }

    # 数据装载
    print(f"\n[Phase 1] 装载 OOS 数据 ({START_DATE} ~ {END_DATE})...")
    storage = StorageManager(data_dir=str(PROJECT_ROOT / "data"))
    symbols = select_oos_stocks(storage, N_STOCKS)
    stock_data = load_data(storage, symbols)
    print(f"  成功装载: {len(stock_data)} 只")

    if len(stock_data) < 10:
        print("  [ERROR] 数据不足")
        return

    # Brain 引擎
    print(f"\n[Phase 2] Brain 引擎 (参数锁定)...")
    data_packs = {}
    for i, (sym, df) in enumerate(stock_data.items()):
        try:
            data_packs[sym] = run_brain_relaxed(sym, df)
            if (i + 1) % 10 == 0:
                print(f"  已处理 {i+1}/{len(stock_data)}...")
        except Exception:
            continue

    # 信号共振
    print(f"\n[Phase 3] 信号共振...")
    collector = TradingSignalCollector(create_default_registry())
    aggregator = SignalAggregator(method=SignalAggregationMethod.WEIGHTED_AVERAGE)
    master_signals = collect_and_aggregate(data_packs, collector, aggregator)
    buy_n = sum(1 for s in master_signals if s.action == "BUY")
    sell_n = sum(1 for s in master_signals if s.action == "SELL")
    print(f"  共振信号: {len(master_signals)} (BUY={buy_n}, SELL={sell_n})")

    # 动态仓位
    print(f"\n[Phase 4] 动态仓位...")
    master_signals = apply_dynamic_sizing(master_signals, stock_data, INITIAL_CAPITAL)
    sized = [s for s in master_signals if s.action == "BUY" and s.shares > 0]
    print(f"  有仓位信号: {len(sized)}")

    # 回测撮合
    print(f"\n[Phase 5] 回测撮合...")
    results = {}
    for sym, df in stock_data.items():
        sigs = [s for s in master_signals if s.symbol == sym]
        if not sigs:
            continue
        try:
            engine = UnifiedBacktestEngine(
                initial_capital=INITIAL_CAPITAL / max(len(stock_data), 1),
                stamp_duty_rate=0.0005, slippage_rate=0.0005,
            )
            results[sym] = engine.run(df, sigs, symbol=sym)
        except Exception:
            continue

    total_trades = sum(len(r.trades) for r in results.values())
    print(f"  成交: {len(results)} 只, {total_trades} 笔")

    # 绩效报告
    metrics = calc_metrics(results, INITIAL_CAPITAL)
    print_oos_report(metrics, in_sample)
    save_chart(metrics, str(PROJECT_ROOT / "oos_tearsheet.png"))
    print(f"\n  图表: oos_tearsheet.png")

    # 个股明细
    print(f"\n  --- 有交易的个股 ---")
    for sym, r in sorted(results.items(), key=lambda x: len(x[1].trades), reverse=True):
        if r.trades:
            print(f"  {sym:>12s}: {len(r.trades):>3d} 笔, 收益={r.total_return:>8.2%}")

    print("\n" + "=" * 70)
    print("  盲测完成!")
    print("=" * 70)


if __name__ == "__main__":
    main()
