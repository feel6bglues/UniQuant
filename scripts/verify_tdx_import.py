#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一的通达信导入校验脚本。"""

import argparse
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.data.lake.storage_manager import StorageManager
from uniquant.data.managers.tdx_updater import TdxUpdater
from uniquant.shared.config_loader import get_config


DEFAULT_LATEST_SYMBOLS = ["000001.SZ", "600000.SH", "600036.SH", "000002.SZ"]
DEFAULT_SAMPLE_SYMBOLS = [
    "600000.SH",
    "000001.SZ",
    "600519.SH",
    "000858.SZ",
    "601318.SH",
]


def get_tdx_base_path() -> Optional[Path]:
    """从配置获取通达信基础路径。"""
    config = get_config()
    tdx_path = config.get("base.tdx.path", None)
    return Path(tdx_path) if tdx_path else None


def get_storage() -> StorageManager:
    return StorageManager(data_dir=str(PROJECT_ROOT / "data"))


def get_tdx_file_path(symbol: str) -> Optional[Path]:
    """根据股票代码定位通达信日线文件。"""
    tdx_path = get_tdx_base_path()
    if not tdx_path:
        return None

    code = symbol.split(".")[0]
    market = "sh" if symbol.endswith(".SH") else "sz"
    return tdx_path / "vipdoc" / market / "lday" / f"{market}{code}.day"


def get_tdx_latest_date(symbol: str) -> Optional[pd.Timestamp]:
    """读取通达信本地文件中的最新日期。"""
    try:
        tdx_file = get_tdx_file_path(symbol)
        if tdx_file is None or not tdx_file.exists():
            return None

        updater = TdxUpdater()
        df = updater.parse_day_file(str(tdx_file))
        if df is None or df.empty or "date" not in df.columns:
            return None

        return pd.to_datetime(df["date"].max())
    except Exception:
        return None


def get_parquet_latest_date(symbol: str) -> Optional[pd.Timestamp]:
    """读取数据湖中的最新日期。"""
    try:
        df = get_storage().read_data(symbol, data_type="daily")
        if df is None or df.empty or "date" not in df.columns:
            return None

        return pd.to_datetime(df["date"].max())
    except Exception:
        return None


def validate_symbol(symbol: str) -> Dict[str, Any]:
    """验证单个股票的最新日期一致性。"""
    result = {
        "symbol": symbol,
        "tdx_date": None,
        "parquet_date": None,
        "status": "error",
        "message": "",
    }

    tdx_date = get_tdx_latest_date(symbol)
    if tdx_date is None:
        result["message"] = "通达信文件不存在或不可读"
        return result
    result["tdx_date"] = tdx_date

    parquet_date = get_parquet_latest_date(symbol)
    if parquet_date is None:
        result["message"] = "数据湖文件不存在或为空"
        return result
    result["parquet_date"] = parquet_date

    if parquet_date >= tdx_date:
        result["status"] = "ok"
        result["message"] = f"一致 (P:{parquet_date.date()}, T:{tdx_date.date()})"
    else:
        diff_days = (tdx_date - parquet_date).days
        result["status"] = "diff"
        result["message"] = f"缺失 {diff_days}天 (P:{parquet_date.date()}, T:{tdx_date.date()})"

    return result


def collect_all_symbols_from_tdx() -> List[str]:
    """从通达信本地目录收集全部股票代码。"""
    updater = TdxUpdater(data_dir=str(PROJECT_ROOT / "data"))
    symbols: List[str] = []
    for file_path in updater.get_all_day_files():
        filename = Path(file_path).name.split(".")[0]
        if filename.startswith("sh"):
            symbols.append(f"{filename[2:]}.SH")
        elif filename.startswith("sz"):
            symbols.append(f"{filename[2:]}.SZ")
    return symbols


def print_result_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """输出校验汇总。"""
    ok_count = sum(1 for item in results if item["status"] == "ok")
    diff_count = sum(1 for item in results if item["status"] == "diff")
    error_count = sum(1 for item in results if item["status"] == "error")
    total = len(results)
    pass_rate = ok_count / total * 100 if total else 0.0

    print("\n" + "=" * 70)
    print("验证结果")
    print("=" * 70)
    print(f"检查股票数: {total}")
    print(f"通过: {ok_count}")
    print(f"差异: {diff_count}")
    print(f"错误: {error_count}")
    print(f"通过率: {pass_rate:.1f}%")

    return {
        "total": total,
        "ok": ok_count,
        "diff": diff_count,
        "error": error_count,
        "pass_rate": pass_rate,
    }


def run_latest_mode(symbols: List[str]) -> Dict[str, Any]:
    """检查若干样本股票的最新日期。"""
    print("\n" + "=" * 70)
    print("数据湖日线数据最新日期检查")
    print("=" * 70)

    results = []
    for symbol in symbols:
        result = validate_symbol(symbol)
        results.append(result)
        if result["status"] == "ok":
            print(f"{symbol}: {result['message']}")
        else:
            print(f"{symbol}: {result['message']}")

    return print_result_summary(results)


def run_sample_mode(symbols: List[str]) -> Dict[str, Any]:
    """抽样验证最新日期是否追平。"""
    print("\n" + "=" * 70)
    print("通达信数据更新验证")
    print("=" * 70)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = []
    for symbol in symbols:
        print(f"\n检查股票: {symbol}")
        result = validate_symbol(symbol)
        results.append(result)
        if result["tdx_date"] is not None:
            print(f"  通达信最新日期: {result['tdx_date'].date()}")
        if result["parquet_date"] is not None:
            print(f"  数据湖最新日期: {result['parquet_date'].date()}")
        print(f"  {result['message']}")

    return print_result_summary(results)


def run_random_sample_mode(sample_size: int, seed: int = 42) -> Dict[str, Any]:
    """随机抽样验证。"""
    print("\n" + "=" * 70)
    print(f"随机抽样 {sample_size} 只股票通达信数据验证")
    print("=" * 70)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_symbols = collect_all_symbols_from_tdx()
    print(f"\n[Step 1] 通达信共有 {len(all_symbols)} 只股票")

    random.seed(seed)
    sampled = random.sample(all_symbols, min(sample_size, len(all_symbols)))
    print(f"[Step 2] 抽样校验 {len(sampled)} 只")

    results = []
    for index, symbol in enumerate(sampled, 1):
        results.append(validate_symbol(symbol))
        if index % 50 == 0 or index == len(sampled):
            print(f"  - 已验证 {index}/{len(sampled)} 只...")

    return print_result_summary(results)


def run_daily_mode(symbols: List[str]) -> Dict[str, Any]:
    """读取数据湖样本文件的最新记录。"""
    daily_dir = PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
    files = list(daily_dir.glob("*.parquet"))
    print(f"日线数据文件数: {len(files)}")
    print("\n示例股票最新数据:")

    for symbol in symbols:
        fpath = daily_dir / f"{symbol}.parquet"
        if not fpath.exists():
            print(f"  {symbol}: 文件不存在")
            continue

        df = pd.read_parquet(fpath)
        if df.empty:
            print(f"  {symbol}: 数据为空")
            continue

        latest = df.iloc[-1]
        print(f"  {symbol}: 最新日期={latest['date']}, 收盘价={latest['close']:.2f}")

    total_records = 0
    for fpath in files[:100]:
        try:
            total_records += len(pd.read_parquet(fpath))
        except Exception:
            continue

    print("\n数据统计:")
    print(f"  前100个文件总记录数: {total_records}")
    return {"total_files": len(files), "total_records_first_100": total_records}


def run_deep_mode(sample_size: int) -> Dict[str, Any]:
    """调用深度一致性校验。"""
    from validate_tdx_import import validate_batch

    symbols = collect_all_symbols_from_tdx()
    return validate_batch(symbols, sample_size=sample_size)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统一的通达信导入校验脚本")
    parser.add_argument(
        "--mode",
        choices=["latest", "sample", "random-sample", "daily", "deep"],
        default="sample",
        help="校验模式",
    )
    parser.add_argument("--sample-size", type=int, default=200, help="抽样数量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--symbols", type=str, help="逗号分隔的股票代码列表")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> Dict[str, Any]:
    args = parse_args(argv)

    if args.symbols:
        symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    elif args.mode == "latest":
        symbols = DEFAULT_LATEST_SYMBOLS
    else:
        symbols = DEFAULT_SAMPLE_SYMBOLS

    if args.mode == "latest":
        return run_latest_mode(symbols)
    if args.mode == "sample":
        return run_sample_mode(symbols)
    if args.mode == "random-sample":
        return run_random_sample_mode(args.sample_size, seed=args.seed)
    if args.mode == "daily":
        return run_daily_mode(symbols)
    return run_deep_mode(args.sample_size)


if __name__ == "__main__":
    main()
