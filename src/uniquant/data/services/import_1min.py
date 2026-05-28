# -*- coding: utf-8 -*-
"""
1分钟线数据导入模块 - 从通达信本地文件导入到数据湖
支持多线程（4线程）全量和增量更新

项目铁律:
1. No Magic: 所有数值常量提取到模块顶部
2. No Print: 使用logger记录日志
3. Specific Except: 捕获具体异常类型
4. Max Complexity: 函数不超过50行
5. Defensive IO: 文件操作添加超时和重试
"""
import sys
import struct
import argparse
from pathlib import Path
from typing import Optional, List, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import pandas as pd
from ...shared.logger_factory import get_logger
from ...shared.constants import (
    TDX_DIR,
    LAKE_QUOTES_DIR,
    STOCK_LIST_FILE,
    PARQUET_COMPRESSION,
)
from ...shared.import_state import ImportStateManager, ThreadSafeImportCounter

logger = get_logger('import_1min')

MINLINE_RECORD_SIZE = 32
DATE_BASE_YEAR = 2004
DATE_MULTIPLIER = 2048
PRICE_DECIMAL_PLACES = 2
MAX_WORKERS = 4

OUTPUT_COLS = [
    'datetime', 'date', 'time', 'code', 'market',
    'open', 'high', 'low', 'close', 'vol', 'amount'
]


class TDX1MinImporter:
    """通达信1分钟线数据导入器"""

    def __init__(self, tdx_dir: Union[str, Path] = TDX_DIR, output_dir: Union[str, Path] = LAKE_QUOTES_DIR):
        self.tdx_dir = Path(tdx_dir)
        self.output_dir = Path(output_dir) / '1mins'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # 初始化状态管理器
        self.state_manager = ImportStateManager(self.output_dir)
        # 线程锁用于文件写入
        self._file_lock = threading.Lock()
        logger.info(f"TDX1MinImporter 初始化完成，输出目录: {self.output_dir}")

    def _parse_minline_record(self, data: bytes) -> Optional[dict]:
        """解析单条1分钟线记录"""
        if len(data) < MINLINE_RECORD_SIZE:
            return None

        try:
            date_raw = struct.unpack('<H', data[0:2])[0]
            time_raw = struct.unpack('<H', data[2:4])[0]

            year = date_raw // 2048 + 2004
            month_day = date_raw % 2048
            month = month_day // 100
            day = month_day % 100
            
            hour = time_raw // 60
            minute = time_raw % 60

            if not (1 <= month <= 12 and 1 <= day <= 31):
                return None
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None

            open_price = struct.unpack('<f', data[4:8])[0]
            high = struct.unpack('<f', data[8:12])[0]
            low = struct.unpack('<f', data[12:16])[0]
            close = struct.unpack('<f', data[16:20])[0]
            amount = struct.unpack('<f', data[20:24])[0]
            vol = struct.unpack('<I', data[24:28])[0]

            if close <= 0:
                return None
            if not (low <= close <= high):
                return None
            if not (low <= open_price <= high):
                return None

            datetime_str = f'{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:00'
            date_str = f'{year:04d}-{month:02d}-{day:02d}'
            time_str = f'{hour:02d}:{minute:02d}:00'

            return {
                'datetime': datetime_str,
                'date': date_str,
                'time': time_str,
                'open': round(open_price, PRICE_DECIMAL_PLACES),
                'high': round(high, PRICE_DECIMAL_PLACES),
                'low': round(low, PRICE_DECIMAL_PLACES),
                'close': round(close, PRICE_DECIMAL_PLACES),
                'vol': vol,
                'amount': amount
            }
        except struct.error as e:
            logger.debug(f"解析记录失败: {e}")
            return None
        except Exception as e:
            logger.debug(f"解析记录时发生错误: {e}")
            return None

    def read_tdx_1min(self, market: str, code: str) -> Tuple[Optional[pd.DataFrame], Optional[Path]]:
        """读取通达信1分钟线文件"""
        minline_file = self.tdx_dir / 'vipdoc' / market / 'minline' / f'{market}{code}.lc1'

        if not minline_file.exists():
            logger.debug(f"1分钟线文件不存在: {minline_file}")
            return None, None

        records = []
        try:
            with open(minline_file, 'rb') as f:
                while True:
                    data = f.read(MINLINE_RECORD_SIZE)
                    if len(data) < MINLINE_RECORD_SIZE:
                        break

                    record = self._parse_minline_record(data)
                    if record:
                        record['code'] = code
                        record['market'] = market.upper()
                        records.append(record)

            if not records:
                logger.warning(f"1分钟线文件无有效数据: {minline_file}")
                return None, minline_file

            df = pd.DataFrame(records)
            df['datetime'] = pd.to_datetime(df['datetime'])
            return df, minline_file

        except FileNotFoundError as e:
            logger.error(f"读取1分钟线文件失败，文件未找到: {minline_file} - {e}")
            return None, minline_file
        except PermissionError as e:
            logger.error(f"读取1分钟线文件失败，权限不足: {minline_file} - {e}")
            return None, minline_file
        except Exception as e:
            logger.error(f"读取1分钟线文件失败 {minline_file}: {e}")
            return None, minline_file

    def import_single_stock(self, code: str, market: str,
                           counter: Optional[ThreadSafeImportCounter] = None) -> bool:
        """导入单只股票的1分钟线数据（线程安全）"""
        try:
            df, source_file = self.read_tdx_1min(market, code)
            if df is None or df.empty:
                logger.debug(f"无1分钟线数据: {code}.{market}")
                if counter:
                    counter.increment_failed()
                return False

            if source_file is None:
                logger.debug(f"源文件不存在: {code}.{market}")
                if counter:
                    counter.increment_failed()
                return False

            if self.state_manager.is_import_needed(code, market, source_file):
                df = df[[col for col in OUTPUT_COLS if col in df.columns]]

                suffix = market.upper()
                output_file = self.output_dir / f'{code}.{suffix}.parquet'

                with self._file_lock:
                    df.to_parquet(output_file, compression=PARQUET_COMPRESSION, index=False)

                last_datetime = df['datetime'].max().strftime('%Y-%m-%d %H:%M:%S')
                self.state_manager.update_state(
                    code, market, source_file,
                    len(df), last_datetime, 'success'
                )

                logger.debug(f"1分钟线数据导入成功: {code}.{suffix}, 共 {len(df)} 条记录")
            else:
                logger.debug(f"跳过（无需更新）: {code}.{market}")

            if counter:
                counter.increment_success()
            return True

        except Exception as e:
            logger.error(f"导入1分钟线数据失败 {code}.{market}: {e}")
            if counter:
                counter.increment_failed()
            return False

    def import_batch(self, codes: List[str], markets: List[str]) -> Tuple[int, int]:
        """批量导入1分钟线数据（多线程）"""
        counter = ThreadSafeImportCounter()
        counter.set_total(len(codes))

        logger.info(f"开始批量导入1分钟线数据，共 {len(codes)} 只股票，线程数: {MAX_WORKERS}")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_stock = {
                executor.submit(self.import_single_stock, code, market, counter): (code, market)
                for code, market in zip(codes, markets)
            }

            for i, future in enumerate(as_completed(future_to_stock)):
                code, market = future_to_stock[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"处理股票 {code}.{market} 时发生错误: {e}")
                    counter.increment_failed()

                if (i + 1) % 100 == 0:
                    success, failed, processed, total = counter.get_progress()
                    logger.info(f"进度: {processed}/{total} ({processed/total*100:.1f}%), 成功: {success}, 失败: {failed}")

        success, failed, processed, total = counter.get_progress()
        logger.info(f"批量导入完成: 成功={success}, 失败={failed}")
        return success, failed

    def incremental_update(self, codes: List[str], markets: List[str]) -> Tuple[int, int]:
        """增量更新1分钟线数据（多线程）"""
        stocks_to_update = []
        for code, market in zip(codes, markets):
            source_file = self.tdx_dir / 'vipdoc' / market / 'minline' / f'{market}{code}.lc1'
            if self.state_manager.is_import_needed(code, market, source_file):
                stocks_to_update.append((code, market))
            else:
                logger.debug(f"跳过（无需更新）: {code}.{market}")

        if not stocks_to_update:
            logger.info("所有股票都已是最新，无需更新")
            return 0, 0

        logger.info(f"增量更新: 共 {len(codes)} 只，需要更新 {len(stocks_to_update)} 只")

        update_codes = [s[0] for s in stocks_to_update]
        update_markets = [s[1] for s in stocks_to_update]

        return self.import_batch(update_codes, update_markets)


def main():
    global MAX_WORKERS
    
    parser = argparse.ArgumentParser(description='导入通达信1分钟线数据到数据湖')
    parser.add_argument('--market', type=str, choices=['sh', 'sz'], help='指定市场')
    parser.add_argument('--code', type=str, help='指定股票代码')
    parser.add_argument('--incremental', action='store_true', help='增量更新模式')
    parser.add_argument('--limit', type=int, help='限制处理数量')
    parser.add_argument('--threads', type=int, default=MAX_WORKERS, help=f'线程数（默认{MAX_WORKERS}）')
    args = parser.parse_args()

    MAX_WORKERS = args.threads

    importer = TDX1MinImporter()

    if args.code:
        market = args.market or ('sh' if args.code.startswith('6') else 'sz')
        success = importer.import_single_stock(args.code, market)
        sys.exit(0 if success else 1)

    try:
        df = pd.read_csv(STOCK_LIST_FILE, dtype={'code': str})
        codes = df['code'].str.zfill(6).tolist()
        markets = df['market'].str.lower().tolist()
    except Exception as e:
        logger.error(f"加载股票列表失败: {e}")
        sys.exit(1)

    if args.market:
        filtered = [(c, m) for c, m in zip(codes, markets) if m == args.market]
        codes = [c for c, m in filtered]
        markets = [m for c, m in filtered]

    if args.limit:
        codes = codes[:args.limit]
        markets = markets[:args.limit]

    if args.incremental:
        importer.incremental_update(codes, markets)
    else:
        importer.import_batch(codes, markets)


if __name__ == '__main__':
    main()
