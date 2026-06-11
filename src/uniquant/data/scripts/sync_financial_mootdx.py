#!/usr/bin/env python3
"""
mootdx 财务数据同步脚本

使用 mootdx FinancialReader 解析本地 TDX 财务数据并导入到 Parquet 数据湖。
支持: gpcw*.dat 文件解析、增量更新、批量同步
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from ...shared.time_provider import get_time_provider
from typing import Dict, List, Optional

import pandas as pd
from uniquant.shared.logger_factory import get_logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
FINANCIAL_DIR = DATA_DIR / "lake" / "financial"
PROGRESS_FILE = DATA_DIR / ".sync_financial_mootdx_progress.json"
LOG_FILE = DATA_DIR / "sync_financial_mootdx.log"

DATA_DIR.mkdir(parents=True, exist_ok=True)
FINANCIAL_DIR.mkdir(parents=True, exist_ok=True)

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


def normalize_code(code: str) -> Optional[str]:
    if pd.isna(code):
        return None
    code = str(code).strip()
    if not code:
        return None
    digits = "".join(ch for ch in code if ch.isdigit()).zfill(6)
    suffix = get_market_suffix(digits)
    return f"{digits}.{suffix}" if suffix else None


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            logger.exception("加载进度文件失败，返回空字典")
            pass
    return {}


def save_progress(progress: dict):
    try:
        progress["last_update"] = get_time_provider().now().isoformat()
        with open(PROGRESS_FILE, "w") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存进度失败: {e}")


def sync_financial(
    tdx_dir: str,
    output_dir: str,
    limit: int = 0,
    symbols: Optional[List[str]] = None,
):
    from mootdx.financial.financial import FinancialReader

    tdx_path = Path(tdx_dir)
    cw_dir = tdx_path / "vipdoc" / "cw"
    out_dir = Path(output_dir) / "lake" / "financial"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not cw_dir.exists():
        logger.error(f"财务数据目录不存在: {cw_dir}")
        return 0, 0

    gpcw_files = sorted(cw_dir.glob("gpcw*.dat"))
    if limit > 0:
        gpcw_files = gpcw_files[:limit]

    if not gpcw_files:
        logger.warning(f"未找到财务数据文件: {cw_dir}")
        return 0, 0

    logger.info(f"找到 {len(gpcw_files)} 个财务数据文件")

    progress = load_progress()
    completed_files = set(progress.get("completed_files", []))

    memory_store: Dict[str, List[pd.DataFrame]] = {}
    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, filepath in enumerate(gpcw_files, 1):
        if filepath.name in completed_files:
            skip_count += 1
            continue

        try:
            df = FinancialReader.to_data(str(filepath))
            if df is None or df.empty:
                logger.warning(f"{filepath.name} 无数据")
                fail_count += 1
                continue

            if df.index.name == "code" or "code" not in df.columns:
                df = df.reset_index()

            if "code" not in df.columns:
                logger.warning(f"{filepath.name} 缺少 code 列")
                fail_count += 1
                continue

            for code_raw in df["code"].unique():
                normalized = normalize_code(code_raw)
                if not normalized:
                    continue
                if symbols and normalized not in symbols:
                    continue

                stock_df = df[df["code"] == code_raw].copy()
                stock_df["code"] = normalized
                if "report_date" in stock_df.columns:
                    stock_df["report_date"] = pd.to_datetime(stock_df["report_date"], errors="coerce")

                memory_store.setdefault(normalized, []).append(stock_df)

            completed_files.add(filepath.name)
            success_count += 1

            if i % 10 == 0:
                logger.info(f"解析进度: {i}/{len(gpcw_files)}")

        except Exception as e:
            logger.error(f"{filepath.name} 解析失败: {e}")
            fail_count += 1

    logger.info(f"解析完成: 成功 {success_count}, 跳过 {skip_count}, 失败 {fail_count}")
    logger.info(f"写入 {len(memory_store)} 只股票的财务数据...")

    write_success = 0
    write_fail = 0

    for symbol, dfs in memory_store.items():
        try:
            merged = pd.concat(dfs, ignore_index=True)
            if "code" in merged.columns and "report_date" in merged.columns:
                merged = merged.drop_duplicates(subset=["code", "report_date"], keep="last")
                merged = merged.sort_values("report_date")

            output_file = out_dir / f"{symbol}.parquet"
            if output_file.exists():
                existing = pd.read_parquet(output_file)
                merged = pd.concat([existing, merged], ignore_index=True)
                if "code" in merged.columns and "report_date" in merged.columns:
                    merged = merged.drop_duplicates(subset=["code", "report_date"], keep="last")
                    merged = merged.sort_values("report_date")

            merged.to_parquet(output_file, compression="snappy", index=False)
            write_success += 1
        except Exception as e:
            logger.error(f"写入 {symbol} 失败: {e}")
            write_fail += 1

    progress["completed_files"] = list(completed_files)
    save_progress(progress)

    logger.info(f"写入完成: 成功 {write_success}, 失败 {write_fail}")
    return success_count, fail_count


def main():
    parser = argparse.ArgumentParser(description="mootdx 财务数据同步")
    parser.add_argument("--tdx-dir", required=True, help="TDX 数据目录")
    parser.add_argument("--output-dir", default=str(DATA_DIR), help="输出目录")
    parser.add_argument("--limit", type=int, default=0, help="限制处理文件数量")
    parser.add_argument("--symbols", nargs="+", help="仅同步指定股票代码")
    args = parser.parse_args()

    sync_financial(args.tdx_dir, args.output_dir, args.limit, args.symbols)


if __name__ == "__main__":
    main()
