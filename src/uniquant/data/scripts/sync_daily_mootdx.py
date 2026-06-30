#!/usr/bin/env python3
"""
mootdx 日线数据同步脚本

使用 mootdx 读取本地 TDX 数据并导入到 Parquet 数据湖。
支持: 断点续传、进度追踪、批量同步
"""

import argparse
import json
from pathlib import Path

from ...shared.time_provider import get_time_provider
from typing import List, Optional

from uniquant.shared.logger_factory import get_logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROGRESS_FILE = DATA_DIR / ".sync_daily_mootdx_progress.json"
LOG_FILE = DATA_DIR / "sync_daily_mootdx.log"

DATA_DIR.mkdir(parents=True, exist_ok=True)

logger = get_logger(__name__)

MARKET_SUFFIX_MAP = {
    "60": "SH", "68": "SH",
    "00": "SZ", "30": "SZ",
    "43": "BJ", "83": "BJ", "87": "BJ",
}


def get_market_suffix(code: str) -> str:
    for prefix, suffix in MARKET_SUFFIX_MAP.items():
        if code.startswith(prefix):
            return suffix
    return "SH"


def get_all_symbols(reader) -> List[str]:
    symbols = []
    for market in ["sh", "sz"]:
        stocks = reader.stocks(market=market)
        if stocks is not None and not stocks.empty:
            code_col = "code" if "code" in stocks.columns else stocks.columns[0]
            for code in stocks[code_col].astype(str):
                code = code.zfill(6)
                suffix = get_market_suffix(code)
                symbols.append(f"{code}.{suffix}")
    return symbols


def load_progress() -> set:
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r") as f:
                return set(json.load(f).get("completed", []))
        except (json.JSONDecodeError, IOError, OSError):
            logger.exception("加载进度文件失败，返回空集合")
            pass
    return set()


def save_progress(completed: set):
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump({"completed": list(completed), "last_update": get_time_provider().now().isoformat()}, f)
    except Exception as e:
        logger.warning(f"保存进度失败: {e}")


def sync_daily(tdx_dir: str, output_dir: str, symbols: Optional[List[str]] = None):
    from mootdx.reader import Reader
    from uniquant.data.lake.storage_manager import StorageManager

    reader = Reader.factory(market="std", tdxdir=tdx_dir)
    storage = StorageManager(data_dir=output_dir)

    if symbols is None:
        symbols = get_all_symbols(reader)
        logger.info(f"获取到 {len(symbols)} 只股票")

    completed = load_progress()
    if completed:
        logger.info(f"断点续传: 已完成 {len(completed)} 只")

    total = len(symbols)
    success_count = 0
    fail_count = 0
    skip_count = 0

    for i, symbol in enumerate(symbols, 1):
        if symbol in completed:
            skip_count += 1
            continue

        try:
            code = symbol.split(".")[0]
            df = reader.daily(symbol=code)

            if df is None or df.empty:
                logger.warning(f"{symbol} 无数据")
                fail_count += 1
                continue

            df = df.copy()
            if "date" not in df.columns and df.index.name == "date":
                df = df.reset_index()

            df["code"] = code
            df["market"] = symbol.split(".")[-1]

            storage.write_data(symbol=symbol, df=df, data_type="daily")
            success_count += 1
            completed.add(symbol)

            if i % 100 == 0:
                save_progress(completed)
                logger.info(f"进度: {i}/{total} (成功: {success_count}, 跳过: {skip_count})")

        except Exception as e:
            logger.error(f"{symbol} 同步失败: {e}")
            fail_count += 1

    save_progress(completed)

    logger.info("=" * 60)
    logger.info("同步完成")
    logger.info(f"总数: {total}, 成功: {success_count}, 跳过: {skip_count}, 失败: {fail_count}")
    return success_count, fail_count


def main():
    parser = argparse.ArgumentParser(description="mootdx 日线数据同步")
    parser.add_argument("--tdx-dir", required=True, help="TDX 数据目录")
    parser.add_argument("--output-dir", default=str(DATA_DIR), help="输出目录")
    parser.add_argument("--symbols", nargs="+", help="股票代码列表 (如 600000.SH)")
    args = parser.parse_args()

    sync_daily(args.tdx_dir, args.output_dir, args.symbols)


if __name__ == "__main__":
    main()
