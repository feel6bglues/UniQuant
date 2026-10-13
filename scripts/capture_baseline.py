#!/usr/bin/env python3
"""
基线捕获脚本 — capture_baseline.py

记录当前系统的数值输出，用于后续回归比对。
输出: tests/benchmark/baseline_v{version}.parquet

用法:
  python scripts/capture_baseline.py                              # golden_20
  python scripts/capture_baseline.py --stock-list golden_100.txt  # golden_100
  python scripts/capture_baseline.py --verify-only                # 仅验证基线完整性
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

SRC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_DIR / "src"))

from uniquant.services import ServiceContainer
from uniquant.services.research_pipeline import PipelineResult

BASELINE_DIR = SRC_DIR / "tests" / "benchmark"
BASELINE_VERSION = "v0"


@dataclass
class StockBaseline:
    symbol: str
    success: bool
    error: Optional[str]
    total_signals: int
    total_trades: int
    total_return: float
    final_cash: float
    initial_capital: float
    equity_curve_len: int
    trace_id: str
    duration_sec: float
    full_result: Optional[Dict[str, Any]] = None


def load_stock_list(path: Path) -> List[str]:
    symbols = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "#" in line:
                line = line.split("#")[0].strip()
            symbols.append(line)
    return symbols


def serialize_result(result: PipelineResult) -> Dict[str, Any]:
    trades_data = []
    if result.backtest.trades:
        for t in result.backtest.trades:
            ts_str = ""
            if hasattr(t, "timestamp") and t.timestamp:
                ts_str = str(t.timestamp)
            elif hasattr(t, "date") and t.date:
                ts_str = str(t.date)
            stamp_val = getattr(t, "stamp_duty", getattr(t, "stamp_tax", 0.0))
            trades_data.append({
                "timestamp": ts_str,
                "date": ts_str,
                "action": getattr(t, "action", ""),
                "symbol": getattr(t, "symbol", result.symbol),
                "shares": getattr(t, "shares", 0),
                "price": getattr(t, "price", 0.0),
                "reason": getattr(t, "reason", ""),
                "commission": getattr(t, "commission", 0.0),
                "stamp_duty": stamp_val,
                "stamp_tax": stamp_val,
                "transfer_fee": getattr(t, "transfer_fee", 0.0),
                "slippage": getattr(t, "slippage", 0.0),
                "pnl": getattr(t, "pnl", 0.0),
            })

    signals_data = []
    for sig in result.signals:
        signals_data.append({
            "action": sig.action,
            "reason": sig.reason,
            "confidence": sig.confidence,
            "shares": sig.shares,
            "symbol": sig.symbol,
            "price": sig.price,
            "timestamp": str(sig.timestamp) if sig.timestamp else "",
        })

    return {
        "symbol": result.symbol,
        "success": result.success,
        "error": result.error,
        "total_signals": result.total_signals,
        "total_trades": result.total_trades,
        "total_return": result.total_return,
        "final_cash": result.backtest.final_cash,
        "initial_capital": result.backtest.initial_capital,
        "equity_curve": result.backtest.equity_curve,
        "daily_returns": result.backtest.daily_returns,
        "equity_curve_len": len(result.backtest.equity_curve),
        "trades": trades_data,
        "signals": signals_data,
        "trace_id": result.trace_id or "",
    }


def capture_baseline(
    stock_list: List[str],
    version: str = BASELINE_VERSION,
    verify_only: bool = False,
) -> pd.DataFrame:
    container = ServiceContainer()
    container.initialize()
    pipeline = container.get("research_pipeline")

    records = []
    out_path = BASELINE_DIR / f"baseline_{version}.parquet"

    if verify_only:
        if not out_path.exists():
            print(f"基线文件不存在: {out_path}")
            sys.exit(1)
        existing = pd.read_parquet(out_path)
        print(f"基线文件存在: {out_path}")
        print(f"  股票数: {len(existing)}")
        print(f"  列: {list(existing.columns)}")
        for _, row in existing.iterrows():
            print(f"  {row['symbol']}: success={row['success']} "
                  f"signals={row['total_signals']} trades={row['total_trades']} "
                  f"return={row['total_return']:.4%}")
        return existing

    print(f"捕获基线 v{version} — {len(stock_list)} 只股票")
    print("=" * 60)

    for i, symbol in enumerate(stock_list, 1):
        t0 = time.time()
        try:
            result = pipeline.run(symbol)
            duration = time.time() - t0
            status = "✓" if result.success else "✗"
            print(f"  [{i:02d}/{len(stock_list)}] {status} {symbol} "
                  f"信号={result.total_signals} 成交={result.total_trades} "
                  f"收益={result.total_return:.4%} ({duration:.1f}s)")
        except Exception as e:
            duration = time.time() - t0
            print(f"  [{i:02d}/{len(stock_list)}] ✗ {symbol} 异常: {e} ({duration:.1f}s)")
            result = PipelineResult(
                symbol=symbol,
                data_pack={},
                decision={},
                signals=[],
                backtest=type("BacktestResult", (), {
                    "trades": [], "equity_curve": [], "daily_returns": [],
                    "final_cash": 0.0, "initial_capital": 0.0,
                    "total_trades": 0, "total_return": 0.0,
                    "__class__": type("BT", (), {}),
                })(),
                success=False,
                error=str(e),
            )

        record = serialize_result(result)
        record["duration_sec"] = round(duration, 2)
        records.append(record)

        # 每5只保存一次中间结果
        if i % 5 == 0:
            _save_intermediate(records, version)

    df = pd.DataFrame(records)
    df.to_parquet(out_path, index=False)
    print(f"\n基线已保存: {out_path}")
    print(f"  股票数: {len(df)}")
    print(f"  成功: {df['success'].sum()} / {len(df)}")
    return df


def _save_intermediate(records: List[Dict], version: str):
    tmp_path = BASELINE_DIR / f"baseline_{version}_intermediate.parquet"
    pd.DataFrame(records).to_parquet(tmp_path, index=False)
    print(f"  → 中间结果已保存 ({len(records)} 只)")


def capture_execution_baseline(
    stock_list: Optional[List[str]] = None,
    version: str = BASELINE_VERSION,
    verify_only: bool = False,
) -> pd.DataFrame:
    """捕获撮合执行层含真实成交的 Golden 基准。"""
    from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine, TradingSignal

    out_path = BASELINE_DIR / f"baseline_execution_{version}.parquet"
    if verify_only:
        if not out_path.exists():
            print(f"执行基线文件不存在: {out_path}")
            sys.exit(1)
        existing = pd.read_parquet(out_path)
        print(f"执行基线文件存在: {out_path}")
        print(f"  股票数: {len(existing)}")
        print(f"  总成交笔数: {existing['total_trades'].sum()}")
        return existing

    if stock_list is None:
        exec_list_path = BASELINE_DIR / "golden_execution.txt"
        stock_list = load_stock_list(exec_list_path)

    print(f"捕获撮合执行基线 v{version} — {len(stock_list)} 只股票")
    print("=" * 60)

    engine = UnifiedBacktestEngine(initial_capital=500_000.0)
    records = []

    for i, symbol in enumerate(stock_list, 1):
        t0 = time.time()
        file_path = SRC_DIR / "data" / "lake" / "quotes" / "daily" / f"{symbol}.parquet"
        if not file_path.exists():
            print(f"  [{i:02d}/{len(stock_list)}] ✗ 缺少日线文件: {file_path}")
            continue

        df = pd.read_parquet(file_path)
        df["date_dt"] = pd.to_datetime(df["date"])
        sub_df = df[(df["date_dt"] >= "2023-01-01") & (df["date_dt"] <= "2023-12-31")].reset_index(drop=True)
        sub_df["ma5"] = sub_df["close"].rolling(5).mean()
        sub_df["ma20"] = sub_df["close"].rolling(20).mean()

        signals = []
        holding = False
        shares = 100 if symbol == "600519.SH" else 500
        for idx in range(20, len(sub_df) - 1):
            row = sub_df.iloc[idx]
            date = row["date"]
            if row["ma5"] > row["ma20"] and not holding:
                signals.append(TradingSignal(action="BUY", symbol=symbol, shares=shares, timestamp=date, reason="MA_CROSS_BUY"))
                holding = True
            elif row["ma5"] < row["ma20"] and holding:
                signals.append(TradingSignal(action="SELL", symbol=symbol, shares=shares, timestamp=date, reason="MA_CROSS_SELL"))
                holding = False

        name = "ST金花" if symbol == "600080.SH" else None
        res = engine.run(df=sub_df, signals=signals, symbol=symbol, name=name)
        duration = time.time() - t0

        trades_data = []
        for t in res.trades:
            ts_str = str(t.timestamp) if hasattr(t, "timestamp") and t.timestamp else ""
            stamp_val = getattr(t, "stamp_duty", getattr(t, "stamp_tax", 0.0))
            trades_data.append({
                "timestamp": ts_str,
                "date": ts_str,
                "action": getattr(t, "action", ""),
                "symbol": getattr(t, "symbol", symbol),
                "shares": getattr(t, "shares", 0),
                "price": getattr(t, "price", 0.0),
                "reason": getattr(t, "reason", ""),
                "commission": getattr(t, "commission", 0.0),
                "stamp_duty": stamp_val,
                "stamp_tax": stamp_val,
                "transfer_fee": getattr(t, "transfer_fee", 0.0),
                "slippage": getattr(t, "slippage", 0.0),
                "pnl": getattr(t, "pnl", 0.0),
            })

        signals_data = [
            {
                "action": s.action,
                "reason": s.reason,
                "confidence": s.confidence,
                "shares": s.shares,
                "symbol": s.symbol,
                "price": s.price,
                "timestamp": str(s.timestamp) if s.timestamp else "",
            }
            for s in signals
        ]

        record = {
            "symbol": symbol,
            "success": True,
            "error": None,
            "total_signals": len(signals),
            "total_trades": res.total_trades,
            "total_return": res.total_return,
            "final_cash": res.final_cash,
            "initial_capital": res.initial_capital,
            "equity_curve": res.equity_curve,
            "daily_returns": res.daily_returns,
            "equity_curve_len": len(res.equity_curve),
            "trades": trades_data,
            "signals": signals_data,
            "trace_id": f"exec_baseline_{symbol}",
            "duration_sec": round(duration, 2),
        }
        records.append(record)
        print(f"  [{i:02d}/{len(stock_list)}] ✓ {symbol} 信号={len(signals)} "
              f"成交={res.total_trades} 收益={res.total_return:.4%} ({duration:.2f}s)")

    df_res = pd.DataFrame(records)
    df_res.to_parquet(out_path, index=False)
    print(f"\n执行基线已保存: {out_path}")
    print(f"  总成交笔数: {df_res['total_trades'].sum()}")
    return df_res


def main():
    parser = argparse.ArgumentParser(description="基线捕获脚本")
    parser.add_argument(
        "--stock-list", type=str, default="golden_20.txt",
        help="股票列表文件 (默认: golden_20.txt)",
    )
    parser.add_argument(
        "--version", type=str, default=BASELINE_VERSION,
        help=f"基线版本号 (默认: {BASELINE_VERSION})",
    )
    parser.add_argument(
        "--execution", action="store_true",
        help="捕获撮合执行层含真实成交基线 (默认股票池: golden_execution.txt)",
    )
    parser.add_argument(
        "--verify-only", action="store_true",
        help="仅验证基线文件是否存在",
    )

    args = parser.parse_args()

    if args.execution:
        list_file = "golden_execution.txt" if args.stock_list == "golden_20.txt" else args.stock_list
        list_path = BASELINE_DIR / list_file
        stock_list = load_stock_list(list_path) if list_path.exists() else None
        capture_execution_baseline(
            stock_list=stock_list,
            version=args.version,
            verify_only=args.verify_only,
        )
        return

    list_path = BASELINE_DIR / args.stock_list

    if not list_path.exists():
        print(f"股票列表不存在: {list_path}")
        sys.exit(1)

    stock_list = load_stock_list(list_path)
    print(f"加载股票列表: {list_path} ({len(stock_list)} 只)")

    capture_baseline(
        stock_list=stock_list,
        version=args.version,
        verify_only=args.verify_only,
    )


if __name__ == "__main__":
    main()
