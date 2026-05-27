"""
数据标准化模块
统一处理所有数据源的输出，确保数据格式一致

注意: 此文件已作为facade，实际实现已迁移到 src/data/utils/normalizer.py
"""

from ..utils.normalizer import (
    normalize_stock_data,
    normalize_multiple_sources,
    compare_sources,
    _convert_units,
    _correct_calculations,
    _get_previous_close,
    _validate_data,
)

# 重新导出所有函数，确保向后兼容
__all__ = [
    "normalize_stock_data",
    "normalize_multiple_sources",
    "compare_sources",
    "_convert_units",
    "_correct_calculations",
    "_get_previous_close",
    "_validate_data",
]
