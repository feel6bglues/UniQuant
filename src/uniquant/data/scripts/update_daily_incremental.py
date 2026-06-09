#!/usr/bin/env python3
"""
AKShare 日线数据增量更新脚本 v2.0
支持: 断点续传、增量更新、数据追加、安全写入
"""

import json
import random
import shutil
import time
import traceback
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from uniquant.shared.logger_factory import get_logger

# NON_RESEARCH_RANDOMNESS: script sleeps are provider throttling/backoff controls.

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DAILY_DIR = DATA_DIR / "lake" / "quotes" / "daily"
STOCK_CODES_FILE = DATA_DIR / "all_stock_codes.csv"
PROGRESS_FILE = DATA_DIR / ".incremental_progress.json"
BACKUP_DIR = DATA_DIR / "backup" / "daily"
LOG_FILE = DATA_DIR / "incremental_update.log"

DAILY_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

logger = get_logger(__name__)


class UpdateMode(Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    SKIP = "skip"


class UpdateResult(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    NO_NEW_DATA = "no_new_data"


class IncrementalUpdater:
    """增量更新器"""

    COLUMN_MAP = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "vol",
        "成交额": "amount",
        "振幅": "amplitude",
        "涨跌幅": "pct_change",
        "换手率": "turnover",
    }

    REQUIRED_COLUMNS = ["date", "open", "close", "high", "low", "vol"]

    def __init__(self):
        self.progress: Dict[str, dict] = self._load_progress()
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "no_new_data": 0,
            "incremental": 0,
            "full": 0,
        }
        self.failed_symbols: List[str] = []

    def _load_progress(self) -> Dict[str, dict]:
        """加载进度文件"""
        if PROGRESS_FILE.exists():
            try:
                with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError, OSError) as e:
                logger.warning(f"加载进度文件失败: {e}")
        return {}

    def _save_progress(self):
        """保存进度"""
        try:
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "stocks": self.progress,
                        "last_update": datetime.now().isoformat(),
                        "stats": self.stats,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.warning(f"保存进度失败: {e}")

    def _load_stock_list(self) -> List[Tuple[str, str]]:
        """加载股票列表"""
        if not STOCK_CODES_FILE.exists():
            logger.error(f"股票列表文件不存在: {STOCK_CODES_FILE}")
            return []

        df = pd.read_csv(STOCK_CODES_FILE, encoding="utf-8-sig")
        valid_stocks = []

        for row in df.itertuples(index=False):
            code_raw = str(row.code)
            status = row.status

            if status != 1:
                continue

            if code_raw.startswith("sh."):
                code = code_raw[3:]
                if code.startswith("60") or code.startswith("68"):
                    valid_stocks.append((code, f"{code}.SH"))
            elif code_raw.startswith("sz."):
                code = code_raw[3:]
                if code.startswith("00") or code.startswith("30"):
                    valid_stocks.append((code, f"{code}.SZ"))
            elif code_raw.startswith("bj."):
                code = code_raw[3:]
                if code.startswith("4") or code.startswith("8"):
                    valid_stocks.append((code, f"{code}.BJ"))

        logger.info(f"加载有效股票数: {len(valid_stocks)}")
        return valid_stocks

    def _get_local_latest_date(self, symbol: str) -> Optional[datetime]:
        """获取本地数据的最新日期"""
        file_path = DAILY_DIR / f"{symbol}.parquet"
        if not file_path.exists():
            return None

        try:
            df = pd.read_parquet(file_path)
            if df.empty or "date" not in df.columns:
                return None

            df["date"] = pd.to_datetime(df["date"])
            return df["date"].max()
        except (FileNotFoundError, IOError, pd.errors.EmptyDataError) as e:
            logger.warning(f"读取本地数据失败 {symbol}: {e}")
            return None

    def _get_local_record_count(self, symbol: str) -> int:
        """获取本地数据记录数"""
        file_path = DAILY_DIR / f"{symbol}.parquet"
        if not file_path.exists():
            return 0

        try:
            df = pd.read_parquet(file_path)
            return len(df)
        except (FileNotFoundError, IOError, pd.errors.EmptyDataError):
            return 0

    def _backup_file(self, symbol: str) -> bool:
        """备份原文件"""
        file_path = DAILY_DIR / f"{symbol}.parquet"
        if not file_path.exists():
            return True

        try:
            backup_path = BACKUP_DIR / f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
            shutil.copy2(file_path, backup_path)
            logger.debug(f"备份文件: {backup_path}")
            return True
        except (FileNotFoundError, IOError, OSError, PermissionError) as e:
            logger.warning(f"备份文件失败 {symbol}: {e}")
            return False

    def _validate_dataframe(self, df: pd.DataFrame) -> bool:
        """验证DataFrame有效性"""
        if df is None or df.empty:
            return False

        for col in self.REQUIRED_COLUMNS:
            if col not in df.columns:
                logger.warning(f"缺少必需列: {col}")
                return False

        if df["date"].isna().all():
            return False

        if (df["close"] <= 0).any():
            logger.warning("存在无效价格数据")
            return False

        return True

    def _fetch_data_from_akshare(
        self, code: str, start_date: str, end_date: str, adjust_type: str
    ) -> Optional[pd.DataFrame]:
        """从AKShare获取数据"""
        import akshare as ak
        import requests

        for retry in range(3):
            try:
                df = ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust_type,
                )
                if df is not None and not df.empty:
                    return df
            except (requests.exceptions.RequestException, ValueError, KeyError, OSError) as e:
                err_str = str(e).lower()
                if "timeout" in err_str or "connection" in err_str:
                    if retry < 2:
                        wait_time = (retry + 1) * 5
                        logger.debug(f"获取 {code} ({adjust_type}) 网络超时，等待 {wait_time}s 后重试")
                        time.sleep(wait_time)
                        continue
                logger.warning(f"获取 {code} ({adjust_type}) 失败: {e}")
        return None

    def _fetch_all_adjust_types(
        self, code: str, start_date: str, end_date: str
    ) -> Tuple[Optional[Dict[str, pd.DataFrame]], bool]:
        """获取三种复权类型的数据"""
        result = {}
        has_data = False

        for adjust_type in ["qfq", "hfq", ""]:
            df = self._fetch_data_from_akshare(code, start_date, end_date, adjust_type)
            if df is not None and not df.empty:
                has_data = True
                key = adjust_type if adjust_type else "raw"
                result[key] = df

        if has_data:
            return result, True
        
        return None, False

    def _get_base_dataframe(self, data: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
        for key in ["raw", "qfq", "hfq"]:
            df = data.get(key)
            if df is not None and not df.empty:
                return df
        return None

    def _merge_adjust_data(self, df: pd.DataFrame, adj_df: Optional[pd.DataFrame], prefix: str) -> pd.DataFrame:
        if adj_df is None or adj_df.empty:
            return df
        
        adj_renamed = adj_df.rename(columns=self.COLUMN_MAP)
        if "日期" in adj_df.columns:
            adj_renamed["date"] = pd.to_datetime(adj_df["日期"])
        elif "date" in adj_renamed.columns:
            adj_renamed["date"] = pd.to_datetime(adj_renamed["date"])
            
        adj_cols = ["date", "open", "close", "high", "low"]
        adj_subset = adj_renamed[adj_cols].copy()
        adj_subset.columns = ["date", f"{prefix}_open", f"{prefix}_close", f"{prefix}_high", f"{prefix}_low"]
        return df.merge(adj_subset, on="date", how="left")

    def _process_data(
        self, data: Dict[str, pd.DataFrame], code: str, symbol: str
    ) -> Optional[pd.DataFrame]:
        """处理数据，合并原始/前复权/后复权"""
        try:
            raw_df = self._get_base_dataframe(data)
            if raw_df is None:
                return None

            df = raw_df.copy()
            df = df.rename(columns=self.COLUMN_MAP)

            if "日期" in raw_df.columns:
                df["date"] = pd.to_datetime(raw_df["日期"])
            elif "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])

            df["code"] = code
            df["market"] = symbol.split(".")[-1] if "." in symbol else ""

            df = self._merge_adjust_data(df, data.get("qfq"), "qfq")
            df = self._merge_adjust_data(df, data.get("hfq"), "hfq")

            if "qfq_close" in df.columns and "close" in df.columns:
                df["qfq_factor"] = np.where(df["close"] > 0, df["qfq_close"] / df["close"], 1.0)

            if "hfq_close" in df.columns and "close" in df.columns:
                df["adj_factor"] = np.where(df["close"] > 0, df["hfq_close"] / df["close"], 1.0)

            numeric_cols = ["open", "high", "low", "close", "vol", "amount"]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            df = df.sort_values("date").reset_index(drop=True)

            return df

        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.error(f"处理数据失败 {symbol}: {e}")
            return None

    def _merge_with_local(
        self, new_df: pd.DataFrame, symbol: str, local_latest_date: Optional[datetime]
    ) -> Optional[pd.DataFrame]:
        """合并新数据与本地数据"""
        if local_latest_date is None:
            return new_df

        file_path = DAILY_DIR / f"{symbol}.parquet"
        try:
            local_df = pd.read_parquet(file_path)
            if local_df.empty:
                return new_df

            local_df["date"] = pd.to_datetime(local_df["date"])
            new_df["date"] = pd.to_datetime(new_df["date"])

            new_df_filtered = new_df[new_df["date"] > local_latest_date].copy()

            if new_df_filtered.empty:
                return None

            merged_df = pd.concat([local_df, new_df_filtered], ignore_index=True)
            merged_df = merged_df.sort_values("date").reset_index(drop=True)

            merged_df = merged_df.drop_duplicates(subset=["date"], keep="last")

            logger.info(f"合并数据: 本地 {len(local_df)} 条 + 新增 {len(new_df_filtered)} 条 = 总计 {len(merged_df)} 条")

            return merged_df

        except (FileNotFoundError, IOError, pd.errors.EmptyDataError, ValueError, KeyError) as e:
            logger.error(f"合并数据失败 {symbol}: {e}")
            return new_df

    def _save_data_atomic(self, df: pd.DataFrame, symbol: str) -> bool:
        """原子写入数据"""
        file_path = DAILY_DIR / f"{symbol}.parquet"
        temp_path = file_path.with_suffix(".tmp")

        try:
            df.to_parquet(str(temp_path), compression="snappy", index=False)

            if file_path.exists():
                file_path.unlink()

            temp_path.rename(file_path)
            return True

        except (IOError, OSError, PermissionError) as e:
            logger.error(f"保存数据失败 {symbol}: {e}")
            if temp_path.exists():
                temp_path.unlink()
            return False

    def _determine_update_mode(self, symbol: str) -> Tuple[UpdateMode, Optional[datetime]]:
        """确定更新模式"""
        local_latest = self._get_local_latest_date(symbol)

        if local_latest is None:
            return UpdateMode.FULL, None

        today = datetime.now()
        days_diff = (today - local_latest).days

        if days_diff <= 0:
            return UpdateMode.SKIP, local_latest

        if days_diff > 365:
            return UpdateMode.FULL, local_latest

        return UpdateMode.INCREMENTAL, local_latest

    def update_single_stock(self, code: str, symbol: str) -> UpdateResult:
        """更新单只股票"""
        mode, local_latest = self._determine_update_mode(symbol)

        if mode == UpdateMode.SKIP:
            logger.debug(f"{symbol} 数据已是最新，跳过")
            return UpdateResult.SKIPPED

        today = datetime.now()
        end_date = today.strftime("%Y%m%d")

        if mode == UpdateMode.FULL:
            start_date = "19900101"
            self.stats["full"] += 1
            logger.info(f"{symbol} 全量更新 (start: {start_date})")
        else:
            start_date = (local_latest + timedelta(days=1)).strftime("%Y%m%d")
            self.stats["incremental"] += 1
            logger.info(f"{symbol} 增量更新 (start: {start_date}, local_latest: {local_latest.date()})")

        data, has_data = self._fetch_all_adjust_types(code, start_date, end_date)
        
        if not has_data:
            if mode == UpdateMode.INCREMENTAL:
                logger.info(f"{symbol} 无新交易数据 (可能是非交易日)")
                return UpdateResult.NO_NEW_DATA
            else:
                logger.warning(f"{symbol} 全量更新失败，无法获取数据")
                return UpdateResult.FAILED

        new_df = self._process_data(data, code, symbol)
        if new_df is None or new_df.empty:
            logger.warning(f"{symbol} 数据处理失败")
            return UpdateResult.FAILED

        if not self._validate_dataframe(new_df):
            logger.warning(f"{symbol} 数据验证失败")
            return UpdateResult.FAILED

        if mode == UpdateMode.INCREMENTAL:
            if not self._backup_file(symbol):
                logger.warning(f"{symbol} 备份失败，但继续更新")

            final_df = self._merge_with_local(new_df, symbol, local_latest)
            if final_df is None:
                logger.info(f"{symbol} 无新数据需要追加")
                return UpdateResult.NO_NEW_DATA
        else:
            final_df = new_df

        if self._save_data_atomic(final_df, symbol):
            self.progress[symbol] = {
                "last_update": datetime.now().isoformat(),
                "record_count": len(final_df),
                "latest_date": final_df["date"].max().strftime("%Y-%m-%d"),
                "mode": mode.value,
            }
            logger.info(f"{symbol} 更新成功，共 {len(final_df)} 条记录")
            return UpdateResult.SUCCESS
        else:
            return UpdateResult.FAILED

    def run(self, force_full: bool = False, symbols_only: Optional[List[str]] = None):
        """运行更新任务"""
        logger.info("=" * 60)
        logger.info("AKShare 日线数据增量更新任务启动 v2.0")
        logger.info("=" * 60)

        stock_list = self._load_stock_list()
        if not stock_list:
            logger.error("没有有效的股票列表")
            return

        if symbols_only:
            stock_list = [(c, s) for c, s in stock_list if s in symbols_only]
            logger.info(f"仅更新指定股票: {len(stock_list)} 只")

        self.stats["total"] = len(stock_list)

        for i, (code, symbol) in enumerate(stock_list, 1):
            if i % 100 == 0:
                logger.info(f"进度: {i}/{len(stock_list)} ({i * 100 // len(stock_list)}%)")
                self._save_progress()

            try:
                result = self.update_single_stock(code, symbol)

                if result == UpdateResult.SUCCESS:
                    self.stats["success"] += 1
                elif result == UpdateResult.FAILED:
                    self.stats["failed"] += 1
                    self.failed_symbols.append(symbol)
                elif result == UpdateResult.SKIPPED:
                    self.stats["skipped"] += 1
                elif result == UpdateResult.NO_NEW_DATA:
                    self.stats["no_new_data"] += 1

            except Exception as e:
                logger.error(f"更新 {symbol} 异常: {e}\n{traceback.format_exc()}")
                self.stats["failed"] += 1
                self.failed_symbols.append(symbol)

            delay = random.uniform(0.5, 1.5)
            time.sleep(delay)

            if i % 50 == 0:
                batch_delay = random.uniform(10, 20)
                logger.info(f"已完成 {i} 只股票，休息 {batch_delay:.1f} 秒...")
                time.sleep(batch_delay)

        self._save_progress()

        logger.info("=" * 60)
        logger.info("更新任务完成")
        logger.info(f"总数: {self.stats['total']}")
        logger.info(f"成功: {self.stats['success']}")
        logger.info(f"跳过(已是最新): {self.stats['skipped']}")
        logger.info(f"无新数据: {self.stats['no_new_data']}")
        logger.info(f"失败: {self.stats['failed']}")
        logger.info(f"增量更新: {self.stats['incremental']}")
        logger.info(f"全量更新: {self.stats['full']}")

        if self.failed_symbols:
            failed_file = DATA_DIR / "failed_incremental_updates.txt"
            with open(failed_file, "w", encoding="utf-8") as f:
                for s in self.failed_symbols:
                    f.write(s + "\n")
            logger.info(f"失败列表已保存到: {failed_file}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AKShare日线数据增量更新")
    parser.add_argument("--force-full", action="store_true", help="强制全量更新")
    parser.add_argument("--symbols", nargs="+", help="仅更新指定股票代码")
    args = parser.parse_args()

    updater = IncrementalUpdater()
    updater.run(force_full=args.force_full, symbols_only=args.symbols)


if __name__ == "__main__":
    main()
