#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TDX 指数数据导入器
从通达信本地日线数据导入主要指数到 data/lake/index 目录

支持的指数:
- 000001.SH: 上证综指
- 399001.SZ: 深证成指
- 399006.SZ: 创业板指
- 000016.SH: 上证50
- 000300.SH: 沪深300
- 000905.SH: 中证500
- 000852.SH: 中证1000
- 932000.SH: 中证2000
"""

import struct
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional, Tuple, Union

import pandas as pd

from ...shared.constants import (
    DATA_DIR,
    LAKE_INDEX_DIR,
    MAJOR_INDEXES,
    PARQUET_COMPRESSION,
    TDX_DIR,
)
from ...shared.import_state import ImportStateManager, ThreadSafeImportCounter
from ...shared.logger_factory import get_logger

logger = get_logger("TDXIndexImporter")

OUTPUT_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]


class TDXIndexImporter:
    """
    TDX 指数数据导入器
    
    从通达信本地 .day 文件导入指数日线数据到 data/lake/index 目录
    """
    
    def __init__(
        self,
        tdx_dir: Union[str, Path] = None,
        output_dir: Union[str, Path] = None,
    ):
        """
        初始化指数导入器
        
        Args:
            tdx_dir: 通达信安装目录路径，默认从配置文件读取
            output_dir: 输出目录，默认为 data/lake/index
        """
        if tdx_dir is None:
            from ...shared.config_loader import get_config
            config = get_config()
            tdx_dir = config.get("base.tdx.path", TDX_DIR)
        
        self.tdx_dir = Path(tdx_dir)
        self.output_dir = Path(output_dir) if output_dir else LAKE_INDEX_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.state_manager = ImportStateManager(DATA_DIR)
        self._file_lock = threading.Lock()
        
        logger.info("TDXIndexImporter 初始化完成")
        logger.info(f"  TDX目录: {self.tdx_dir}")
        logger.info(f"  输出目录: {self.output_dir}")
    
    def _get_tdx_file_path(self, code: str, market: str) -> Optional[Path]:
        """
        获取通达信 .day 文件路径
        
        Args:
            code: 指数代码 (如 000001)
            market: 市场代码 (sh/sz)
            
        Returns:
            .day 文件路径，不存在则返回 None
        """
        day_file = self.tdx_dir / "vipdoc" / market / "lday" / f"{market}{code}.day"
        if day_file.exists():
            return day_file
        return None
    
    def _parse_day_file(self, file_path: Path) -> pd.DataFrame:
        """
        解析通达信 .day 文件
        
        Args:
            file_path: .day 文件路径
            
        Returns:
            解析后的 DataFrame
        """
        data_list = []
        
        try:
            with open(file_path, "rb") as f:
                buffer = f.read()
            
            fmt = "<IIIIIfii"
            for record in struct.iter_unpack(fmt, buffer):
                date_int, open_p, high_p, low_p, close_p, amount, volume, _ = record
                
                date_str = str(date_int)
                if len(date_str) != 8:
                    continue
                
                data_list.append({
                    "date": pd.to_datetime(date_str, format="%Y%m%d"),
                    "open": open_p / 100.0,
                    "high": high_p / 100.0,
                    "low": low_p / 100.0,
                    "close": close_p / 100.0,
                    "volume": volume,
                    "amount": amount,
                })
            
            df = pd.DataFrame(data_list)
            df = df[OUTPUT_COLS]
            df = df.sort_values("date").reset_index(drop=True)
            
            return df
            
        except Exception as e:
            logger.error(f"解析 .day 文件失败: {file_path}, 错误: {e}")
            return pd.DataFrame()
    
    def _parse_symbol(self, symbol: str) -> Tuple[str, str]:
        """
        解析指数代码
        
        Args:
            symbol: 指数代码 (如 000001.SH)
            
        Returns:
            (code, market) 元组
        """
        code, suffix = symbol.split(".")
        market = suffix.lower()
        return code, market
    
    def import_single_index(
        self,
        symbol: str,
        counter: Optional[ThreadSafeImportCounter] = None,
    ) -> bool:
        """
        导入单个指数数据
        
        Args:
            symbol: 指数代码 (如 000001.SH)
            counter: 线程安全计数器
            
        Returns:
            是否导入成功
        """
        try:
            code, market = self._parse_symbol(symbol)
            index_name = MAJOR_INDEXES.get(symbol, symbol)
            
            source_file = self._get_tdx_file_path(code, market)
            if source_file is None:
                logger.warning(f"指数文件不存在: {symbol} ({index_name})")
                if counter:
                    counter.increment_failed()
                return False
            
            if not self.state_manager.is_import_needed(code, market, source_file):
                logger.debug(f"指数数据无变化，跳过: {symbol}")
                if counter:
                    counter.increment_success()
                return True
            
            df = self._parse_day_file(source_file)
            if df.empty:
                logger.warning(f"指数数据解析为空: {symbol}")
                if counter:
                    counter.increment_failed()
                return False
            
            output_file = self.output_dir / f"{symbol}.parquet"
            
            with self._file_lock:
                df.to_parquet(output_file, compression=PARQUET_COMPRESSION, index=False)
            
            last_date = df["date"].max().strftime("%Y-%m-%d")
            self.state_manager.update_state(
                code, market, source_file, len(df), last_date, "success"
            )
            
            logger.info(f"成功导入指数: {symbol} ({index_name}), 共 {len(df)} 条记录")
            
            if counter:
                counter.increment_success()
            
            return True
            
        except Exception as e:
            logger.error(f"导入指数数据失败: {symbol}, 错误: {e}")
            if counter:
                counter.increment_failed()
            return False
    
    def import_all_indexes(self, max_workers: int = 4) -> Tuple[int, int]:
        """
        导入所有主要指数数据
        
        Args:
            max_workers: 最大线程数
            
        Returns:
            (成功数, 失败数) 元组
        """
        symbols = list(MAJOR_INDEXES.keys())
        logger.info(f"开始导入 {len(symbols)} 个主要指数...")
        
        counter = ThreadSafeImportCounter()
        counter.set_total(len(symbols))
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self.import_single_index, symbol, counter)
                for symbol in symbols
            ]
            
            for future in futures:
                future.result()
        
        success, failed, _, _ = counter.get_progress()
        logger.info(f"指数导入完成: 成功 {success}, 失败 {failed}")
        
        return success, failed
    
    def incremental_update(self, max_workers: int = 4) -> Tuple[int, int]:
        """
        增量更新指数数据
        
        Args:
            max_workers: 最大线程数
            
        Returns:
            (成功数, 失败数) 元组
        """
        symbols_to_update = []
        
        for symbol in MAJOR_INDEXES.keys():
            code, market = self._parse_symbol(symbol)
            source_file = self._get_tdx_file_path(code, market)
            
            if source_file and self.state_manager.is_import_needed(code, market, source_file):
                symbols_to_update.append(symbol)
        
        if not symbols_to_update:
            logger.info("所有指数数据已是最新，无需更新")
            return 0, 0
        
        logger.info(f"需要更新 {len(symbols_to_update)} 个指数")
        
        counter = ThreadSafeImportCounter()
        counter.set_total(len(symbols_to_update))
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self.import_single_index, symbol, counter)
                for symbol in symbols_to_update
            ]
            
            for future in futures:
                future.result()
        
        success, failed, _, _ = counter.get_progress()
        logger.info(f"增量更新完成: 成功 {success}, 失败 {failed}")
        
        return success, failed
    
    def get_index_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        读取已导入的指数数据
        
        Args:
            symbol: 指数代码 (如 000001.SH)
            
        Returns:
            指数数据 DataFrame，不存在则返回 None
        """
        output_file = self.output_dir / f"{symbol}.parquet"
        
        if not output_file.exists():
            logger.warning(f"指数数据文件不存在: {output_file}")
            return None
        
        try:
            df = pd.read_parquet(output_file)
            logger.info(f"读取指数数据: {symbol}, 共 {len(df)} 条记录")
            return df
        except Exception as e:
            logger.error(f"读取指数数据失败: {symbol}, 错误: {e}")
            return None
    
    def list_imported_indexes(self) -> List[str]:
        """
        列出已导入的指数
        
        Returns:
            已导入的指数代码列表
        """
        imported = []
        for symbol in MAJOR_INDEXES.keys():
            output_file = self.output_dir / f"{symbol}.parquet"
            if output_file.exists():
                imported.append(symbol)
        return imported


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="TDX 指数数据导入器")
    parser.add_argument(
        "--tdx-dir",
        type=str,
        default=str(TDX_DIR),
        help="通达信 vipdoc 目录路径",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="输出目录，默认为 data/lake/index",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="最大线程数",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="增量更新模式",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出已导入的指数",
    )
    
    args = parser.parse_args()
    
    importer = TDXIndexImporter(
        tdx_dir=args.tdx_dir,
        output_dir=args.output_dir,
    )
    
    if args.list:
        imported = importer.list_imported_indexes()
        logger.info(f"已导入的指数 ({len(imported)} 个):")
        for symbol in imported:
            name = MAJOR_INDEXES.get(symbol, symbol)
            logger.info(f"  {symbol}: {name}")
        return
    
    if args.incremental:
        importer.incremental_update(args.max_workers)
    else:
        importer.import_all_indexes(args.max_workers)


if __name__ == "__main__":
    main()
