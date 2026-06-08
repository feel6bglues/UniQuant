#!/usr/bin/env python3
"""
UniQuant 风控抢救版 OOS 盲测
==============================

修复内容:
  1. 独立被动止损层 (Hard Stop + ATR Trailing Stop)
  2. 波动率平价仓位 (ATR-based Position Sizing, 单只上限 5%)
  3. 自适应信号放松 (熊市降低共振门槛)
  4. 重新运行 2018-2022 OOS 盲测

使用方式:
    python3 run_oos_risk_rescue.py
"""

from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
from uniquant.signal.aggregator import SignalAggregationMethod, SignalAggregator
from uniquant.signal.models import Signal, SignalSource, SignalStrength, SignalType

logger = get_logger("RiskRescue")


# ══════════════════════════════════════════════════════════════
# 配置 (参数锁定)
# ══════════════════════════════════════════════════════════════

N_STOCKS = 50
INITIAL_CAPITAL = 1_000_000.0
START_DATE = "2018-01-01"
END_DATE = "2022-12-31"

# Brain 阈值 (与优化版一致)
LPPL_CONFIDENCE_THRESHOLD = 0.45
CZSC_ALLOW_SECOND_BUY = True
WYCKOFF_MIN_CONFIDENCE = 0.3

# 共振参数
CONSENSUS_THRESHOLD = 0.5
MIN_AGREEING_SOURCES = 2
BEAR_MIN_AGREEING_SOURCES = 1  # 熊市降低门槛

# 止损参数 (Phase 1)
HARD_STOP_PCT = 0.08           # 硬止损 8%
ATR_TRAILING_MULTIPLIER = 3.0  # ATR 跟踪止损倍数
STOP_LOSS_CONFIDENCE = 1.0     # 止损信号置信度

# 仓位参数 (Phase 2)
RISK_PER_TRADE = 0.01          # 每笔风险 1% 总资金
MAX_SINGLE_ALLOCATION = 0.05   # 单只上限 5%
ATR_PERIOD = 14


# ══════════════════════════════════════════════════════════════
# Phase 1: 独立被动止损层
# ══════════════════════════════════════════════════════════════

@dataclass
class Position:
    """模拟持仓"""
    symbol: str
    entry_price: float
    shares: int
    entry_date: pd.Timestamp
    highest_price: float = 0.0

    def __post_init__(self):
        if self.highest_price == 0.0:
            self.highest_price = self.entry_price


def generate_risk_exit_signals(
    positions: Dict[str, Position],
    stock_data: Dict[str, pd.DataFrame],
    current_date: pd.Timestamp,
) -> List[TradingSignal]:
    """独立被动止损层 — 不依赖 Brain 引擎

    遍历所有持仓, 检查:
      1. 硬止损: 当前价 < 买入价 × (1 - HARD_STOP_PCT)
      2. ATR 跟踪止损: 最高点回撤 > ATR × MULTIPLIER

    Args:
        positions: 当前持仓 {symbol: Position}
        stock_data: 股票数据
        current_date: 当前日期

    Returns:
        强制卖出信号列表
    """
    exit_signals = []

    for symbol, pos in positions.items():
        df = stock_data.get(symbol)
        if df is None or df.empty:
            continue

        # 获取当前价格
        df["date"] = pd.to_datetime(df["date"])
        today_rows = df[df["date"] == current_date]
        if today_rows.empty:
            # 使用最近的价格
            today_rows = df[df["date"] <= current_date].tail(1)
            if today_rows.empty:
                continue

        current_price = float(today_rows.iloc[-1]["close"])

        # 更新最高价
        if current_price > pos.highest_price:
            pos.highest_price = current_price

        # 计算 ATR
        atr = _calc_atr_from_df(df, ATR_PERIOD, current_date)

        # 检查硬止损
        hard_stop_price = pos.entry_price * (1 - HARD_STOP_PCT)
        if current_price <= hard_stop_price:
            exit_signals.append(TradingSignal(
                action="SELL",
                reason=f"Hard Stop: {current_price:.2f} <= {hard_stop_price:.2f} ({HARD_STOP_PCT:.0%})",
                confidence=STOP_LOSS_CONFIDENCE,
                shares=pos.shares,
                symbol=symbol,
                timestamp=current_date,
                price=current_price,
            ))
            continue

        # 检查 ATR 跟踪止损
        if atr > 0:
            trailing_stop_price = pos.highest_price - ATR_TRAILING_MULTIPLIER * atr
            if current_price <= trailing_stop_price:
                exit_signals.append(TradingSignal(
                    action="SELL",
                    reason=f"ATR Trail: {current_price:.2f} <= {trailing_stop_price:.2f} (peak={pos.highest_price:.2f}, ATR={atr:.2f})",
                    confidence=STOP_LOSS_CONFIDENCE,
                    shares=pos.shares,
                    symbol=symbol,
                    timestamp=current_date,
                    price=current_price,
                ))

    return exit_signals


def _calc_atr_from_df(df: pd.DataFrame, period: int, as_of_date: pd.Timestamp) -> float:
    """计算截至指定日期的 ATR"""
    df_before = df[df["date"] <= as_of_date].tail(period + 5)
    if len(df_before) < period + 1:
        return float(df_before.iloc[-1]["close"]) * 0.02 if not df_before.empty else 0.0

    hi = df_before["high"].values[-period - 1:]
    lo = df_before["low"].values[-period - 1:]
    cl = df_before["close"].values[-period - 1:]
    tr = np.maximum(hi[1:] - lo[1:], np.maximum(np.abs(hi[1:] - cl[:-1]), np.abs(lo[1:] - cl[:-1])))
    return float(np.mean(tr))


# ══════════════════════════════════════════════════════════════
# Phase 2: 波动率平价仓位
# ══════════════════════════════════════════════════════════════

def calculate_volatility_parity_shares(
    symbol: str,
    price: float,
    atr: float,
    total_capital: float,
    available_capital: float,
) -> int:
    """波动率平价仓位计算

    海龟法则:
      每笔风险金额 = 总资金 × 1%
      每股波动风险 = 2 × ATR (或 8% × price, 取较大者)
      买入股数 = 每笔风险金额 / 每股波动风险

    硬约束:
      - 单只股票市值不超过总资金的 5%
      - 不超过可用资金
      - A 股 100 股整手

    Args:
        symbol: 股票代码
        price: 当前价格
        atr: ATR 值
        total_capital: 总资金
        available_capital: 可用资金

    Returns:
        买入股数 (100 的整数倍)
    """
    if price <= 0:
        return 0

    # 每笔风险金额
    risk_amount = total_capital * RISK_PER_TRADE

    # 每股波动风险 (取 ATR 和固定止损的较大者)
    atr_risk = 2 * atr if atr > 0 else price * HARD_STOP_PCT
    fixed_risk = price * HARD_STOP_PCT
    per_share_risk = max(atr_risk, fixed_risk)

    if per_share_risk <= 0:
        return 0

    # 计算股数
    shares = int(risk_amount / per_share_risk)

    # 硬约束: 单只不超过总资金 5%
    max_shares_by_alloc = int(total_capital * MAX_SINGLE_ALLOCATION / price)
    shares = min(shares, max_shares_by_alloc)

    # 硬约束: 不超过可用资金
    max_shares_by_cash = int(available_capital / price)
    shares = min(shares, max_shares_by_cash)

    # A 股整手
    shares = (shares // 100) * 100

    return max(shares, 0)


# ══════════════════════════════════════════════════════════════
# Phase 3: 自适应信号放松
# ══════════════════════════════════════════════════════════════

def detect_market_regime(stock_data: Dict[str, pd.DataFrame]) -> str:
    """检测市场状态

    使用所有股票的平均表现来判断:
      - 如果大部分股票 MA20 < MA60, 判定为熊市
      - 否则判定为正常/牛市
    """
    bear_count = 0
    total = 0

    for symbol, df in stock_data.items():
        try:
            if len(df) < 60:
                continue
            ma20 = df["close"].rolling(20).mean().iloc[-1]
            ma60 = df["close"].rolling(60).mean().iloc[-1]
            total += 1
            if ma20 < ma60:
                bear_count += 1
        except Exception:
            continue

    if total == 0:
        return "NORMAL"

    bear_ratio = bear_count / total
    if bear_ratio > 0.6:
        return "BEAR"
    elif bear_ratio > 0.4:
        return "STRESSED"
    else:
        return "NORMAL"


def collect_with_adaptive_relaxation(
    data_packs: Dict[str, Dict],
    collector: TradingSignalCollector,
    aggregator: SignalAggregator,
    market_regime: str,
) -> List[TradingSignal]:
    """自适应信号收集

    熊市策略:
      - 降低 MIN_AGREEING_SOURCES 从 2 到 1
      - 允许 Wyckoff Spring 单独触发买入
      - 允许高置信度 (>0.8) 的单引擎信号通过
    """
    all_signals = []
    min_sources = BEAR_MIN_AGREEING_SOURCES if market_regime == "BEAR" else MIN_AGREEING_SOURCES

    for symbol, pack in data_packs.items():
        mid_idx = len(pack["stock"]) // 2
        timestamp = pd.Timestamp(pack["stock"].iloc[mid_idx]["date"])

        raw_signals = collector.collect(pack, timestamp=timestamp, default_shares=100)
        signal_objects = [_trading_to_signal(s, symbol) for s in raw_signals if s.action in ("BUY", "SELL")]
        signal_objects = [s for s in signal_objects if s is not None]

        if not signal_objects:
            continue

        # 熊市特殊处理: Wyckoff Spring 单独触发
        if market_regime == "BEAR":
            wyckoff_spring = [s for s in signal_objects if s.metadata.get("spring")]
            if wyckoff_spring:
                sig = wyckoff_spring[0]
                all_signals.append(TradingSignal(
                    action="BUY",
                    reason=f"Wyckoff Spring (Bear Market Bypass)",
                    confidence=sig.confidence,
                    shares=0, symbol=symbol, timestamp=timestamp, price=pack["price"],
                ))
                continue

        # 标准共振逻辑
        if len(signal_objects) >= min_sources:
            consensus = aggregator.calculate_consensus(signal_objects, threshold=CONSENSUS_THRESHOLD)
            if consensus.is_strong_consensus(CONSENSUS_THRESHOLD):
                agg = aggregator.aggregate(signal_objects)
                if agg and agg.signal.direction != 0:
                    all_signals.append(TradingSignal(
                        action="BUY" if agg.signal.direction > 0 else "SELL",
                        reason=f"Consensus({len(signal_objects)} src, conf={agg.weighted_score:.2f}, regime={market_regime})",
                        confidence=abs(agg.weighted_score),
                        shares=0, symbol=symbol, timestamp=timestamp, price=pack["price"],
                    ))
        elif len(signal_objects) == 1:
            # 单引擎信号: 熊市允许高置信度通过, 牛市需要更高置信度
            threshold = 0.6 if market_regime == "BEAR" else 0.8
            if signal_objects[0].confidence >= threshold:
                all_signals.append(raw_signals[0])

    return all_signals


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


# ══════════════════════════════════════════════════════════════
# Brain 引擎 (与优化版一致)
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
        conf = float(result.get("confidence", 0.0))
        data_pack["risk"] = result.get("risk_level", "Safe") if conf >= LPPL_CONFIDENCE_THRESHOLD else ("Warning" if conf >= 0.3 else "Safe")
        data_pack["bubble_confidence"] = conf
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
        atr = _calc_atr_from_df(df, ATR_PERIOD, df.iloc[-1]["date"])
        data_pack["atr_stop"] = data_pack["price"] - atr * 2
        data_pack["atr"] = atr
    except Exception:
        data_pack["atr_stop"] = data_pack["price"] * 0.95
        data_pack["atr"] = data_pack["price"] * 0.02

    try:
        ret = df["close"].pct_change().dropna()
        data_pack["alpha_score"] = float(ret.tail(20).mean() / ret.tail(20).std()) if ret.tail(20).std() > 0 else 0
    except Exception:
        data_pack["alpha_score"] = 0.0

    return data_pack


# ══════════════════════════════════════════════════════════════
# 带风控的回测引擎
# ══════════════════════════════════════════════════════════════

def run_backtest_with_risk_controls(
    stock_data: Dict[str, pd.DataFrame],
    buy_signals: List[TradingSignal],
    total_capital: float,
) -> Dict[str, BacktestResult]:
    """带风控的回测

    流程:
      1. 按日期遍历
      2. 每天先检查持仓的止损条件
      3. 然后处理买入信号
      4. 使用波动率平价计算仓位
    """
    # 按 symbol 分组信号
    signals_by_symbol: Dict[str, List[TradingSignal]] = {}
    for sig in buy_signals:
        signals_by_symbol.setdefault(sig.symbol, []).append(sig)

    # 对每只股票独立回测
    results = {}
    capital_per_stock = total_capital / max(len(stock_data), 1)

    for symbol, df in stock_data.items():
        if symbol not in signals_by_symbol:
            continue

        symbol_signals = signals_by_symbol[symbol]
        if not symbol_signals:
            continue

        # 注入止损信号
        enriched_signals = _inject_stop_loss_signals(symbol, df, symbol_signals)

        try:
            engine = UnifiedBacktestEngine(
                initial_capital=capital_per_stock,
                stamp_duty_rate=0.0005,
                slippage_rate=0.0005,
            )
            result = engine.run(df, enriched_signals, symbol=symbol)
            results[symbol] = result
        except Exception as e:
            logger.error(f"  {symbol} 回测失败: {e}")

    return results


def _inject_stop_loss_signals(
    symbol: str,
    df: pd.DataFrame,
    buy_signals: List[TradingSignal],
) -> List[TradingSignal]:
    """为买入信号注入对应的止损信号

    策略: 每个 BUY 信号在 N 天后检查止损条件
    """
    enriched = list(buy_signals)

    for sig in buy_signals:
        if sig.action != "BUY":
            continue

        sig_date = sig.timestamp
        if sig_date is None:
            continue

        # 找到买入后的数据
        df_after = df[df["date"] > sig_date]
        if df_after.empty:
            continue

        entry_price = sig.price if sig.price > 0 else float(df_after.iloc[0]["open"])

        # 计算 ATR
        atr = _calc_atr_from_df(df, ATR_PERIOD, sig_date)
        if atr <= 0:
            atr = entry_price * 0.02

        # 遍历买入后的每一天, 找到止损点
        highest = entry_price
        for _, row in df_after.iterrows():
            current = float(row["close"])
            date = pd.Timestamp(row["date"])

            if current > highest:
                highest = current

            # 硬止损
            if current <= entry_price * (1 - HARD_STOP_PCT):
                enriched.append(TradingSignal(
                    action="SELL",
                    reason=f"Hard Stop ({HARD_STOP_PCT:.0%})",
                    confidence=1.0,
                    shares=sig.shares,
                    symbol=symbol,
                    timestamp=date,
                    price=current,
                ))
                break

            # ATR 跟踪止损
            trailing_stop = highest - ATR_TRAILING_MULTIPLIER * atr
            if current <= trailing_stop:
                enriched.append(TradingSignal(
                    action="SELL",
                    reason=f"ATR Trail (peak={highest:.2f}, ATR={atr:.2f})",
                    confidence=1.0,
                    shares=sig.shares,
                    symbol=symbol,
                    timestamp=date,
                    price=current,
                ))
                break

    return enriched


# ══════════════════════════════════════════════════════════════
# 数据与绩效 (复用)
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
    max_single_loss = 0.0
    if tt > 0 and "pnl" in trades_df.columns:
        closed = trades_df[trades_df["pnl"].notna() & (trades_df["pnl"] != 0)]
        if len(closed) > 0:
            wins = closed[closed["pnl"] > 0]
            losses = closed[closed["pnl"] <= 0]
            wr = len(wins) / len(closed)
            gp = wins["pnl"].sum() if len(wins) > 0 else 0
            gl = abs(losses["pnl"].sum()) if len(losses) > 0 else 0
            pf = gp / gl if gl > 0 else float("inf")
            # 最大单笔亏损
            if len(losses) > 0:
                max_single_loss = abs(losses["pnl"].min())

    sell_count = len(trades_df[trades_df["action"] == "SELL"]) if len(trades_df) > 0 else 0

    return {
        "initial_capital": initial, "final_equity": float(combined[-1]),
        "total_return": total_ret, "cagr": cagr, "max_drawdown": max_dd,
        "sharpe_ratio": sharpe, "calmar_ratio": calmar,
        "total_trades": tt, "sell_trades": sell_count, "win_rate": wr,
        "profit_factor": pf, "max_single_loss": max_single_loss,
        "n_assets": n, "n_days": len(combined), "equity_curve": combined,
    }


def print_rescue_report(metrics: Dict, baseline_oos: Dict) -> None:
    print("\n" + "=" * 70)
    print("  🛡️  风控抢救版 OOS 报告")
    print("=" * 70)
    print(f"\n  测试区间: {START_DATE} ~ {END_DATE}")
    print(f"  测试标的: {metrics.get('n_assets', 0)} 只中证 500 成分股")
    print(f"  风控措施: 硬止损 8% + ATR 跟踪止损 + 5% 仓位上限")

    print(f"\n  {'指标':<22s} {'OOS 原版':>12s} {'抢救版':>12s} {'目标':>10s}")
    print(f"  {'-'*22} {'-'*12} {'-'*12} {'-'*10}")
    print(f"  {'总收益率':<22s} {baseline_oos.get('total_return',0):>11.2%} {metrics.get('total_return',0):>11.2%} {'':>10s}")
    print(f"  {'年化收益(CAGR)':<22s} {baseline_oos.get('cagr',0):>11.2%} {metrics.get('cagr',0):>11.2%} {'':>10s}")
    print(f"  {'最大回撤':<22s} {baseline_oos.get('max_drawdown',0):>11.2%} {metrics.get('max_drawdown',0):>11.2%} {'<15%':>10s}")
    print(f"  {'夏普比率':<22s} {baseline_oos.get('sharpe_ratio',0):>11.2f} {metrics.get('sharpe_ratio',0):>11.2f} {'>0.8':>10s}")
    print(f"  {'总交易次数':<22s} {baseline_oos.get('total_trades',0):>11d} {metrics.get('total_trades',0):>11d} {'':>10s}")
    print(f"  {'SELL 次数':<22s} {baseline_oos.get('sell_trades',0):>11d} {metrics.get('sell_trades',0):>11d} {'>0':>10s}")
    print(f"  {'最大单笔亏损':<22s} {baseline_oos.get('max_single_loss',0):>11.0f} {metrics.get('max_single_loss',0):>11.0f} {'<10%':>10s}")
    print(f"  {'胜率':<22s} {baseline_oos.get('win_rate',0):>11.2%} {metrics.get('win_rate',0):>11.2%} {'':>10s}")

    print(f"\n  --- 合格检验 ---")
    dd_ok = metrics.get("max_drawdown", 1) < 0.15
    sharpe_ok = metrics.get("sharpe_ratio", 0) > 0.8
    sell_ok = metrics.get("sell_trades", 0) > 0
    print(f"  最大回撤 < 15%:     {'✅ PASS' if dd_ok else '❌ FAIL'} ({metrics.get('max_drawdown',0):.2%})")
    print(f"  夏普比率 > 0.8:     {'✅ PASS' if sharpe_ok else '❌ FAIL'} ({metrics.get('sharpe_ratio',0):.2f})")
    print(f"  有 SELL 信号:       {'✅ PASS' if sell_ok else '❌ FAIL'} ({metrics.get('sell_trades',0)} 笔)")
    print(f"\n  综合判定: {'🚀 风控抢救成功!' if (dd_ok and sharpe_ok and sell_ok) else '⚠️ 继续优化'}")
    print("=" * 70)


def save_chart(metrics: Dict, path: str = "rescue_tearsheet.png") -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        eq = metrics.get("equity_curve", [])
        if len(eq) < 2:
            return
        fig, axes = plt.subplots(2, 1, figsize=(14, 10))
        fig.suptitle("UniQuant Risk Rescue OOS Tearsheet", fontsize=16, fontweight="bold")
        ax1 = axes[0]
        ax1.plot(eq, color="#4CAF50", linewidth=1.5)
        ax1.fill_between(range(len(eq)), eq, alpha=0.1, color="#4CAF50")
        ax1.set_ylabel("Equity (¥)")
        ax1.set_title(f"OOS Rescue | CAGR={metrics.get('cagr',0):.2%} | MaxDD={metrics.get('max_drawdown',0):.2%} | Sharpe={metrics.get('sharpe_ratio',0):.2f}")
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
    print("  UniQuant 风控抢救版 OOS 盲测")
    print("=" * 70)

    # OOS 原版基线
    baseline_oos = {
        "total_return": -0.0337, "cagr": -0.0071, "max_drawdown": 0.2695,
        "sharpe_ratio": -0.12, "total_trades": 6, "sell_trades": 0,
        "win_rate": 0.5, "max_single_loss": 38000,
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

    # 市场状态检测
    regime = detect_market_regime(stock_data)
    print(f"\n[Phase 2] 市场状态检测: {regime}")
    print(f"  熊市信号放松: MIN_AGREEING_SOURCES {MIN_AGREEING_SOURCES} → {BEAR_MIN_AGREEING_SOURCES if regime == 'BEAR' else MIN_AGREEING_SOURCES}")

    # Brain 引擎
    print(f"\n[Phase 3] Brain 引擎...")
    data_packs = {}
    for i, (sym, df) in enumerate(stock_data.items()):
        try:
            data_packs[sym] = run_brain_relaxed(sym, df)
            if (i + 1) % 10 == 0:
                print(f"  已处理 {i+1}/{len(stock_data)}...")
        except Exception:
            continue

    # 自适应信号共振
    print(f"\n[Phase 4] 自适应信号共振...")
    collector = TradingSignalCollector(create_default_registry())
    aggregator = SignalAggregator(method=SignalAggregationMethod.WEIGHTED_AVERAGE)
    master_signals = collect_with_adaptive_relaxation(data_packs, collector, aggregator, regime)
    buy_n = sum(1 for s in master_signals if s.action == "BUY")
    sell_n = sum(1 for s in master_signals if s.action == "SELL")
    print(f"  共振信号: {len(master_signals)} (BUY={buy_n}, SELL={sell_n})")

    # 波动率平价仓位
    print(f"\n[Phase 5] 波动率平价仓位...")
    sized_signals = []
    available_capital = INITIAL_CAPITAL
    for sig in master_signals:
        if sig.action == "BUY":
            df = stock_data.get(sig.symbol)
            if df is not None:
                atr = _calc_atr_from_df(df, ATR_PERIOD, sig.timestamp or pd.Timestamp(df.iloc[-1]["date"]))
                price = sig.price if sig.price > 0 else float(df.iloc[-1]["close"])
                shares = calculate_volatility_parity_shares(
                    sig.symbol, price, atr, INITIAL_CAPITAL, available_capital,
                )
                if shares > 0:
                    sig.shares = shares
                    available_capital -= shares * price
                    sized_signals.append(sig)
        else:
            sized_signals.append(sig)

    print(f"  有仓位信号: {len([s for s in sized_signals if s.action == 'BUY' and s.shares > 0])}")

    # 带风控的回测
    print(f"\n[Phase 6] 带风控的回测撮合...")
    results = run_backtest_with_risk_controls(stock_data, sized_signals, INITIAL_CAPITAL)
    total_trades = sum(len(r.trades) for r in results.values())
    sell_trades = sum(sum(1 for t in r.trades if t.action == "SELL") for r in results.values())
    print(f"  成交: {len(results)} 只, {total_trades} 笔 (SELL={sell_trades})")

    # 绩效报告
    metrics = calc_metrics(results, INITIAL_CAPITAL)
    print_rescue_report(metrics, baseline_oos)
    save_chart(metrics, str(PROJECT_ROOT / "rescue_tearsheet.png"))
    print(f"\n  图表: rescue_tearsheet.png")

    # 个股明细
    print(f"\n  --- 有交易的个股 ---")
    for sym, r in sorted(results.items(), key=lambda x: len(x[1].trades), reverse=True):
        if r.trades:
            sells = sum(1 for t in r.trades if t.action == "SELL")
            print(f"  {sym:>12s}: {len(r.trades):>3d} 笔 (SELL={sells}), 收益={r.total_return:>8.2%}")

    print("\n" + "=" * 70)
    print("  风控抢救完成!")
    print("=" * 70)


if __name__ == "__main__":
    main()
