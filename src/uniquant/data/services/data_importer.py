#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导入工具
将已下载的CSV数据转换为系统可用的Parquet格式
支持通达信TDX数据文件导入
"""

import os
import sys
import json
import pandas as pd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Dict, Any

from ...data.lake.storage_manager import StorageManager
from ...data.pipeline.data_adjuster import DataAdjuster
from ...data.parsers.tdx_parser import TDXParser
from ...data.managers.factor_manager import FactorManager
from ...shared.logger_factory import get_logger

logger = get_logger("DataImporter")


class DataImporter:
    """
    数据导入器
    负责将CSV格式的股票数据转换为系统可用的Parquet格式
    """

    def __init__(self, data_dir: str = "./data", tdx_path: Optional[str] = None):
        """
        初始化数据导入器

        Args:
            data_dir: 数据存储根目录
            tdx_path: 通达信安装目录路径
        """
        import threading
        
        self.data_dir = Path(data_dir)
        self.storage_manager = StorageManager(data_dir)
        self.data_adjuster = DataAdjuster(self.storage_manager)
        self.tdx_path = Path(tdx_path) if tdx_path else None
        # 初始化TDXParser，传递vipdoc_path参数
        vipdoc_path = None
        if self.tdx_path:
            vipdoc_path = str(self.tdx_path / "vipdoc")
        self.tdx_parser = TDXParser(vipdoc_path=vipdoc_path)
        self.gbbq_data = None
        
        # 文件指纹记录，用于增量更新
        self.fingerprint_file = self.data_dir / ".file_fingerprints.json"
        self.file_fingerprints = self._load_fingerprints()
        
        # 添加线程锁，解决多线程并发访问文件指纹字典的问题
        self.fingerprint_lock = threading.Lock()
        
        # 创建fq目录，用于存储gbbq数据
        self.fq_dir = self.data_dir / "fq"
        self.fq_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"创建fq目录: {self.fq_dir}")
        
        # 初始化 FactorManager
        self.factor_manager = FactorManager(data_dir)
        
        # 初始化gbbq数据
        self.gbbq_data = pd.DataFrame()
        
        logger.info(f"初始化数据导入器，数据目录: {data_dir}")

    def _load_fingerprints(self) -> Dict[str, Dict[str, Any]]:
        """
        加载文件指纹记录

        Returns:
            文件指纹字典
        """
        if self.fingerprint_file.exists():
            try:
                with open(self.fingerprint_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content:
                        logger.warning("文件指纹文件为空")
                        return {}
                    return json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"文件指纹文件格式错误: {e}")
                logger.info("创建新的文件指纹记录，删除损坏的文件")
                try:
                    self.fingerprint_file.unlink()
                except OSError:
                    pass
                return {}
            except Exception as e:
                logger.error(f"加载文件指纹失败: {e}")
                return {}
        else:
            logger.info("文件指纹文件不存在，创建新的记录")
            return {}

    def _save_fingerprints(self):
        """
        保存文件指纹记录
        """
        try:
            # 确保目录存在
            self.fingerprint_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.fingerprint_file, 'w', encoding='utf-8') as f:
                json.dump(self.file_fingerprints, f, indent=2, ensure_ascii=False)
            logger.debug(f"成功保存文件指纹到: {self.fingerprint_file}")
        except Exception as e:
            logger.error(f"保存文件指纹失败: {e}")

    def _get_file_fingerprint(self, file_path: Path) -> Dict[str, Any]:
        """
        获取文件指纹

        Args:
            file_path: 文件路径

        Returns:
            文件指纹字典
        """
        try:
            stat = file_path.stat()
            return {
                'mtime': stat.st_mtime,
                'size': stat.st_size
            }
        except Exception as e:
            logger.error(f"获取文件指纹失败: {e}")
            return {}

    def _normalize_path(self, file_path: Path) -> str:
        """
        标准化文件路径，确保路径格式一致

        Args:
            file_path: 文件路径

        Returns:
            标准化后的路径字符串
        """
        return str(file_path.absolute()).replace('\\', '/')

    def _needs_update(self, file_path: Path) -> bool:
        """
        检查文件是否需要更新

        Args:
            file_path: 文件路径

        Returns:
            是否需要更新
        """
        try:
            file_key = self._normalize_path(file_path)
            current_fingerprint = self._get_file_fingerprint(file_path)
            
            if not current_fingerprint:
                logger.warning(f"无法获取文件指纹: {file_path}")
                return True
            
            with self.fingerprint_lock:
                old_fingerprint = self.file_fingerprints.get(file_key, {})
                if not old_fingerprint:
                    logger.debug(f"文件指纹不存在，需要更新: {file_path}")
                    return True
                
                is_different = current_fingerprint != old_fingerprint
                if is_different:
                    logger.debug(f"文件指纹不同，需要更新: {file_path}")
                return is_different
        except Exception as e:
            logger.error(f"检查文件更新状态失败: {e}")
            return True

    def _update_fingerprint(self, file_path: Path):
        """
        更新文件指纹

        Args:
            file_path: 文件路径
        """
        try:
            file_key = self._normalize_path(file_path)
            fingerprint = self._get_file_fingerprint(file_path)
            if fingerprint:
                with self.fingerprint_lock:
                    self.file_fingerprints[file_key] = fingerprint
                    self._save_fingerprints()
                logger.debug(f"成功更新文件指纹: {file_path}")
            else:
                logger.warning(f"无法更新文件指纹，获取指纹失败: {file_path}")
        except Exception as e:
            logger.error(f"更新文件指纹失败: {e}")

    def convert_symbol_format(self, filename: str) -> Optional[str]:
        """
        转换股票代码格式
        从 sh600000.csv 转换为 600000.SH

        Args:
            filename: 文件名，如 sh600000.csv

        Returns:
            转换后的股票代码，如 600000.SH
        """
        try:
            symbol_part = filename.split('.')[0]
            
            if symbol_part.startswith('sh'):
                code = symbol_part[2:]
                return f"{code}.SH"
            elif symbol_part.startswith('sz'):
                code = symbol_part[2:]
                return f"{code}.SZ"
            else:
                logger.warning(f"无法识别的股票代码格式: {filename}")
                return None
        except Exception as e:
            logger.error(f"转换股票代码格式失败: {e}")
            return None

    def read_csv_data(self, csv_path: Path) -> Optional[pd.DataFrame]:
        """
        读取CSV文件数据

        Args:
            csv_path: CSV文件路径

        Returns:
            数据DataFrame
        """
        try:
            logger.info(f"读取CSV文件: {csv_path}")
            df = pd.read_csv(csv_path)
            
            required_columns = ['date', 'open', 'high', 'low', 'close', 'amount', 'volume']
            if not all(col in df.columns for col in required_columns):
                logger.error(f"CSV文件格式不正确，缺少必要列: {csv_path}")
                return None
            
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            
            logger.info(f"成功读取CSV文件，共 {len(df)} 条记录: {csv_path}")
            return df
        except Exception as e:
            logger.error(f"读取CSV文件失败: {e}")
            return None

    def import_single_file(self, csv_path: Path) -> bool:
        """
        导入单个CSV文件

        Args:
            csv_path: CSV文件路径

        Returns:
            是否导入成功
        """
        try:
            if not self._needs_update(csv_path):
                logger.info(f"文件无需更新: {csv_path.name}")
                return True
            
            symbol = self.convert_symbol_format(csv_path.name)
            if not symbol:
                return False
            
            df = self.read_csv_data(csv_path)
            if df is None or df.empty:
                return False
            
            success = self.storage_manager.save_data(symbol, df)
            if success:
                logger.info(f"成功导入数据: {symbol}")
                self._update_fingerprint(csv_path)
            else:
                logger.error(f"导入数据失败: {symbol}")
            
            return success
        except Exception as e:
            logger.error(f"导入单个文件失败: {e}")
            return False

    def import_tdx_day_file(self, day_path: Path) -> bool:
        """
        导入单个通达信 .day 文件

        Args:
            day_path: .day 文件路径

        Returns:
            是否导入成功
        """
        try:
            logger.info(f"开始导入TDX文件: {day_path.name}")
            
            if not day_path.exists():
                logger.error(f"文件不存在: {day_path}")
                return False
            
            symbol = self.tdx_parser.get_symbol_from_filename(day_path.name)
            if not symbol:
                logger.warning(f"无法从文件名提取股票代码: {day_path.name}")
                return False
            
            logger.info(f"处理股票: {symbol}")
            
            df_existing = self.storage_manager.read_local_raw(symbol)
            has_existing_data = not df_existing.empty
            
            if has_existing_data:
                if not self._needs_update(day_path):
                    logger.info(f"文件无变化，跳过更新: {day_path.name}")
                    return True
                logger.info(f"检测到已有数据，执行增量更新: {symbol}")
            else:
                logger.info(f"无现有数据，执行全量更新: {symbol}")
            
            try:
                df = self.tdx_parser.parse_day_file(str(day_path))
                if df is None or df.empty:
                    logger.warning(f"解析 .day 文件失败或数据为空: {day_path.name}")
                    return False
                
                if 'date' not in df.columns and df.index.name == 'date':
                    df = df.reset_index()
                elif 'date' not in df.columns:
                    df = df.reset_index()
                    
                logger.info(f"成功解析 .day 文件，共 {len(df)} 条记录")
            except Exception as e:
                logger.error(f"解析 .day 文件失败: {e}")
                return False
            
            if has_existing_data:
                df_combined = pd.concat([df_existing, df]).drop_duplicates(
                    subset=["date"], keep="last"
                )
                df_combined = df_combined.sort_values("date").reset_index(drop=True)
                df_to_save = df_combined
                logger.info(f"增量合并后共 {len(df_to_save)} 条记录")
            else:
                df_to_save = df.reset_index()
                if 'date' not in df_to_save.columns and df_to_save.index.name == 'date':
                    df_to_save = df_to_save.reset_index()
                logger.info(f"全量数据共 {len(df_to_save)} 条记录")
            
            success = self.storage_manager.save_data(symbol, df_to_save)
            if success:
                logger.info(f"成功导入TDX数据到 daily 目录: {symbol}")
                try:
                    self._update_fingerprint(day_path)
                    logger.debug(f"更新文件指纹成功: {day_path.name}")
                except Exception as e:
                    logger.error(f"更新文件指纹失败: {e}")
            else:
                logger.error(f"导入TDX数据失败: {symbol}")
            
            logger.info(f"导入TDX文件完成: {day_path.name}")
            return success
        except Exception as e:
            logger.error(f"导入TDX文件失败: {e}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            return False

    def import_directory(self, directory: str, max_workers: int = 4) -> int:
        """
        导入目录下的所有CSV文件

        Args:
            directory: 目录路径
            max_workers: 最大工作线程数

        Returns:
            成功导入的文件数
        """
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            logger.error(f"目录不存在或不是目录: {directory}")
            return 0

        csv_files = list(dir_path.glob('**/*.csv'))
        logger.info(f"找到 {len(csv_files)} 个CSV文件: {directory}")

        success_count = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(self.import_single_file, csv_files))
            success_count = sum(results)

        logger.info(f"导入完成，成功: {success_count}, 失败: {len(csv_files) - success_count}")
        return success_count

    def import_tdx_directory(self, directory: str, max_workers: int = 4) -> int:
        """
        导入目录下的所有通达信 .day 文件

        Args:
            directory: 目录路径
            max_workers: 最大工作线程数

        Returns:
            成功导入的文件数
        """
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            logger.error(f"目录不存在或不是目录: {directory}")
            return 0

        day_files = list(dir_path.glob('**/*.day'))
        logger.info(f"找到 {len(day_files)} 个 .day 文件: {directory}")

        success_count = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(self.import_tdx_day_file, day_files))
            success_count = sum(results)

        logger.info(f"导入完成，成功: {success_count}, 失败: {len(day_files) - success_count}")
        return success_count

    def import_all_data(self, max_workers: int = 4) -> int:
        """
        导入所有已下载的数据

        Args:
            max_workers: 最大工作线程数

        Returns:
            成功导入的文件数
        """
        total_success = 0

        sh_dir = self.data_dir / "sh" / "daily"
        if sh_dir.exists():
            logger.info("开始导入上海股票数据...")
            sh_success = self.import_directory(str(sh_dir), max_workers)
            total_success += sh_success

        sz_dir = self.data_dir / "sz" / "daily"
        if sz_dir.exists():
            logger.info("开始导入深圳股票数据...")
            sz_success = self.import_directory(str(sz_dir), max_workers)
            total_success += sz_success

        logger.info(f"所有数据导入完成，成功导入 {total_success} 个文件")
        return total_success

    def parse_gbbq_to_fq(self) -> bool:
        """
        解析gbbq文件到data/fq目录

        Returns:
            是否成功
        """
        if not self.tdx_path:
            logger.error("通达信路径未设置")
            return False

        gbbq_path = self.tdx_path / "T0002" / "hq_cache" / "gbbq"
        if not gbbq_path.exists():
            logger.error(f"gbbq 文件不存在: {gbbq_path}")
            return False

        logger.info(f"开始解析 gbbq 文件: {gbbq_path}")
        
        if not self._needs_update(gbbq_path):
            logger.info("gbbq 文件无变化，跳过更新")
            fq_output = self.fq_dir / "gbbq.parquet"
            if fq_output.exists():
                try:
                    self.gbbq_data = pd.read_parquet(str(fq_output))
                    logger.info(f"加载现有gbbq数据，共 {len(self.gbbq_data)} 条记录")
                    return True
                except Exception as e:
                    logger.warning(f"加载现有gbbq数据失败，将重新解析: {e}")
            else:
                logger.warning("gbbq文件无变化但本地数据不存在，将重新解析")
        
        try:
            df_gbbq = self.tdx_parser.parse_gbbq_file(str(gbbq_path))
            
            if df_gbbq.empty:
                logger.error("解析gbbq文件失败，返回空数据")
                return False
            
            fq_output = self.fq_dir / "gbbq.parquet"
            df_gbbq.to_parquet(str(fq_output), compression="snappy")
            logger.info(f"成功保存gbbq数据到: {fq_output}")
            logger.info(f"gbbq数据共 {len(df_gbbq)} 条记录")
            
            self._update_fingerprint(gbbq_path)
            logger.info("已更新gbbq文件指纹")
            
            self.gbbq_data = df_gbbq
            
            return True
        except Exception as e:
            logger.error(f"解析gbbq文件失败: {e}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            return False

    def import_daily_data(self, max_workers: int = 4) -> int:
        """
        导入日线数据到data/daily目录

        Args:
            max_workers: 最大工作线程数

        Returns:
            成功导入的文件数
        """
        if not self.tdx_path:
            logger.error("通达信路径未设置")
            return 0

        total_success = 0

        sh_dir = self.tdx_path / "vipdoc" / "sh" / "lday"
        if sh_dir.exists():
            logger.info("开始导入通达信上海股票数据...")
            sh_success = self.import_tdx_directory(str(sh_dir), max_workers)
            total_success += sh_success

        sz_dir = self.tdx_path / "vipdoc" / "sz" / "lday"
        if sz_dir.exists():
            logger.info("开始导入通达信深圳股票数据...")
            sz_success = self.import_tdx_directory(str(sz_dir), max_workers)
            total_success += sz_success

        logger.info(f"日线数据导入完成，成功导入 {total_success} 个文件")
        return total_success

    def calculate_factors(self) -> int:
        """
        根据daily和fq数据计算复权因子

        Returns:
            成功计算的文件数
        """
        if self.gbbq_data is None or self.gbbq_data.empty:
            fq_path = self.fq_dir / "gbbq.parquet"
            if fq_path.exists():
                logger.info(f"从 {fq_path} 加载gbbq数据")
                try:
                    self.gbbq_data = pd.read_parquet(str(fq_path))
                    logger.info(f"成功加载gbbq数据，共 {len(self.gbbq_data)} 条记录")
                except Exception as e:
                    logger.error(f"加载gbbq数据失败: {e}")
                    return 0
            else:
                logger.error("gbbq数据不存在，无法计算复权因子")
                return 0

        daily_files = list(self.storage_manager.daily_dir.glob("*.parquet"))
        logger.info(f"开始计算复权因子，共 {len(daily_files)} 个股票文件")

        success_count = self.factor_manager.batch_calculate_factors(daily_files, self.gbbq_data)

        logger.info(f"复权因子计算完成，成功计算 {success_count} 个股票的复权因子")
        return success_count

    def import_tdx_all_data(self, max_workers: int = 4) -> int:
        """
        导入通达信所有数据

        Args:
            max_workers: 最大工作线程数

        Returns:
            成功导入的文件数
        """
        logger.info("开始分步处理TDX数据...")
        
        logger.info("步骤1: 解析gbbq文件到data/fq目录")
        if not self.parse_gbbq_to_fq():
            logger.error("解析gbbq文件失败，终止导入")
            return 0
        
        logger.info("步骤2: 导入日线数据到data/daily目录")
        daily_success = self.import_daily_data(max_workers)
        if daily_success == 0:
            logger.error("导入日线数据失败，终止导入")
            return 0
        
        logger.info("步骤3: 计算复权因子到factors目录")
        factor_success = self.calculate_factors()
        
        logger.info(f"通达信数据导入完成，成功导入 {daily_success} 个文件，计算 {factor_success} 个复权因子")
        return daily_success


def main():
    """
    主函数
    """
    import argparse
    import traceback

    logger.info("启动数据导入工具...")
    
    parser = argparse.ArgumentParser(description='数据导入工具')
    parser.add_argument('--data-dir', default='./data', help='数据存储目录')
    parser.add_argument('--max-workers', type=int, default=4, help='最大工作线程数')
    parser.add_argument('--directory', help='指定导入目录')
    parser.add_argument('--tdx-path', help='通达信安装目录路径')
    parser.add_argument('--tdx', action='store_true', help='导入通达信所有数据')
    parser.add_argument('--tdx-directory', help='指定通达信 .day 文件目录')
    parser.add_argument('--parse-gbbq', action='store_true', help='仅解析gbbq文件到data/fq目录')
    parser.add_argument('--import-daily', action='store_true', help='仅导入日线数据到data/daily目录')
    parser.add_argument('--calculate-factors', action='store_true', help='仅计算复权因子到factors目录')

    args = parser.parse_args()
    logger.info(f"参数解析完成: {args}")

    try:
        logger.info(f"初始化数据导入器，数据目录: {args.data_dir}, 通达信路径: {args.tdx_path}")
        importer = DataImporter(args.data_dir, args.tdx_path)
        logger.info("数据导入器初始化成功")

        if args.parse_gbbq:
            logger.info("开始解析gbbq文件到data/fq目录...")
            success = importer.parse_gbbq_to_fq()
            logger.info(f"解析gbbq文件结果: {success}")
        elif args.import_daily:
            logger.info("开始导入日线数据到data/daily目录...")
            success_count = importer.import_daily_data(args.max_workers)
            logger.info(f"成功导入 {success_count} 个日线数据文件")
        elif args.calculate_factors:
            logger.info("开始计算复权因子到factors目录...")
            success_count = importer.calculate_factors()
            logger.info(f"成功计算 {success_count} 个股票的复权因子")
        elif args.tdx:
            logger.info("开始导入通达信所有数据（分步处理）...")
            success_count = importer.import_tdx_all_data(args.max_workers)
            logger.info(f"成功导入 {success_count} 个通达信文件")
        elif args.tdx_directory:
            logger.info(f"开始导入指定通达信目录: {args.tdx_directory}...")
            success_count = importer.import_tdx_directory(args.tdx_directory, args.max_workers)
            logger.info(f"成功导入 {success_count} 个通达信文件")
        elif args.directory:
            logger.info(f"开始导入指定目录: {args.directory}...")
            success_count = importer.import_directory(args.directory, args.max_workers)
            logger.info(f"成功导入 {success_count} 个文件")
        else:
            logger.info("开始导入所有数据...")
            success_count = importer.import_all_data(args.max_workers)
            logger.info(f"成功导入 {success_count} 个文件")
    except Exception as e:
        logger.error(f"错误: {e}")
        logger.error("详细错误信息:")
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
