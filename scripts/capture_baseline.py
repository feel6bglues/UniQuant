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
import json
import os
import sys
import time
import traceback
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
            trades_data.append({
                "date": str(t.date) if hasattr(t, "date") else "",
                "action": t.action if hasattr(t, "action") else "",
                "symbol": t.symbol if hasattr(t, "symbol") else result.symbol,
                "shares": t.shares if hasattr(t, "shares") else 0,
                "price": t.price if hasattr(t, "price") else 0.0,
                "reason": t.reason if hasattr(t, "reason") else "",
                "commission": t.commission if hasattr(t, "commission") else 0.0,
                "stamp_tax": t.stamp_tax if hasattr(t, "stamp_tax") else 0.0,
                "transfer_fee": t.transfer_fee if hasattr(t, "transfer_fee") else 0.0,
                "slippage": t.slippage if hasattr(t, "slippage") else 0.0,
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
        "--verify-only", action="store_true",
        help="仅验证基线文件是否存在",
    )

    args = parser.parse_args()
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
