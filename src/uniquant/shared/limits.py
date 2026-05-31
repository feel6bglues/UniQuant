"""
涨跌停检查模块（兼容层）
为 brain/wyckoff/classifiers.py 提供兼容接口
实际实现位于 limit_checker.py
"""

from .limit_checker import is_limit_down, is_limit_up, check_limit_status, LimitStatus

__all__ = ['is_limit_down', 'is_limit_up', 'check_limit_status', 'LimitStatus']
