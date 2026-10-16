"""
数据源基类

``DataSource`` 是本地数据源的抽象契约: 名称 / 资源释放 (上下文管理器) / 三个
数据获取抽象方法。具体的列名标准化由 ``data/utils/normalizer.py`` 统一负责
(单一实现), 基类不再保留重复的列处理工具。
"""

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class DataSource(ABC):
    """
    数据源基类
    """

    @property
    def name(self) -> str:
        """
        数据源名称
        """
        return self.__class__.__name__.replace("Source", "")

    def close(self) -> None:
        """关闭会话资源"""
        if hasattr(self, 'session') and self.session is not None:
            try:
                self.session.close()
            except Exception as e:
                logger.debug(f"Error closing session: {e}")
            self.session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

    # ── Abstract methods ─────────────────────────────────────────────────

    @abstractmethod
    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取日线数据

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            pd.DataFrame: 日线数据
        """
        pass

    @abstractmethod
    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """
        获取实时数据

        Args:
            symbol: 股票代码，None 表示获取所有

        Returns:
            pd.DataFrame: 实时数据
        """
        pass

    @abstractmethod
    def fetch_market_cap(self, symbol: str) -> float:
        """
        获取市值

        Args:
            symbol: 股票代码

        Returns:
            float: 市值
        """
        pass
