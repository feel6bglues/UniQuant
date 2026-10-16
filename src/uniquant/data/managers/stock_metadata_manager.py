"""
股票元数据管理器
管理股票的基本信息、IPO日期、退市日期、板块等元数据
"""

from dataclasses import dataclass
from datetime import date
from ...shared.time_provider import get_time_provider
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from ...shared.constants import DataSourceConstants
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


def _normalize_stock_code(code: str) -> str:
    """将 baostock 格式 (sh.600519) 归一为 XXXXXX.SH/SZ/BJ (对齐 storage_manager._normalize_stock_code)

    D5: 主数据 code 列是 sh./sz. 前缀格式，直接作缓存键会让 get_stock_info("600519.SH")
    永不命中 → 退市守卫静默失效。归一化后键统一为后缀格式。
    """
    if not code or pd.isna(code):
        return ""
    code = str(code).strip().upper()
    clean = code.replace(".", "").replace("SH", "").replace("SZ", "").replace("BJ", "")
    clean = clean.lstrip("SH").lstrip("SZ").lstrip("BJ")
    if not clean:
        return ""
    if clean.startswith("6"):
        return f"{clean}.SH"
    elif clean.startswith(("00", "30")):
        return f"{clean}.SZ"
    elif clean.startswith(("83", "87", "43")):
        return f"{clean}.BJ"
    return f"{clean}.SH"


@dataclass
class StockMetadata:
    """股票元数据"""
    code: str
    name: str
    market: str
    sector: Optional[str] = None
    ipo_date: Optional[date] = None
    delist_date: Optional[date] = None
    stock_type: Optional[str] = None
    stock_status: Optional[str] = None
    vol_unit: Optional[int] = None
    decimal_point: Optional[int] = None


class StockMetadataManager:
    """
    股票元数据管理器
    负责加载和管理股票的基本信息
    """
    
    def __init__(self, data_dir: Optional[str] = None):
        """
        初始化元数据管理器
        
        Args:
            data_dir: 数据存储根目录；默认指向项目 data/（绝对路径，D5 裁决，
                      修复相对 CWD 导致的静默失效）
        """
        from ...shared.constants.path import DATA_DIR

        if data_dir is None:
            data_dir = str(DATA_DIR)
        self.data_dir = Path(data_dir)
        self._stock_list_path = self.data_dir / "all_stock_codes.csv"
        self._all_codes_path = self.data_dir / "all_stock_codes.csv"
        
        self._metadata_cache: Dict[str, StockMetadata] = {}
        self._loaded = False
        
    def load(self) -> bool:
        """
        加载股票元数据
        
        Returns:
            bool: 是否加载成功
        """
        try:
            self._load_all_codes()
            self._loaded = True
            logger.info(f"成功加载 {len(self._metadata_cache)} 个股票元数据")
            return True
        except (OSError, ValueError, KeyError, pd.errors.ParserError) as e:
            logger.error(f"加载股票元数据失败: {e}")
            return False
    
    def _load_all_codes(self) -> None:
        """加载全量股票代码数据

        R-5 (D5 裁决 A): 主数据文件缺失 → 硬失败，禁止 warning 降级为空
        （空元数据会让退市守卫静默失效，回测带幸存者偏差）。
        """
        if not self._all_codes_path.exists():
            raise FileNotFoundError(
                f"全量代码文件不存在: {self._all_codes_path} (R-5 硬失败)。"
                f"请执行 resync: python -c \"from uniquant.data.managers.baostock_cache_manager "
                f"import create_baostock_cache; create_baostock_cache()\""
            )
        
        df = pd.read_csv(self._all_codes_path, encoding='utf-8-sig')
        df = self._normalize_columns(df)
        
        for row in df.itertuples(index=False):
            raw_code = str(row.code)
            if not raw_code:
                continue
            code = _normalize_stock_code(raw_code)
            if not code:
                continue
            
            metadata = self._metadata_cache.get(code, StockMetadata(
                code=code,
                name='',
                market=self._infer_market(code)
            ))
            
            metadata.name = str(getattr(row, 'name', getattr(row, 'code_name', metadata.name)))
            metadata.stock_type = str(row.stock_type) if pd.notna(getattr(row, 'stock_type', None)) else metadata.stock_type
            # §7.4 #4: _normalize_columns 已把 status/上市状态 重命名为 stock_status，
            # itertuples 不可能再暴露 'status' 属性 —— 原守卫 getattr(row,'status',None)
            # 恒为 None，导致 stock_status 永远是空字段。改用归一后的列名守卫。
            metadata.stock_status = str(row.stock_status) if pd.notna(getattr(row, 'stock_status', None)) else metadata.stock_status
            
            if pd.notna(getattr(row, 'ipo_date', None)):
                metadata.ipo_date = self._parse_date(row.ipo_date)
            if pd.notna(getattr(row, 'delist_date', None)):
                metadata.delist_date = self._parse_date(getattr(row, 'outDate', getattr(row, 'delist_date', None)))
            
            self._metadata_cache[code] = metadata
    
    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化列名"""
        column_mapping = {}
        
        for col in df.columns:
            for alias in DataSourceConstants.IPO_DATE_COLS:
                if col == alias:
                    column_mapping[col] = 'ipo_date'
                    break
            for alias in DataSourceConstants.DELIST_DATE_COLS:
                if col == alias:
                    column_mapping[col] = 'delist_date'
                    break
            for alias in DataSourceConstants.STOCK_TYPE_COLS:
                if col == alias:
                    column_mapping[col] = 'stock_type'
                    break
            for alias in DataSourceConstants.STOCK_STATUS_COLS:
                if col == alias:
                    column_mapping[col] = 'stock_status'
                    break
            for alias in DataSourceConstants.NAME_COLS:
                if col == alias:
                    column_mapping[col] = 'name'
                    break
            for alias in DataSourceConstants.SECTOR_COLS:
                if col == alias:
                    column_mapping[col] = 'sector'
                    break
            for alias in DataSourceConstants.VOL_UNIT_COLS:
                if col == alias:
                    column_mapping[col] = 'vol_unit'
                    break
            for alias in DataSourceConstants.DECIMAL_POINT_COLS:
                if col == alias:
                    column_mapping[col] = 'decimal_point'
                    break
        
        if column_mapping:
            df = df.rename(columns=column_mapping)
        
        return df
    
    def _parse_date(self, date_value) -> Optional[date]:
        """解析日期值"""
        if pd.isna(date_value):
            return None
        
        if isinstance(date_value, date):
            return date_value
        
        try:
            if isinstance(date_value, str):
                s = date_value.strip()
                if not s or s in ("-", "None", "nan", "NaT"):
                    return None
                if len(s) == 10 and s[4] == "-" and s[7] == "-":
                    return date.fromisoformat(s)
                if len(s) == 8 and s.isdigit():
                    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
                return pd.to_datetime(s).date()
            return pd.to_datetime(date_value).date()
        except (ValueError, TypeError, pd.errors.ParserError):
            return None
    
    def _infer_market(self, code: str) -> str:
        """根据股票代码推断市场"""
        clean_code = code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        
        if clean_code.startswith('60') or clean_code.startswith('68'):
            return 'SH'
        elif clean_code.startswith('00') or clean_code.startswith('30'):
            return 'SZ'
        elif clean_code.startswith('83') or clean_code.startswith('87') or clean_code.startswith('43'):
            return 'BJ'
        return ''
    
    def get_stock_info(self, code: str) -> Optional[StockMetadata]:
        if not self._loaded:
            self.load()
        # §7.4 #5: 缓存键由模块级 _normalize_stock_code 统一为 XXXXXX.SH/SZ/BJ，
        # 但此处曾经只剥离 .SH/.SZ/.BJ 后缀 —— 于是 sh.600519 这类 baostock 前缀
        # 形式永不命中（退市守卫静默失效）。先用同一归一函数归一化再查。
        normalized = _normalize_stock_code(code)
        if normalized and normalized in self._metadata_cache:
            return self._metadata_cache[normalized]
        clean_code = code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        for suffix in ['', '.SH', '.SZ', '.BJ']:
            lookup_code = clean_code + suffix
            if lookup_code in self._metadata_cache:
                return self._metadata_cache[lookup_code]
        return None

    def get_name(self, code: str) -> Optional[str]:
        """获取股票名称"""
        info = self.get_stock_info(code)
        return info.name if info else None
    
    def get_ipo_date(self, code: str) -> Optional[date]:
        """获取IPO日期"""
        info = self.get_stock_info(code)
        return info.ipo_date if info else None
    
    def get_delist_date(self, code: str) -> Optional[date]:
        """获取退市日期"""
        info = self.get_stock_info(code)
        return info.delist_date if info else None
    
    def is_delisted(self, code: str, as_of: Optional[date] = None) -> bool:
        """
        检查是否已退市
        
        Args:
            code: 股票代码
            as_of: 截止日期，默认为今天
            
        Returns:
            bool: 是否已退市
        """
        info = self.get_stock_info(code)
        if not info or not info.delist_date:
            return False
        
        check_date = as_of or get_time_provider().today()
        return info.delist_date <= check_date
    
    def is_ipo(self, code: str, as_of: Optional[date] = None) -> bool:
        """
        检查是否已上市
        
        Args:
            code: 股票代码
            as_of: 截止日期，默认为今天
            
        Returns:
            bool: 是否已上市
        """
        info = self.get_stock_info(code)
        if not info or not info.ipo_date:
            return True
        
        check_date = as_of or get_time_provider().today()
        return info.ipo_date <= check_date
    
    def get_all_codes(self) -> List[str]:
        """获取所有股票代码"""
        if not self._loaded:
            self.load()
        return list(self._metadata_cache.keys())
    
    def get_active_stocks(self, as_of: Optional[date] = None) -> List[str]:
        """
        获取当前活跃股票列表（已上市且未退市）
        
        Args:
            as_of: 截止日期，默认为今天
            
        Returns:
            List[str]: 活跃股票代码列表
        """
        if not self._loaded:
            self.load()
        
        check_date = as_of or get_time_provider().today()
        
        return [
            code for code, meta in self._metadata_cache.items()
            if (not meta.ipo_date or meta.ipo_date <= check_date)
            and (not meta.delist_date or meta.delist_date > check_date)
        ]
