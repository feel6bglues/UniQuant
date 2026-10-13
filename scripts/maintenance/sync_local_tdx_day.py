#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniQuant 离线本地通达信断点增量更新与 GBBQ 同步脚本

功能：
1. 深入扫描 ~/.local/share/tdxcfv/drive_c/tc/vipdoc/ 下 sh/lday 与 sz/lday 二进制 .day 行情；
2. 多进程增量解包，仅解包大于现有数据湖最后日期的 Bar；
3. 严格分类路由：基于 is_index_symbol 区分写入 data/lake/quotes/index 与 quotes/daily；
4. 原子落盘：采用 .tmp.{pid} + os.replace 机制，防止读写竞态与文件损坏；
5. 同步更新本地 GBBQ 股本变迁与除权除息库到 data/fq/gbbq.parquet，消除除权缺口；
6. 完善的执行统计与对账报表。
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.data.lake.storage_manager import is_index_symbol
from uniquant.shared.logger_factory import get_logger

logger = get_logger("maintenance.sync_local_tdx_day")

DEFAULT_VIPDOC_DIR = Path.home() / ".local/share/tdxcfv/drive_c/tc/vipdoc"
DEFAULT_GBBQ_PATH = Path.home() / ".local/share/tdxcfv/drive_c/tc/T0002/hq_cache/gbbq"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

# 通达信 .day 紧凑结构体格式: date(u32), open(u32), high(u32), low(u32), close(u32), amount(f32), volume(u32), reserved(u32)
DAY_STRUCT_FMT = "<IIIIIfII"
RECORD_SIZE = 32

COLUMNS_ORDER = [
    "date", "open", "high", "low", "close", "amount", "volume", "reserved", "code"
]


@dataclass
class SyncStats:
    total_scanned: int = 0
    updated: int = 0
    up_to_date: int = 0
    created_new: int = 0
    failed: int = 0
    new_bars_count: int = 0
    min_date: Optional[str] = None
    max_date: Optional[str] = None


def get_price_divisor(code: str) -> float:
    """根据证券代码前缀获取通达信价格除数。"""
    if code.startswith(("11", "12")):
        return 10000.0  # 可转债等
    elif code.startswith(("5", "15", "9")):
        return 1000.0   # 基金、B股等
    return 100.0        # A股股票、指数等


def symbol_from_day_filename(day_path: Path) -> Tuple[str, str, str]:
    """
    从 .day 文件路径提取标准股票/指数代码。
    例如: sh600519.day -> ('600519', 'SH', '600519.SH')
          sz000001.day -> ('000001', 'SZ', '000001.SZ')
    """
    stem = day_path.stem.lower()
    market = stem[:2].upper()
    code = stem[2:]
    symbol = f"{code}.{market}"
    return code, market, symbol


def sync_gbbq(
    gbbq_source_path: Path,
    output_parquet_path: Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    解析本地通达信 GBBQ 二进制并更新 data/fq/gbbq.parquet。
    """
    if not gbbq_source_path.exists():
        logger.warning(f"GBBQ 源文件不存在: {gbbq_source_path}")
        return {"status": "skipped", "reason": "source_not_found"}

    try:
        from pytdx.reader import GbbqReader
        reader = GbbqReader()
        df_raw = reader.get_df(str(gbbq_source_path))
        if df_raw is None or df_raw.empty:
            logger.error("GBBQ 解析结果为空")
            return {"status": "failed", "reason": "empty_result"}

        col_mapping = {
            "datetime": "date",
            "hongli_panqianliutong": "cash_div",
            "peigujia_qianzongguben": "rights_price",
            "songgu_qianzongguben": "split_ratio",
            "peigu_houzongguben": "rights_ratio",
        }
        df_clean = df_raw.rename(columns=col_mapping)
        
        target_cols = [
            "code", "market", "date", "category",
            "cash_div", "split_ratio", "rights_ratio", "rights_price"
        ]
        available_cols = [c for c in target_cols if c in df_clean.columns]
        df_clean = df_clean[available_cols]

        if "code" in df_clean.columns:
            df_clean["code"] = df_clean["code"].astype(str).str.zfill(6)
        if "date" in df_clean.columns:
            df_clean["date"] = df_clean["date"].astype(int)

        df_clean = df_clean.sort_values(["code", "date"]).reset_index(drop=True)

        min_date = int(df_clean["date"].min())
        max_date = int(df_clean["date"].max())
        total_records = len(df_clean)

        if not dry_run:
            output_parquet_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = output_parquet_path.with_suffix(f".parquet.tmp.{os.getpid()}")
            df_clean.to_parquet(tmp_path, index=False, compression="snappy")
            os.replace(tmp_path, output_parquet_path)
            logger.info(
                f"GBBQ 同步成功: {total_records} 条记录, 日期跨度 {min_date} -> {max_date} "
                f"=> {output_parquet_path}"
            )

        return {
            "status": "success",
            "records": total_records,
            "min_date": min_date,
            "max_date": max_date,
        }
    except Exception as e:
        logger.error(f"GBBQ 同步异常: {e}")
        return {"status": "error", "error": str(e)}


def parse_incremental_day_file(
    day_file: Path,
    last_date_int: int = 0,
) -> List[Dict[str, Any]]:
    """
    高效流式解包 .day 文件中大于 last_date_int 的记录。
    """
    file_size = day_file.stat().st_size
    if file_size < RECORD_SIZE or file_size % RECORD_SIZE != 0:
        return []

    code, market, symbol = symbol_from_day_filename(day_file)
    divisor = get_price_divisor(code)

    records: List[Dict[str, Any]] = []
    with open(day_file, "rb") as f:
        buf = f.read()

    for r in struct.iter_unpack(DAY_STRUCT_FMT, buf):
        d_int = r[0]
        if d_int > last_date_int:
            # 基础数据格式验证
            d_str = str(d_int)
            if len(d_str) != 8:
                continue
            records.append({
                "date": pd.to_datetime(d_str, format="%Y%m%d"),
                "open": float(r[1] / divisor),
                "high": float(r[2] / divisor),
                "low": float(r[3] / divisor),
                "close": float(r[4] / divisor),
                "amount": float(r[5]),
                "volume": int(r[6]),
                "reserved": int(r[7]),
                "code": symbol,
            })
    return records


def sync_single_file(args: Tuple) -> Dict[str, Any]:
    """
    单个 .day 文件的增量同步任务函数（供多进程池调用）。
    """
    if len(args) == 4:
        day_file, data_dir, force, dry_run = args
    else:
        day_file, data_dir, force = args
        dry_run = False
    try:
        code, market, symbol = symbol_from_day_filename(day_file)
        is_idx = is_index_symbol(symbol)

        target_dir = data_dir / "lake" / "quotes" / ("index" if is_idx else "daily")
        target_path = target_dir / f"{symbol}.parquet"

        last_date_int = 0
        existing_df: Optional[pd.DataFrame] = None

        if target_path.exists() and not force:
            try:
                # 检查是否为软链接，如果是，解析真实路径
                real_target = target_path.resolve()
                existing_df = pd.read_parquet(real_target)
                if not existing_df.empty and "date" in existing_df.columns:
                    last_dt = pd.to_datetime(existing_df["date"]).max()
                    last_date_int = int(last_dt.strftime("%Y%m%d"))
            except Exception as e:
                logger.warning(f"读取现有 parquet 失败 {target_path}: {e}")
                existing_df = None

        new_records = parse_incremental_day_file(day_file, last_date_int=last_date_int)

        if not new_records:
            return {
                "symbol": symbol,
                "status": "up_to_date",
                "new_bars": 0,
            }

        new_df = pd.DataFrame(new_records)[COLUMNS_ORDER]

        if existing_df is not None and not existing_df.empty and not force:
            # 规范列与类型
            existing_df["date"] = pd.to_datetime(existing_df["date"])
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(subset=["date"], keep="last")
            combined_df = combined_df.sort_values("date").reset_index(drop=True)
        else:
            combined_df = new_df.sort_values("date").reset_index(drop=True)

        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
            tmp_target = target_path.with_suffix(f".parquet.tmp.{os.getpid()}")
            combined_df.to_parquet(tmp_target, index=False, compression="snappy")
            os.replace(tmp_target, target_path)

        return {
            "symbol": symbol,
            "status": "updated" if existing_df is not None else "created_new",
            "new_bars": len(new_records),
            "total_bars": len(combined_df),
            "min_date": str(combined_df["date"].min().date()),
            "max_date": str(combined_df["date"].max().date()),
        }

    except Exception as e:
        return {
            "symbol": day_file.name,
            "status": "failed",
            "error": str(e),
        }


def run_sync(
    vipdoc_dir: Path = DEFAULT_VIPDOC_DIR,
    data_dir: Path = DEFAULT_DATA_DIR,
    gbbq_path: Path = DEFAULT_GBBQ_PATH,
    max_workers: int = 16,
    symbols: Optional[List[str]] = None,
    force: bool = False,
    dry_run: bool = False,
) -> SyncStats:
    """执行通达信数据湖增量补齐主控流程。"""
    t0 = time.time()
    logger.info("=" * 70)
    logger.info("开始执行本地通达信 44 日离线断点更新与 GBBQ 同步")
    logger.info(f"Vipdoc 目录: {vipdoc_dir}")
    logger.info(f"目标数据湖: {data_dir}")
    logger.info(f"并行进程数: {max_workers}")
    logger.info("=" * 70)

    # 1. 同步 GBBQ
    gbbq_out = data_dir / "fq" / "gbbq.parquet"
    gbbq_res = sync_gbbq(gbbq_path, gbbq_out, dry_run=dry_run)
    logger.info(f"GBBQ 同步结论: {gbbq_res}")

    # 2. 搜集 .day 文件
    day_files: List[Path] = []
    for m in ("sh", "sz"):
        m_dir = vipdoc_dir / m / "lday"
        if m_dir.exists():
            day_files.extend(list(m_dir.glob("*.day")))

    logger.info(f"共发现 {len(day_files)} 个 .day 行情文件")

    if symbols:
        sym_set = {s.upper() for s in symbols}
        day_files = [
            f for f in day_files
            if symbol_from_day_filename(f)[2] in sym_set
            or symbol_from_day_filename(f)[0] in sym_set
        ]
        logger.info(f"根据过滤条件，保留 {len(day_files)} 个待处理文件")

    stats = SyncStats(total_scanned=len(day_files))

    tasks = [(f, data_dir, force, dry_run) for f in day_files]

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(sync_single_file, task): task for task in tasks}
        completed = 0
        total = len(futures)

        for fut in as_completed(futures):
            completed += 1
            res = fut.result()
            st = res.get("status")

            if st == "updated":
                stats.updated += 1
                stats.new_bars_count += res.get("new_bars", 0)
                stats.max_date = res.get("max_date")
            elif st == "created_new":
                stats.created_new += 1
                stats.new_bars_count += res.get("new_bars", 0)
            elif st == "up_to_date":
                stats.up_to_date += 1
            else:
                stats.failed += 1
                logger.error(f"处理失败 {res.get('symbol')}: {res.get('error')}")

            if completed % 1000 == 0 or completed == total:
                logger.info(
                    f"进度: {completed}/{total} ({completed/total*100:.1f}%) | "
                    f"更新: {stats.updated} | 最新: {stats.up_to_date} | "
                    f"新建: {stats.created_new} | 失败: {stats.failed}"
                )

    elapsed = time.time() - t0
    logger.info("=" * 70)
    logger.info("离线断点更新执行完成:")
    logger.info(f"耗时: {elapsed:.2f} 秒")
    logger.info(f"扫描文件数: {stats.total_scanned}")
    logger.info(f"增量更新文件数: {stats.updated}")
    logger.info(f"已是最新无需更新: {stats.up_to_date}")
    logger.info(f"新建文件数: {stats.created_new}")
    logger.info(f"失败文件数: {stats.failed}")
    logger.info(f"新增 Bar 记录总数: {stats.new_bars_count:,}")
    logger.info("=" * 70)

    return stats


def main():
    parser = argparse.ArgumentParser(description="UniQuant 本地通达信 44 日离线断点同步工具")
    parser.add_argument("--vipdoc-dir", type=Path, default=DEFAULT_VIPDOC_DIR, help="通达信 vipdoc 目录路径")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="UniQuant 数据目录路径")
    parser.add_argument("--gbbq-path", type=Path, default=DEFAULT_GBBQ_PATH, help="通达信 gbbq 文件路径")
    parser.add_argument("--max-workers", type=int, default=16, help="并行工作进程数")
    parser.add_argument("--symbols", type=str, default=None, help="逗号分隔的股票/指数代码列表")
    parser.add_argument("--force", action="store_true", help="强制全量重新构建")
    parser.add_argument("--dry-run", action="store_true", help="演练模式，不写磁盘")
    args = parser.parse_args()

    sym_list = [s.strip() for s in args.symbols.split(",")] if args.symbols else None

    run_sync(
        vipdoc_dir=args.vipdoc_dir,
        data_dir=args.data_dir,
        gbbq_path=args.gbbq_path,
        max_workers=args.max_workers,
        symbols=sym_list,
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
