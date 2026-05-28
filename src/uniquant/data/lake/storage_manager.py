import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

import pandas as pd
from filelock import FileLock

from ...shared.error_handling import handle_errors
from ...shared.exceptions import DataStorageError
from ...shared.logger_factory import get_logger
from ..utils.normalizer import normalize_column_names as _normalize_columns

logger = get_logger("StorageManager")


class StorageManager:
    """
    存储管理器
    负责文件系统操作，包括文件读写、目录管理等
    """

    def __init__(self, data_dir: str = "./data"):
        """
        初始化存储管理器

        Args:
            data_dir: 数据存储根目录
        """
        self.data_dir = Path(data_dir)
        
        self.lake_dir = self.data_dir / "lake"
        self.quotes_dir = self.lake_dir / "quotes"
        
        self.daily_dir = self.quotes_dir / "daily"
        self.weekly_dir = self.quotes_dir / "weekly"
        self.monthly_dir = self.quotes_dir / "monthly"
        self.min1_dir = self.quotes_dir / "1mins"
        self.min5_dir = self.quotes_dir / "5mins"
        self.factor_dir = self.data_dir / "factors"
        
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self.weekly_dir.mkdir(parents=True, exist_ok=True)
        self.monthly_dir.mkdir(parents=True, exist_ok=True)
        self.min1_dir.mkdir(parents=True, exist_ok=True)
        self.min5_dir.mkdir(parents=True, exist_ok=True)
        self.factor_dir.mkdir(parents=True, exist_ok=True)

        self.all_stock_codes = self._load_all_stock_codes()
        logger.info(f"加载了 {len(self.all_stock_codes)} 个股票代码")

        self.data_types = ["daily", "factor", "index", "1mins", "5mins"]
        self.base_dir = self.data_dir
        logger.info(f"初始化存储管理器，数据目录: {data_dir}")

    def ensure_directory(self, dir_path: str):
        """确保目录存在"""
        dir_path_obj = Path(dir_path)
        if not dir_path_obj.exists():
            dir_path_obj.mkdir(parents=True, exist_ok=True)

    @handle_errors(
        IOError, OSError, DataStorageError, default_return=False, log_level=logging.ERROR
    )
    def write_parquet(
        self, file_path: str, df: pd.DataFrame, overwrite: bool = False
    ) -> bool:
        """写入Parquet文件"""
        if df.empty:
            logger.warning(f"尝试写入空DataFrame到 {file_path}")
            return False

        file_path_obj = Path(file_path)
        dir_path = file_path_obj.parent
        self.ensure_directory(str(dir_path))

        if file_path_obj.exists() and not overwrite:
            logger.warning(f"文件已存在: {file_path} 且 overwrite 为 False. 跳过写入.")
            return False

        lock_path = str(file_path_obj.with_suffix(file_path_obj.suffix + ".lock"))
        with FileLock(lock_path):
            try:
                df.to_parquet(file_path, compression="snappy")
                logger.info(f"成功写入数据到 {file_path}")
                return True
            except Exception as e:
                logger.error(f"写入数据到 {file_path} 失败: {e}")
                return False

    @handle_errors(
        IOError,
        OSError,
        DataStorageError,
        default_return=pd.DataFrame(),
        log_level=logging.ERROR,
    )
    def read_parquet(self, file_path: str, normalize: bool = True) -> pd.DataFrame:
        """读取Parquet文件"""
        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            logger.warning(f"文件不存在: {file_path}")
            return pd.DataFrame()

        try:
            df = pd.read_parquet(file_path)
            if normalize and not df.empty:
                df = self.normalize_dataframe_columns(df)
            logger.info(f"成功读取数据从 {file_path}, 共 {len(df)} 条记录")
            return df
        except Exception as e:
            logger.error(f"读取数据从 {file_path} 失败: {e}")
            return pd.DataFrame()

    @handle_errors(IOError, OSError, default_return=False, log_level=logging.ERROR)
    def delete_file(self, file_path: str) -> bool:
        """删除文件"""
        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            logger.warning(f"文件不存在: {file_path}")
            return True

        try:
            file_path_obj.unlink()
            logger.info(f"删除文件: {file_path}")
            lock_path_obj = file_path_obj.with_suffix(file_path_obj.suffix + ".lock")
            if lock_path_obj.exists():
                lock_path_obj.unlink()
                logger.info(f"删除锁文件: {lock_path_obj}")
            return True
        except Exception as e:
            logger.error(f"删除文件 {file_path} 失败: {e}")
            return False

    def list_files(self, dir_path: str, extension: str = ".parquet") -> list:
        """列出目录中的文件"""
        files: List[str] = []
        dir_path_obj = Path(dir_path)
        if not dir_path_obj.exists():
            return files

        try:
            for file_name in dir_path_obj.iterdir():
                if file_name.name.endswith(extension):
                    files.append(file_name.name)
        except Exception as e:
            logger.error(f"列出目录 {dir_path} 中的文件失败: {e}")

        return files

    def file_exists(self, file_path: str) -> bool:
        """检查文件是否存在"""
        file_path_obj = Path(file_path)
        return file_path_obj.exists()

    def _load_all_stock_codes(self) -> set:
        """加载全量股票代码并统一格式为 XXXXXX.SH/SZ/BJ"""
        stock_codes_file = self.data_dir / "all_stock_codes.csv"
        if not stock_codes_file.exists():
            logger.warning(f"全量股票代码文件不存在: {stock_codes_file}")
            return set()
        
        try:
            df = pd.read_csv(stock_codes_file, encoding='utf-8-sig')
            code_column = None
            if "code" in df.columns:
                code_column = df["code"].astype(str)
            elif "代码" in df.columns:
                code_column = df["代码"].astype(str)
            else:
                logger.warning("全量股票代码文件缺少 'code' 或 '代码' 列")
                return set()
            
            normalized_codes = set()
            for code in code_column:
                normalized = self._normalize_stock_code(code)
                if normalized:
                    normalized_codes.add(normalized)
            
            logger.info(f"加载并标准化了 {len(normalized_codes)} 个股票代码")
            return normalized_codes
        except Exception as e:
            logger.error(f"加载全量股票代码失败: {e}")
            return set()
    
    def _normalize_stock_code(self, code: str) -> Optional[str]:
        """将各种格式的股票代码统一为标准格式 XXXXXX.SH/SZ/BJ"""
        if not code or pd.isna(code):
            return None
        
        code = str(code).strip().upper()
        
        if "." in code:
            parts = code.split(".")
            if len(parts) == 2:
                prefix_or_suffix, num_part = parts[0], parts[1]
                if prefix_or_suffix in ["SH", "SZ", "BJ"]:
                    return f"{num_part}.{prefix_or_suffix}"
                elif num_part in ["SH", "SZ", "BJ"]:
                    return f"{prefix_or_suffix}.{num_part}"
        
        clean_code = code.replace(".", "").replace("SH", "").replace("SZ", "").replace("BJ", "")
        clean_code = clean_code.lstrip("SH").lstrip("SZ").lstrip("BJ")
        
        if clean_code.startswith("6"):
            return f"{clean_code}.SH"
        elif clean_code.startswith(("00", "30")):
            return f"{clean_code}.SZ"
        elif clean_code.startswith(("83", "87", "43")):
            return f"{clean_code}.BJ"
        
        return f"{clean_code}.SH"
    
    def _get_stock_suffix(self, symbol: str) -> str:
        """根据股票代码获取正确的后缀"""
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        clean_symbol = clean_symbol.replace("sh", "").replace("sz", "").replace("bj", "").upper()
        
        if clean_symbol.startswith("6"):
            preferred_suffix = ".SH"
            if f"{clean_symbol}{preferred_suffix}" in self.all_stock_codes:
                return preferred_suffix
            return ".SH"
        elif clean_symbol.startswith(("00", "30")):
            preferred_suffix = ".SZ"
            if f"{clean_symbol}{preferred_suffix}" in self.all_stock_codes:
                return preferred_suffix
            if f"{clean_symbol}.SH" in self.all_stock_codes:
                return ".SH"
            return ".SZ"
        elif clean_symbol.startswith(("83", "87", "43")):
            preferred_suffix = ".BJ"
            if f"{clean_symbol}{preferred_suffix}" in self.all_stock_codes:
                return preferred_suffix
            return ".BJ"
        
        for suffix in [".SH", ".SZ", ".BJ"]:
            if f"{clean_symbol}{suffix}" in self.all_stock_codes:
                return suffix
        
        if clean_symbol.startswith("6"):
            return ".SH"
        elif clean_symbol.startswith(("00", "30")):
            return ".SZ"
        elif clean_symbol.startswith(("83", "87", "43")):
            return ".BJ"
        
        return ""
    
    def read_local_raw(self, symbol: str) -> pd.DataFrame:
        """读取本地原始数据"""
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        clean_symbol = clean_symbol.replace("sh", "").replace("sz", "").replace("bj", "").upper()
        
        suffix = self._get_stock_suffix(clean_symbol)
        standard_symbol = f"{clean_symbol}{suffix}"
        
        possible_symbols = [
            standard_symbol,
            f"{clean_symbol}.SH",
            f"{clean_symbol}.SZ",
            f"{clean_symbol}.BJ",
            clean_symbol,
            symbol,
        ]
        
        seen = set()
        for test_symbol in possible_symbols:
            if test_symbol in seen:
                continue
            seen.add(test_symbol)
            
            file_path = self.daily_dir / f"{test_symbol}.parquet"
            df = self.read_parquet(str(file_path))
            if not df.empty:
                logger.info(f"成功读取数据: {test_symbol}")
                return df
        
        logger.warning(f"未找到股票 {symbol} 的数据")
        return pd.DataFrame()

    def read_local_factor(self, symbol: str) -> pd.DataFrame:
        """读取本地复权因子数据"""
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        clean_symbol = clean_symbol.replace("sh", "").replace("sz", "").replace("bj", "").upper()
        
        suffix = self._get_stock_suffix(clean_symbol)
        standard_symbol = f"{clean_symbol}{suffix}"
        
        possible_symbols = [
            standard_symbol,
            f"{clean_symbol}.SH",
            f"{clean_symbol}.SZ",
            f"{clean_symbol}.BJ",
            clean_symbol,
            symbol,
        ]
        
        seen = set()
        for test_symbol in possible_symbols:
            if test_symbol in seen:
                continue
            seen.add(test_symbol)
            
            file_path = self.factor_dir / f"{test_symbol}.parquet"
            df = self.read_parquet(str(file_path))
            if not df.empty:
                logger.info(f"成功读取因子数据: {test_symbol}")
                return df
        
        logger.warning(f"未找到股票 {symbol} 的因子数据")
        return pd.DataFrame()

    def save_data(self, symbol: str, df: pd.DataFrame):
        """原子写入数据"""
        file_path = self.daily_dir / f"{symbol}.parquet"
        temp_path = file_path.with_suffix(".tmp")

        if not self.write_parquet(str(temp_path), df, overwrite=True):
            logger.error(f"写入临时文件失败: {temp_path}")
            return False

        try:
            if file_path.exists():
                file_path.unlink()
            temp_path.rename(file_path)
            logger.info(f"原子写入成功: {file_path}")
            return True
        except Exception as e:
            logger.error(f"原子替换失败: {e}")
            if temp_path.exists():
                temp_path.unlink()
            return False

    def save_factor(self, symbol: str, df: pd.DataFrame):
        """原子写入复权因子数据"""
        file_path = self.factor_dir / f"{symbol}.parquet"
        temp_path = file_path.with_suffix(".tmp")

        if not self.write_parquet(str(temp_path), df, overwrite=True):
            logger.error(f"写入因子临时文件失败: {temp_path}")
            return False

        try:
            if file_path.exists():
                file_path.unlink()
            temp_path.rename(file_path)
            logger.info(f"原子写入因子成功: {file_path}")
            return True
        except Exception as e:
            logger.error(f"原子替换因子失败: {e}")
            if temp_path.exists():
                temp_path.unlink()
            return False

    def has_data(self, symbol: str) -> bool:
        file_path = self.daily_dir / f"{symbol}.parquet"
        return file_path.exists()

    def get_symbols(self):
        """获取所有已存储的股票代码"""
        symbols = []
        for file in self.daily_dir.glob("*.parquet"):
            symbols.append(file.stem)
        logger.info(f"获取到 {len(symbols)} 个已存储的股票代码")
        return symbols

    def clean_data(self, symbol):
        """清理并重建数据"""
        daily_file = self.daily_dir / f"{symbol}.parquet"
        if daily_file.exists():
            daily_file.unlink()
            logger.info(f"清理日线数据: {daily_file}")

        factor_file = self.factor_dir / f"{symbol}.parquet"
        if factor_file.exists():
            factor_file.unlink()
            logger.info(f"清理因子数据: {factor_file}")

    def synthesize_weekly(self, symbol: str) -> pd.DataFrame:
        """从日线数据合成周线

        规则:
        - open: 同一周第一个交易日的 open
        - high: 同一周最高价
        - low: 同一周最低价
        - close: 同一周最后一个交易日的 close
        - volume: 同一周成交量合计
        - amount: 同一周成交额合计

        Args:
            symbol: 股票代码

        Returns:
            合成后的周线 DataFrame
        """
        daily = self.read_data(symbol=symbol, data_type="daily")
        if daily is None or daily.empty:
            logger.warning(f"无日线数据可供合成周线: {symbol}")
            return pd.DataFrame()

        if "date" not in daily.columns:
            logger.warning(f"日线数据缺少 date 列: {symbol}")
            return pd.DataFrame()

        daily = daily.copy()
        daily["date"] = pd.to_datetime(daily["date"])
        daily["_year"] = daily["date"].dt.isocalendar().year.astype(int)
        daily["_week"] = daily["date"].dt.isocalendar().week.astype(int)

        agg_dict = {}
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in daily.columns:
                if col == "open":
                    agg_dict[col] = "first"
                elif col == "high":
                    agg_dict[col] = "max"
                elif col == "low":
                    agg_dict[col] = "min"
                elif col == "close":
                    agg_dict[col] = "last"
                else:
                    agg_dict[col] = "sum"

        if not agg_dict:
            logger.warning(f"日线数据无可聚合列: {symbol}")
            return pd.DataFrame()

        weekly = daily.groupby(["_year", "_week"]).agg(agg_dict).reset_index()
        weekly = weekly.rename(columns={"_year": "year", "_week": "week"})

        self.write_data(symbol=symbol, df=weekly, data_type="weekly")
        logger.info(f"合成周线完成: {symbol}, 共 {len(weekly)} 条")
        return weekly

    def synthesize_monthly(self, symbol: str) -> pd.DataFrame:
        """从日线数据合成月线

        规则:
        - open: 同月第一个交易日的 open
        - high: 同月最高价
        - low: 同月最低价
        - close: 同月最后一个交易日的 close
        - volume: 同月成交量合计
        - amount: 同月成交额合计

        Args:
            symbol: 股票代码

        Returns:
            合成后的月线 DataFrame
        """
        daily = self.read_data(symbol=symbol, data_type="daily")
        if daily is None or daily.empty:
            logger.warning(f"无日线数据可供合成月线: {symbol}")
            return pd.DataFrame()

        if "date" not in daily.columns:
            logger.warning(f"日线数据缺少 date 列: {symbol}")
            return pd.DataFrame()

        daily = daily.copy()
        daily["date"] = pd.to_datetime(daily["date"])
        daily["_year"] = daily["date"].dt.year
        daily["_month"] = daily["date"].dt.month

        agg_dict = {}
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in daily.columns:
                if col == "open":
                    agg_dict[col] = "first"
                elif col == "high":
                    agg_dict[col] = "max"
                elif col == "low":
                    agg_dict[col] = "min"
                elif col == "close":
                    agg_dict[col] = "last"
                else:
                    agg_dict[col] = "sum"

        if not agg_dict:
            logger.warning(f"日线数据无可聚合列: {symbol}")
            return pd.DataFrame()

        monthly = daily.groupby(["_year", "_month"]).agg(agg_dict).reset_index()
        monthly = monthly.rename(columns={"_year": "year", "_month": "month"})

        self.write_data(symbol=symbol, df=monthly, data_type="monthly")
        logger.info(f"合成月线完成: {symbol}, 共 {len(monthly)} 条")
        return monthly

    # --- 兼容性方法 (Compat with legacy DataLake) ---

    def _get_file_path(self, symbol: str, data_type: str = "daily") -> Path:
        """获取文件路径的内部方法"""
        if data_type == "daily" or data_type == "stock":
            return self.daily_dir / f"{symbol}.parquet"
        elif data_type == "weekly":
            return self.weekly_dir / f"{symbol}.parquet"
        elif data_type == "monthly":
            return self.monthly_dir / f"{symbol}.parquet"
        elif data_type == "factor":
            return self.factor_dir / f"{symbol}.parquet"
        elif data_type == "index":
            index_dir = self.lake_dir / "index"
            self.ensure_directory(str(index_dir))
            return index_dir / f"{symbol}.parquet"
        elif data_type == "1mins" or data_type == "min1":
            return self.min1_dir / f"{symbol}.parquet"
        elif data_type == "5mins" or data_type == "min5":
            return self.min5_dir / f"{symbol}.parquet"
        else:
            return self.base_dir / data_type / f"{symbol}.parquet"

    def read_data(
        self, symbol: str, data_type: str = "daily", **kwargs
    ) -> pd.DataFrame:
        """从对应目录读取数据"""
        file_path = self._get_file_path(symbol, data_type)
        return self.read_parquet(str(file_path))

    def write_data(
        self, symbol: str, df: pd.DataFrame, data_type: str = "daily", **kwargs
    ):
        """写入数据到对应目录"""
        file_path = self._get_file_path(symbol, data_type)
        self.ensure_directory(str(file_path.parent))

        temp_path = file_path.with_suffix(".tmp")
        if not self.write_parquet(str(temp_path), df, overwrite=True):
            logger.error(f"写入数据临时文件失败: {temp_path}")
            return False

        try:
            if file_path.exists():
                file_path.unlink()
            temp_path.rename(file_path)
            logger.info(f"数据写入成功: {file_path}")
            return True
        except Exception as e:
            logger.error(f"原子替换失败: {e}")
            if temp_path.exists():
                temp_path.unlink()
            return False

    def delete_data(self, symbol: str, data_type: str = "daily") -> bool:
        """删除数据"""
        file_path = self._get_file_path(symbol, data_type)
        return self.delete_file(str(file_path))

    def batch_read_data(
        self, symbols: List[str], data_type: str = "daily", **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """批量读取多个标的的数据"""
        results: Dict[str, pd.DataFrame] = {}
        
        for symbol in symbols:
            try:
                df = self.read_data(symbol, data_type, **kwargs)
                if df is not None and not df.empty:
                    results[symbol] = df
            except Exception as e:
                logger.warning(f"Failed to read {symbol}: {e}")
                continue
                
        return results

    def load_portfolio(self) -> Dict[str, Any]:
        """加载投资组合数据 (兼容性占位)"""
        portfolio_path = self.base_dir / "portfolio.parquet"
        if portfolio_path.exists():
            df = self.read_parquet(str(portfolio_path))
            return df.to_dict(orient="records") if not df.empty else {}
        return {}
    
    def normalize_dataframe_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化DataFrame列名"""
        return _normalize_columns(df)
    
    def get_stock_metadata(self, code: str) -> Optional[Dict[str, Any]]:
        """获取股票元数据"""
        from ..managers.stock_metadata_manager import StockMetadataManager
        
        manager = StockMetadataManager(str(self.data_dir))
        info = manager.get_stock_info(code)
        
        if info:
            return {
                "code": info.code,
                "name": info.name,
                "market": info.market,
                "sector": info.sector,
                "ipo_date": info.ipo_date,
                "delist_date": info.delist_date,
                "stock_type": info.stock_type,
                "stock_status": info.stock_status,
            }
        return None
