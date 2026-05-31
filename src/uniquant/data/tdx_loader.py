from typing import Optional
import pandas as pd


def load_tdx_data(filepath: str) -> Optional[pd.DataFrame]:
    try:
        import pytdx.reader as reader
        df = reader.TdxDayBarReader.get_data(filepath)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return None
