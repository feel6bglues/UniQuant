"""
数据服务
使用门面模式协调各个组件
"""
import logging
import multiprocessing
import os
from ..shared.time_provider import get_time_provider
from functools import partial
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from joblib import Parallel, delayed

from ..data.pipeline.data_cleaner import DataCleaner
from ..data.data_fetcher import DataFetcher
from ..data.lake.storage_manager import StorageManager
from ..shared.constants import PerformanceConstants, TimeConstants
from ..shared.error_handling import handle_errors
from ..shared.exceptions import (
    CacheError,
    DataFetchError,
    DataStorageError,
    DataValidationError,
)
from ..shared.logger_factory import get_logger

from .cache_coordinator import CacheCoordinator
from .data_access_service import DataAccessService
from .data_quality_service import DataQualityService
from .stock_query_service import StockQueryService

logger = get_logger("DataService")


class DataService:
    """
    数据服务 - 门面模式
    
    协调以下专职服务：
    - CacheCoordinator: 缓存管理
    - DataQualityService: 数据质量检查
    - StockQueryService: 股票查询
    
    保持向后兼容性，同时将职责委托给专门的服务。
    """

    CACHE_TTL_SECONDS = PerformanceConstants.CACHE_TTL_SECONDS
    MAX_CACHE_ENTRIES = PerformanceConstants.CACHE_MAX_SIZE

    def __init__(
        self,
        fetcher: Optional[DataFetcher] = None,
        storage_manager: Optional[StorageManager] = None,
        cleaner: Optional[DataCleaner] = None,
    ) -> None:
        """
        初始化数据服务

        Args:
            fetcher: DataFetcher实例
            storage_manager: StorageManager实例
            cleaner: DataCleaner实例
        """
        if storage_manager is not None:
            self.storage_manager = storage_manager
        elif fetcher is not None and hasattr(fetcher, "storage_manager"):
            self.storage_manager = fetcher.storage_manager
        else:
            self.storage_manager = StorageManager()

        self.fetcher = (
            fetcher
            if fetcher is not None
            else DataFetcher(
                data_dir=str(self.storage_manager.data_dir),
                storage_manager=self.storage_manager,
            )
        )
        self.cleaner = cleaner if cleaner is not None else DataCleaner()
        
        self.lake = self.storage_manager
        
        self._cache_coordinator = CacheCoordinator()
        self._quality_service = DataQualityService()
        self._stock_query = StockQueryService(fetcher=self.fetcher)
        self.access_service = DataAccessService(self)
        self._market_cache = None
        
        self.cache_manager = self._cache_coordinator.cache_manager

        logger.info("DataService initialized with facade pattern")

    @property
    def stock_map(self) -> Dict[str, str]:
        """获取股票映射"""
        return self._stock_query.stock_map

    @property
    def etf_list(self) -> List[str]:
        """获取 ETF 列表"""
        return self._stock_query.etf_list

    @property
    def lake_root(self) -> str:
        """获取数据湖根路径"""
        return str(self.storage_manager.base_dir)

    def _get_cache_key(self, prefix: str, *args, namespace: str = "default") -> str:
        """生成缓存键"""
        return self._cache_coordinator.generate_cache_key(prefix, *args, namespace=namespace)

    def _generate_cache_key(self, prefix: str, **kwargs) -> str:
        """生成缓存键，兼容 AnalysisEngineFactory 的缓存需求"""
        parts = [prefix]
        for k, v in sorted(kwargs.items()):
            if v is not None:
                parts.append(f"{k}={v}")
        return ":".join(parts)

    def _get_access_service(self) -> DataAccessService:
        if not hasattr(self, "access_service") or self.access_service is None:
            self.access_service = DataAccessService(self)
        return self.access_service

    @staticmethod
    def _clone_dataframe(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if df is None:
            return None
        return df.copy(deep=True)

    def _get_cached(self, key: str) -> Optional[Any]:
        """获取缓存数据"""
        return self._cache_coordinator.get(key)

    def _set_cache(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        data_type: str = "general",
    ) -> None:
        """设置缓存"""
        self._cache_coordinator.set(key, value, ttl=ttl, data_type=data_type)

    def clear_cache(self) -> None:
        """清除所有缓存"""
        self._cache_coordinator.clear()

    def attach_market_cache(self, market_cache: Any) -> None:
        """Attach market-level cache for invalidation broadcasts."""
        self._market_cache = market_cache

    def _clear_fetcher_price_cache(
        self,
        symbol: Optional[str] = None,
        adjust: Optional[str] = None,
    ) -> int:
        if hasattr(self.fetcher, "clear_price_cache"):
            return self.fetcher.clear_price_cache(symbol=symbol, adjust=adjust)
        return 0

    def invalidate_symbol_cache(
        self,
        symbol: str,
        data_type: str = "stock",
        market: str = "cn",
    ) -> Dict[str, Any]:
        """Invalidate all known service/fetcher caches touched by a symbol update."""
        removed_price_entries = self._clear_fetcher_price_cache(symbol)
        cache_key = self._get_cache_key(data_type, symbol, market, namespace="datalake")
        service_cache_deleted = False
        if hasattr(self.cache_manager, "delete"):
            service_cache_deleted = bool(self.cache_manager.delete(cache_key))

        market_cache_cleared = False
        if data_type == "index" and self._market_cache is not None:
            self._market_cache.clear()
            market_cache_cleared = True

        return {
            "symbol": symbol,
            "data_type": data_type,
            "removed_price_entries": removed_price_entries,
            "service_cache_deleted": service_cache_deleted,
            "market_cache_cleared": market_cache_cleared,
        }

    @handle_errors(CacheError, default_return=False, log_level=logging.ERROR)
    def cache_data(
        self, key: str, data: Any, ttl: Optional[int] = None, data_type: str = "general"
    ) -> bool:
        """缓存数据"""
        return self._cache_coordinator.safe_cache_data(key, data, ttl=ttl, data_type=data_type)

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return self._cache_coordinator.get_stats()

    def check_cache_consistency(
        self, symbol: str, data_type: str = "stock", market: str = "cn"
    ) -> bool:
        """检查缓存与数据源的一致性"""
        cache_key = self._get_cache_key(data_type, symbol, market, namespace="datalake")
        cached_data = self._get_cached(cache_key)
        
        source_data = self.fetcher.get_price(symbol)
        if source_data is not None and not source_data.empty:
            source_data = self.cleaner.clean_stock_daily(source_data)
        
        return self._cache_coordinator.check_consistency(symbol, cached_data, source_data)

    def rebuild_cache(
        self, symbol: str, data_type: str = "stock", market: str = "cn"
    ) -> bool:
        """重建缓存"""
        self._clear_fetcher_price_cache(symbol)

        if data_type in ["stock", "etf"]:
            source_data = self.fetcher.get_price(symbol)
        elif data_type == "index":
            source_data = self.fetcher.get_price(symbol, adjust="")
        else:
            logger.error("Unsupported data type for cache rebuild: %s", data_type)
            return False

        if source_data is None or source_data.empty:
            logger.warning("Failed to fetch data for cache rebuild")
            return False

        cleaned_data = self.cleaner.clean_stock_daily(source_data)

        if cleaned_data.empty:
            logger.warning("Cleaned data is empty for cache rebuild")
            return False

        self.lake.write_data(symbol, cleaned_data, data_type, market=market, overwrite=True)

        self.invalidate_symbol_cache(symbol, data_type=data_type, market=market)
        cache_key = self._get_cache_key(data_type, symbol, market, namespace="datalake")
        self._set_cache(cache_key, cleaned_data, data_type=data_type)

        logger.info("Cache rebuilt for %s (%s)", symbol, data_type)
        return True

    def check_cache_health(self) -> Dict[str, Any]:
        """检查缓存健康状态"""
        return self._cache_coordinator.check_health()

    def calculate_data_quality(
        self, symbol: str, data_type: str = "stock", market: str = "cn"
    ) -> Dict[str, Any]:
        """计算数据质量指标"""
        data = self.lake.read_data(symbol, data_type, market=market)
        return self._quality_service.calculate_data_quality(data, symbol, data_type)

    def check_data_health(
        self, symbols: List[str], data_type: str = "stock", market: str = "cn"
    ) -> List[Dict[str, Any]]:
        """检查多个符号的数据健康状态"""
        data_items = []
        for symbol in symbols:
            data = self.lake.read_data(symbol, data_type, market=market)
            data_items.append({"data": data, "symbol": symbol, "data_type": data_type})
        return self._quality_service.check_data_health(data_items)

    def generate_data_quality_report(
        self, symbols: List[str], data_type: str = "stock", market: str = "cn"
    ) -> Dict[str, Any]:
        """生成数据质量报告"""
        data_items = []
        for symbol in symbols:
            data = self.lake.read_data(symbol, data_type, market=market)
            data_items.append({"data": data, "symbol": symbol, "data_type": data_type})
        return self._quality_service.generate_data_quality_report(data_items)

    def monitor_data_quality(
        self,
        symbols: List[str],
        data_type: str = "stock",
        market: str = "cn",
        threshold: float = 70.0,
    ) -> List[Dict[str, Any]]:
        """监控数据质量并生成告警"""
        data_items = []
        for symbol in symbols:
            data = self.lake.read_data(symbol, data_type, market=market)
            data_items.append({"data": data, "symbol": symbol, "data_type": data_type})
        return self._quality_service.monitor_data_quality(data_items, threshold)

    def refresh_stock_map(self) -> Dict[str, str]:
        """刷新股票映射"""
        return self._stock_query.refresh_stock_map()

    def get_stock_name(self, symbol: str) -> str:
        """根据股票代码获取股票名称"""
        return self._stock_query.get_stock_name(symbol)

    @handle_errors(
        DataFetchError,
        DataValidationError,
        DataStorageError,
        CacheError,
        default_return=None,
        log_level=logging.ERROR,
    )
    def fetch_data(
        self, symbol: str, start_date: str, end_date: str, use_cache: bool = True
    ) -> Optional[pd.DataFrame]:
        """获取数据（带缓存降级策略）"""
        return self._get_access_service().fetch_data(
            symbol, start_date, end_date, use_cache
        )

    def _fetch_from_cache(self, cache_key: str, symbol: str) -> Optional[pd.DataFrame]:
        return self._get_access_service().fetch_from_cache(cache_key, symbol)

    def _fetch_from_source(
        self, symbol: str, start_date: str, end_date: str, cache_key: str, use_cache: bool
    ) -> Optional[pd.DataFrame]:
        return self._get_access_service().fetch_from_source(
            symbol, start_date, end_date, cache_key, use_cache
        )

    def _fetch_from_lake(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        return self._get_access_service().fetch_from_lake(symbol, start_date, end_date)

    @handle_errors(
        DataFetchError,
        DataValidationError,
        DataStorageError,
        default_return=None,
        log_level=logging.ERROR,
    )
    def fetch_and_save_stock(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """获取并保存股票数据"""
        return self._get_access_service().fetch_and_save_dataset(
            symbol, start_date, end_date, data_type="stock"
        )

    def _fetch_and_filter_price(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """获取价格数据并过滤日期范围"""
        return self._get_access_service()._fetch_and_filter_price(
            symbol, start_date, end_date
        )

    @handle_errors(
        DataFetchError,
        DataValidationError,
        DataStorageError,
        default_return=None,
        log_level=logging.ERROR,
    )
    def fetch_and_save_index(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """获取并保存指数数据"""
        return self._get_access_service().fetch_and_save_dataset(
            symbol, start_date, end_date, data_type="index"
        )

    def _fetch_and_filter_index(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """获取指数数据并过滤日期范围"""
        return self._get_access_service()._fetch_and_filter_index(
            symbol, start_date, end_date
        )

    @handle_errors(
        DataStorageError,
        default_return=None,
        log_level=logging.ERROR,
    )
    def get_stock(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """从数据湖获取股票数据"""
        return self._get_access_service().get_from_lake(symbol, "stock")

    @handle_errors(
        DataStorageError,
        default_return=None,
        log_level=logging.ERROR,
    )
    def get_index(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """从数据湖获取指数数据"""
        return self._get_access_service().get_from_lake(symbol, "index")

    @handle_errors(
        DataStorageError,
        DataFetchError,
        default_return={},
        log_level=logging.ERROR,
    )
    def fetch_for_brain(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """为大脑准备数据"""
        data_pack = {}
        data_pack["stock"] = self._load_data_with_fallback(
            symbol, "stock", f"stock data for {symbol}"
        )
        data_pack["bench"] = self._load_data_with_fallback(
            "sh000300", "index", "benchmark data (HS300)"
        )
        data_pack["etf"] = self._load_etf_data()
        return data_pack

    def _load_data_with_fallback(self, symbol: str, data_type: str, description: str) -> pd.DataFrame:
        """加载数据，失败时回退到数据源"""
        return self._get_access_service().load_data_with_fallback(
            symbol, data_type, description
        )

    def _load_etf_data(self) -> pd.DataFrame:
        """加载ETF数据"""
        return self._get_access_service().load_etf_data()

    @handle_errors(DataFetchError, default_return=None, log_level=logging.ERROR)
    def get_industry_data(self) -> Optional[pd.DataFrame]:
        """获取行业分类数据"""
        industries, _ = self.fetcher.fetch_industry_concept_data()
        return industries

    @handle_errors(DataFetchError, default_return=None, log_level=logging.ERROR)
    def get_sector_performance(
        self, sector_name: str, days: int = TimeConstants.DATA_WINDOW_30DAYS
    ) -> Optional[pd.DataFrame]:
        """获取板块表现数据"""
        end_date = pd.Timestamp(get_time_provider().now()).strftime("%Y-%m-%d")
        start_date = (pd.Timestamp(get_time_provider().now()) - pd.DateOffset(days=days)).strftime("%Y-%m-%d")
        df = self.fetcher.fetch_sector_daily(sector_name, start_date, end_date)
        if df.empty:
            logger.warning("No sector data for %s", sector_name)
            return None
        return df

    @handle_errors(DataFetchError, default_return={}, log_level=logging.ERROR)
    def get_stock_info(self) -> Dict[str, str]:
        """获取股票代码到名称的映射"""
        return self._stock_query.get_stock_info()

    def _process_single_stock(
        self, symbol: str, start_date: str, end_date: str
    ) -> Tuple[str, bool]:
        """处理单个股票"""
        try:
            result = self.lake.read_data(symbol, data_type="stock", market="cn")
            success = result is not None and not result.empty
            if success:
                logger.info("Successfully processed %s from data lake", symbol)
            else:
                logger.warning("Failed to process %s: no data in data lake", symbol)
            return symbol, success
        except (DataStorageError, Exception) as e:
            logger.error("Error processing %s: %s", symbol, e)
            return symbol, False

    @handle_errors(
        DataFetchError,
        DataValidationError,
        DataStorageError,
        default_return={},
        log_level=logging.ERROR,
    )
    def batch_process_stocks(
        self, symbols: List[str], start_date: str, end_date: str
    ) -> Dict[str, bool]:
        """批量处理股票"""
        num_cores = min(multiprocessing.cpu_count(), len(symbols), 4)
        logger.info("Batch processing %d stocks with %d cores", len(symbols), num_cores)

        process_func = partial(
            self._process_single_stock, start_date=start_date, end_date=end_date
        )

        results = Parallel(n_jobs=num_cores, backend="threading")(
            delayed(process_func)(symbol) for symbol in symbols
        )

        return dict(results)

    @handle_errors(DataStorageError, default_return=[], log_level=logging.ERROR)
    def list_data_files(self) -> List[str]:
        """列出数据湖中的数据文件"""
        files = []
        symbols = self.storage_manager.get_symbols()
        for symbol in symbols:
            file_path = os.path.join(str(self.storage_manager.daily_dir), f"{symbol}.parquet")
            files.append(file_path)
        return files

    def delete_file(self, file_path: str) -> bool:
        """从数据湖删除文件"""
        try:
            import os
            file_name = os.path.basename(file_path)
            if file_name.endswith(".parquet"):
                symbol = file_name[:-8]
                for data_type in self.lake.data_types:
                    expected_path = self.lake._get_file_path(symbol, data_type)
                    if expected_path == file_path:
                        return self.lake.delete_data(symbol, data_type)

            logger.error("Could not parse file path: %s", file_path)
            return False
        except (DataStorageError, Exception) as e:
            logger.error("Failed to delete file: %s", e)
            return False

    @handle_errors(
        DataFetchError,
        DataValidationError,
        DataStorageError,
        default_return=False,
        log_level=logging.ERROR,
    )
    def download_stock(self, symbol: str) -> bool:
        """下载股票数据"""
        end_date = pd.Timestamp(get_time_provider().now()).strftime("%Y-%m-%d")
        start_date = (
            pd.Timestamp(get_time_provider().now()) - pd.DateOffset(days=TimeConstants.DATA_WINDOW_365DAYS)
        ).strftime("%Y-%m-%d")

        result = self.fetch_and_save_stock(symbol, start_date, end_date)
        return result is not None and not result.empty

    def download_etf_sector_data(self) -> bool:
        """下载ETF板块数据"""
        try:
            etfs = ["510300", "510500", "510050", "513050"]
            end_date = pd.Timestamp(get_time_provider().now()).strftime("%Y-%m-%d")
            start_date = (
                pd.Timestamp(get_time_provider().now()) - pd.DateOffset(days=TimeConstants.DATA_WINDOW_365DAYS)
            ).strftime("%Y-%m-%d")

            results = self.batch_process_stocks(etfs, start_date, end_date)
            success_count = sum(results.values())

            logger.info("Downloaded ETF data: %d/%d successful", success_count, len(etfs))
            return success_count > 0
        except (DataFetchError, DataValidationError, DataStorageError, Exception) as e:
            logger.error("Failed to download ETF sector data: %s", e)
            return False

    @handle_errors(
        DataFetchError,
        DataValidationError,
        DataStorageError,
        default_return=None,
        log_level=logging.ERROR,
    )
    def get_real_kline_data(
        self, ticker: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """获取实时K线数据"""
        return self.get_stock(ticker, start_date, end_date)

    @handle_errors(DataStorageError, default_return=None, log_level=logging.ERROR)
    def query_lake(self, sql_condition: str) -> Optional[pd.DataFrame]:
        """查询数据湖"""
        logger.warning("query_lake method not fully implemented")
        return None

    @handle_errors(DataFetchError, default_return=[], log_level=logging.ERROR)
    def scan_etfs(self) -> List[str]:
        """扫描ETF"""
        return self._stock_query.scan_etfs()

    @handle_errors(DataStorageError, default_return={}, log_level=logging.ERROR)
    def get_portfolio(self) -> Dict[str, Any]:
        """获取投资组合"""
        try:
            portfolio = self.lake.load_portfolio()
            logger.info("Loaded portfolio with %d positions", len(portfolio))
            return portfolio
        except (DataStorageError, Exception) as e:
            logger.error("Failed to get portfolio: %s", e)
            return {}
