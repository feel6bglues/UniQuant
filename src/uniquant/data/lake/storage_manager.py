import datetime
import logging
import os
import struct
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

import pandas as pd
from filelock import FileLock

from ...shared.error_handling import handle_errors
from ...shared.exceptions import DataStorageError
from ...shared.logger_factory import get_logger
from ..utils.normalizer import normalize_column_names as _normalize_columns

logger = get_logger("StorageManager")


def is_index_symbol(symbol) -> bool:
    """符号级指数判定 (2026-08-18 P0 数据净化, 与 scripts/wyckoff_full_scan._is_index 语义一致)。

    "000001.SH" -> True (上证指数)
    "399001.SZ" -> True (深证成指)
    "000001.SZ" -> False (平安银行, SZ 主板股票)
    "600000.SH" -> False
    """
    if symbol is None:
        return False
    if _isnan_symbol(symbol):
        return False
    symbol = str(symbol)
    code, sep, exch = symbol.partition(".")
    if not sep or not code.isdigit() or len(code) != 6:
        return False
    return (exch == "SH" and code.startswith("000")) or (
        exch == "SZ" and code.startswith("399")
    )


def _isnan_symbol(symbol) -> bool:
    """NaN 判定 (pd.isna 对 str 安全)"""
    try:
        import pandas as pd

        return bool(pd.isna(symbol))
    except Exception:
        return False


def _format_date_val(val: Any) -> Optional[str]:
    """格式化日期值为标准 YYYY-MM-DD 字符串"""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    try:
        dt = pd.to_datetime(s)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


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
        self.index_dir = self.quotes_dir / "index"
        self.factor_dir = self.data_dir / "factors"
        
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self.weekly_dir.mkdir(parents=True, exist_ok=True)
        self.monthly_dir.mkdir(parents=True, exist_ok=True)
        self.min1_dir.mkdir(parents=True, exist_ok=True)
        self.min5_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.factor_dir.mkdir(parents=True, exist_ok=True)

        self.all_stock_codes = self._load_all_stock_codes()
        logger.info(f"加载了 {len(self.all_stock_codes)} 个股票代码")

        self.data_types = ["daily", "factor", "index", "1mins", "5mins"]
        self.base_dir = self.data_dir
        self._data_sources: Dict[str, str] = {}
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
        
        # 路径遍历校验：确保写入目标在 data_dir 内
        try:
            resolved = file_path_obj.resolve()
            data_dir_resolved = self.data_dir.resolve()
            if not str(resolved).startswith(str(data_dir_resolved)):
                logger.error(f"路径遍历拒绝: {file_path} 不在 {self.data_dir} 内")
                return False
        except (OSError, ValueError) as e:
            logger.error(f"路径解析失败: {e}")
            return False
        
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
        """加载全量股票代码并统一格式为 XXXXXX.SH/SZ/BJ

        R-5 (D5 裁决 A): 主数据文件缺失 → 硬失败，禁止 warning 降级为空集
        （空集会让 get_symbols 静默失效，横截面研究带幸存者偏差）。
        """
        stock_codes_file = self.data_dir / "all_stock_codes.csv"
        if not stock_codes_file.exists():
            raise FileNotFoundError(
                f"全量股票代码文件不存在: {stock_codes_file} (R-5 硬失败)。"
                f"请执行 resync: python -c \"from uniquant.data.managers.baostock_cache_manager "
                f"import create_baostock_cache; create_baostock_cache()\""
            )
        
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
            if not file_path.exists() and is_index_symbol(test_symbol):
                file_path = self.index_dir / f"{test_symbol}.parquet"
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
        if file_path.exists():
            return True
        if is_index_symbol(symbol) and (self.index_dir / f"{symbol}.parquet").exists():
            return True
        return False

    def get_symbols(self, exclude_indices: bool = True):
        """获取所有已存储的股票代码

        Args:
            exclude_indices: 默认 True, 剔除指数 (SH 000xxx / SZ 399xxx, 符号级判定)。
                2026-08-18 P0 净化: daily/ 曾混入 554 指数文件, 因子/扫描管线应只处理股票。
                需要指数时显式传 False。
        """
        symbols = []
        for file in self.daily_dir.glob("*.parquet"):
            symbols.append(file.stem)
        if exclude_indices:
            symbols = [s for s in symbols if not is_index_symbol(s)]
        else:
            if hasattr(self, "index_dir") and self.index_dir.exists():
                for file in self.index_dir.glob("*.parquet"):
                    if file.stem not in symbols:
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

    # --- 数据新鲜度检测 (两级 SLA 架构) ---

    def _read_parquet_max_date(self, file_path: Path) -> Optional[str]:
        """从 parquet 文件中高效提取最大交易日"""
        try:
            import pyarrow.parquet as pq

            pf = pq.ParquetFile(str(file_path))
            if pf.num_row_groups > 0:
                rg = pf.metadata.row_group(pf.num_row_groups - 1)
                for i in range(rg.num_columns):
                    col = rg.column(i)
                    if "date" in col.path_in_schema and col.statistics and col.statistics.has_min_max:
                        d_str = _format_date_val(col.statistics.max)
                        if d_str:
                            return d_str
        except Exception:
            pass

        try:
            df = pd.read_parquet(file_path, columns=["date"])
            if not df.empty and "date" in df.columns:
                max_val = df["date"].dropna().max()
                return _format_date_val(max_val)
        except Exception as e:
            logger.warning(f"读取 parquet 日期失败 {file_path}: {e}")
            raise
        return None

    def _find_tdx_max_date(
        self, tdx_dir: Optional[Union[str, Path]] = None
    ) -> Tuple[Optional[str], Optional[Path]]:
        """从通达信本地 .day 目录提取最大交易日"""
        resolved_dir: Optional[Path] = None
        if tdx_dir:
            cand = Path(tdx_dir)
            if cand.exists():
                resolved_dir = cand
        else:
            candidates = []
            env_vipdoc = os.environ.get("TDX_VIPDOC_DIR")
            if env_vipdoc:
                candidates.append(Path(env_vipdoc))
            env_tdx = os.environ.get("TDX_PATH")
            if env_tdx:
                candidates.append(Path(env_tdx))
            try:
                from ...shared.config_loader import ConfigLoader

                cfg = ConfigLoader().load_config()
                cfg_tdx = cfg.get("tdx", {}).get("path")
                if cfg_tdx:
                    candidates.append(Path(cfg_tdx))
            except Exception:
                pass
            candidates.extend([
                Path.home() / ".local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday",
                Path.home() / ".local/share/tdxcfv/drive_c/tc/vipdoc",
                Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday"),
            ])
            for c in candidates:
                if c.exists():
                    resolved_dir = c
                    break

        if not resolved_dir or not resolved_dir.exists():
            return None, None

        day_files: List[Path] = []
        if (resolved_dir / "sh" / "lday").exists():
            day_files.extend(list((resolved_dir / "sh" / "lday").glob("*.day")))
            if (resolved_dir / "sz" / "lday").exists():
                day_files.extend(list((resolved_dir / "sz" / "lday").glob("*.day")))
        elif resolved_dir.is_dir():
            day_files.extend(list(resolved_dir.glob("*.day")))

        if not day_files:
            return None, resolved_dir

        anchors = {"sh600519.day", "sh000001.day", "sz000001.day", "sz399001.day"}
        candidates_list = [f for f in day_files if f.name.lower() in anchors]
        newest = sorted(day_files, key=lambda f: f.stat().st_mtime, reverse=True)[:20]
        for f in newest:
            if f not in candidates_list:
                candidates_list.append(f)

        dates: List[str] = []
        for f in candidates_list:
            try:
                s = f.stat().st_size
                if s >= 32 and s % 32 == 0:
                    with open(f, "rb") as fp:
                        fp.seek(s - 32)
                        d_int = struct.unpack("<I", fp.read(4))[0]
                        d_str = str(d_int)
                        if len(d_str) == 8 and d_str.isdigit():
                            dates.append(f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:]}")
            except Exception:
                continue

        return (max(dates) if dates else None), resolved_dir

    def validate_freshness(
        self,
        max_lag_days: int = 7,
        tdx_dir: Optional[Union[str, Path]] = None,
        as_of_date: Optional[Union[str, datetime.date, pd.Timestamp]] = None,
        sample_size: int = 50,
        check_tdx: bool = True,
        require_l1_fresh: bool = False,
    ) -> Dict[str, Any]:
        """扫描数据湖日线数据最近日期，并与上游通达信数据比对评估两级新鲜度。

        两级 SLA 架构 (R10):
        - L1 SLA: TDX 相对当前交易日的滞后 (通达信盘后行情获取人工/脚本步)
        - L2 SLA: 湖相对 TDX 的滞后 (本地 TDX .day 到 Parquet 数据湖同步步)

        Args:
            max_lag_days: L2 滞后天数容忍阈值 (默认 7 天)
            tdx_dir: 通达信本地 vipdoc 或 lday 目录 (可选，未指定时尝试自动发现)
            as_of_date: 比对基准日期 (可选，默认使用当前时间提供者日期)
            sample_size: 湖文件扫描抽样数量 (<=0 表示全量扫描，默认 50)
            check_tdx: 是否比对本地 TDX 上游数据 (默认 True)
            require_l1_fresh: 判定整体 is_fresh 时是否要求 L1 也新鲜 (默认 False，仅考核 L2)

        Returns:
            Dict: {
                "is_fresh": bool,
                "lake_max_date": str,
                "tdx_max_date": Optional[str],
                "l2_lag_days": int,
                "details": dict
            }
        """
        # 1. 确定基准日期 as_of_date
        if as_of_date is None:
            try:
                from ...shared.time_provider import get_time_provider

                as_of_obj = get_time_provider().today()
            except Exception:
                as_of_obj = datetime.date.today()
        elif isinstance(as_of_date, str):
            as_of_obj = datetime.date.fromisoformat(as_of_date[:10])
        elif isinstance(as_of_date, (datetime.datetime, pd.Timestamp)):
            as_of_obj = as_of_date.date()
        elif isinstance(as_of_date, datetime.date):
            as_of_obj = as_of_date
        else:
            as_of_obj = datetime.date.today()
        as_of_str = as_of_obj.strftime("%Y-%m-%d")

        # 2. 扫描数据湖日线 parquet 文件获取 lake_max_date
        read_errors: List[str] = []
        parquet_files: List[Path] = []
        if self.daily_dir.exists():
            parquet_files = [
                f for f in self.daily_dir.glob("*.parquet") if f.is_file() or f.exists()
            ]

        lake_empty = len(parquet_files) == 0
        lake_max_date = ""
        lake_dates: List[str] = []
        scanned_count = 0

        if not lake_empty:
            anchors = {
                "600519.SH.parquet",
                "000001.SZ.parquet",
                "601398.SH.parquet",
                "000858.SZ.parquet",
            }
            candidates: List[Path] = [f for f in parquet_files if f.name in anchors]
            if sample_size <= 0 or sample_size >= len(parquet_files):
                candidates = list(parquet_files)
            else:
                newest = sorted(
                    parquet_files, key=lambda f: f.stat().st_mtime, reverse=True
                )[:sample_size]
                for f in newest:
                    if f not in candidates:
                        candidates.append(f)

            scanned_count = len(candidates)
            for f in candidates:
                try:
                    d_str = self._read_parquet_max_date(f)
                    if d_str:
                        lake_dates.append(d_str)
                except Exception as e:
                    read_errors.append(f"{f.name}: {e}")

            if lake_dates:
                lake_max_date = max(lake_dates)
            else:
                lake_empty = True

        # 3. 扫描通达信本地 .day 获取 tdx_max_date (可选)
        tdx_max_date: Optional[str] = None
        resolved_tdx_path: Optional[Path] = None
        if check_tdx:
            tdx_max_date, resolved_tdx_path = self._find_tdx_max_date(tdx_dir)

        # 4. 计算两级滞后天数
        l1_lag_days: Optional[int] = None
        l2_lag_days: int = -1
        stale_reasons: List[str] = []

        if tdx_max_date:
            tdx_d = datetime.date.fromisoformat(tdx_max_date)
            l1_lag_days = max(0, (as_of_obj - tdx_d).days)
            if l1_lag_days > 1:
                stale_reasons.append(f"L1_TDX_STALE_{l1_lag_days}D")
                logger.warning(
                    f"TDX 上游数据停更/滞后: l1_lag={l1_lag_days}天, "
                    f"tdx_max_date={tdx_max_date}, as_of_date={as_of_str}"
                )

        if lake_empty or not lake_max_date:
            l2_lag_days = -1
            is_fresh = False
            stale_reasons.append("L2_LAKE_EMPTY")
            logger.warning("数据湖日线数据为空，SLA 判定不新鲜 (lake_empty=True)")
        else:
            lake_d = datetime.date.fromisoformat(lake_max_date)
            if tdx_max_date:
                tdx_d = datetime.date.fromisoformat(tdx_max_date)
                l2_lag_days = max(0, (tdx_d - lake_d).days)
            else:
                l2_lag_days = max(0, (as_of_obj - lake_d).days)

            l2_is_fresh = l2_lag_days <= max_lag_days
            if not l2_is_fresh:
                stale_reasons.append(
                    f"L2_LAG_EXCEEDED_{l2_lag_days}D_GT_{max_lag_days}D"
                )
                logger.warning(
                    f"数据湖滞后超阈值: l2_lag={l2_lag_days}天 (阈值={max_lag_days}天), "
                    f"lake_max_date={lake_max_date}, tdx_max_date={tdx_max_date}"
                )

            if require_l1_fresh and l1_lag_days is not None and l1_lag_days > 1:
                is_fresh = False
            else:
                is_fresh = l2_is_fresh

        # 5. 计算交易日滞后天数 (增强细节)
        l1_lag_trading: Optional[int] = None
        l2_lag_trading: Optional[int] = None
        try:
            from ..managers.trade_calendar_manager import TradeCalendarManager

            tcm = TradeCalendarManager()
            if tdx_max_date and as_of_str > tdx_max_date:
                cal1 = tcm.get_trade_calendar(tdx_max_date, as_of_str)
                if cal1 is not None and not cal1.empty and "trade_date" in cal1.columns:
                    l1_lag_trading = max(
                        0,
                        len(
                            cal1[
                                pd.to_datetime(cal1["trade_date"])
                                > pd.to_datetime(tdx_max_date)
                            ]
                        ),
                    )
            if lake_max_date:
                ref_date = tdx_max_date or as_of_str
                if ref_date > lake_max_date:
                    cal2 = tcm.get_trade_calendar(lake_max_date, ref_date)
                    if (
                        cal2 is not None
                        and not cal2.empty
                        and "trade_date" in cal2.columns
                    ):
                        l2_lag_trading = max(
                            0,
                            len(
                                cal2[
                                    pd.to_datetime(cal2["trade_date"])
                                    > pd.to_datetime(lake_max_date)
                                ]
                            ),
                        )
        except Exception:
            pass

        details: Dict[str, Any] = {
            "as_of_date": as_of_str,
            "lake_empty": lake_empty,
            "lake_dir": str(self.daily_dir),
            "lake_max_date": lake_max_date,
            "scanned_files_count": scanned_count,
            "tdx_dir": str(resolved_tdx_path) if resolved_tdx_path else None,
            "tdx_max_date": tdx_max_date,
            "l1_lag_days": l1_lag_days,
            "l2_lag_days": l2_lag_days,
            "l1_lag_trading_days": l1_lag_trading,
            "l2_lag_trading_days": l2_lag_trading,
            "l1_is_fresh": (l1_lag_days is None or l1_lag_days <= 1),
            "l2_is_fresh": (
                not lake_empty and l2_lag_days >= 0 and l2_lag_days <= max_lag_days
            ),
            "max_lag_days": max_lag_days,
            "stale_reasons": stale_reasons,
            "read_errors": read_errors,
        }

        return {
            "is_fresh": is_fresh,
            "lake_max_date": lake_max_date,
            "tdx_max_date": tdx_max_date,
            "l2_lag_days": l2_lag_days,
            "details": details,
        }

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
            index_dir = self.quotes_dir / "index"
            if not index_dir.exists() and (self.lake_dir / "index").exists():
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
        if not file_path.exists():
            if data_type == "daily" and is_index_symbol(symbol):
                idx_path = self.index_dir / f"{symbol}.parquet"
                if idx_path.exists():
                    return self.read_parquet(str(idx_path))
            logger.warning(f"数据文件不存在: {file_path}")
            return pd.DataFrame()
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
