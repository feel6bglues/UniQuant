"""
通用工具函数
"""

import threading
import time
from typing import Any, Callable, Optional, TypeVar

import pandas as pd

from .logger_factory import get_logger

logger = get_logger("Utils")

T = TypeVar("T")


def with_timeout(
    func: Callable[..., T], timeout: float = 5.0, default: Optional[T] = None
) -> Optional[T]:
    """
    带超时控制的函数执行

    Args:
        func: 要执行的函数
        timeout: 超时时间（秒）
        default: 超时时的默认返回值

    Returns:
        函数执行结果或默认值
    """
    result: list = []

    def target():
        try:
            result.append(func())
        except Exception as e:
            logger.warning(f"函数执行出错: {e}")
            if default is not None:
                result.append(default)

    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        logger.warning(f"函数执行超时（{timeout}秒）")
        return default

    return result[0] if result else default


def safe_execute(
    func: Callable[..., T],
    default: Optional[T] = None,
    error_message: str = "执行操作时出错",
) -> Optional[T]:
    """
    安全执行函数，捕获所有异常

    Args:
        func: 要执行的函数
        default: 出错时的默认返回值
        error_message: 错误信息前缀

    Returns:
        函数执行结果或默认值
    """
    try:
        return func()
    except Exception as e:
        logger.error(f"{error_message}: {e}")
        return default


def fetch_with_timeout(
    source: Any,
    method_name: str,
    *args,
    timeout: float = 5.0,
    default: Optional[Any] = None,
    **kwargs,
) -> Optional[Any]:
    """
    带超时控制的数据源方法调用

    Args:
        source: 数据源对象
        method_name: 方法名
        *args: 位置参数
        timeout: 超时时间（秒）
        default: 超时时的默认返回值
        **kwargs: 关键字参数

    Returns:
        方法执行结果或默认值
    """
    result = []

    def target():
        try:
            method = getattr(source, method_name)
            result.append(method(*args, **kwargs))
        except Exception as e:
            logger.warning(f"数据源方法调用出错: {e}")
            result.append(default)

    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        logger.warning(f"数据源方法调用超时（{timeout}秒）")
        return default

    return result[0] if result else default


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    标准化DataFrame列名

    Args:
        df: 原始DataFrame

    Returns:
        标准化后的DataFrame
    """
    if df.empty:
        return df

    # 列名映射
    column_mappings = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "Date": "date",
        "Open": "open",
        "Close": "close",
        "High": "high",
        "Low": "low",
        "Volume": "volume",
        "Amount": "amount",
    }

    # 重命名列
    df = df.rename(columns=column_mappings)

    # 确保日期列是datetime类型
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])

    return df


def retry_on_failure(
    func: Callable[..., T],
    max_retries: int = 3,
    delay: float = 1.0,
    default: Optional[T] = None,
) -> Optional[T]:
    """
    失败时自动重试的函数执行

    Args:
        func: 要执行的函数
        max_retries: 最大重试次数
        delay: 重试间隔（秒）
        default: 多次失败后的默认返回值

    Returns:
        函数执行结果或默认值
    """
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            logger.warning(f"尝试 {attempt + 1}/{max_retries} 失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                logger.error(f"最大重试次数已用尽")

    return default
