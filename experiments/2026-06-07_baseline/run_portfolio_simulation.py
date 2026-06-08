#!/usr/bin/env python3
"""
UniQuant 多资产组合实盘模拟脚本
================================

使用全新的 UnifiedResearchPipeline + UnifiedBacktestEngine
在 10 只活跃股票上执行组合回测，输出专业绩效研报。

使用方式:
    python3 run_portfolio_simulation.py
"""

from __future__ import annotations

import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# 忽略旧引擎的废弃警告
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ── 项目路径设置 ───────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ── 导入核心组件 ───────────────────────────────────────────
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

logger = get_logger("PortfolioSimulation")

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════

# 10 只代表性 A 股 (覆盖主板/创业板/科创板)
STOCK_POOL = [
    "600036.SH",  # 招商银行 (银行)
    "600519.SH",  # 贵州茅台 (白酒)
    "000858.SZ",  # 五粮液 (白酒)
    "300750.SZ",  # 宁德时代 (新能源)
    "601318.SH",  # 中国平安 (保险)
    "000333.SZ",  # 美的集团 (家电)
    "600276.SH",  # 恒瑞医药 (医药)
    "002475.SZ",  # 立讯精密 (电子)
    "601012.SH",  # 隆基绿能 (光伏)
    "600900.SH",  # 长江电力 (电力)
]

INITIAL_CAPITAL = 1_000_000.0  # 100 万
DEFAULT_SHARES = 500  # 每笔交易 500 股


# ══════════════════════════════════════════════════════════════
# Phase 1: 数据装载
# ══════════════════════════════════════════════════════════════

def load_stock_data(
    storage: StorageManager,
    symbols: List[str],
    start_date: str = "2023-01-01",
    end_date: str = "2025-12-31",
) -> Dict[str, pd.DataFrame]:
    """从数据湖装载多只股票的日线数据

    Args:
        storage: 存储管理器
        symbols: 股票代码列表
        start_date: 起始日期
        end_date: 结束日期

    Returns:
        {symbol: DataFrame} 字典
    """
    data = {}
    for symbol in symbols:
        try:
            df = storage.read_data(symbol, data_type="daily")
            if df is None or df.empty:
                logger.warning(f"[SKIP] {symbol}: 无数据")
                continue

            # 日期过滤
            df["date"] = pd.to_datetime(df["date"])
            df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

            if len(df) < 60:
                logger.warning(f"[SKIP] {symbol}: 数据不足 ({len(df)} 行)")
                continue

            # 补充必需列
            df = df.sort_values("date").reset_index(drop=True)
            df["pre_close"] = df["close"].shift(1).fillna(df["open"])
            df["avg_daily_volume"] = df["volume"].rolling(20, min_periods=1).mean()

            data[symbol] = df
            logger.info(f"[OK] {symbol}: {len(df)} 行, "
                        f"{df['date'].min().date()} ~ {df['date'].max().date()}")
        except Exception as e:
            logger.error(f"[ERR] {symbol}: {e}")

    return data


# ══════════════════════════════════════════════════════════════
# Phase 2: 信号收割
# ══════════════════════════════════════════════════════════════

def harvest_signals(
    stock_data: Dict[str, pd.DataFrame],
    collector: TradingSignalCollector,
    default_shares: int = DEFAULT_SHARES,
) -> List[TradingSignal]:
    """对每只股票运行 Brain 引擎并收集信号

    注意: 此函数直接调用 Brain 引擎，不依赖 AnalysisService
    (因为 AnalysisService 需要完整的 DataService 初始化)

    Args:
        stock_data: {symbol: DataFrame} 字典
        collector: 信号收集器
        default_shares: 默认交易股数

    Returns:
        全局信号列表
    """
    all_signals: List[TradingSignal] = []

    for symbol, df in stock_data.items():
        try:
            data_pack = _run_brain_engines(symbol, df)
            if not data_pack:
                continue

            # 使用 df 中间日期作为信号时间戳
            mid_idx = len(df) // 2
            timestamp = pd.Timestamp(df.iloc[mid_idx]["date"])

            signals = collector.collect(
                data_pack, timestamp=timestamp, default_shares=default_shares,
            )
            all_signals.extend(signals)

            buy_count = sum(1 for s in signals if s.action == "BUY")
            sell_count = sum(1 for s in signals if s.action == "SELL")
            logger.info(f"  {symbol}: {len(signals)} 信号 (BUY={buy_count}, SELL={sell_count})")

        except Exception as e:
            logger.error(f"  {symbol} 信号收割失败: {e}")

    return all_signals


def _run_brain_engines(symbol: str, df: pd.DataFrame) -> Optional[Dict]:
    """运行 Brain 引擎生成 data_pack

    直接调用 Brain 引擎，跳过 AnalysisService 层。
    这是一个轻量级的替代方案，避免完整的 DI 初始化。
    """
    data_pack: Dict = {
        "stock": df,
        "symbol": symbol,
        "market": "CN",
        "price": float(df.iloc[-1]["close"]),
        "returns": df["close"].pct_change().dropna(),
    }

    # LPPL (泡沫检测)
    try:
        from uniquant.brain.lppl.engine import LPPLEngine
        lppl = LPPLEngine()
        result = lppl.detect_bubble(df)
        data_pack["risk"] = result.get("risk_level", "Safe")
        data_pack["bubble_confidence"] = result.get("confidence", 0.0)
    except Exception:
        data_pack["risk"] = "Safe"
        data_pack["bubble_confidence"] = 0.0

    # CZSC (缠论)
    try:
        from uniquant.brain.czsc.czsc_engine import CZSCEngine
        czsc = CZSCEngine()
        result = czsc.get_czsc_signals(df)
        data_pack["is_3rd_buy"] = result.get("is_3rd_buy", False)
        data_pack["bi_count"] = result.get("bi_count", 0)
    except Exception:
        data_pack["is_3rd_buy"] = False
        data_pack["bi_count"] = 0

    # Wyckoff
    try:
        from uniquant.brain.wyckoff.engine import WyckoffEngine
        wyckoff = WyckoffEngine()
        report = wyckoff.analyze(df, symbol=symbol)
        data_pack["wyckoff_phase"] = report.structure.phase.value
        data_pack["wyckoff_confidence"] = {
            "A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3,
        }.get(report.signal.confidence.value, 0.3)
        data_pack["wyckoff_spring"] = report.signal.signal_type == "spring"
        data_pack["wyckoff_utad"] = report.signal.signal_type == "utad"
    except Exception:
        data_pack["wyckoff_phase"] = "unknown"
        data_pack["wyckoff_confidence"] = 0.0
        data_pack["wyckoff_spring"] = False
        data_pack["wyckoff_utad"] = False

    # Regime (使用简单均线判断)
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

    # ATR 止损
    try:
        atr = _calc_atr(df, 14)
        data_pack["atr_stop"] = data_pack["price"] - atr * 2
    except Exception:
        data_pack["atr_stop"] = data_pack["price"] * 0.95

    return data_pack


def _calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """计算 ATR"""
    if len(df) < period + 1:
        return df.iloc[-1]["close"] * 0.02

    hi = df["high"].values[-period - 1:]
    lo = df["low"].values[-period - 1:]
    cl = df["close"].values[-period - 1:]
    tr = np.maximum(
        hi[1:] - lo[1:],
        np.maximum(np.abs(hi[1:] - cl[:-1]), np.abs(lo[1:] - cl[:-1])),
    )
    return float(np.mean(tr))


# ══════════════════════════════════════════════════════════════
# Phase 3: 组合撮合
# ══════════════════════════════════════════════════════════════

def run_portfolio_backtest(
    stock_data: Dict[str, pd.DataFrame],
    signals: List[TradingSignal],
    engine: UnifiedBacktestEngine,
) -> Dict[str, BacktestResult]:
    """对每只股票独立运行回测

    Args:
        stock_data: {symbol: DataFrame}
        signals: 全局信号列表
        engine: 回测引擎

    Returns:
        {symbol: BacktestResult}
    """
    results = {}

    # 按 symbol 分组信号
    signals_by_symbol: Dict[str, List[TradingSignal]] = {}
    for sig in signals:
        signals_by_symbol.setdefault(sig.symbol, []).append(sig)

    for symbol, df in stock_data.items():
        symbol_signals = signals_by_symbol.get(symbol, [])
        if not symbol_signals:
            logger.info(f"  {symbol}: 无信号, 跳过")
            continue

        try:
            result = engine.run(df, symbol_signals, symbol=symbol)
            results[symbol] = result
            logger.info(
                f"  {symbol}: {result.total_trades} 笔交易, "
                f"收益={result.total_return:.2%}"
            )
        except Exception as e:
            logger.error(f"  {symbol} 回测失败: {e}")

    return results


# ══════════════════════════════════════════════════════════════
# Phase 4: 绩效归因与研报
# ══════════════════════════════════════════════════════════════

def calculate_portfolio_metrics(
    results: Dict[str, BacktestResult],
    initial_capital: float,
    risk_free_rate: float = 0.02,
) -> Dict:
    """计算组合级绩效指标

    Args:
        results: {symbol: BacktestResult}
        initial_capital: 初始资金
        risk_free_rate: 无风险利率

    Returns:
        绩效指标字典
    """
    if not results:
        return {}

    # 合并所有交易
    all_trades = []
    for symbol, result in results.items():
        for t in result.trades:
            all_trades.append({
                "symbol": symbol,
                "timestamp": t.timestamp,
                "action": t.action,
                "price": t.price,
                "shares": t.shares,
                "commission": t.commission,
                "stamp_duty": t.stamp_duty,
                "pnl": t.pnl,
            })

    if not all_trades:
        return {"total_trades": 0}

    trades_df = pd.DataFrame(all_trades)

    # 合并权益曲线 (简单加总)
    max_len = max(len(r.equity_curve) for r in results.values())
    combined_equity = np.zeros(max_len)
    for r in results.values():
        arr = np.array(r.equity_curve)
        combined_equity[:len(arr)] += arr
    # 填充不足的部分
    for r in results.values():
        arr = np.array(r.equity_curve)
        if len(arr) < max_len:
            combined_equity[len(arr):] += arr[-1]

    # 归一化到初始资金
    n_assets = len(results)
    if n_assets > 0:
        combined_equity = combined_equity / n_assets

    # 计算指标
    total_trades = len(trades_df)
    buy_trades = trades_df[trades_df["action"] == "BUY"]
    sell_trades = trades_df[trades_df["action"] == "SELL"]

    closed_trades = sell_trades[sell_trades["pnl"].notna()]
    if len(closed_trades) > 0:
        wins = closed_trades[closed_trades["pnl"] > 0]
        losses = closed_trades[closed_trades["pnl"] <= 0]
        win_rate = len(wins) / len(closed_trades)
        gross_profit = wins["pnl"].sum() if len(wins) > 0 else 0
        gross_loss = abs(losses["pnl"].sum()) if len(losses) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    else:
        win_rate = 0.0
        profit_factor = 0.0

    # 年化收益
    n_days = len(combined_equity)
    total_return = (combined_equity[-1] - combined_equity[0]) / combined_equity[0] if combined_equity[0] > 0 else 0
    years = n_days / 252
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    # 最大回撤
    peak = np.maximum.accumulate(combined_equity)
    drawdown = (combined_equity - peak) / peak
    max_drawdown = abs(drawdown.min())

    # 夏普比率
    daily_returns = np.diff(combined_equity) / combined_equity[:-1]
    if len(daily_returns) > 1 and np.std(daily_returns) > 0:
        sharpe = (np.mean(daily_returns) - risk_free_rate / 252) / np.std(daily_returns) * np.sqrt(252)
    else:
        sharpe = 0.0

    # 卡玛比率
    calmar = cagr / max_drawdown if max_drawdown > 0 else 0

    return {
        "initial_capital": initial_capital,
        "final_equity": float(combined_equity[-1]),
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "calmar_ratio": calmar,
        "total_trades": total_trades,
        "buy_trades": len(buy_trades),
        "sell_trades": len(sell_trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "n_assets": n_assets,
        "n_days": n_days,
        "equity_curve": combined_equity,
    }


def print_tearsheet(metrics: Dict) -> None:
    """打印绩效研报"""
    print("\n" + "=" * 60)
    print("  UniQuant 组合回测绩效研报 (Tearsheet)")
    print("=" * 60)

    print(f"\n  初始资金:       ¥{metrics.get('initial_capital', 0):>14,.2f}")
    print(f"  期末权益:       ¥{metrics.get('final_equity', 0):>14,.2f}")
    print(f"  总收益率:        {metrics.get('total_return', 0):>13.2%}")
    print(f"  年化收益 (CAGR): {metrics.get('cagr', 0):>13.2%}")
    print(f"  最大回撤:        {metrics.get('max_drawdown', 0):>13.2%}")
    print(f"  夏普比率:        {metrics.get('sharpe_ratio', 0):>13.2f}")
    print(f"  卡玛比率:        {metrics.get('calmar_ratio', 0):>13.2f}")

    print(f"\n  --- 交易统计 ---")
    print(f"  总交易次数:      {metrics.get('total_trades', 0):>13d}")
    print(f"  买入次数:        {metrics.get('buy_trades', 0):>13d}")
    print(f"  卖出次数:        {metrics.get('sell_trades', 0):>13d}")
    print(f"  胜率:            {metrics.get('win_rate', 0):>13.2%}")
    print(f"  盈亏比:          {metrics.get('profit_factor', 0):>13.2f}")

    print(f"\n  --- 组合信息 ---")
    print(f"  资产数量:        {metrics.get('n_assets', 0):>13d}")
    print(f"  回测天数:        {metrics.get('n_days', 0):>13d}")
    print("=" * 60)


def save_tearsheet_chart(metrics: Dict, output_path: str = "portfolio_tearsheet.png") -> None:
    """保存资金曲线图"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        equity = metrics.get("equity_curve", [])
        if len(equity) < 2:
            logger.warning("权益曲线数据不足, 跳过绘图")
            return

        fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1]})
        fig.suptitle("UniQuant Portfolio Tearsheet", fontsize=16, fontweight="bold")

        # 上图: 资金曲线
        ax1 = axes[0]
        ax1.plot(equity, color="#2196F3", linewidth=1.5, label="Portfolio Equity")
        ax1.fill_between(range(len(equity)), equity, alpha=0.1, color="#2196F3")
        ax1.set_ylabel("Equity (¥)")
        ax1.set_title(f"Equity Curve | CAGR={metrics.get('cagr', 0):.2%} | "
                       f"MaxDD={metrics.get('max_drawdown', 0):.2%} | "
                       f"Sharpe={metrics.get('sharpe_ratio', 0):.2f}")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # 下图: 回撤
        ax2 = axes[1]
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak * 100
        ax2.fill_between(range(len(drawdown)), drawdown, 0, color="#F44336", alpha=0.4)
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Trading Days")
        ax2.set_title("Drawdown")
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        logger.info(f"研报图表已保存: {output_path}")

    except ImportError:
        logger.warning("matplotlib 未安装, 跳过绘图")
    except Exception as e:
        logger.error(f"绘图失败: {e}")


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  UniQuant 多资产组合实盘模拟")
    print("=" * 60)

    # Phase 1: 数据装载
    print("\n[Phase 1] 数据湖装载...")
    storage = StorageManager(data_dir=str(PROJECT_ROOT / "data"))
    stock_data = load_stock_data(
        storage, STOCK_POOL,
        start_date="2023-01-01",
        end_date="2025-12-31",
    )
    print(f"  成功加载 {len(stock_data)}/{len(STOCK_POOL)} 只股票")

    if not stock_data:
        print("  [ERROR] 无可用数据, 退出")
        return

    # Phase 2: 信号收割
    print("\n[Phase 2] 全局信号收割...")
    collector = TradingSignalCollector(create_default_registry())
    master_signals = harvest_signals(stock_data, collector)

    # 信号统计
    total = len(master_signals)
    buy_count = sum(1 for s in master_signals if s.action == "BUY")
    sell_count = sum(1 for s in master_signals if s.action == "SELL")
    hold_count = sum(1 for s in master_signals if s.action == "HOLD")
    print(f"\n  信号总计: {total}")
    print(f"  BUY:  {buy_count} ({buy_count/max(total,1)*100:.1f}%)")
    print(f"  SELL: {sell_count} ({sell_count/max(total,1)*100:.1f}%)")
    print(f"  HOLD: {hold_count} ({hold_count/max(total,1)*100:.1f}%)")

    # Phase 3: 组合撮合
    print("\n[Phase 3] 统一组合撮合...")
    engine = UnifiedBacktestEngine(
        initial_capital=INITIAL_CAPITAL / len(stock_data),  # 等权分配
        stamp_duty_rate=0.0005,
        slippage_rate=0.0005,
    )
    results = run_portfolio_backtest(stock_data, master_signals, engine)

    # Phase 4: 绩效研报
    print("\n[Phase 4] 绩效归因研报...")
    metrics = calculate_portfolio_metrics(results, INITIAL_CAPITAL)
    print_tearsheet(metrics)

    # 保存图表
    chart_path = str(PROJECT_ROOT / "portfolio_tearsheet.png")
    save_tearsheet_chart(metrics, chart_path)
    print(f"\n  研报图表: {chart_path}")

    # 按股票输出明细
    print("\n  --- 个股明细 ---")
    for symbol, result in sorted(results.items()):
        trades = result.total_trades
        ret = result.total_return
        print(f"  {symbol:>12s}: {trades:>3d} 笔交易, 收益={ret:>8.2%}")

    print("\n" + "=" * 60)
    print("  模拟完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
