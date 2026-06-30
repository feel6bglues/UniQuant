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
    
    def __init__(self, data_dir: str = "./data"):
        """
        初始化元数据管理器
        
        Args:
            data_dir: 数据存储根目录
        """
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
            self._load_stock_list()
            self._load_all_codes()
            self._loaded = True
            logger.info(f"成功加载 {len(self._metadata_cache)} 个股票元数据")
            return True
        except (OSError, ValueError, KeyError, pd.errors.ParserError) as e:
            logger.error(f"加载股票元数据失败: {e}")
            return False
    
    def _load_stock_list(self) -> None:
        """加载股票列表数据"""
        if not self._stock_list_path.exists():
            logger.warning(f"股票列表文件不存在: {self._stock_list_path}")
            return
        
        df = pd.read_csv(self._stock_list_path, encoding='utf-8-sig')
        df = self._normalize_columns(df)
        
        for row in df.itertuples(index=False):
            code = str(row.code)
            if not code:
                continue
            
            metadata = self._metadata_cache.get(code, StockMetadata(
                code=code,
                name='',
                market=''
            ))
            
            metadata.name = str(row.name)
            metadata.market = str(row.market)
            metadata.sector = getattr(row, 'sector', None) if pd.notna(getattr(row, 'sector', None)) else metadata.sector
            metadata.vol_unit = int(getattr(row, 'vol_unit', None)) if pd.notna(getattr(row, 'vol_unit', None)) else metadata.vol_unit
            metadata.decimal_point = int(getattr(row, 'decimal_point', None)) if pd.notna(getattr(row, 'decimal_point', None)) else metadata.decimal_point
            
            self._metadata_cache[code] = metadata
    
    def _load_all_codes(self) -> None:
        """加载全量股票代码数据"""
        if not self._all_codes_path.exists():
            logger.warning(f"全量代码文件不存在: {self._all_codes_path}")
            return
        
        df = pd.read_csv(self._all_codes_path, encoding='utf-8-sig')
        df = self._normalize_columns(df)
        
        for row in df.itertuples(index=False):
            code = str(row.code)
            if not code:
                continue
            
            metadata = self._metadata_cache.get(code, StockMetadata(
                code=code,
                name='',
                market=self._infer_market(code)
            ))
            
            metadata.name = str(getattr(row, 'name', getattr(row, 'code_name', metadata.name)))
            metadata.stock_type = str(row.stock_type) if pd.notna(getattr(row, 'stock_type', None)) else metadata.stock_type
            metadata.stock_status = str(row.stock_status) if pd.notna(getattr(row, 'status', None)) else metadata.stock_status
            
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
                if len(date_value) == 8:
                    return pd.to_datetime(date_value, format='%Y%m%d').date()
                return pd.to_datetime(date_value).date()
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
        """
        获取股票完整信息
        
        Args:
            code: 股票代码
            
        Returns:
            StockMetadata: 股票元数据，不存在返回None
        """
        if not self._loaded:
            self.load()
        
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
    
    def get_sector(self, code: str) -> Optional[str]:
        """获取所属板块"""
        info = self.get_stock_info(code)
        return info.sector if info else None
    
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
    
    def get_codes_by_sector(self, sector: str) -> List[str]:
        """
        获取指定板块的所有股票代码
        
        Args:
            sector: 板块名称
            
        Returns:
            List[str]: 股票代码列表
        """
        if not self._loaded:
            self.load()
        
        return [
            code for code, meta in self._metadata_cache.items()
            if meta.sector == sector
        ]
    
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
