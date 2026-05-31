from typing import Optional
import pandas as pd

from .lake.storage_manager import StorageManager


class DataManager:
    def __init__(self):
        self.storage = StorageManager()

    def get_data(self, symbol: str) -> Optional[pd.DataFrame]:
        return self.storage.read_data(symbol)
