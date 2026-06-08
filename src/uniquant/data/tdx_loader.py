from typing import Optional

import pandas as pd

from uniquant.shared.logger_factory import get_logger

logger = get_logger(__name__)


def load_tdx_data(filepath: str) -> Optional[pd.DataFrame]:
    try:
        import pytdx.reader as reader
        df = reader.TdxDayBarReader.get_data(filepath)
        if df is not None and not df.empty:
            return df
    except Exception:
        logger.warning("Failed to load TDX data from %s", filepath, exc_info=True)
    return None
