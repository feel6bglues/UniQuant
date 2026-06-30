from typing import Optional
import pandas as pd
from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


class DataIngestionService:
    def __init__(self, fetcher):
        self._fetcher = fetcher

    def fetch_price(self, symbol: str, source: str = "auto") -> Optional[pd.DataFrame]:
        try:
            return self._fetcher.source_router.fetch_with_fallback(symbol, source)
        except Exception as e:
            logger.error("Failed to fetch %s: %s", symbol, e)
            return None
