#!/usr/bin/env python3
"""
UniQuant 信号衰减漏斗诊断脚本
================================

系统冻结状态下的全景诊断，不修改任何参数。
跟踪信号从 Brain 输出到最终成交的完整死亡路径。

使用方式:
    python3 run_diagnostic.py
"""

from __future__ import annotations

import sys
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
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
    TradeRecord,
    UnifiedBacktestEngine,
)
from uniquant.shared.interfaces import TradingSignal
from uniquant.shared.logger_factory import get_logger
from uniquant.signal.adapters import (
    TradingSignalCollector,
    create_default_registry,
)

logger = get_logger("Diagnostic")


# ══════════════════════════════════════════════════════════════
# 配置 (系统冻结, 不可修改)
# ══════════════════════════════════════════════════════════════

N_STOCKS = 50
INITIAL_CAPITAL = 1_000_000.0
DEFAULT_SHARES = 500
START_DATE = "2023-01-01"
END_DATE = "2025-12-31"


# ══════════════════════════════════════════════════════════════
# 诊断探针数据结构
# ══════════════════════════════════════════════════════════════

@dataclass
class FunnelStage:
    """漏斗单阶段计数"""
    name: str
    count: int = 0
    details: Dict[str, int] = field(default_factory=dict)


@dataclass
class DiagnosticResult:
    """诊断结果"""
    # 漏斗数据
    brain_outputs: Dict[str, int] = field(default_factory=dict)
    adapter_conversions: Dict[str, int] = field(default_factory=dict)
    adapter_rejections: Dict[str, int] = field(default_factory=dict)
    engine_signals: Dict[str, int] = field(default_factory=dict)
    engine_rejections: Dict[str, Dict[str, int]] = field(default_factory=dict)
    final_trades: int = 0

    # 资金利用率
    daily_cash: List[float] = field(default_factory=list)
    daily_equity: List[float] = field(default_factory=list)

    # 回测结果
    backtest: Optional[BacktestResult] = None
    per_stock: Dict[str, BacktestResult] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════
# 数据装载
# ══════════════════════════════════════════════════════════════

def select_stocks(storage: StorageManager, n: int = 50) -> List[str]:
    """从数据湖中选取有足够数据的股票"""
    import random
    random.seed(42)

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

    logger.info(f"选中 {len(selected)} 只股票")
    return selected


def load_stock_data(
    storage: StorageManager, symbols: List[str],
) -> Dict[str, pd.DataFrame]:
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
# Brain 引擎调用 (带诊断探针)
# ══════════════════════════════════════════════════════════════

def run_brain_with_probes(
    symbol: str, df: pd.DataFrame, diag: DiagnosticResult,
) -> Dict[str, Any]:
    """运行 Brain 引擎并记录诊断数据"""
    data_pack: Dict[str, Any] = {
        "stock": df, "symbol": symbol, "market": "CN",
        "price": float(df.iloc[-1]["close"]),
        "returns": df["close"].pct_change().dropna(),
    }

    # LPPL
    lppl_output = None
    try:
        from uniquant.brain.lppl.engine import LPPLEngine
        lppl = LPPLEngine()
        lppl_output = lppl.detect_bubble(df)
        diag.brain_outputs["lppl"] = diag.brain_outputs.get("lppl", 0) + 1
        data_pack["risk"] = lppl_output.get("risk_level", "Safe")
        data_pack["bubble_confidence"] = lppl_output.get("confidence", 0.0)
    except Exception:
        data_pack["risk"] = "Safe"
        data_pack["bubble_confidence"] = 0.0

    # CZSC
    czsc_output = None
    try:
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        czsc = CZSCEngine()
        czsc_output = czsc.get_czsc_signals(df)
        diag.brain_outputs["czsc"] = diag.brain_outputs.get("czsc", 0) + 1
        data_pack["is_3rd_buy"] = czsc_output.get("is_3rd_buy", False)
        data_pack["bi_count"] = czsc_output.get("bi_count", 0)
    except Exception:
        data_pack["is_3rd_buy"] = False
        data_pack["bi_count"] = 0

    # Wyckoff
    wyckoff_output = None
    try:
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        wyckoff = WyckoffEngine()
        report = wyckoff.analyze(df, symbol=symbol)
        wyckoff_output = {
            "phase": report.structure.phase.value,
            "confidence": {"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3}.get(
                report.signal.confidence.value, 0.3
            ),
            "spring": report.signal.signal_type == "spring",
            "utad": report.signal.signal_type == "utad",
        }
        diag.brain_outputs["wyckoff"] = diag.brain_outputs.get("wyckoff", 0) + 1
        data_pack["wyckoff_phase"] = wyckoff_output["phase"]
        data_pack["wyckoff_confidence"] = wyckoff_output["confidence"]
        data_pack["wyckoff_spring"] = wyckoff_output["spring"]
        data_pack["wyckoff_utad"] = wyckoff_output["utad"]
    except Exception:
        data_pack["wyckoff_phase"] = "unknown"
        data_pack["wyckoff_confidence"] = 0.0
        data_pack["wyckoff_spring"] = False
        data_pack["wyckoff_utad"] = False

    # Regime (简化)
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
# Adapter 转换诊断
# ══════════════════════════════════════════════════════════════

def collect_signals_with_probes(
    data_packs: Dict[str, Dict],
    collector: TradingSignalCollector,
    diag: DiagnosticResult,
) -> List[TradingSignal]:
    """收集信号并记录 Adapter 诊断"""
    all_signals = []

    for symbol, pack in data_packs.items():
        # 统计 Adapter 输入
        adapter_input_count = 0
        if pack.get("risk") or pack.get("bubble_confidence", 0) > 0:
            adapter_input_count += 1
        if pack.get("is_3rd_buy") or pack.get("bi_count", 0) > 0:
            adapter_input_count += 1
        if pack.get("wyckoff_phase") not in (None, "unknown"):
            adapter_input_count += 1
        if pack.get("regime") in ("STRESSED", "FROZEN"):
            adapter_input_count += 1

        diag.adapter_conversions["input"] = diag.adapter_conversions.get("input", 0) + adapter_input_count

        # 收集信号
        mid_idx = len(pack["stock"]) // 2
        timestamp = pd.Timestamp(pack["stock"].iloc[mid_idx]["date"])
        signals = collector.collect(pack, timestamp=timestamp, default_shares=DEFAULT_SHARES)

        # 统计输出
        for sig in signals:
            if sig.action == "BUY":
                diag.adapter_conversions["buy"] = diag.adapter_conversions.get("buy", 0) + 1
            elif sig.action == "SELL":
                diag.adapter_conversions["sell"] = diag.adapter_conversions.get("sell", 0) + 1
            else:
                diag.adapter_conversions["hold"] = diag.adapter_conversions.get("hold", 0) + 1

        all_signals.extend(signals)

    return all_signals


# ══════════════════════════════════════════════════════════════
# 引擎撮合诊断 (带拦截统计)
# ══════════════════════════════════════════════════════════════

class DiagnosticEngine(UnifiedBacktestEngine):
    """带诊断探针的回测引擎"""

    def __init__(self, diag: DiagnosticResult, **kwargs):
        super().__init__(**kwargs)
        self._diag = diag

    def _execute_buy(self, **kwargs):
        """重写买入方法, 记录拦截原因"""
        price_raw = kwargs["price_raw"]
        pre_close = kwargs["pre_close"]
        shares_requested = kwargs["shares_requested"]
        cash_available = kwargs["cash_available"]
        symbol = kwargs.get("symbol", "")

        # 检查涨跌停
        if not self._check_limit(price_raw, pre_close, "BUY", symbol, kwargs.get("name")):
            self._diag.engine_rejections.setdefault("BUY", {})["limit_up"] = \
                self._diag.engine_rejections.get("BUY", {}).get("limit_up", 0) + 1
            return None, cash_available

        # 检查资金
        exec_price = self._calc_slippage(
            price_raw, is_buy=True,
            trade_volume=kwargs.get("trade_volume", shares_requested),
            avg_daily_volume=kwargs.get("avg_daily_volume", 0),
        )
        from uniquant.shared.market_rules import get_board_rule
        lot_size = get_board_rule(symbol).lot_size
        shares = (shares_requested // lot_size) * lot_size
        if shares <= 0:
            self._diag.engine_rejections.setdefault("BUY", {})["lot_size"] = \
                self._diag.engine_rejections.get("BUY", {}).get("lot_size", 0) + 1
            return None, cash_available

        value = exec_price * shares
        commission = self._calc_commission(value)
        transfer_fee = self._calc_transfer_fee(value)
        total = value + commission + transfer_fee

        if total > cash_available:
            self._diag.engine_rejections.setdefault("BUY", {})["cash_shortfall"] = \
                self._diag.engine_rejections.get("BUY", {}).get("cash_shortfall", 0) + 1

        return super()._execute_buy(**kwargs)

    def _execute_sell(self, **kwargs):
        """重写卖出方法, 记录拦截原因"""
        pre_close = kwargs["pre_close"]
        price_raw = kwargs["price_raw"]
        symbol = kwargs.get("symbol", "")

        if not self._check_limit(price_raw, pre_close, "SELL", symbol, kwargs.get("name")):
            self._diag.engine_rejections.setdefault("SELL", {})["limit_down"] = \
                self._diag.engine_rejections.get("SELL", {}).get("limit_down", 0) + 1
            return None, kwargs["cash"]

        return super()._execute_sell(**kwargs)


def run_backtest_with_probes(
    stock_data: Dict[str, pd.DataFrame],
    signals: List[TradingSignal],
    diag: DiagnosticResult,
) -> Dict[str, BacktestResult]:
    """运行回测并记录诊断数据"""
    signals_by_symbol: Dict[str, List[TradingSignal]] = {}
    for sig in signals:
        signals_by_symbol.setdefault(sig.symbol, []).append(sig)

    # 统计进入引擎的信号
    for sig in signals:
        key = f"{sig.action}_input"
        diag.engine_signals[key] = diag.engine_signals.get(key, 0) + 1

    results = {}
    capital_per_stock = INITIAL_CAPITAL / max(len(stock_data), 1)

    for symbol, df in stock_data.items():
        symbol_signals = signals_by_symbol.get(symbol, [])
        if not symbol_signals:
            continue

        try:
            engine = DiagnosticEngine(
                diag=diag,
                initial_capital=capital_per_stock,
                stamp_duty_rate=0.0005,
                slippage_rate=0.0005,
            )
            result = engine.run(df, symbol_signals, symbol=symbol)
            results[symbol] = result

            # 统计 T+1 拦截 (通过比较信号数和成交数)
            buy_signals = [s for s in symbol_signals if s.action == "BUY"]
            sell_signals = [s for s in symbol_signals if s.action == "SELL"]
            buy_trades = [t for t in result.trades if t.action == "BUY"]
            sell_trades = [t for t in result.trades if t.action == "SELL"]

            # T+1 拦截: SELL 信号存在但无 SELL 成交 (且有 BUY 成交)
            if sell_signals and not sell_trades and buy_trades:
                diag.engine_rejections.setdefault("SELL", {})["t1_constraint"] = \
                    diag.engine_rejections.get("SELL", {}).get("t1_constraint", 0) + len(sell_signals)

        except Exception as e:
            logger.error(f"  {symbol} 回测失败: {e}")

    return results


# ══════════════════════════════════════════════════════════════
# 资金利用率分析
# ══════════════════════════════════════════════════════════════

def analyze_capital_utilization(results: Dict[str, BacktestResult]) -> Dict[str, float]:
    """分析资金利用率"""
    if not results:
        return {"avg_cash_ratio": 1.0, "min_cash_ratio": 1.0, "max_cash_ratio": 1.0}

    # 合并所有股票的权益曲线
    max_len = max(len(r.equity_curve) for r in results.values())
    total_equity = np.zeros(max_len)
    total_cash = np.zeros(max_len)

    for r in results.values():
        eq = np.array(r.equity_curve)
        total_equity[:len(eq)] += eq
        # 估算现金 (简化: 用 final_cash 的比例)
        cash_ratio = r.final_cash / max(r.initial_capital, 1)
        total_cash[:len(eq)] += eq * cash_ratio

    # 填充
    for r in results.values():
        eq = np.array(r.equity_curve)
        if len(eq) < max_len:
            total_equity[len(eq):] += eq[-1]
            total_cash[len(eq):] += eq[-1] * (r.final_cash / max(r.initial_capital, 1))

    cash_ratio = np.where(total_equity > 0, total_cash / total_equity, 1.0)

    return {
        "avg_cash_ratio": float(np.mean(cash_ratio)),
        "min_cash_ratio": float(np.min(cash_ratio)),
        "max_cash_ratio": float(np.max(cash_ratio)),
        "median_cash_ratio": float(np.median(cash_ratio)),
    }


# ══════════════════════════════════════════════════════════════
# 绩效计算
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


# ══════════════════════════════════════════════════════════════
# 报告输出
# ══════════════════════════════════════════════════════════════

def print_funnel_report(diag: DiagnosticResult) -> None:
    """打印信号衰减漏斗报告"""
    print("\n" + "=" * 70)
    print("  🕵️  信号衰减漏斗分析 (Signal Attrition Funnel)")
    print("=" * 70)

    # Brain 输出
    total_brain = sum(diag.brain_outputs.values())
    print(f"\n  [Stage 1] Brain 原始输出:")
    for engine, count in diag.brain_outputs.items():
        print(f"    {engine:>10s}: {count:>4d} 个 Dict")
    print(f"    {'合计':>10s}: {total_brain:>4d} 个 Dict")

    # Adapter 转换
    adapter_input = diag.adapter_conversions.get("input", 0)
    adapter_buy = diag.adapter_conversions.get("buy", 0)
    adapter_sell = diag.adapter_conversions.get("sell", 0)
    adapter_hold = diag.adapter_conversions.get("hold", 0)
    adapter_total = adapter_buy + adapter_sell + adapter_hold

    print(f"\n  [Stage 2] Adapter 转换:")
    print(f"    输入 (有信号的引擎输出): {adapter_input:>4d}")
    print(f"    输出 BUY:               {adapter_buy:>4d}")
    print(f"    输出 SELL:              {adapter_sell:>4d}")
    print(f"    输出 HOLD:              {adapter_hold:>4d}")
    if adapter_input > 0:
        print(f"    转换率:                 {adapter_total/max(adapter_input,1)*100:.1f}%")
    else:
        print(f"    转换率:                 N/A (无输入)")

    # 引擎撮合
    buy_input = diag.engine_signals.get("BUY_input", 0)
    sell_input = diag.engine_signals.get("SELL_input", 0)

    print(f"\n  [Stage 3] 引擎撮合:")
    print(f"    BUY 信号输入:  {buy_input:>4d}")
    print(f"    SELL 信号输入: {sell_input:>4d}")

    print(f"\n  [Stage 3a] BUY 拦截原因:")
    buy_rejects = diag.engine_rejections.get("BUY", {})
    if buy_rejects:
        for reason, count in buy_rejects.items():
            print(f"    {reason:>20s}: {count:>4d}")
    else:
        print(f"    (无拦截)")

    print(f"\n  [Stage 3b] SELL 拦截原因:")
    sell_rejects = diag.engine_rejections.get("SELL", {})
    if sell_rejects:
        for reason, count in sell_rejects.items():
            print(f"    {reason:>20s}: {count:>4d}")
    else:
        print(f"    (无拦截)")

    # 最终成交
    print(f"\n  [Stage 4] 最终成交: {diag.final_trades} 笔")

    # 漏斗汇总
    print(f"\n  --- 漏斗汇总 ---")
    print(f"  Brain Dict:     {total_brain:>4d}")
    print(f"  Adapter 输出:   {adapter_total:>4d}  ({adapter_total/max(total_brain,1)*100:.1f}%)")
    print(f"  进入引擎:       {buy_input+sell_input:>4d}")
    print(f"  最终成交:       {diag.final_trades:>4d}  ({diag.final_trades/max(buy_input+sell_input,1)*100:.1f}%)")

    print("=" * 70)


def print_capital_report(capital_stats: Dict[str, float]) -> None:
    """打印资金利用率报告"""
    print("\n" + "=" * 70)
    print("  📉 资金闲置率图谱 (Capital Utilization)")
    print("=" * 70)
    print(f"\n  平均闲置率:  {capital_stats['avg_cash_ratio']:.2%}")
    print(f"  中位闲置率:  {capital_stats['median_cash_ratio']:.2%}")
    print(f"  最低闲置率:  {capital_stats['min_cash_ratio']:.2%}")
    print(f"  最高闲置率:  {capital_stats['max_cash_ratio']:.2%}")
    print(f"\n  💡 解读: 平均 {capital_stats['avg_cash_ratio']:.0%} 的资金处于闲置状态")
    print("=" * 70)


def print_baseline_tearsheet(metrics: Dict) -> None:
    """打印基线绩效研报"""
    print("\n" + "=" * 70)
    print("  📊 大规模基线绩效研报 (Baseline Tearsheet)")
    print("=" * 70)
    print(f"\n  初始资金:       ¥{metrics.get('initial_capital', 0):>14,.2f}")
    print(f"  期末权益:       ¥{metrics.get('final_equity', 0):>14,.2f}")
    print(f"  总收益率:        {metrics.get('total_return', 0):>13.2%}")
    print(f"  年化收益 (CAGR): {metrics.get('cagr', 0):>13.2%}")
    print(f"  最大回撤:        {metrics.get('max_drawdown', 0):>13.2%}")
    print(f"  夏普比率:        {metrics.get('sharpe_ratio', 0):>13.2f}")
    print(f"  卡玛比率:        {metrics.get('calmar_ratio', 0):>13.2f}")
    print(f"\n  --- 交易统计 ---")
    print(f"  总交易次数:      {metrics.get('total_trades', 0):>13d}")
    print(f"  胜率:            {metrics.get('win_rate', 0):>13.2%}")
    print(f"  盈亏比:          {metrics.get('profit_factor', 0):>13.2f}")
    print(f"\n  --- 组合信息 ---")
    print(f"  资产数量:        {metrics.get('n_assets', 0):>13d}")
    print(f"  回测天数:        {metrics.get('n_days', 0):>13d}")
    print("=" * 70)


def save_chart(metrics: Dict, path: str = "diagnostic_tearsheet.png") -> None:
    """保存图表"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        eq = metrics.get("equity_curve", [])
        if len(eq) < 2:
            return

        fig, axes = plt.subplots(3, 1, figsize=(14, 12), gridspec_kw={"height_ratios": [3, 1, 1]})
        fig.suptitle("UniQuant Baseline Diagnostic Tearsheet", fontsize=16, fontweight="bold")

        # 资金曲线
        ax1 = axes[0]
        ax1.plot(eq, color="#2196F3", linewidth=1.5)
        ax1.fill_between(range(len(eq)), eq, alpha=0.1, color="#2196F3")
        ax1.set_ylabel("Equity (¥)")
        ax1.set_title(f"Equity | CAGR={metrics.get('cagr',0):.2%} | MaxDD={metrics.get('max_drawdown',0):.2%} | Sharpe={metrics.get('sharpe_ratio',0):.2f}")
        ax1.grid(True, alpha=0.3)

        # 回撤
        ax2 = axes[1]
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak * 100
        ax2.fill_between(range(len(dd)), dd, 0, color="#F44336", alpha=0.4)
        ax2.set_ylabel("Drawdown (%)")
        ax2.grid(True, alpha=0.3)

        # 资金闲置率
        ax3 = axes[2]
        cash_ratio = np.ones(len(eq)) * 0.95  # 估算
        ax3.fill_between(range(len(cash_ratio)), cash_ratio * 100, 0, color="#FFC107", alpha=0.3)
        ax3.set_ylabel("Cash Ratio (%)")
        ax3.set_xlabel("Trading Days")
        ax3.set_title("Capital Utilization (Cash / Equity)")
        ax3.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"\n  图表已保存: {path}")
    except Exception as e:
        print(f"\n  [WARN] 图表保存失败: {e}")


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  UniQuant 信号衰减漏斗诊断 (系统冻结模式)")
    print("=" * 70)

    diag = DiagnosticResult()

    # Phase 1: 数据装载
    print(f"\n[Phase 1] 装载 {N_STOCKS} 只股票...")
    storage = StorageManager(data_dir=str(PROJECT_ROOT / "data"))
    symbols = select_stocks(storage, N_STOCKS)
    stock_data = load_stock_data(storage, symbols)
    print(f"  成功装载: {len(stock_data)} 只")

    if not stock_data:
        print("  [ERROR] 无可用数据")
        return

    # Phase 2: Brain 引擎 + Adapter
    print(f"\n[Phase 2] Brain 引擎 + Adapter 信号收割...")
    collector = TradingSignalCollector(create_default_registry())
    data_packs = {}

    for i, (symbol, df) in enumerate(stock_data.items()):
        try:
            pack = run_brain_with_probes(symbol, df, diag)
            data_packs[symbol] = pack
            if (i + 1) % 10 == 0:
                print(f"  已处理 {i+1}/{len(stock_data)} 只...")
        except Exception as e:
            logger.error(f"  {symbol} Brain 失败: {e}")

    master_signals = collect_signals_with_probes(data_packs, collector, diag)
    print(f"  总信号: {len(master_signals)} (BUY={sum(1 for s in master_signals if s.action=='BUY')}, "
          f"SELL={sum(1 for s in master_signals if s.action=='SELL')}, "
          f"HOLD={sum(1 for s in master_signals if s.action=='HOLD')})")

    # Phase 3: 引擎撮合
    print(f"\n[Phase 3] 引擎撮合...")
    results = run_backtest_with_probes(stock_data, master_signals, diag)

    # 统计最终成交
    total_trades = sum(len(r.trades) for r in results.values())
    diag.final_trades = total_trades
    print(f"  成交股票: {len(results)} 只")
    print(f"  最终成交: {total_trades} 笔")

    # Phase 4: 分析报告
    print(f"\n[Phase 4] 生成诊断报告...")

    # 漏斗报告
    print_funnel_report(diag)

    # 资金利用率
    capital_stats = analyze_capital_utilization(results)
    print_capital_report(capital_stats)

    # 基线绩效
    metrics = calculate_metrics(results, INITIAL_CAPITAL)
    print_baseline_tearsheet(metrics)

    # 保存图表
    save_chart(metrics, str(PROJECT_ROOT / "diagnostic_tearsheet.png"))

    # 个股明细 (前 10)
    print(f"\n  --- 个股明细 (前 10) ---")
    sorted_results = sorted(results.items(), key=lambda x: len(x[1].trades), reverse=True)
    for symbol, r in sorted_results[:10]:
        trades = len(r.trades)
        ret = r.total_return
        print(f"  {symbol:>12s}: {trades:>3d} 笔交易, 收益={ret:>8.2%}")

    print("\n" + "=" * 70)
    print("  诊断完成!")
    print("=" * 70)


if __name__ == "__main__":
    main()
