"""
数据源层

包含: base (ABC), protocols (能力协议), 10 个数据源实现
"""
from .base import DataSource
from .mootdx_local import MootdxLocalSource
from .mootdx_online import MootdxOnlineSource
from .tdxdata_online import TdxDataOnlineSource

__all__ = [
    "DataSource",
    "MootdxLocalSource",
    "MootdxOnlineSource",
    "TdxDataOnlineSource",
]
