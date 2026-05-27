"""
通达信数据更新器
负责批量更新通达信日线数据和GBBQ数据
智能更新策略：
- 日线数据：无数据时全量更新，有数据时校验后增量更新
- GBBQ数据：校验文件变化后才更新
"""

import os
import json
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Dict

import pandas as pd

from ...shared.logger_factory import get_logger
from ...data.sources.tdx import TdxSource
from ...data.lake.storage_manager import StorageManager
from ...data.pipeline.data_cleaner import DataCleaner
from ...data.pipeline.data_validator import DataValidator
from .baostock_cache_manager import create_baostock_cache
from pytdx.reader import GbbqReader

logger = get_logger("TdxUpdater")


class TdxUpdater:
    """
    通达信数据更新器
    负责批量更新通达信日线数据和GBBQ数据
    """

    def __init__(self, data_dir: str = "./data", tdx_path: Optional[str] = None):
        """
        初始化通达信数据更新器

        Args:
            data_dir: 数据存储目录
            tdx_path: 通达信安装目录路径
        """
        self.data_dir = Path(data_dir)
        self.storage_manager = StorageManager(data_dir)
        self.tdx_source = TdxSource(tdx_path)
        self.data_cleaner = DataCleaner()
        self.data_validator = DataValidator()

        self.fq_dir = self.data_dir / "fq"
        self.fq_dir.mkdir(parents=True, exist_ok=True)
        
        self.fingerprint_file = self.data_dir / ".tdx_fingerprints.json"
        self.file_fingerprints = self._load_fingerprints()
        
        # 加载股票代码类型数据
        self.stock_codes_data = self._load_stock_codes()
        # 允许的品种类型
        self.allowed_types = {'1', '2', '5'}  # 1: 普通股票, 2: 指数, 5: ETF
        # 允许上市状态
        self.allowed_status = {1}  # 1: 正常上市, 0: 退市

    def _load_stock_codes(self) -> Optional[pd.DataFrame]:
        """
        加载股票代码类型数据
        
        Returns:
            Optional[pd.DataFrame]: 股票代码类型数据，失败返回 None
        """
        stock_codes_path = self.data_dir / "all_stock_codes.csv"
        if stock_codes_path.exists():
            try:
                df = pd.read_csv(stock_codes_path, encoding='utf-8')
                logger.info(f"成功加载股票代码类型数据，共 {len(df)} 条记录")
                return df
            except (OSError, ValueError, pd.errors.ParserError) as e:
                logger.error(f"加载股票代码类型数据失败: {e}")
                return None
        else:
            logger.warning(f"股票代码类型文件不存在: {stock_codes_path}")
            return None

    @staticmethod
    def is_allowed_security(code: str, exchange: str) -> bool:
        if exchange not in {"sz", "sh", "bj"}:
            return False
        if not code or not code.isdigit():
            return False
        return True

    def _fetch_active_codes(self):
        codes = []
        for exchange in ["sz", "sh", "bj"]:
            df = self._get_security_list(exchange)
            if df is not None and not df.empty:
                codes.extend(df["code"].tolist())
        return codes

    def _load_fingerprints(self) -> Dict[str, Dict]:
        """加载文件指纹记录"""
        if self.fingerprint_file.exists():
            try:
                with open(self.fingerprint_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content:
                        return {}
                    return json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"指纹文件损坏 (JSON解析错误): {e}，将重建指纹文件")
                self._backup_corrupted_fingerprint()
                return {}
            except (OSError, ValueError) as e:
                logger.error(f"加载文件指纹失败: {e}")
                return {}
        return {}

    def _backup_corrupted_fingerprint(self):
        """备份损坏的指纹文件"""
        try:
            if self.fingerprint_file.exists():
                backup_path = self.fingerprint_file.with_suffix('.json.bak')
                self.fingerprint_file.rename(backup_path)
                logger.info(f"已备份损坏的指纹文件到: {backup_path}")
        except OSError as e:
            logger.error(f"备份损坏指纹文件失败: {e}")

    def _save_fingerprints(self):
        """保存文件指纹记录 (原子写入)"""
        try:
            self.fingerprint_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.fingerprint_file.with_suffix('.json.tmp')
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.file_fingerprints, f, indent=2, ensure_ascii=False)
            
            if self.fingerprint_file.exists():
                self.fingerprint_file.unlink()
            temp_file.rename(self.fingerprint_file)
        except OSError as e:
            logger.error(f"保存文件指纹失败: {e}")
            temp_file = self.fingerprint_file.with_suffix('.json.tmp')
            if temp_file.exists():
                temp_file.unlink()

    def _get_file_fingerprint(self, file_path: Path) -> Dict:
        """获取文件指纹"""
        try:
            stat = file_path.stat()
            return {
                'mtime': stat.st_mtime,
                'size': stat.st_size
            }
        except OSError as e:
            logger.error(f"获取文件指纹失败: {e}")
            return {}

    def _normalize_path(self, file_path: Path) -> str:
        """标准化文件路径"""
        return str(file_path.absolute()).replace('\\', '/')

    def _needs_update(self, file_path: Path) -> bool:
        """检查文件是否需要更新"""
        try:
            file_key = self._normalize_path(file_path)
            current_fingerprint = self._get_file_fingerprint(file_path)
            
            if not current_fingerprint:
                return True
            
            old_fingerprint = self.file_fingerprints.get(file_key, {})
            if not old_fingerprint:
                return True
            
            return current_fingerprint != old_fingerprint
        except (OSError, ValueError, TypeError) as e:
            logger.error(f"检查文件更新状态失败: {e}")
            return True

    def _update_fingerprint(self, file_path: Path):
        """更新文件指纹"""
        try:
            file_key = self._normalize_path(file_path)
            fingerprint = self._get_file_fingerprint(file_path)
            if fingerprint:
                self.file_fingerprints[file_key] = fingerprint
                self._save_fingerprints()
        except (OSError, TypeError) as e:
            logger.error(f"更新文件指纹失败: {e}")

    def get_all_day_files(self) -> List[str]:
        """
        获取通达信安装目录下的所有 .day 文件

        Returns:
            List[str]: .day 文件路径列表
        """
        if not self.tdx_source.tdx_path:
            logger.error("通达信路径未设置")
            return []

        day_files = []
        markets = ["sh", "sz"]

        for market in markets:
            day_dir = self.tdx_source.tdx_path / "vipdoc" / market / "lday"
            if day_dir.exists():
                for file_path in day_dir.glob("*.day"):
                    day_files.append(str(file_path))

        logger.info(f"找到 {len(day_files)} 个 .day 文件")
        return day_files

    def parse_day_file(self, file_path: str) -> Optional[pd.DataFrame]:
        """
        解析单个 .day 文件

        Args:
            file_path: .day 文件路径

        Returns:
            Optional[pd.DataFrame]: 解析后的数据，失败返回 None
        """
        try:
            # 从文件名提取股票代码
            filename = os.path.basename(file_path)
            symbol_part = filename.split('.')[0]
            
            if symbol_part.startswith('sh'):
                code = symbol_part[2:]
                symbol = f"{code}.SH"
            elif symbol_part.startswith('sz'):
                code = symbol_part[2:]
                symbol = f"{code}.SZ"
            else:
                logger.warning(f"无法识别的文件名格式: {filename}")
                return None

            # 使用 TdxSource 解析数据
            df = self.tdx_source.fetch_daily(symbol, "19900101", "20991231")
            
            if not df.empty:
                logger.info(f"成功解析 {symbol} 的 .day 文件，共 {len(df)} 条记录")
                return df
            else:
                logger.warning(f"解析 {symbol} 的 .day 文件失败，返回空数据")
                return None

        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.error(f"解析 .day 文件失败 {file_path}: {e}")
            return None

    def update_daily_data_full(self, max_workers: int = 8) -> int:
        """
        全量更新通达信日线数据

        Args:
            max_workers: 线程池大小

        Returns:
            int: 成功更新的股票数量
        """
        logger.info("开始全量更新通达信日线数据")

        day_files = self.get_all_day_files()
        if not day_files:
            logger.error("未找到 .day 文件")
            return 0

        success_count = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_file = {
                executor.submit(self.parse_day_file, file_path): file_path
                for file_path in day_files
            }

            # 处理结果
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    df = future.result()
                    if df is not None and not df.empty:
                        # 从文件名提取股票代码
                        filename = os.path.basename(file_path)
                        symbol_part = filename.split('.')[0]
                        
                        if symbol_part.startswith('sh'):
                            code = symbol_part[2:]
                            symbol = f"{code}.SH"
                        elif symbol_part.startswith('sz'):
                            code = symbol_part[2:]
                            symbol = f"{code}.SZ"
                        else:
                            continue

                        # 清洗和验证数据
                        df_clean = self.data_cleaner.clean(df)
                        if self.data_validator.validate(df_clean):
                            # 检查是否为允许的品种类型
                            if TdxUpdater.is_allowed_security(code, symbol_part[:2]):
                                # 保存数据
                                if self.storage_manager.save_data(symbol, df_clean):
                                    success_count += 1
                                    logger.info(f"成功更新 {symbol} 的日线数据")
                            else:
                                logger.info(f"跳过不允许的品种类型: {symbol}")
                except (OSError, ValueError, KeyError, TypeError) as e:
                    logger.error(f"处理文件 {file_path} 失败: {e}")

        logger.info(f"全量更新完成，成功更新 {success_count} 只股票的日线数据")
        return success_count

    def update_daily_data_incremental(self, max_workers: int = 8) -> int:
        """
        增量更新通达信日线数据

        Args:
            max_workers: 线程池大小

        Returns:
            int: 成功更新的股票数量
        """
        logger.info("开始增量更新通达信日线数据")

        day_files = self.get_all_day_files()
        if not day_files:
            logger.error("未找到 .day 文件")
            return 0

        success_count = 0
        skipped_count = 0
        updated_symbols = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_file = {
                executor.submit(self.parse_day_file, file_path): file_path
                for file_path in day_files
            }

            # 处理结果
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    df_new = future.result()
                    if df_new is not None and not df_new.empty:
                        # 从文件名提取股票代码
                        filename = os.path.basename(file_path)
                        symbol_part = filename.split('.')[0]
                        
                        if symbol_part.startswith('sh'):
                            code = symbol_part[2:]
                            symbol = f"{code}.SH"
                        elif symbol_part.startswith('sz'):
                            code = symbol_part[2:]
                            symbol = f"{code}.SZ"
                        else:
                            continue

                        # 读取现有数据
                        df_old = self.storage_manager.read_local_raw(symbol)

                        # 检查是否需要更新：比较最新日期
                        needs_update = False
                        if df_old.empty:
                            # 本地无数据，需要更新
                            needs_update = True
                            df_combined = df_new
                        else:
                            # 获取新旧数据的最新日期
                            old_max_date = df_old["date"].max()
                            new_max_date = df_new["date"].max()
                            
                            if pd.to_datetime(new_max_date) > pd.to_datetime(old_max_date):
                                # 通达信有新数据，需要更新
                                needs_update = True
                                # 合并数据
                                df_combined = pd.concat([df_old, df_new]).drop_duplicates(
                                    subset=["date"], keep="last"
                                )
                                df_combined = df_combined.sort_values("date").reset_index(drop=True)
                            else:
                                # 本地数据已是最新，跳过
                                needs_update = False
                                skipped_count += 1
                                if skipped_count <= 5 or skipped_count % 1000 == 0:
                                    logger.debug(f"跳过 {symbol}，本地数据已是最新 (最新日期: {old_max_date})")

                        if needs_update:
                            # 清洗和验证数据
                            df_clean = self.data_cleaner.clean(df_combined)
                            if self.data_validator.validate(df_clean):
                                # 保存数据
                                if self.storage_manager.save_data(symbol, df_clean):
                                    success_count += 1
                                    updated_symbols.append(symbol)
                                    if success_count <= 5 or success_count % 100 == 0:
                                        logger.info(f"成功增量更新 {symbol} 的日线数据 (新日期: {new_max_date})")
                except (OSError, ValueError, KeyError, TypeError) as e:
                    logger.error(f"处理文件 {file_path} 失败: {e}")

        logger.info(f"增量更新完成: 成功更新 {success_count} 只，跳过 {skipped_count} 只")
        if updated_symbols:
            logger.info(f"更新的股票示例: {updated_symbols[:10]}")
        return success_count

    def get_gbbq_path(self) -> Optional[str]:
        """
        获取通达信 GBBQ 文件路径

        Returns:
            Optional[str]: GBBQ 文件路径，失败返回 None
        """
        if not self.tdx_source.tdx_path:
            logger.error("通达信路径未设置")
            return None

        gbbq_path = self.tdx_source.tdx_path / "T0002" / "hq_cache" / "gbbq"
        if gbbq_path.exists():
            logger.info(f"找到 GBBQ 文件: {gbbq_path}")
            return str(gbbq_path)
        else:
            logger.error(f"GBBQ 文件不存在: {gbbq_path}")
            return None

    def update_gbbq_data_full(self) -> bool:
        """
        全量更新 GBBQ 数据
        校验文件变化后才更新，无变化不更新

        Returns:
            bool: 是否更新成功
        """
        logger.info("开始全量更新 GBBQ 数据")

        gbbq_path = self.get_gbbq_path()
        if not gbbq_path:
            return False

        gbbq_path_obj = Path(gbbq_path)
        
        if not self._needs_update(gbbq_path_obj):
            logger.info("GBBQ 文件无变化，跳过更新")
            output_path = self.fq_dir / "gbbq.parquet"
            if output_path.exists():
                logger.info("使用现有 GBBQ 数据")
                return True
            else:
                logger.warning("GBBQ文件无变化但本地数据不存在，将重新解析")

        try:
            logger.info("使用 pytdx 解析 GBBQ 文件...")
            reader = GbbqReader()
            df_gbbq = reader.get_df(gbbq_path)

            if df_gbbq.empty:
                logger.warning("解析 GBBQ 文件返回空数据，跳过更新")
                return False

            logger.info(f"pytdx 原始列名: {df_gbbq.columns.tolist()}")
            logger.info(f"pytdx 原始数据形状: {df_gbbq.shape}")

            logger.info("开始转换列名...")
            new_df = pd.DataFrame()
            
            column_mapping = {
                'code': 'code',
                'market': 'market',
                'datetime': 'date',
                'category': 'category',
                'hongli_panqianliutong': 'cash_div',
                'peigujia_qianzongguben': 'rights_price',
                'songgu_qianzongguben': 'split_ratio',
                'peigu_houzongguben': 'rights_ratio'
            }
            
            for old_col, new_col in column_mapping.items():
                if old_col in df_gbbq.columns:
                    new_df[new_col] = df_gbbq[old_col]
                    logger.info(f"映射列: {old_col} -> {new_col}")
                else:
                    new_df[new_col] = 0.0
                    logger.warning(f"列 {old_col} 不存在，使用默认值 0.0")
            
            target_columns = [
                'code', 'market', 'date', 'category', 
                'cash_div', 'split_ratio', 'rights_ratio', 'rights_price'
            ]
            new_df = new_df[target_columns]
            
            logger.info(f"转换后列名: {new_df.columns.tolist()}")
            logger.info(f"转换后数据形状: {new_df.shape}")

            output_path = self.fq_dir / "gbbq.parquet"
            logger.info(f"保存 GBBQ 数据到: {output_path}")
            new_df.to_parquet(str(output_path), compression="snappy")
            
            self._update_fingerprint(gbbq_path_obj)
            logger.info("已更新 GBBQ 文件指纹")

            logger.info(f"成功保存 GBBQ 数据到: {output_path}")
            logger.info(f"GBBQ 数据形状: {new_df.shape}")
            return True

        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.error(f"更新 GBBQ 数据失败: {e}")
            import traceback
            logger.error(f"堆栈信息: {traceback.format_exc()}")
            return False

    def update_gbbq_data_incremental(self) -> bool:
        """
        增量更新 GBBQ 数据
        校验文件变化后才更新，无变化不更新

        Returns:
            bool: 是否更新成功
        """
        logger.info("开始增量更新 GBBQ 数据")

        gbbq_path = self.get_gbbq_path()
        if not gbbq_path:
            return False

        gbbq_path_obj = Path(gbbq_path)
        
        if not self._needs_update(gbbq_path_obj):
            logger.info("GBBQ 文件无变化，跳过更新")
            output_path = self.fq_dir / "gbbq.parquet"
            if output_path.exists():
                logger.info("使用现有 GBBQ 数据")
                return True
            else:
                logger.warning("GBBQ文件无变化但本地数据不存在，将重新解析")

        try:
            logger.info("使用 pytdx 解析 GBBQ 文件...")
            reader = GbbqReader()
            df_new = reader.get_df(gbbq_path)

            if df_new.empty:
                logger.warning("解析 GBBQ 文件返回空数据，跳过更新")
                return False

            logger.info(f"pytdx 原始列名: {df_new.columns.tolist()}")

            logger.info("开始转换列名...")
            new_df = pd.DataFrame()
            
            column_mapping = {
                'code': 'code',
                'market': 'market',
                'datetime': 'date',
                'category': 'category',
                'hongli_panqianliutong': 'cash_div',
                'peigujia_qianzongguben': 'rights_price',
                'songgu_qianzongguben': 'split_ratio',
                'peigu_houzongguben': 'rights_ratio'
            }
            
            for old_col, new_col in column_mapping.items():
                if old_col in df_new.columns:
                    new_df[new_col] = df_new[old_col]
                    logger.info(f"映射列: {old_col} -> {new_col}")
                else:
                    new_df[new_col] = 0.0
                    logger.warning(f"列 {old_col} 不存在，使用默认值 0.0")
            
            target_columns = [
                'code', 'market', 'date', 'category', 
                'cash_div', 'split_ratio', 'rights_ratio', 'rights_price'
            ]
            new_df = new_df[target_columns]
            
            logger.info(f"转换后列名: {new_df.columns.tolist()}")
            logger.info(f"转换后数据形状: {new_df.shape}")

            output_path = self.fq_dir / "gbbq.parquet"
            if output_path.exists():
                df_old = pd.read_parquet(str(output_path))
                # 只保留标准列，丢弃可能遗留的 pytdx 原始列
                target_columns_set = set(target_columns)
                df_old = df_old[[c for c in df_old.columns if c in target_columns_set]]
                df_combined = pd.concat([df_old, new_df]).drop_duplicates(
                    subset=["code", "date"], keep="last"
                )
                df_combined = df_combined.sort_values(["code", "date"]).reset_index(drop=True)
            else:
                df_combined = new_df

            df_combined.to_parquet(str(output_path), compression="snappy")
            
            self._update_fingerprint(gbbq_path_obj)
            logger.info("已更新 GBBQ 文件指纹")

            logger.info(f"成功增量更新 GBBQ 数据到: {output_path}")
            logger.info(f"GBBQ 数据形状: {df_combined.shape}")
            return True

        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.error(f"增量更新 GBBQ 数据失败: {e}")
            import traceback
            logger.error(f"堆栈信息: {traceback.format_exc()}")
            return False

    def update_all_data(self, full_update: bool = False) -> dict:
        """
        更新所有数据
        智能更新策略：
        - 无数据时：全量更新
        - 有数据时：校验后增量更新

        Args:
            full_update: 是否强制全量更新

        Returns:
            dict: 更新结果
        """
        results = {}
        
        logger.info("步骤0: 更新全量股票代码缓存...")
        try:
            create_baostock_cache()
            self.stock_codes_data = self._load_stock_codes()
            logger.info("全量股票代码缓存更新完成")
        except (RuntimeError, ConnectionError, OSError, ImportError) as e:
            logger.warning(f"更新全量股票代码缓存失败: {e}，将继续使用现有缓存")
        
        existing_symbols = self.storage_manager.get_symbols()
        has_existing_data = len(existing_symbols) > 0
        
        if full_update:
            logger.info("强制全量更新模式")
            results["daily"] = self.update_daily_data_full()
            results["gbbq"] = self.update_gbbq_data_full()
        elif has_existing_data:
            logger.info(f"检测到已有 {len(existing_symbols)} 只股票数据，执行智能增量更新")
            results["daily"] = self.update_daily_data_incremental()
            results["gbbq"] = self.update_gbbq_data_incremental()
        else:
            logger.info("无现有数据，执行全量更新")
            results["daily"] = self.update_daily_data_full()
            results["gbbq"] = self.update_gbbq_data_full()

        return results
