# -*- coding: utf-8 -*-
"""
财务数据导入模块 - 从通达信本地文件导入到数据湖
使用 mootdx 库解析 gpcw*.dat 文件（按报告期存储）
支持增量更新（基于源文件指纹）

两阶段导入策略：
1. 阶段1：多线程解析 + 内存聚合（充分利用多核）
2. 阶段2：顺序写入（避免并发竞争）

通达信财务数据格式:
1. gpcwYYYYMMDD.dat - 按报告期存储，每个文件包含所有股票在该报告期的财务数据
   - 如 gpcw20231231.dat 包含所有股票2023年年报数据
   - mootdx 的 FinancialReader 支持此格式

项目铁律:
1. No Magic: 所有数值常量提取到模块顶部
2. No Print: 使用logger记录日志
3. Specific Except: 捕获具体异常类型
4. Max Complexity: 函数不超过50行
5. Defensive IO: 文件操作添加超时和重试
"""
import sys
import json
import argparse
from pathlib import Path
from typing import Optional, Tuple, Dict, List
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from ...shared.time_provider import get_time_provider
from collections import defaultdict
import threading

import pandas as pd
from mootdx.financial.financial import FinancialReader

from ...shared.logger_factory import get_logger
from ...shared.constants import (
    TDX_DIR,
    DATA_DIR,
    LAKE_FINANCIAL_DIR,
    PARQUET_COMPRESSION,
    STOCK_LIST_FILE,
)

logger = get_logger('import_financial')

MAX_WORKERS = 8
FINGERPRINT_FILE = DATA_DIR / 'financial_fingerprint.json'
ALLOWED_SECURITY_TYPES = {'1'}
ALLOWED_SECURITY_STATUS = {1}

MARKET_SUFFIX_MAP = {
    '60': 'SH', '68': 'SH',
    '00': 'SZ', '30': 'SZ',
    '43': 'BJ', '83': 'BJ', '87': 'BJ',
}


class FinancialFingerprint:
    """财务数据文件指纹管理器"""

    def __init__(self, filepath: Path = FINGERPRINT_FILE):
        self.filepath = filepath
        self._fingerprints = self._load()

    def _load(self) -> Dict:
        if self.filepath.exists():
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载指纹文件失败: {e}")
        return {}

    def save(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self._fingerprints, f, indent=2, ensure_ascii=False)

    def is_update_needed(self, filepath: Path) -> bool:
        if filepath.name not in self._fingerprints:
            return True
        fp = self._fingerprints[filepath.name]
        if fp.get('status') != 'success':
            return True
        try:
            current_mtime = filepath.stat().st_mtime
            current_size = filepath.stat().st_size
            return (current_mtime != fp.get('mtime') or 
                    current_size != fp.get('size'))
        except OSError:
            return True

    def update(self, filepath: Path, record_count: int, success: bool = True):
        try:
            self._fingerprints[filepath.name] = {
                'mtime': filepath.stat().st_mtime,
                'size': filepath.stat().st_size,
                'records': record_count,
                'status': 'success' if success else 'failed',
                'updated_at': get_time_provider().now().isoformat(),
            }
        except OSError:
            logger.exception("获取文件状态失败，跳过")
            pass

    def get_stats(self) -> Dict:
        return {
            'total': len(self._fingerprints),
            'success': sum(1 for v in self._fingerprints.values() if v.get('status') == 'success'),
            'failed': sum(1 for v in self._fingerprints.values() if v.get('status') == 'failed'),
        }


class TDXFinancialImporter:
    """通达信财务数据导入器 - 两阶段导入：内存聚合 + 顺序写入"""

    def __init__(
        self,
        tdx_dir: Path = TDX_DIR,
        output_dir: Path = LAKE_FINANCIAL_DIR,
        stock_codes_file: Path = STOCK_LIST_FILE,
    ):
        self.tdx_dir = Path(tdx_dir)
        self.cw_dir = self.tdx_dir / 'vipdoc' / 'cw'
        self.output_dir = Path(output_dir)
        self.stock_codes_file = Path(stock_codes_file)
        self.fingerprint = FinancialFingerprint()
        self._memory_store: Dict[str, List[pd.DataFrame]] = defaultdict(list)
        self._store_lock = threading.Lock()
        self.allowed_stock_codes = self._load_allowed_stock_codes()
        logger.info("TDXFinancialImporter 初始化完成")
        logger.info(f"  通达信财务目录: {self.cw_dir}")
        logger.info(f"  输出目录: {self.output_dir}")
        logger.info(f"  指纹文件: {FINGERPRINT_FILE}")
        logger.info(f"  允许导入的股票代码数: {len(self.allowed_stock_codes)}")

    def _get_market_suffix(self, code: str) -> Optional[str]:
        for prefix, suffix in MARKET_SUFFIX_MAP.items():
            if code.startswith(prefix):
                return suffix
        return None

    def _to_all_stock_codes_format(self, normalized_code: str) -> Optional[str]:
        if not normalized_code or "." not in normalized_code:
            return None

        code, market = normalized_code.split(".", 1)
        market_lower = market.lower()
        if market_lower not in {"sh", "sz", "bj"}:
            return None
        return f"{market_lower}.{code}"

    def _load_allowed_stock_codes(self) -> set[str]:
        if not self.stock_codes_file.exists():
            logger.warning(f"股票代码文件不存在，跳过股票代码过滤: {self.stock_codes_file}")
            return set()

        try:
            df = pd.read_csv(self.stock_codes_file, encoding='utf-8-sig')
        except (OSError, ValueError, pd.errors.ParserError) as e:
            logger.warning(f"加载股票代码文件失败，跳过股票代码过滤: {e}")
            return set()

        if 'code' not in df.columns or 'type' not in df.columns:
            logger.warning("股票代码文件缺少 code/type 列，跳过股票代码过滤")
            return set()

        filtered = df[df['type'].astype(str).isin(ALLOWED_SECURITY_TYPES)].copy()
        if 'status' in filtered.columns:
            filtered = filtered[filtered['status'].isin(ALLOWED_SECURITY_STATUS)]

        allowed_codes: set[str] = set()
        for raw_code in filtered['code']:
            normalized = self._normalize_stock_code(raw_code)
            if normalized:
                allowed_codes.add(normalized)

        return allowed_codes

    def is_allowed_security(self, normalized_code: str) -> bool:
        if not self.allowed_stock_codes:
            return True
        return normalized_code in self.allowed_stock_codes

    def _normalize_stock_code(self, code: object) -> Optional[str]:
        if pd.isna(code):
            return None

        code_str = str(code).strip().upper()
        if not code_str:
            return None

        if "." in code_str:
            left, right = code_str.split(".", 1)
            if right in {"SH", "SZ", "BJ"} and left.isdigit():
                return f"{left.zfill(6)}.{right}"
            if left in {"SH", "SZ", "BJ"} and right.isdigit():
                return f"{right.zfill(6)}.{left}"

        digits = "".join(ch for ch in code_str if ch.isdigit())
        if len(digits) > 6:
            digits = digits[-6:]
        digits = digits.zfill(6)

        suffix = self._get_market_suffix(digits)
        return f"{digits}.{suffix}" if suffix else None

    def _normalize_date_column(self, series: pd.Series) -> pd.Series:
        as_str = series.astype(str).str.strip()
        parsed = pd.Series(pd.NaT, index=series.index, dtype='datetime64[ns]')

        len8_mask = as_str.str.fullmatch(r'\d{8}')
        if len8_mask.any():
            parsed.loc[len8_mask] = pd.to_datetime(as_str.loc[len8_mask], format='%Y%m%d', errors='coerce')

        len6_mask = parsed.isna() & as_str.str.fullmatch(r'\d{6}')
        if len6_mask.any():
            parsed.loc[len6_mask] = pd.to_datetime(as_str.loc[len6_mask], format='%y%m%d', errors='coerce')

        fallback_mask = parsed.isna()
        if fallback_mask.any():
            parsed.loc[fallback_mask] = pd.to_datetime(series.loc[fallback_mask], errors='coerce')

        return parsed

    def _normalize_financial_df(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        if 'code' in df.columns:
            df['code'] = df['code'].map(self._normalize_stock_code)
            df = df[df['code'].notna()].copy()
            if self.allowed_stock_codes:
                df = df[df['code'].isin(self.allowed_stock_codes)].copy()

        if 'report_date' in df.columns:
            df['report_date'] = self._normalize_date_column(df['report_date'])
            df = df[df['report_date'].notna()].copy()

        return df

    def _fix_duplicate_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        cols = list(df.columns)
        seen: Dict[str, int] = {}
        new_cols: List[str] = []
        for col in cols:
            if col in seen:
                seen[col] += 1
                new_cols.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                new_cols.append(col)
        df.columns = new_cols
        return df

    def _parse_gpcw_file(self, filepath: Path) -> Optional[pd.DataFrame]:
        try:
            df = FinancialReader.to_data(str(filepath))
            if df is None or df.empty:
                return None
            if df.index.name == 'code' or 'code' not in df.columns:
                df = df.reset_index()
            if 'code' in df.columns:
                df['code'] = df['code'].map(self._normalize_stock_code)
            return self._normalize_financial_df(df)
        except Exception as e:
            logger.error(f"解析文件失败 {filepath.name}: {e}")
            return None

    def _process_file_to_memory(self, filepath: Path, force: bool = False) -> Tuple[bool, str, int]:
        """阶段1：解析单个文件并将结果存入内存"""
        if not filepath.name.startswith('gpcw') or not filepath.name.endswith('.dat'):
            return False, 'skipped', 0

        if not force and not self.fingerprint.is_update_needed(filepath):
            return True, 'skipped', 0

        try:
            df = self._parse_gpcw_file(filepath)
            if df is None or df.empty:
                self.fingerprint.update(filepath, 0, success=False)
                return False, 'empty', 0

            df = self._fix_duplicate_columns(df)
            
            if 'code' not in df.columns:
                logger.error(f"文件缺少code列: {filepath.name}")
                self.fingerprint.update(filepath, 0, success=False)
                return False, 'no_code', 0

            codes = df['code'].unique()
            stored_count = 0
            
            for code in codes:
                stock_df = df[df['code'] == code].copy()
                if stock_df.empty:
                    continue
                
                with self._store_lock:
                    self._memory_store[code].append(stock_df)
                stored_count += 1

            self.fingerprint.update(filepath, len(df), success=True)
            return True, 'parsed', stored_count

        except Exception as e:
            logger.error(f"处理文件失败 {filepath.name}: {e}")
            self.fingerprint.update(filepath, 0, success=False)
            return False, 'failed', 0

    def _write_single_stock(self, code: str, dfs: List[pd.DataFrame]) -> bool:
        """阶段2：将单个股票的所有数据合并写入文件"""
        if not dfs:
            return False

        normalized_code = self._normalize_stock_code(code)
        if not normalized_code:
            return False
        if not self.is_allowed_security(normalized_code):
            logger.info(f"跳过非股票代码财务导入: {normalized_code}")
            return False

        output_file = self.output_dir / f'{normalized_code}.parquet'
        
        try:
            merged_df = pd.concat(dfs, ignore_index=True)
            if output_file.exists():
                existing_df = pd.read_parquet(output_file)
                merged_df = pd.concat([existing_df, merged_df], ignore_index=True)

            merged_df = self._normalize_financial_df(merged_df)
            merged_df = merged_df.drop_duplicates(subset=['code', 'report_date'], keep='last')
            merged_df = merged_df.sort_values('report_date')
            merged_df.to_parquet(output_file, compression=PARQUET_COMPRESSION, index=False)
            return True
        except Exception as e:
            logger.error(f"写入股票文件失败 {code}: {e}")
            return False

    def import_batch(self, limit: int = 0, force: bool = False, workers: int = MAX_WORKERS) -> Tuple[int, int, int]:
        """两阶段批量导入"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        gpcw_files = sorted(self.cw_dir.glob('gpcw*.dat'))
        if limit > 0:
            gpcw_files = gpcw_files[:limit]

        if not gpcw_files:
            logger.warning(f"未找到财务数据文件: {self.cw_dir}")
            return 0, 0, 0

        logger.info(f"开始导入，共 {len(gpcw_files)} 个文件，线程数: {workers}")
        logger.info("阶段1：多线程解析 + 内存聚合...")

        success_count = 0
        skip_count = 0
        fail_count = 0
        total_stocks = 0
        counter_lock = threading.Lock()

        def process_file(filepath: Path) -> Tuple[bool, str, int]:
            return self._process_file_to_memory(filepath, force=force)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_file, f): f for f in gpcw_files}
            for i, future in enumerate(as_completed(futures)):
                try:
                    success, status, count = future.result()
                    with counter_lock:
                        if success:
                            if status == 'parsed':
                                success_count += 1
                                total_stocks += count
                            elif status == 'skipped':
                                skip_count += 1
                        else:
                            fail_count += 1
                except Exception as e:
                    logger.error(f"处理文件异常: {e}")
                    with counter_lock:
                        fail_count += 1

                if (i + 1) % 20 == 0:
                    logger.info(f"解析进度: {i+1}/{len(gpcw_files)}, 成功: {success_count}, 跳过: {skip_count}, 失败: {fail_count}")

        logger.info(f"阶段1完成：解析 {success_count} 个文件，内存中 {len(self._memory_store)} 只股票")
        logger.info("阶段2：顺序写入文件...")

        write_success = 0
        write_fail = 0
        total_codes = len(self._memory_store)
        
        for i, (code, dfs) in enumerate(self._memory_store.items()):
            if self._write_single_stock(code, dfs):
                write_success += 1
            else:
                write_fail += 1
            
            if (i + 1) % 500 == 0:
                logger.info(f"写入进度: {i+1}/{total_codes}, 成功: {write_success}, 失败: {write_fail}")

        self.fingerprint.save()
        logger.info(f"导入完成：解析成功 {success_count}, 跳过 {skip_count}, 失败 {fail_count}")
        logger.info(f"写入完成：成功 {write_success}, 失败 {write_fail}")
        
        self._memory_store.clear()
        return success_count, skip_count, fail_count


def main():
    parser = argparse.ArgumentParser(description='通达信财务数据导入工具')
    parser.add_argument('--force', '-f', action='store_true', help='强制更新所有文件')
    parser.add_argument('--limit', '-n', type=int, default=0, help='限制处理文件数量')
    parser.add_argument('--workers', '-w', type=int, default=MAX_WORKERS, help='并发线程数')
    args = parser.parse_args()

    importer = TDXFinancialImporter()
    success, skipped, failed = importer.import_batch(
        limit=args.limit, 
        force=args.force, 
        workers=args.workers
    )
    
    print(f"\n导入结果: 成功={success}, 跳过={skipped}, 失败={failed}")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
