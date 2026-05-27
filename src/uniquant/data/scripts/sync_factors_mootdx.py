#!/usr/bin/env python3
"""
mootdx 复权因子同步脚本

使用 mootdx 读取本地 TDX 除权除息数据(gbbq)并计算复权因子。
支持: gbbq 文件解析、按股票拆分存储、增量更新
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
FACTOR_DIR = DATA_DIR / "lake" / "factors"
PROGRESS_FILE = DATA_DIR / ".sync_factors_mootdx_progress.json"
LOG_FILE = DATA_DIR / "sync_factors_mootdx.log"

DATA_DIR.mkdir(parents=True, exist_ok=True)
FACTOR_DIR.mkdir(parents=True, exist_ok=True)

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


def get_market_suffix(code: str) -> str:
    for prefix, suffix in MARKET_SUFFIX_MAP.items():
        if code.startswith(prefix):
            return suffix
    return "SH"


def normalize_code(code: str) -> Optional[str]:
    if pd.isna(code):
        return None
    code = str(code).strip()
    if not code:
        return None
    digits = "".join(ch for ch in code if ch.isdigit()).zfill(6)
    suffix = get_market_suffix(digits)
    return f"{digits}.{suffix}" if suffix else None


def load_progress() -> set:
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r") as f:
                return set(json.load(f).get("completed", []))
        except (json.JSONDecodeError, IOError, OSError):
            pass
    return set()


def save_progress(completed: set):
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump({"completed": list(completed), "last_update": datetime.now().isoformat()}, f)
    except Exception as e:
        logger.warning(f"保存进度失败: {e}")


def parse_gbbq(tdx_dir: str) -> pd.DataFrame:
    gbbq_path = Path(tdx_dir) / "T0002" / "hq_cache" / "gbbq"
    if not gbbq_path.exists():
        gbbq_path = Path(tdx_dir) / "vipdoc" / "gbbq"

    if not gbbq_path.exists():
        logger.error(f"gbbq 文件不存在: {gbbq_path}")
        return pd.DataFrame()

    try:
        from pytdx.reader import GbbqReader
        reader = GbbqReader()
        df = reader.get_df(str(gbbq_path))

        if df is None or df.empty:
            logger.warning("gbbq 文件解析为空")
            return pd.DataFrame()

        column_map = {
            "代码": "code", "证券代码": "code",
            "日期": "date", "除权除息日": "date",
            "分红": "cash_div", "派息": "cash_div",
            "送股": "split_ratio", "送转股": "split_ratio",
            "配股": "rights_ratio", "配股价": "rights_price",
        }
        df = df.rename(columns=column_map)

        if "code" in df.columns:
            df["code"] = df["code"].astype(str).str.strip()
            df = df[df["code"].str.match(r"^\d{6}$")]

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
            df = df.dropna(subset=["date"])

        logger.info(f"解析 gbbq 成功: {len(df)} 条记录, {df['code'].nunique()} 只股票")
        return df

    except ImportError:
        logger.error("pytdx 未安装，请执行: pip install pytdx")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"解析 gbbq 失败: {e}")
        return pd.DataFrame()


def calculate_adj_factors(df_day: pd.DataFrame, df_gbbq: pd.DataFrame) -> pd.DataFrame:
    if df_day.empty or df_gbbq.empty:
        return pd.DataFrame(columns=["date", "adj_factor"])

    df = df_day.copy()
    if "date" not in df.columns and df.index.name == "date":
        df = df.reset_index()

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if "close" not in df.columns:
        return pd.DataFrame(columns=["date", "adj_factor"])

    df["adj_factor"] = 1.0

    for _, row in df_gbbq.iterrows():
        ex_date = row.get("date")
        if pd.isna(ex_date):
            continue

        cash_div = float(row.get("cash_div", 0) or 0)
        split_ratio = float(row.get("split_ratio", 0) or 0)
        rights_ratio = float(row.get("rights_ratio", 0) or 0)
        rights_price = float(row.get("rights_price", 0) or 0)

        mask = df["date"] >= ex_date
        if not mask.any():
            continue

        close_before = df.loc[df["date"] < ex_date, "close"]
        if close_before.empty:
            continue

        ref_close = close_before.iloc[-1]
        if ref_close <= 0:
            continue

        new_price = ref_close - cash_div + rights_ratio * rights_price
        new_price = new_price / (1 + split_ratio + rights_ratio)

        if new_price > 0:
            ratio = new_price / ref_close
            df.loc[mask, "adj_factor"] *= ratio

    df["adj_factor"] = df["adj_factor"] / df["adj_factor"].iloc[-1]

    return df[["date", "adj_factor"]]


def sync_factors(
    tdx_dir: str,
    output_dir: str,
    symbols: Optional[List[str]] = None,
):
    factor_out_dir = Path(output_dir) / "lake" / "factors"
    factor_out_dir.mkdir(parents=True, exist_ok=True)

    gbbq_df = parse_gbbq(tdx_dir)
    if gbbq_df.empty:
        logger.error("无 gbbq 数据可处理")
        return 0, 0

    all_codes = gbbq_df["code"].unique()
    stock_list = []
    for code in all_codes:
        normalized = normalize_code(code)
        if normalized:
            if symbols and normalized not in symbols:
                continue
            stock_list.append((code, normalized))

    logger.info(f"需处理 {len(stock_list)} 只股票的复权因子")

    completed = load_progress()
    success_count = 0
    fail_count = 0
    skip_count = 0

    daily_dir = Path(output_dir) / "lake" / "quotes" / "daily"

    for i, (raw_code, symbol) in enumerate(stock_list, 1):
        if symbol in completed:
            skip_count += 1
            continue

        try:
            symbol_gbbq = gbbq_df[gbbq_df["code"] == raw_code].copy()
            if symbol_gbbq.empty:
                skip_count += 1
                continue

            daily_file = daily_dir / f"{symbol}.parquet"
            if daily_file.exists():
                day_df = pd.read_parquet(daily_file)
            else:
                logger.debug(f"{symbol} 无日线数据，生成纯因子")
                day_df = pd.DataFrame(columns=["date", "close"])

            factor_df = calculate_adj_factors(day_df, symbol_gbbq)

            if factor_df.empty:
                logger.warning(f"{symbol} 计算因子为空")
                fail_count += 1
                continue

            factor_df["code"] = symbol
            output_file = factor_out_dir / f"{symbol}.parquet"
            factor_df.to_parquet(output_file, compression="snappy", index=False)

            success_count += 1
            completed.add(symbol)

            if i % 200 == 0:
                save_progress(completed)
                logger.info(f"进度: {i}/{len(stock_list)} (成功: {success_count})")

        except Exception as e:
            logger.error(f"{symbol} 因子计算失败: {e}")
            fail_count += 1

    save_progress(completed)

    logger.info("=" * 60)
    logger.info("复权因子同步完成")
    logger.info(f"总数: {len(stock_list)}, 成功: {success_count}, 跳过: {skip_count}, 失败: {fail_count}")
    return success_count, fail_count


def main():
    parser = argparse.ArgumentParser(description="mootdx 复权因子同步")
    parser.add_argument("--tdx-dir", required=True, help="TDX 数据目录")
    parser.add_argument("--output-dir", default=str(DATA_DIR), help="输出目录")
    parser.add_argument("--symbols", nargs="+", help="仅同步指定股票代码")
    args = parser.parse_args()

    sync_factors(args.tdx_dir, args.output_dir, args.symbols)


if __name__ == "__main__":
    main()
