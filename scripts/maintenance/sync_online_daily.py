#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UniQuant 在线通达信日线批量增量同步脚本 (免 Wine 云端替代)。

功能:
1. 扫描数据湖日线与指数目录 (data/lake/quotes/daily 与 index);
2. 提取现有 Parquet 最大日期, 增量拉取最新数据 (tdxdata 新协议);
3. 严格执行 9 列 Parquet 契约与 dtypes 锁定:
   [date, open, high, low, close, amount, volume, reserved, code]
4. 原子写入 (.tmp.{pid}_{tid} + os.replace), 杜绝半写损坏;
5. 记录逐标的增量指纹与断点状态 (data/.online_daily_fingerprints.json);
6. 多线程并发与分批持久化, 产出对账存证 JSON。

用法:
    python scripts/maintenance/sync_online_daily.py --symbols 000300.SH,600519.SH
    python scripts/maintenance/sync_online_daily.py --index-only
    python scripts/maintenance/sync_online_daily.py --stock-only --workers 8
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import struct
import sys
import threading
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uniquant.data.lake.storage_manager import is_index_symbol  # noqa: E402
from uniquant.data.sources.tdxdata_online import TdxDataOnlineSource  # noqa: E402
from uniquant.shared.logger_factory import get_logger  # noqa: E402

logger = get_logger("maintenance.sync_online_daily")

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_LAKE_QUOTES = DEFAULT_DATA_DIR / "lake" / "quotes"
DEFAULT_FINGERPRINT_PATH = DEFAULT_DATA_DIR / ".online_daily_fingerprints.json"
DEFAULT_LOCAL_VIPDOC = Path.home() / ".local/share/tdxcfv/drive_c/tc/vipdoc"

DAILY_CONTRACT_COLUMNS = [
    "date", "open", "high", "low", "close", "amount", "volume", "reserved", "code"
]


@dataclass
class SyncStats:
    total_scanned: int = 0
    updated: int = 0
    up_to_date: int = 0
    created_new: int = 0
    failed: int = 0
    new_bars: int = 0
    verified_count: int = 0
    verification_skipped: int = 0
    errors: Dict[str, str] = field(default_factory=dict)
    symbol_details: Dict[str, Any] = field(default_factory=dict)


def parse_local_day_tail(day_path: Path, min_date_int: int = 19900101) -> pd.DataFrame:
    """快速读取本地 .day 结尾记录 (每次仅读末尾 30 根以保证性能)。"""
    if not day_path.exists():
        return pd.DataFrame()
    s = day_path.stat().st_size
    if s < 32:
        return pd.DataFrame()
    offset = max(0, s - 32 * 30)
    with open(day_path, "rb") as f:
        f.seek(offset)
        buf = f.read()
    records = []
    stem = day_path.stem.lower()
    code = stem[2:]
    divisor = 10000.0 if code.startswith(("11", "12")) else (1000.0 if code.startswith(("5", "15", "9")) else 100.0)
    for r in struct.iter_unpack("<IIIIIfII", buf):
        d_int = r[0]
        if d_int >= min_date_int:
            records.append({
                "date": pd.to_datetime(str(d_int), format="%Y%m%d"),
                "open": float(r[1] / divisor),
                "high": float(r[2] / divisor),
                "low": float(r[3] / divisor),
                "close": float(r[4] / divisor),
                "amount": float(r[5]),
                "volume": int(r[6]),
            })
    return pd.DataFrame(records)


def cross_validate_new_bars(
    symbol: str,
    new_df: pd.DataFrame,
    vipdoc_dir: Path,
) -> Tuple[bool, Optional[str]]:
    """比对在线增量拉取的 K 线与本地 .day 记录，确保数据一致。"""
    if new_df.empty or not vipdoc_dir.exists():
        return True, "SKIPPED_NO_VIPDOC"
    code, ext = symbol.split(".")
    market = ext.lower()
    day_file = vipdoc_dir / market / "lday" / f"{market}{code}.day"
    if not day_file.exists():
        return True, "SKIPPED_NO_LOCAL_FILE"

    min_date_int = int(new_df["date"].min().strftime("%Y%m%d"))
    local_df = parse_local_day_tail(day_file, min_date_int=min_date_int)
    if local_df.empty:
        return True, "LOCAL_NO_NEW_BARS"

    merged = new_df.merge(local_df, on="date", suffixes=("_on", "_loc"))
    if merged.empty:
        return False, "NO_DATE_OVERLAP"

    is_star = symbol.startswith("68")
    is_idx = is_index_symbol(symbol)
    price_tol = 0.20 if is_star else (0.05 if is_idx else 0.01)

    for _, row in merged.iterrows():
        if abs(row["close_on"] - row["close_loc"]) > price_tol:
            return False, f"CLOSE_MISMATCH on {row['date'].strftime('%Y-%m-%d')}"
        if abs(row["open_on"] - row["open_loc"]) > price_tol:
            return False, f"OPEN_MISMATCH on {row['date'].strftime('%Y-%m-%d')}"
        if abs(row["high_on"] - row["high_loc"]) > price_tol:
            return False, f"HIGH_MISMATCH on {row['date'].strftime('%Y-%m-%d')}"
        if abs(row["low_on"] - row["low_loc"]) > price_tol:
            return False, f"LOW_MISMATCH on {row['date'].strftime('%Y-%m-%d')}"
        if abs(row["volume_on"] - row["volume_loc"]) > 100:
            return False, f"VOLUME_MISMATCH on {row['date'].strftime('%Y-%m-%d')}"

    return True, f"VERIFIED_{len(merged)}_BARS"


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


def discover_symbols(
    lake_quotes: Path,
    include_stock: bool = True,
    include_index: bool = True,
) -> List[Tuple[str, bool]]:
    """扫描现有湖分片，返回 [(symbol, is_index), ...]。"""
    symbols: List[Tuple[str, bool]] = []
    if include_index:
        idx_dir = lake_quotes / "index"
        if idx_dir.exists():
            for p in sorted(idx_dir.glob("*.parquet")):
                symbols.append((p.stem, True))
    if include_stock:
        daily_dir = lake_quotes / "daily"
        if daily_dir.exists():
            for p in sorted(daily_dir.glob("*.parquet")):
                symbols.append((p.stem, False))
    return symbols


def sync_single_symbol(
    symbol: str,
    lake_quotes: Path,
    source: TdxDataOnlineSource,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    force: bool = False,
    dry_run: bool = False,
    vipdoc_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """单标的增量拉取与合并写入。"""
    is_idx = is_index_symbol(symbol)
    target_dir = lake_quotes / ("index" if is_idx else "daily")
    target_path = target_dir / f"{symbol}.parquet"

    existing_df: Optional[pd.DataFrame] = None
    last_dt: Optional[pd.Timestamp] = None

    if target_path.exists() and not force:
        try:
            existing_df = pd.read_parquet(target_path)
            if not existing_df.empty and "date" in existing_df.columns:
                existing_df["date"] = pd.to_datetime(existing_df["date"])
                last_dt = existing_df["date"].max()
        except Exception as e:
            logger.warning(f"{symbol} 读取既有 parquet 失败: {e}")
            existing_df = None

    today_str = (datetime.now()).strftime("%Y-%m-%d")
    target_end = end_date or today_str

    if last_dt is not None and not force:
        target_start = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        if target_start > target_end:
            return {
                "symbol": symbol,
                "status": "up_to_date",
                "new_bars": 0,
                "total_bars": len(existing_df) if existing_df is not None else 0,
                "last_date": last_dt.strftime("%Y-%m-%d"),
            }
    else:
        target_start = start_date or "1990-01-01"

    # 调用在线源拉取
    try:
        new_df = source.fetch_daily(symbol, start_date=target_start, end_date=target_end)
    except Exception as e:
        logger.error(f"{symbol} 在线拉取异常: {e}")
        return {"symbol": symbol, "status": "error", "error": str(e), "new_bars": 0}

    if new_df is None or new_df.empty:
        return {
            "symbol": symbol,
            "status": "up_to_date",
            "new_bars": 0,
            "total_bars": len(existing_df) if existing_df is not None else 0,
            "last_date": last_dt.strftime("%Y-%m-%d") if last_dt is not None else None,
        }

    # 格式化新数据，补齐 9 列
    new_df = new_df.copy()
    new_df["date"] = pd.to_datetime(new_df["date"])
    if "reserved" not in new_df.columns:
        new_df["reserved"] = 0
    if "code" not in new_df.columns:
        new_df["code"] = symbol

    # 本地 TDX 交叉校验 (防伪防错)
    ver_status = None
    if vipdoc_dir is not None:
        ok, reason = cross_validate_new_bars(symbol, new_df, vipdoc_dir)
        if not ok:
            logger.error(f"{symbol} 本地 TDX 交叉校验失败: {reason}")
            return {"symbol": symbol, "status": "validation_failed", "error": reason, "new_bars": 0}
        ver_status = reason

    # 合并既有数据
    if existing_df is not None and not existing_df.empty and not force:
        # 确保列齐全
        for col in DAILY_CONTRACT_COLUMNS:
            if col not in existing_df.columns:
                existing_df[col] = 0 if col in ("volume", "reserved") else 0.0
        combined = pd.concat([existing_df[DAILY_CONTRACT_COLUMNS], new_df[DAILY_CONTRACT_COLUMNS]], ignore_index=True)
        combined = combined.drop_duplicates(subset=["date"], keep="last")
        combined = combined.sort_values("date").reset_index(drop=True)
    else:
        combined = new_df[DAILY_CONTRACT_COLUMNS].drop_duplicates(subset=["date"], keep="last")
        combined = combined.sort_values("date").reset_index(drop=True)

    # 锁定物理 dtypes
    combined["date"] = pd.to_datetime(combined["date"])
    combined["open"] = combined["open"].astype("float64")
    combined["high"] = combined["high"].astype("float64")
    combined["low"] = combined["low"].astype("float64")
    combined["close"] = combined["close"].astype("float64")
    combined["amount"] = combined["amount"].astype("float64")
    combined["volume"] = combined["volume"].astype("int64")
    combined["reserved"] = combined["reserved"].astype("int64")
    combined["code"] = combined["code"].astype("str")

    added_bars = len(new_df)
    total_bars = len(combined)
    max_date_str = combined["date"].max().strftime("%Y-%m-%d")

    # 原子写
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
            logger.error(f"{symbol} 写入 parquet 失败: {e}")
            return {"symbol": symbol, "status": "write_error", "error": str(e), "new_bars": 0}

    return {
        "symbol": symbol,
        "status": "updated" if existing_df is not None else "created_new",
        "new_bars": added_bars,
        "total_bars": total_bars,
        "last_date": max_date_str,
        "verified": ver_status,
    }


def run_sync(
    lake_quotes: Path,
    symbols: Optional[List[str]] = None,
    include_stock: bool = True,
    include_index: bool = True,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    workers: int = 4,
    batch_size: int = 50,
    force: bool = False,
    dry_run: bool = False,
    fingerprint_path: Optional[Path] = None,
    vipdoc_dir: Optional[Path] = None,
) -> SyncStats:
    """主同步循环，支持线程池并发与分批更新指纹。"""
    fp_path = fingerprint_path or DEFAULT_FINGERPRINT_PATH
    fingerprints = load_fingerprints(fp_path)

    if symbols:
        target_symbols = [(s.strip(), is_index_symbol(s.strip())) for s in symbols if s.strip()]
    else:
        target_symbols = discover_symbols(
            lake_quotes, include_stock=include_stock, include_index=include_index
        )

    stats = SyncStats(total_scanned=len(target_symbols))
    logger.info(f"开始日线同步: 待处理标的 {len(target_symbols)} 只, 并发 workers={workers}")

    # 线程局部 source 工厂以保证独立 TCP 套接字
    thread_local = threading.local()

    def get_thread_source() -> TdxDataOnlineSource:
        if not hasattr(thread_local, "source"):
            thread_local.source = TdxDataOnlineSource()
        return thread_local.source

    def worker_task(sym_item: Tuple[str, bool]) -> Dict[str, Any]:
        sym, _ = sym_item
        src = get_thread_source()
        return sync_single_symbol(
            symbol=sym,
            lake_quotes=lake_quotes,
            source=src,
            start_date=start_date,
            end_date=end_date,
            force=force,
            dry_run=dry_run,
            vipdoc_dir=vipdoc_dir,
        )

    processed_count = 0
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_sym = {executor.submit(worker_task, sym): sym[0] for sym in target_symbols}
            for future in as_completed(future_to_sym):
                sym = future_to_sym[future]
                processed_count += 1
                try:
                    res = future.result()
                    _record_result(res, stats, fingerprints)
                except Exception as e:
                    stats.failed += 1
                    stats.errors[sym] = str(e)
                    logger.error(f"{sym} 执行异常: {e}")

                if processed_count % batch_size == 0 and not dry_run:
                    save_fingerprints(fp_path, fingerprints)
                    logger.info(f"同步进度: {processed_count}/{len(target_symbols)} | 更新: {stats.updated}, 最新: {stats.up_to_date}, 失败: {stats.failed}")
    else:
        for sym_item in target_symbols:
            processed_count += 1
            sym, _ = sym_item
            try:
                src = get_thread_source()
                res = sync_single_symbol(
                    symbol=sym,
                    lake_quotes=lake_quotes,
                    source=src,
                    start_date=start_date,
                    end_date=end_date,
                    force=force,
                    dry_run=dry_run,
                    vipdoc_dir=vipdoc_dir,
                )
                _record_result(res, stats, fingerprints)
            except Exception as e:
                stats.failed += 1
                stats.errors[sym] = str(e)
                logger.error(f"{sym} 执行异常: {e}")

            if processed_count % batch_size == 0 and not dry_run:
                save_fingerprints(fp_path, fingerprints)
                logger.info(f"同步进度: {processed_count}/{len(target_symbols)} | 更新: {stats.updated}, 最新: {stats.up_to_date}, 失败: {stats.failed}")

    if not dry_run:
        save_fingerprints(fp_path, fingerprints)

    logger.info(
        f"日线同步完成: 总计={stats.total_scanned}, 更新={stats.updated}, "
        f"新建={stats.created_new}, 保持最新={stats.up_to_date}, 失败={stats.failed}, "
        f"校验一致={stats.verified_count}, 校验跳过={stats.verification_skipped}, "
        f"新增K线={stats.new_bars}"
    )
    return stats


def _record_result(res: Dict[str, Any], stats: SyncStats, fingerprints: Dict[str, Any]) -> None:
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

    ver = res.get("verified")
    if ver:
        if "VERIFIED" in str(ver):
            stats.verified_count += 1
        else:
            stats.verification_skipped += 1

    if st in ("updated", "created_new", "up_to_date"):
        fingerprints["symbols"][sym] = {
            "last_date": res.get("last_date"),
            "total_bars": res.get("total_bars"),
            "updated_at": datetime.now().isoformat(),
            "status": st,
            "verified": ver,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="UniQuant 在线通达信日线批量增量同步")
    parser.add_argument("--lake-root", type=str, default=str(DEFAULT_LAKE_QUOTES), help="湖 quotes 根目录")
    parser.add_argument("--symbols", type=str, default=None, help="标的代码列表 (逗号分隔)")
    parser.add_argument("--stock-only", action="store_true", help="仅同步个股")
    parser.add_argument("--index-only", action="store_true", help="仅同步指数")
    parser.add_argument("--start-date", type=str, default=None, help="起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default=None, help="截止日期 (YYYY-MM-DD)")
    parser.add_argument("--workers", type=int, default=4, help="并发线程数 (默认 4)")
    parser.add_argument("--batch-size", type=int, default=50, help="指纹分批暂存步长 (默认 50)")
    parser.add_argument("--force", action="store_true", help="强制从 start-date 重写")
    parser.add_argument("--dry-run", action="store_true", help="空跑演练 (不写真实文件)")
    parser.add_argument("--verify-local", action="store_true", help="启用与本地 TDX .day 盘后数据交叉校验")
    parser.add_argument("--local-vipdoc", type=str, default=str(DEFAULT_LOCAL_VIPDOC), help="本地 TDX vipdoc 路径")
    parser.add_argument("--summary-json", type=str, default=None, help="对账存证摘要 JSON 输出路径")
    args = parser.parse_args()

    lake_quotes = Path(args.lake_root)
    sym_list = [s.strip() for s in args.symbols.split(",")] if args.symbols else None

    inc_stock = not args.index_only
    inc_index = not args.stock_only

    vipdoc_path = Path(args.local_vipdoc) if args.verify_local else None

    stats = run_sync(
        lake_quotes=lake_quotes,
        symbols=sym_list,
        include_stock=inc_stock,
        include_index=inc_index,
        start_date=args.start_date,
        end_date=args.end_date,
        workers=args.workers,
        batch_size=args.batch_size,
        force=args.force,
        dry_run=args.dry_run,
        vipdoc_dir=vipdoc_path,
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
