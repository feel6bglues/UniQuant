"""
重试装饰器模块
提供统一的重试逻辑封装
"""

import time
from functools import wraps
from typing import Any, Callable, Optional, Tuple, Type

from .logger_factory import get_logger

logger = get_logger("RetryDecorator")


def retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: Optional[float] = None,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
    on_failure: Optional[Callable[[Exception], None]] = None,
):
    """
    重试装饰器

    自动重试失败的函数调用，支持指数退避

    Args:
        max_retries: 最大重试次数
        delay: 初始延迟(秒)
        backoff: 退避因子
        max_delay: 最大延迟(秒)
        exceptions: 需要重试的异常类型
        on_retry: 重试时的回调函数
        on_failure: 最终失败时的回调函数

    Returns:
        装饰器函数

    Example:
        >>> @retry(max_retries=3, delay=1.0)
        ... def fetch_data():
        ...     return requests.get("https://api.example.com/data")
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} 第 {attempt + 1}/{max_retries} 次尝试失败: {e}, "
                            f"{current_delay}s 后重试..."
                        )

                        if on_retry:
                            on_retry(e, attempt + 1)

                        time.sleep(current_delay)

                        # 计算下次延迟
                        current_delay *= backoff
                        if max_delay:
                            current_delay = min(current_delay, max_delay)
                    else:
                        logger.error(f"{func.__name__} 所有 {max_retries} 次重试都失败")
                        if on_failure:
                            on_failure(e)
                        raise

            # 不应该到达这里
            raise last_exception if last_exception else RuntimeError("Unexpected error")

        return wrapper

    return decorator


def retry_with_fallback(
    fallback_value: Any,
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    带降级值的重试装饰器

    所有重试失败后返回降级值而不是抛出异常

    Args:
        fallback_value: 降级值
        max_retries: 最大重试次数
        delay: 初始延迟(秒)
        backoff: 退避因子
        exceptions: 需要重试的异常类型

    Returns:
        装饰器函数

    Example:
        >>> @retry_with_fallback(fallback_value=[], max_retries=3)
        ... def fetch_list():
        ...     return api.get_list()
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} 第 {attempt + 1}/{max_retries} 次尝试失败: {e}, "
                            f"{current_delay}s 后重试..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"{func.__name__} 所有 {max_retries} 次重试都失败，"
                            f"返回降级值: {fallback_value}"
                        )
                        return fallback_value

        return wrapper

    return decorator


class RetryConfig:
    """
    重试配置类
    统一管理重试参数
    """

    # 默认配置
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_DELAY = 1.0
    DEFAULT_BACKOFF = 2.0
    DEFAULT_MAX_DELAY = 60.0

    # 数据源特定配置
    DATA_SOURCE_CONFIGS = {
        "eastmoney": {"max_retries": 3, "delay": 1.0, "backoff": 2.0},
        "sina": {"max_retries": 3, "delay": 0.5, "backoff": 1.5},
        "tencent": {"max_retries": 3, "delay": 0.5, "backoff": 1.5},
    }

    @classmethod
    def get_config(cls, source: str) -> dict:
        """
        获取数据源特定的重试配置

        Args:
            source: 数据源名称

        Returns:
            dict: 重试配置
        """
        return cls.DATA_SOURCE_CONFIGS.get(
            source,
            {
                "max_retries": cls.DEFAULT_MAX_RETRIES,
                "delay": cls.DEFAULT_DELAY,
                "backoff": cls.DEFAULT_BACKOFF,
            },
        )
