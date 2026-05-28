from typing import List, Optional, Any
import pandas as pd
from .managers.source_router import SourceRouter
from .managers.standard_adapter import StandardAdapter
from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


class DataIngestionService:
    def __init__(self, data_dir: str = "./data"):
        self._sources: List[Any] = []
        self._router: Optional[SourceRouter] = None
        self._initialized = False
        self._data_dir = data_dir

    def ensure_initialized(self):
        if not self._initialized:
            self._init_sources()
            self._initialized = True

    def _init_sources(self):
        from .sources.tdx import TdxSource
        from .sources.baostock import BaostockSource
        from .sources.sina import SinaSource
        from .sources.ths import ThsSource
        from .sources.tencent import TencentSource
        source_classes = [TdxSource, BaostockSource, SinaSource, ThsSource, TencentSource]
        self._sources = []
        FETCHER_INIT_RECOVERABLE_ERRORS = (Exception,)
        for source_cls in source_classes:
            try:
                self._sources.append(source_cls())
            except FETCHER_INIT_RECOVERABLE_ERRORS as e:
                logger.warning("数据源 %s 初始化失败，跳过: %s", source_cls.__name__, e)
        adapters = [StandardAdapter(s) for s in self._sources]
        self._router = SourceRouter(adapters)

    def fetch_price(self, symbol: str, source: str = "auto") -> Optional[pd.DataFrame]:
        self.ensure_initialized()
        return self._do_fetch(symbol, source)

    def _do_fetch(self, symbol: str, source: str) -> Optional[pd.DataFrame]:
        try:
            return self._router.fetch_with_fallback(symbol, source)
        except Exception as e:
            logger.error("Failed to fetch %s: %s", symbol, e)
            return None
