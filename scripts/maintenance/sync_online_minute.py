#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UniQuant 在线通达信分钟线批量增量同步脚本 (5mins / 1mins 湖)。

功能:
1. 增量同步 5 分钟 (5min/5mins) 与 1 分钟 (1min/1mins) K 线至数据湖;
2. 严格执行 8 列 Parquet 契约与 dtypes 锁定:
   [datetime, open, high, low, close, volume, amount, code]
3. 遵循在线深度语义 (5min 约 10.5 个月/10,224 根, 1min 约数日), 支持断点增量;
4. 原子写入 (.tmp.{pid}_{tid} + os.replace), 杜绝损坏;
5. 记录逐标的增量指纹与断点状态 (data/.online_minute_fingerprints.json);
6. 多线程并发与分批持久化, 产出对账存证 JSON。

用法:
    python scripts/maintenance/sync_online_minute.py --symbols 000300.SH,600519.SH --frequency 5min
    python scripts/maintenance/sync_online_minute.py --frequency 5min --workers 4
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import threading
from typing import Any, Dict, List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.data.sources.tdxdata_online import TdxDataOnlineSource  # noqa: E402
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("maintenance.sync_online_minute")

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_LAKE_QUOTES = DEFAULT_DATA_DIR / "lake" / "quotes"
DEFAULT_FINGERPRINT_PATH = DEFAULT_DATA_DIR / ".online_minute_fingerprints.json"

FREQUENCY_DIR_MAP = {
    "1min": "1mins",
    "1mins": "1mins",
    "5min": "5mins",
    "5mins": "5mins",
    "15min": "15mins",
    "30min": "30mins",
    "60min": "60mins",
}

MINUTE_CONTRACT_COLUMNS = [
    "datetime", "open", "high", "low", "close", "volume", "amount", "code"
]


@dataclass
class MinuteSyncStats:
    total_scanned: int = 0
    updated: int = 0
    up_to_date: int = 0
    created_new: int = 0
    failed: int = 0
    new_bars: int = 0
    frequency: str = "5min"
    errors: Dict[str, str] = field(default_factory=dict)
    symbol_details: Dict[str, Any] = field(default_factory=dict)


def load_fingerprints(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取指纹文件 {path} 失败: {e}, 初始化为空")
    return {"version": 1, "last_updated": None, "symbols": {}}


def save_fingerprints(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f".json.tmp.{os.getpid()}")
    try:
        data["last_updated"] = datetime.now().isoformat()
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        logger.error(f"保存指纹文件失败: {e}")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def discover_minute_symbols(lake_quotes: Path, freq_subdir: str) -> List[str]:
    """发现既有分钟湖中的标的，或从日线/指数湖发现所有标的代码。"""
    minute_dir = lake_quotes / freq_subdir
    symbols = []
    if minute_dir.exists():
        symbols = [p.stem for p in sorted(minute_dir.glob("*.parquet"))]
    if not symbols:
        # 若分钟湖为空，从日线湖种子发现标的
        daily_dir = lake_quotes / "daily"
        idx_dir = lake_quotes / "index"
        if idx_dir.exists():
            symbols.extend([p.stem for p in sorted(idx_dir.glob("*.parquet"))])
        if daily_dir.exists():
            symbols.extend([p.stem for p in sorted(daily_dir.glob("*.parquet"))])
    return symbols


def sync_single_minute_symbol(
    symbol: str,
    lake_quotes: Path,
    frequency: str,
    source: TdxDataOnlineSource,
    start_dt: Optional[str] = None,
    end_dt: Optional[str] = None,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """单标的分钟增量拉取与合并写入。"""
    freq_dir_name = FREQUENCY_DIR_MAP.get(frequency.lower(), f"{frequency}s")
    target_dir = lake_quotes / freq_dir_name
    target_path = target_dir / f"{symbol}.parquet"

    existing_df: Optional[pd.DataFrame] = None
    last_dt: Optional[pd.Timestamp] = None

    if target_path.exists() and not force:
        try:
            existing_df = pd.read_parquet(target_path)
            if not existing_df.empty and "datetime" in existing_df.columns:
                existing_df["datetime"] = pd.to_datetime(existing_df["datetime"])
                last_dt = existing_df["datetime"].max()
        except Exception as e:
            logger.warning(f"{symbol} 读取既有分钟 parquet 失败: {e}")
            existing_df = None

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target_end = end_dt or now_str

    if last_dt is not None and not force:
        target_start = (last_dt + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        if target_start > target_end:
            return {
                "symbol": symbol,
                "status": "up_to_date",
                "new_bars": 0,
                "total_bars": len(existing_df) if existing_df is not None else 0,
                "last_datetime": last_dt.strftime("%Y-%m-%d %H:%M:%S"),
            }
    else:
        target_start = start_dt

    # 在线拉取
    try:
        new_df = source.fetch_minute(
            symbol=symbol,
            frequency=frequency,
            start_dt=target_start,
            end_dt=target_end,
        )
    except Exception as e:
        logger.error(f"{symbol} 在线分钟拉取异常: {e}")
        return {"symbol": symbol, "status": "error", "error": str(e), "new_bars": 0}

    if new_df is None or new_df.empty:
        return {
            "symbol": symbol,
            "status": "up_to_date",
            "new_bars": 0,
            "total_bars": len(existing_df) if existing_df is not None else 0,
            "last_datetime": last_dt.strftime("%Y-%m-%d %H:%M:%S") if last_dt is not None else None,
        }

    new_df = new_df.copy()
    new_df["datetime"] = pd.to_datetime(new_df["datetime"])
    if "code" not in new_df.columns:
        new_df["code"] = symbol

    # 合并既有数据
    if existing_df is not None and not existing_df.empty and not force:
        for col in MINUTE_CONTRACT_COLUMNS:
            if col not in existing_df.columns:
                existing_df[col] = 0.0
        combined = pd.concat([existing_df[MINUTE_CONTRACT_COLUMNS], new_df[MINUTE_CONTRACT_COLUMNS]], ignore_index=True)
        combined = combined.drop_duplicates(subset=["datetime"], keep="last")
        combined = combined.sort_values("datetime").reset_index(drop=True)
    else:
        combined = new_df[MINUTE_CONTRACT_COLUMNS].drop_duplicates(subset=["datetime"], keep="last")
        combined = combined.sort_values("datetime").reset_index(drop=True)

    # 锁定数据类型
    combined["datetime"] = pd.to_datetime(combined["datetime"])
    combined["open"] = combined["open"].astype("float64")
    combined["high"] = combined["high"].astype("float64")
    combined["low"] = combined["low"].astype("float64")
    combined["close"] = combined["close"].astype("float64")
    combined["volume"] = combined["volume"].astype("float64")
    combined["amount"] = combined["amount"].astype("float64")
    combined["code"] = combined["code"].astype("str")

    added_bars = len(new_df)
    total_bars = len(combined)
    max_dt_str = combined["datetime"].max().strftime("%Y-%m-%d %H:%M:%S")

    # 原子写入
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        tid = threading.get_ident()
        tmp_target = target_path.with_suffix(f".parquet.tmp.{os.getpid()}_{tid}")
        try:
            combined.to_parquet(tmp_target, index=False, compression="snappy")
            os.replace(tmp_target, target_path)
        except Exception as e:
            if tmp_target.exists():
                try:
                    tmp_target.unlink()
                except OSError:
                    pass
            logger.error(f"{symbol} 写入分钟 parquet 失败: {e}")
            return {"symbol": symbol, "status": "write_error", "error": str(e), "new_bars": 0}

    return {
        "symbol": symbol,
        "status": "updated" if existing_df is not None else "created_new",
        "new_bars": added_bars,
        "total_bars": total_bars,
        "last_datetime": max_dt_str,
    }


def run_minute_sync(
    lake_quotes: Path,
    symbols: Optional[List[str]] = None,
    frequency: str = "5min",
    start_dt: Optional[str] = None,
    end_dt: Optional[str] = None,
    workers: int = 4,
    batch_size: int = 50,
    force: bool = False,
    dry_run: bool = False,
    fingerprint_path: Optional[Path] = None,
) -> MinuteSyncStats:
    """主分钟同步循环。"""
    freq_dir = FREQUENCY_DIR_MAP.get(frequency.lower(), f"{frequency}s")
    fp_path = fingerprint_path or DEFAULT_FINGERPRINT_PATH
    fingerprints = load_fingerprints(fp_path)

    if symbols:
        target_symbols = [s.strip() for s in symbols if s.strip()]
    else:
        target_symbols = discover_minute_symbols(lake_quotes, freq_dir)

    stats = MinuteSyncStats(
        total_scanned=len(target_symbols),
        frequency=frequency,
    )
    logger.info(
        f"开始分钟同步 ({frequency}): 待处理标的 {len(target_symbols)} 只, "
        f"输出目录 {freq_dir}, 并发 workers={workers}"
    )

    thread_local = threading.local()

    def get_thread_source() -> TdxDataOnlineSource:
        if not hasattr(thread_local, "source"):
            thread_local.source = TdxDataOnlineSource()
        return thread_local.source

    def worker_task(sym: str) -> Dict[str, Any]:
        src = get_thread_source()
        return sync_single_minute_symbol(
            symbol=sym,
            lake_quotes=lake_quotes,
            frequency=frequency,
            source=src,
            start_dt=start_dt,
            end_dt=end_dt,
            force=force,
            dry_run=dry_run,
        )

    processed_count = 0
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_sym = {executor.submit(worker_task, sym): sym for sym in target_symbols}
            for future in as_completed(future_to_sym):
                sym = future_to_sym[future]
                processed_count += 1
                try:
                    res = future.result()
                    _record_minute_result(res, stats, fingerprints, frequency)
                except Exception as e:
                    stats.failed += 1
                    stats.errors[sym] = str(e)
                    logger.error(f"{sym} 执行异常: {e}")

                if processed_count % batch_size == 0 and not dry_run:
                    save_fingerprints(fp_path, fingerprints)
                    logger.info(
                        f"分钟同步进度: {processed_count}/{len(target_symbols)} | "
                        f"更新: {stats.updated}, 最新: {stats.up_to_date}, 失败: {stats.failed}"
                    )
    else:
        for sym in target_symbols:
            processed_count += 1
            try:
                src = get_thread_source()
                res = sync_single_minute_symbol(
                    symbol=sym,
                    lake_quotes=lake_quotes,
                    frequency=frequency,
                    source=src,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    force=force,
                    dry_run=dry_run,
                )
                _record_minute_result(res, stats, fingerprints, frequency)
            except Exception as e:
                stats.failed += 1
                stats.errors[sym] = str(e)
                logger.error(f"{sym} 执行异常: {e}")

            if processed_count % batch_size == 0 and not dry_run:
                save_fingerprints(fp_path, fingerprints)
                logger.info(
                    f"分钟同步进度: {processed_count}/{len(target_symbols)} | "
                    f"更新: {stats.updated}, 最新: {stats.up_to_date}, 失败: {stats.failed}"
                )

    if not dry_run:
        save_fingerprints(fp_path, fingerprints)

    logger.info(
        f"分钟同步完成 ({frequency}): 总计={stats.total_scanned}, 更新={stats.updated}, "
        f"新建={stats.created_new}, 保持最新={stats.up_to_date}, 失败={stats.failed}, "
        f"新增K线={stats.new_bars}"
    )
    return stats


def _record_minute_result(
    res: Dict[str, Any],
    stats: MinuteSyncStats,
    fingerprints: Dict[str, Any],
    frequency: str,
) -> None:
    sym = res["symbol"]
    st = res.get("status")
    stats.symbol_details[sym] = res
    if st == "updated":
        stats.updated += 1
        stats.new_bars += res.get("new_bars", 0)
    elif st == "created_new":
        stats.created_new += 1
        stats.new_bars += res.get("new_bars", 0)
    elif st == "up_to_date":
        stats.up_to_date += 1
    else:
        stats.failed += 1
        if "error" in res:
            stats.errors[sym] = res["error"]

    if st in ("updated", "created_new", "up_to_date"):
        freq_key = frequency.lower()
        sym_fps = fingerprints["symbols"].setdefault(sym, {})
        sym_fps[freq_key] = {
            "last_datetime": res.get("last_datetime"),
            "total_bars": res.get("total_bars"),
            "updated_at": datetime.now().isoformat(),
            "status": st,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="UniQuant 在线通达信分钟线批量增量同步")
    parser.add_argument("--lake-root", type=str, default=str(DEFAULT_LAKE_QUOTES), help="湖 quotes 根目录")
    parser.add_argument("--symbols", type=str, default=None, help="标的代码列表 (逗号分隔)")
    parser.add_argument("--frequency", type=str, default="5min", help="分钟频率 (5min / 1min 等, 默认 5min)")
    parser.add_argument("--start-dt", type=str, default=None, help="起始时间 (YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--end-dt", type=str, default=None, help="截止时间 (YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--workers", type=int, default=4, help="并发线程数 (默认 4)")
    parser.add_argument("--batch-size", type=int, default=50, help="指纹分批暂存步长 (默认 50)")
    parser.add_argument("--force", action="store_true", help="强制从 start-dt 重写")
    parser.add_argument("--dry-run", action="store_true", help="空跑演练 (不写真实文件)")
    parser.add_argument("--summary-json", type=str, default=None, help="对账存证摘要 JSON 输出路径")
    args = parser.parse_args()

    lake_quotes = Path(args.lake_root)
    sym_list = [s.strip() for s in args.symbols.split(",")] if args.symbols else None

    stats = run_minute_sync(
        lake_quotes=lake_quotes,
        symbols=sym_list,
        frequency=args.frequency,
        start_dt=args.start_dt,
        end_dt=args.end_dt,
        workers=args.workers,
        batch_size=args.batch_size,
        force=args.force,
        dry_run=args.dry_run,
    )

    if args.summary_json:
        out_path = Path(args.summary_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        summary_payload = {
            "timestamp": datetime.now().isoformat(),
            "stats": asdict(stats),
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary_payload, f, ensure_ascii=False, indent=2)
        logger.info(f"对账存证摘要已输出至 {out_path}")

    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
