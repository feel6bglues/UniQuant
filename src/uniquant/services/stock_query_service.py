"""
股票查询服务
负责股票代码映射、名称查询和ETF列表管理
"""
from typing import Dict, List, Optional

from ..shared.logger_factory import get_logger

logger = get_logger("StockQueryService")

QUERY_RECOVERABLE_ERRORS = (
    AttributeError,
    KeyError,
    OSError,
    TypeError,
    ValueError,
)


class StockQueryService:
    """
    股票查询服务
    
    职责：
    - 股票代码到名称的映射
    - 股票信息查询
    - ETF列表管理
    """
    
    def __init__(self, fetcher=None):
        """
        初始化股票查询服务
        
        Args:
            fetcher: DataFetcher实例（可选，用于获取股票信息）
        """
        self._fetcher = fetcher
        self._stock_map: Dict[str, str] = {}
        self._etf_list: List[str] = []
    
    @property
    def stock_map(self) -> Dict[str, str]:
        """获取股票映射"""
        return self._stock_map
    
    @property
    def etf_list(self) -> List[str]:
        """获取 ETF 列表"""
        return self._etf_list
    
    def refresh_stock_map(self) -> Dict[str, str]:
        """
        刷新股票映射
        
        Returns:
            Dict[str, str]: 股票映射
        """
        if self._fetcher is None:
            logger.warning("No fetcher available, cannot refresh stock map")
            return self._stock_map
        
        try:
            self._stock_map = self._fetcher.fetch_stock_info()
            logger.info("Refreshed stock map with %d entries", len(self._stock_map))
        except QUERY_RECOVERABLE_ERRORS as e:
            logger.error("Failed to refresh stock map: %s", e)
            self._stock_map = {}
        
        return self._stock_map
    
    def get_stock_name(self, symbol: str) -> str:
        """
        根据股票代码获取股票名称
        
        Args:
            symbol: 股票代码
            
        Returns:
            股票名称
        """
        if not self._stock_map:
            self.refresh_stock_map()
        
        name = self._get_from_map(symbol)
        if name:
            return name
        
        name = self._get_with_suffix(symbol)
        if name:
            return name
        
        if "." in symbol:
            base_symbol = symbol.split(".")[0]
            if base_symbol in self._stock_map:
                return self._stock_map[base_symbol]
        
        return self._get_from_source(symbol)
    
    def _get_from_map(self, symbol: str) -> Optional[str]:
        """从映射中直接获取"""
        return self._stock_map.get(symbol)
    
    def _get_with_suffix(self, symbol: str) -> Optional[str]:
        """尝试添加市场后缀查找"""
        if symbol.startswith(("000", "002", "300")):
            sz_symbol = f"{symbol}.SZ"
            if sz_symbol in self._stock_map:
                return self._stock_map[sz_symbol]
        elif symbol.startswith("6"):
            sh_symbol = f"{symbol}.SH"
            if sh_symbol in self._stock_map:
                return self._stock_map[sh_symbol]
        return None
    
    def _get_from_source(self, symbol: str) -> str:
        """从外部数据源获取并更新映射"""
        if self._fetcher is None:
            return symbol
        
        try:
            stock_info = self._fetcher.fetch_stock_info()
            if symbol in stock_info:
                name = stock_info[symbol]
                self._stock_map[symbol] = name
                return name
            
            if not symbol.endswith(".SH") and not symbol.endswith(".SZ"):
                if symbol.startswith(("000", "002", "300")):
                    sz_symbol = f"{symbol}.SZ"
                    if sz_symbol in stock_info:
                        name = stock_info[sz_symbol]
                        self._stock_map[symbol] = name
                        return name
                elif symbol.startswith("6"):
                    sh_symbol = f"{symbol}.SH"
                    if sh_symbol in stock_info:
                        name = stock_info[sh_symbol]
                        self._stock_map[symbol] = name
                        return name
            
            return symbol
        except QUERY_RECOVERABLE_ERRORS as e:
            logger.warning("Failed to get stock name from data source: %s", e)
            return symbol
    
    def scan_etfs(self) -> List[str]:
        """
        扫描ETF
        
        Returns:
            List[str]: ETF列表
        """
        if self._fetcher is None:
            logger.warning("No fetcher available, cannot scan ETFs")
            return self._etf_list
        
        try:
            etf_data = self._fetcher.fetch_stock_info()
            etfs = [symbol for symbol in etf_data.keys() if symbol.startswith("51")]
            self._etf_list = etfs
            logger.info("Scanned %d ETFs", len(etfs))
            return etfs
        except QUERY_RECOVERABLE_ERRORS as e:
            logger.error("Failed to scan ETFs: %s", e)
            return []
    
    def get_stock_info(self) -> Dict[str, str]:
        """
        获取股票代码到名称的映射
        
        Returns:
            Dict[str, str]: 股票映射
        """
        if self._fetcher is None:
            return self._stock_map
        
        try:
            return self._fetcher.fetch_stock_info()
        except QUERY_RECOVERABLE_ERRORS as e:
            logger.error("Failed to get stock info: %s", e)
            return self._stock_map
    
    def is_etf(self, symbol: str) -> bool:
        """
        判断是否为ETF
        
        Args:
            symbol: 证券代码
            
        Returns:
            bool: 是否为ETF
        """
        return symbol.startswith("51") or symbol in self._etf_list
    
    def get_market(self, symbol: str) -> str:
        """
        获取股票所属市场
        
        Args:
            symbol: 证券代码
            
        Returns:
            str: 市场代码 (SH/SZ)
        """
        if symbol.endswith(".SH"):
            return "SH"
        elif symbol.endswith(".SZ"):
            return "SZ"
        elif symbol.startswith("6"):
            return "SH"
        elif symbol.startswith(("000", "002", "300")):
            return "SZ"
        return "UNKNOWN"
