
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, List, Any

from ...shared.logger_factory import get_logger
from ...data.lake.storage_manager import StorageManager
from ...data.utils.smart_factor_calculator import SmartFactorCalculator

logger = get_logger("FactorManager")


class FactorManager:
    """
    复权因子管理器
    负责复权因子的计算、存储和管理
    """

    def __init__(self, data_dir: str = "./data"):
        """
        初始化复权因子管理器

        Args:
            data_dir: 数据存储目录
        """
        self.data_dir = Path(data_dir)
        self.factors_dir = self.data_dir / "factors"
        self.factors_dir.mkdir(parents=True, exist_ok=True)
        
        self.calculator = SmartFactorCalculator()
        self._lake = StorageManager(str(self.data_dir))
        
        # 文件指纹记录，用于增量更新
        self.fingerprint_file = self.data_dir / ".factor_fingerprints.json"
        self.file_fingerprints = self._load_fingerprints()
        
        # 加载股票代码状态数据
        self.stock_codes_data = self._load_stock_codes()
        # 允许上市状态
        self.allowed_status = {1}  # 1: 正常上市, 0: 退市
    
    def _load_stock_codes(self) -> Optional[pd.DataFrame]:
        """
        加载股票代码状态数据
        
        Returns:
            Optional[pd.DataFrame]: 股票代码状态数据，失败返回 None
        """
        stock_codes_path = self.data_dir / "all_stock_codes.csv"
        if stock_codes_path.exists():
            try:
                df = pd.read_csv(stock_codes_path, encoding='utf-8')
                logger.info(f"成功加载股票代码状态数据，共 {len(df)} 条记录")
                return df
            except (OSError, ValueError, pd.errors.ParserError) as e:
                logger.error(f"加载股票代码状态数据失败: {e}")
                return None
        else:
            logger.warning(f"股票代码状态文件不存在: {stock_codes_path}")
            return None
    
    def is_listed_stock(self, symbol: str) -> bool:
        return self._lake.has_data(symbol)

    def _load_fingerprints(self) -> Dict[str, Dict[str, Any]]:
        """
        加载文件指纹记录

        Returns:
            文件指纹字典
        """
        try:
            if self.fingerprint_file.exists():
                import json
                with open(self.fingerprint_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content:
                        return json.loads(content)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            logger.error(f"加载文件指纹失败: {e}")
        return {}

    def _save_fingerprints(self):
        """
        保存文件指纹记录
        """
        try:
            import json
            with open(self.fingerprint_file, 'w', encoding='utf-8') as f:
                json.dump(self.file_fingerprints, f, indent=2, ensure_ascii=False)
        except (OSError, TypeError) as e:
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
        except OSError as e:
            logger.error(f"获取文件指纹失败: {e}")
            return {}

    def _needs_update(self, file_path: Path) -> bool:
        """
        检查文件是否需要更新

        Args:
            file_path: 文件路径

        Returns:
            是否需要更新
        """
        try:
            file_key = str(file_path.absolute()).replace('\\', '/')
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
        """
        更新文件指纹

        Args:
            file_path: 文件路径
        """
        try:
            file_key = str(file_path.absolute()).replace('\\', '/')
            fingerprint = self._get_file_fingerprint(file_path)
            if fingerprint:
                self.file_fingerprints[file_key] = fingerprint
                self._save_fingerprints()
        except (OSError, TypeError) as e:
            logger.error(f"更新文件指纹失败: {e}")

    def calculate_factor(self, symbol: str, df_day: pd.DataFrame, df_gbbq: pd.DataFrame) -> pd.DataFrame:
        """
        计算复权因子

        Args:
            symbol: 股票代码
            df_day: 日线数据
            df_gbbq: 除权除息数据

        Returns:
            复权因子数据
        """
        logger.info(f"计算 {symbol} 的复权因子")
        
        # 使用 SmartFactorCalculator 计算复权因子
        df_factor = self.calculator.calculate_cumulative_factor(df_day, df_gbbq)
        
        if df_factor.empty:
            logger.warning(f"未计算到 {symbol} 的复权因子")
            return pd.DataFrame()
        
        return df_factor

    def save_factor(self, symbol: str, df_factor: pd.DataFrame) -> bool:
        """
        保存复权因子

        Args:
            symbol: 股票代码
            df_factor: 复权因子数据

        Returns:
            是否保存成功
        """
        try:
            if df_factor.empty:
                logger.warning(f"复权因子数据为空，跳过保存: {symbol}")
                return False
            
            # 确保数据格式正确
            if 'date' not in df_factor.columns:
                logger.error(f"复权因子数据缺少 'date' 列: {symbol}")
                return False
            
            if 'factor' not in df_factor.columns:
                logger.error(f"复权因子数据缺少 'factor' 列: {symbol}")
                return False
            
            # 确保date列是datetime类型且时区一致
            if not pd.api.types.is_datetime64_any_dtype(df_factor['date']):
                try:
                    df_factor['date'] = pd.to_datetime(df_factor['date'], errors='coerce')
                    df_factor = df_factor.dropna(subset=['date'])
                except (ValueError, TypeError):
                    logger.error(f"日期类型转换失败: {symbol}")
                    return False
            
            # 确保factor列是正确的数值类型
            if not pd.api.types.is_numeric_dtype(df_factor['factor']):
                try:
                    df_factor['factor'] = pd.to_numeric(df_factor['factor'], errors='coerce')
                    df_factor = df_factor.dropna(subset=['factor'])
                except (ValueError, TypeError):
                    logger.error(f"因子值类型转换失败: {symbol}")
                    return False
            
            # 保存为 Parquet 文件
            factor_file = self.factors_dir / f"{symbol}.parquet"
            df_factor.to_parquet(str(factor_file), compression="snappy", index=False)
            
            logger.info(f"成功保存 {symbol} 的复权因子: {len(df_factor)} 条记录")
            return True
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.error(f"保存复权因子失败 {symbol}: {e}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            return False

    def read_factor(self, symbol: str) -> pd.DataFrame:
        """
        读取复权因子

        Args:
            symbol: 股票代码

        Returns:
            复权因子数据
        """
        try:
            factor_file = self.factors_dir / f"{symbol}.parquet"
            if not factor_file.exists():
                logger.warning(f"复权因子文件不存在: {symbol}")
                return pd.DataFrame()
            
            df_factor = pd.read_parquet(str(factor_file))
            logger.info(f"成功读取 {symbol} 的复权因子: {len(df_factor)} 条记录")
            return df_factor
        except (OSError, ValueError, pd.errors.ParserError) as e:
            logger.error(f"读取复权因子失败 {symbol}: {e}")
            return pd.DataFrame()

    def calculate_and_save_factor(self, symbol: str, df_day: pd.DataFrame, df_gbbq: pd.DataFrame) -> bool:
        """
        计算并保存复权因子

        Args:
            symbol: 股票代码
            df_day: 日线数据
            df_gbbq: 除权除息数据

        Returns:
            是否成功
        """
        try:
            # 计算复权因子
            df_factor = self.calculate_factor(symbol, df_day, df_gbbq)
            
            if df_factor.empty:
                return False
            
            # 保存复权因子
            return self.save_factor(symbol, df_factor)
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.error(f"计算并保存复权因子失败 {symbol}: {e}")
            return False

    def batch_calculate_factors(self, daily_files: List[Path], gbbq_data: pd.DataFrame, batch_size: int = 100) -> int:
        """
        批量计算复权因子

        Args:
            daily_files: 日线文件列表
            gbbq_data: 除权除息数据
            batch_size: 批量大小

        Returns:
            成功计算的股票数量
        """
        success_count = 0
        
        logger.info(f"开始批量计算复权因子，共 {len(daily_files)} 个股票文件")
        
        # 预先分组 GBBQ 数据
        if not gbbq_data.empty and 'code' in gbbq_data.columns:
            gbbq_map = dict(list(gbbq_data.groupby('code')))
        else:
            gbbq_map = {}
        
        for i, file_path in enumerate(daily_files):
            try:
                # 提取股票代码和市场
                file_stem = file_path.stem
                market = ''
                symbol_code = ''
                
                if file_stem.startswith('sh'):
                    market = 'SH'
                    symbol_code = file_stem[2:]
                elif file_stem.startswith('sz'):
                    market = 'SZ'
                    symbol_code = file_stem[2:]
                else:
                    # 处理带后缀的格式，如 600000.SH
                    if '.SH' in file_stem:
                        market = 'SH'
                        symbol_code = file_stem.replace('.SH', '')
                    elif '.SZ' in file_stem:
                        market = 'SZ'
                        symbol_code = file_stem.replace('.SZ', '')
                    elif '.BJ' in file_stem:
                        market = 'BJ'
                        symbol_code = file_stem.replace('.BJ', '')
                    else:
                        symbol_code = file_stem
                
                # 跳过 B 股
                if symbol_code.startswith('900') or symbol_code.startswith('200'):
                    continue
                
                # 过滤非指定范围内的股票代码
                if market == 'SH':
                    # 沪市只保留 60xxxx (主板) 和 68xxxx (科创板)
                    if not (symbol_code.startswith('60') or symbol_code.startswith('68')) or len(symbol_code) != 6:
                        logger.info(f"股票代码 {file_stem} 不在指定范围内，跳过")
                        continue
                elif market == 'SZ':
                    # 深市只保留 00xxxx (主板/中小板) 和 30xxxx (创业板)
                    if not (symbol_code.startswith('00') or symbol_code.startswith('30')) or len(symbol_code) != 6:
                        logger.info(f"股票代码 {file_stem} 不在指定范围内，跳过")
                        continue
                else:
                    # 跳过其他市场的股票
                    logger.info(f"股票代码 {file_stem} 不在指定市场范围内，跳过")
                    continue
                
                # 过滤退市股票
                full_symbol = f"{symbol_code}.{market}"
                if not self.is_listed_stock(full_symbol):
                    continue
                
                # 读取日线数据
                df_day = pd.read_parquet(str(file_path))
                
                # 获取对应股票的 GBBQ 数据
                stock_gbbq = gbbq_map.get(symbol_code, pd.DataFrame())
                
                if stock_gbbq.empty:
                    logger.info(f"未找到 {symbol_code} 的除权除息数据，跳过")
                    continue
                
                # 计算并保存复权因子
                success = self.calculate_and_save_factor(file_stem, df_day, stock_gbbq)
                if success:
                    success_count += 1
                
                # 每处理一批保存一次文件指纹
                if (i + 1) % batch_size == 0:
                    self._save_fingerprints()
                    logger.info(f"已处理 {i + 1}/{len(daily_files)} 个股票文件")
                    
            except (OSError, ValueError, KeyError, TypeError) as e:
                logger.error(f"处理 {file_path.stem} 失败: {e}")
                continue
        
        # 保存最后一批的文件指纹
        self._save_fingerprints()
        
        logger.info(f"批量计算完成，成功计算 {success_count} 个股票的复权因子")
        return success_count

    def validate_factor(self, symbol: str, df_factor: pd.DataFrame) -> bool:
        """
        验证复权因子数据质量

        Args:
            symbol: 股票代码
            df_factor: 复权因子数据

        Returns:
            是否验证通过
        """
        try:
            if df_factor.empty:
                logger.warning(f"复权因子数据为空: {symbol}")
                return False
            
            # 检查数据完整性
            if 'date' not in df_factor.columns or 'factor' not in df_factor.columns:
                logger.error(f"复权因子数据缺少必要列: {symbol}")
                return False
            
            # 检查因子值是否合理
            if (df_factor['factor'] <= 0).any():
                logger.error(f"复权因子包含负值或零: {symbol}")
                return False
            
            # 检查因子值范围是否合理
            max_factor = df_factor['factor'].max()
            min_factor = df_factor['factor'].min()
            
            if max_factor > 1000 or min_factor < 0.001:
                logger.warning(f"复权因子范围异常: {symbol}, 最大值={max_factor}, 最小值={min_factor}")
                
            # 检查日期是否排序
            if not df_factor['date'].is_monotonic_increasing:
                logger.error(f"复权因子日期未排序: {symbol}")
                return False
            
            logger.info(f"复权因子数据验证通过: {symbol}")
            return True
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"验证复权因子失败 {symbol}: {e}")
            return False

    def get_factor_stats(self) -> Dict[str, Any]:
        """
        获取复权因子统计信息

        Returns:
            统计信息字典
        """
        try:
            factor_files = list(self.factors_dir.glob("*.parquet"))
            total_factors = len(factor_files)
            
            stats = {
                'total_factors': total_factors,
                'factors_dir': str(self.factors_dir.absolute()),
                'last_updated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            logger.info(f"复权因子统计: {stats}")
            return stats
        except OSError as e:
            logger.error(f"获取复权因子统计失败: {e}")
            return {}
