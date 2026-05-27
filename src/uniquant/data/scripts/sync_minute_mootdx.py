#!/usr/bin/env python3
"""
mootdx 分钟线数据同步脚本

使用 mootdx 读取本地 TDX 分钟线数据并导入到 Parquet 数据湖。
支持: 1min/5min 频率、断点续传、批量同步
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROGRESS_FILE = DATA_DIR / ".sync_minute_mootdx_progress.json"
LOG_FILE = DATA_DIR / "sync_minute_mootdx.log"

DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

MARKET_SUFFIX_MAP = {
    "60": "SH", "68": "SH",
    "00": "SZ", "30": "SZ",
    "43": "BJ", "83": "BJ", "87": "BJ",
}

FREQUENCY_MAP = {
    "1min": "1mins",
    "5min": "5mins",
    "1mins": "1mins",
    "5mins": "5mins",
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


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            pass
    return {}


def save_progress(progress: dict):
    try:
        progress["last_update"] = datetime.now().isoformat()
        with open(PROGRESS_FILE, "w") as f:
            json.dump(progress, f)
    except Exception as e:
        logger.warning(f"保存进度失败: {e}")


def sync_minute(
    tdx_dir: str,
    output_dir: str,
    frequency: str = "5min",
    symbols: Optional[List[str]] = None,
):
    from mootdx.reader import Reader
    from uniquant.data.lake.storage_manager import StorageManager

    reader = Reader.factory(market="std", tdxdir=tdx_dir)
    storage = StorageManager(data_dir=output_dir)

    freq_key = FREQUENCY_MAP.get(frequency, "5mins")
    data_type = freq_key

    if symbols is None:
        symbols = get_all_symbols(reader)
        logger.info(f"获取到 {len(symbols)} 只股票")

    progress = load_progress()
    completed = set(progress.get("completed", {}).get(freq_key, []))

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
            freq_int = 1 if "1" in frequency else 5
            df = reader.minute(symbol=code, frequency=freq_int)

            if df is None or df.empty:
                logger.warning(f"{symbol} 无 {frequency} 数据")
                fail_count += 1
                continue

            df = df.copy()
            if "date" not in df.columns and df.index.name == "date":
                df = df.reset_index()

            df["code"] = code
            df["market"] = symbol.split(".")[-1]

            storage.write_data(symbol=symbol, df=df, data_type=data_type)
            success_count += 1
            completed.add(symbol)

            if i % 100 == 0:
                progress.setdefault("completed", {})[freq_key] = list(completed)
                save_progress(progress)
                logger.info(f"进度: {i}/{total} (成功: {success_count}, 跳过: {skip_count})")

        except Exception as e:
            logger.error(f"{symbol} 同步失败: {e}")
            fail_count += 1

    progress.setdefault("completed", {})[freq_key] = list(completed)
    save_progress(progress)

    logger.info("=" * 60)
    logger.info(f"{frequency} 同步完成")
    logger.info(f"总数: {total}, 成功: {success_count}, 跳过: {skip_count}, 失败: {fail_count}")
    return success_count, fail_count


def main():
    parser = argparse.ArgumentParser(description="mootdx 分钟线数据同步")
    parser.add_argument("--tdx-dir", required=True, help="TDX 数据目录")
    parser.add_argument("--output-dir", default=str(DATA_DIR), help="输出目录")
    parser.add_argument("--frequency", default="5min", choices=["1min", "5min"], help="分钟线频率")
    parser.add_argument("--symbols", nargs="+", help="股票代码列表")
    args = parser.parse_args()

    sync_minute(args.tdx_dir, args.output_dir, args.frequency, args.symbols)


if __name__ == "__main__":
    main()
