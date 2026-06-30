"""
数据获取器 - 系统的大脑和总指挥
根据 datapipeline.md 架构设计重构
"""

import logging
from datetime import datetime
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple
import pandas as pd

from ..shared.error_handling import handle_errors
from ..shared.exceptions import DataFetchError, DataValidationError
from ..shared.logger_factory import get_logger
from ..shared.time_provider import get_time_provider

from .lake.storage_manager import StorageManager
from .managers.standard_adapter import StandardAdapter
from .managers.source_router import SourceRouter
from .pipeline.data_adjuster import DataAdjuster
from .pipeline.data_cleaner import DataCleaner
from .pipeline.data_validator import DataValidator

from .sources.baostock import BaostockSource
from .sources.tdx import TdxSource
from .sources.sina import SinaSource
from .sources.tencent import TencentSource
from .sources.ths import ThsSource
from .data_pipeline_service import DataPipelineService

# 新增的 Managers
from .managers.stock_metadata_manager import StockMetadataManager
from .managers.trade_calendar_manager import TradeCalendarManager
from .managers.adjust_factor_manager import AdjustFactorManager
from .managers.market_data_coordinator import MarketDataCoordinator
from .managers.stock_data_updater import StockDataUpdater

logger = get_logger("DataFetcher")

FETCHER_INIT_RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

MARKET_CAP_RECOVERABLE_ERRORS = (
    AttributeError,
    DataFetchError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

class DataFetcher:
    """
    数据获取器 - 系统的大脑和总指挥
    根据 datapipeline.md 架构设计实现
    """

    def __init__(
        self,
        data_dir: str = "./data",
        storage_manager: Optional[StorageManager] = None,
        pipeline: Optional[DataPipelineService] = None,
    ):
        logger.info("初始化 DataFetcher - 系统的大脑和总指挥")

        self.storage_manager = (
            storage_manager if storage_manager is not None else StorageManager(data_dir)
        )
        data_dir = str(self.storage_manager.data_dir)

        # 容错初始化数据源：单个失败不影响其他源
        source_classes = [TdxSource, BaostockSource, SinaSource, ThsSource, TencentSource]
        self.data_sources = []
        for source_cls in source_classes:
            source_name = getattr(source_cls, "__name__", str(source_cls))
            try:
                self.data_sources.append(source_cls())
            except FETCHER_INIT_RECOVERABLE_ERRORS as e:
                logger.warning(f"数据源 {source_name} 初始化失败，跳过: {e}")

        self.adapters = [StandardAdapter(source) for source in self.data_sources]
        self.source_router = SourceRouter(self.adapters)

        self.data_cleaner = DataCleaner()
        self.data_validator = DataValidator()
        self.data_adjuster = DataAdjuster(self.storage_manager)

        # 初始化独立的专门管理器
        self.metadata_manager = StockMetadataManager(data_dir=data_dir)
        self.calendar_manager = TradeCalendarManager(data_dir=data_dir)
        self.adjust_factor_manager = AdjustFactorManager(self.storage_manager)
        self.market_coordinator = MarketDataCoordinator(self)
        self.stock_updater = StockDataUpdater(self)

        self.pipeline = (
            pipeline
            if pipeline is not None
            else DataPipelineService(data_dir, storage_manager=self.storage_manager)
        )

        self._price_cache: OrderedDict = OrderedDict()
        self._max_cache_size = 5000

        logger.info("DataFetcher 初始化完成")

    def get_price(self, symbol: str, adjust: str = "") -> pd.DataFrame:
        cached = self._get_price_cached(symbol, adjust)
        if cached is not None:
            return cached

        logger.info(f"获取 {symbol} 数据，复权类型: {adjust}")
        try:
            df = self.source_router.fetch_with_fallback(symbol, "fetch")
        except Exception:
            df = None
        if df is None or df.empty:
            logger.warning(f"未获取到 {symbol} 的数据")
            return pd.DataFrame()

        df = self.pipeline.process(df, symbol, adjust=adjust)

        self._set_price_cache(symbol, adjust, df)
        return df

    def _get_price_cached(self, symbol: str, adjust: str):
        key = (symbol, adjust)
        if key in self._price_cache:
            self._price_cache.move_to_end(key)
            return self._price_cache[key].copy()
        return None

    def _set_price_cache(self, symbol: str, adjust: str, df):
        key = (symbol, adjust)
        self._price_cache[key] = df.copy()
        while len(self._price_cache) > self._max_cache_size:
            self._price_cache.popitem(last=False)

    def clear_price_cache(
        self,
        symbol: Optional[str] = None,
        adjust: Optional[str] = None,
    ) -> int:
        """Clear in-memory price cache entries by symbol and optional adjust."""
        if symbol is None:
            count = len(self._price_cache)
            self._price_cache.clear()
            return count

        keys_to_delete = [
            key for key in self._price_cache
            if key[0] == symbol and (adjust is None or key[1] == adjust)
        ]
        for key in keys_to_delete:
            del self._price_cache[key]
        return len(keys_to_delete)

    def _needs_update(self, df: pd.DataFrame) -> bool:
        return self.stock_updater.needs_update(df)

    def _update_stock(self, symbol: str, df_old: pd.DataFrame) -> pd.DataFrame:
        return self.stock_updater.update_stock(symbol, df_old)

    def update_all(self, symbols: list):
        self.stock_updater.update_all(symbols)

    def fetch_stock_daily(self, symbol: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
        logger.info(f"获取个股日线数据: {symbol}, {start_date} 到 {end_date}")
        df = self.get_price(symbol, adjust)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            df = df[(df["date"] >= start) & (df["date"] <= end)]
        return df

    def fetch_stock_market_cap(self, symbol: str) -> float:
        for source in self.data_sources:
            try:
                if hasattr(source, "fetch_market_cap"):
                    market_cap = source.fetch_market_cap(symbol)
                    if market_cap > 0:
                        return market_cap
            except MARKET_CAP_RECOVERABLE_ERRORS as e:
                logger.warning(f"获取市值失败 {symbol} from {source.__class__.__name__}: {e}")
        return 0.0

    def fetch_stocks_daily(self, symbols: List[str], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        result = {}
        max_workers = min(16, len(symbols)) if symbols else 1
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_symbol = {
                executor.submit(self.fetch_stock_daily, symbol, start_date, end_date): symbol
                for symbol in symbols
            }
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    result[symbol] = future.result()
                except Exception as e:
                    logger.warning(f"获取 {symbol} 数据失败: {e}")
                    result[symbol] = pd.DataFrame()
        
        return result

    def fetch_index_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.market_coordinator.fetch_index_daily(symbol, start_date, end_date)

    def fetch_etf_daily_robust(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.market_coordinator.fetch_etf_daily_robust(symbol, start_date, end_date)

    def fetch_industry_concept_data(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        return self.market_coordinator.fetch_industry_concept_data()

    def fetch_sector_daily(self, sector_name: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.market_coordinator.fetch_sector_daily(sector_name, start_date, end_date)

    def fetch_stock_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        logger.info(f"获取实时数据: {symbol}")
        return pd.DataFrame()

    @handle_errors(DataFetchError, DataValidationError, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def fetch_history(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        is_index = symbol.startswith(("sh000", "sz399")) or (symbol.startswith("000") and symbol.endswith(".SH"))
        if is_index:
            return self.fetch_index_daily(symbol, start_date, end_date)
        return self.fetch_stock_daily(symbol, start_date, end_date)

    def get_symbols(self):
        return self.storage_manager.get_symbols()

    def clean_data(self, symbol):
        return self.stock_updater.clean_data(symbol)

    def get_source_health_report(self):
        return self.source_router.get_source_health_report()

    def print_source_health_report(self):
        self.source_router.print_source_health_report()

    def fetch_for_brain(self, symbol: str) -> Dict:
        logger.info(f"为大脑获取 {symbol} 数据")
        stock_data = self.get_price(symbol)
        return {
            "stock": stock_data,
            "symbol": symbol,
            "timestamp": get_time_provider().now().isoformat(),
        }

    # ---- 委托给 StockMetadataManager 的方法 ----
    def fetch_all_stock_codes(self, force_update: bool = False) -> pd.DataFrame:
        logger.info("获取全量股票代码和名称")
        self.metadata_manager.load()
        codes = []
        names = []
        for code, meta in self.metadata_manager._metadata_cache.items():
            codes.append(code)
            names.append(meta.name)
        if not codes:
            logger.warning("未能通过 MetadataManager 加载股票代码缓存")
            return pd.DataFrame()
        return pd.DataFrame({"代码": codes, "名称": names})

    def fetch_stock_info(self) -> Dict[str, str]:
        logger.info("获取所有股票的基础信息")
        df = self.fetch_all_stock_codes()
        if not df.empty:
            return dict(zip(df["代码"], df["名称"]))
        return {}

    def is_valid_symbol(self, symbol: str) -> bool:
        logger.info(f"验证股票代码 {symbol} 的有效性")
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "").replace("sh", "").replace("sz", "").replace("bj", "").replace(".", "")
        df = self.fetch_all_stock_codes()
        if not df.empty and "代码" in df.columns:
            return clean_symbol in [str(code).strip() for code in df["代码"].astype(str).tolist()]
        return False

    def validate_symbols(self, symbols: list) -> list:
        logger.info(f"开始批量验证 {len(symbols)} 个股票代码")
        return [s for s in symbols if self.is_valid_symbol(s)]
        
    # ---- 委托给 TradeCalendarManager 的方法 ----
    def generate_trade_calendar(self, year: int, force_update: bool = False) -> pd.DataFrame:
        return self.calendar_manager.generate_trade_calendar(year, force_update)

    def is_trading_day(self, date: datetime) -> bool:
        return self.calendar_manager.is_trading_day(date)

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        return self.calendar_manager.get_trade_calendar(start_date, end_date)

    # ---- 委托给 AdjustFactorManager 的方法 ----
    def get_adjust_factors(self, symbol: str, gbbq_path: Optional[str] = None) -> Optional[pd.DataFrame]:
        return self.adjust_factor_manager.get_adjust_factors(symbol, gbbq_path)

    def convert_gbbq_to_fq(self, gbbq_path: Optional[str] = None) -> bool:
        return self.adjust_factor_manager.convert_gbbq_to_fq(gbbq_path)

class LegacyDataFetcher(DataFetcher):
    """
    传统数据获取器（保持原有行为）
    """
    def __init__(self) -> None:
        super().__init__()

def create_fetcher(data_dir: str = "./data") -> DataFetcher:
    return DataFetcher(data_dir)
