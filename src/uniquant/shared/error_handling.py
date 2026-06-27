import functools
import inspect
import logging
import random
import threading
import time
import traceback
import warnings
from typing import Any, Callable, Dict, Optional, Tuple, Type

import pandas as pd
import requests
import urllib3

from .constants import NetworkConstants
from .exceptions import AlphaTacticianError
from .logger_factory import get_logger

# 使用原始logging，避免装饰器递归调用问题
_error_logger = logging.getLogger("alpha_tactician.errors")
logger = get_logger("ErrorHandling")

# NON_RESEARCH_RANDOMNESS: retry jitter is network backoff noise, not research RNG.

# 错误统计 - 线程安全实现
_error_stats: Dict[str, Dict[str, int]] = {}
_error_stats_lock = threading.Lock()


def _emit_log(
    log_level: Any,
    message: str,
    *,
    exc_info: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """统一日志出口，兼容 logging level 与 logger.method 两种传参。"""
    if callable(log_level):
        try:
            log_level(message, exc_info=exc_info, extra=extra)
            return
        except TypeError:
            log_level(message)
            return

    level = log_level if isinstance(log_level, int) else logging.ERROR
    _error_logger.log(level, message, exc_info=exc_info, extra=extra)


def _update_error_stats(func_name: str, error_type: str):
    """更新错误统计 - 线程安全"""
    with _error_stats_lock:
        if func_name not in _error_stats:
            _error_stats[func_name] = {}
        _error_stats[func_name][error_type] = _error_stats[func_name].get(error_type, 0) + 1


def _resolve_log_level(log_level: Any) -> int:
    """兼容传入 logging level 或 logger method。"""
    if isinstance(log_level, int):
        return log_level

    if callable(log_level):
        name = getattr(log_level, "__name__", "").lower()
        return getattr(logging, name.upper(), logging.ERROR)

    return logging.ERROR


def handle_errors(
    *expected_exceptions: Type[Exception],
    default_return: Any = None,
    log_level: int = logging.ERROR,
    reraise: bool = True,
    error_type: str = "unknown",
    context: Optional[Dict[str, Any]] = None,
):
    """通用错误处理装饰器

    Args:
        expected_exceptions: 预期捕获的异常类型
        default_return: 异常发生时的默认返回值
        log_level: 日志级别
        reraise: 是否重新抛出异常
        error_type: 错误类型
        context: 上下文信息
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except expected_exceptions as e:
                # 更新错误统计
                _update_error_stats(func.__name__, error_type)

                # 构建错误消息
                error_msg = f"Error in {func.__name__}: {e}"
                if context:
                    error_msg += f" Context: {context}"

                # 记录详细错误信息
                _emit_log(
                    log_level,
                    error_msg,
                    exc_info=True,
                    extra={
                        "function": func.__name__,
                        "error_type": error_type,
                        "context": context,
                        "func_args": str(args[:2]) + ("..." if len(args) > 2 else ""),
                        "func_kwargs": {
                            k: v
                            for k, v in kwargs.items()
                            if k not in ["password", "token"]
                        },
                    },
                )

                if reraise:
                    raise
                return default_return
            except AlphaTacticianError as e:
                # 自定义异常，直接记录并处理
                _update_error_stats(func.__name__, "alpha_tactician_error")

                error_msg = f"AlphaTacticianError in {func.__name__}: {e}"
                if context:
                    error_msg += f" Context: {context}"

                _emit_log(
                    log_level,
                    error_msg,
                    exc_info=True,
                    extra={
                        "function": func.__name__,
                        "error_type": "alpha_tactician_error",
                        "context": context,
                        "func_args": str(args[:2]) + ("..." if len(args) > 2 else ""),
                        "func_kwargs": {
                            k: v
                            for k, v in kwargs.items()
                            if k not in ["password", "token"]
                        },
                    },
                )

                if reraise:
                    raise
                return default_return
            except Exception as e:
                # 未预期的异常，记录为错误
                _update_error_stats(func.__name__, "unexpected")

                error_msg = f"Unexpected error in {func.__name__}: {e}"
                if context:
                    error_msg += f" Context: {context}"

                _emit_log(
                    logging.ERROR,
                    error_msg,
                    exc_info=True,
                    extra={
                        "function": func.__name__,
                        "error_type": "unexpected",
                        "context": context,
                        "traceback": traceback.format_exc(),
                        "func_args": str(args[:2]) + ("..." if len(args) > 2 else ""),
                        "func_kwargs": {
                            k: v
                            for k, v in kwargs.items()
                            if k not in ["password", "token"]
                        },
                    },
                )

                if reraise:
                    raise
                return default_return

        return wrapper

    return decorator


def retry_on_exception(
    max_retries: Optional[int] = None,
    backoff: Optional[float] = None,
    retry_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    jitter: bool = True,
    max_wait_time: float = 30.0,
):
    """重试装饰器

    .. deprecated::
        请使用 ``uniquant.shared.retry_decorator.retry`` 代替，此函数将在后续版本移除。
    """
    warnings.warn(
        "retry_on_exception 已弃用，请使用 retry_decorator.retry 代替",
        DeprecationWarning,
        stacklevel=2,
    )
    if max_retries is None:
        max_retries = NetworkConstants.MAX_RETRIES
    if backoff is None:
        backoff = NetworkConstants.RETRY_DELAY_BASE

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except retry_exceptions as e:
                    if attempt == max_retries - 1:
                        _error_logger.error(
                            f"All {max_retries} attempts failed for {func.__name__}: {e}",
                            extra={
                                "function": func.__name__,
                                "attempts": max_retries,
                                "error": str(e),
                            },
                        )
                        raise

                    wait_time = min(
                        backoff * (NetworkConstants.RETRY_BACKOFF**attempt),
                        max_wait_time,
                    )
                    if jitter:
                        # 使用常量中的抖动因子
                        wait_time *= (
                            NetworkConstants.RETRY_JITTER_MIN
                            + (
                                NetworkConstants.RETRY_JITTER_MAX
                                - NetworkConstants.RETRY_JITTER_MIN
                            )
                            * random.random()
                        )

                    _error_logger.warning(
                        f"Attempt {attempt + 1} failed for {func.__name__}: {e}. "
                        f"Retrying in {wait_time:.2f}s...",
                        extra={
                            "function": func.__name__,
                            "attempt": attempt + 1,
                            "max_attempts": max_retries,
                            "wait_time": wait_time,
                            "error": str(e),
                        },
                    )
                    time.sleep(wait_time)

        return wrapper

    return decorator


def validate_inputs(**validators):
    """输入验证装饰器

    Args:
        validators: 键值对，键为参数名，值为验证函数
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # 获取函数签名
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # 执行验证
            for param_name, validator in validators.items():
                if param_name in bound_args.arguments:
                    value = bound_args.arguments[param_name]
                    if not validator(value):
                        error_msg = f"Invalid value for {param_name}: {value}"
                        logger.error(
                            error_msg,
                            extra={
                                "function": func.__name__,
                                "param_name": param_name,
                                "param_value": str(value),
                            },
                        )
                        raise ValueError(error_msg)

            return func(*args, **kwargs)

        return wrapper

    return decorator


def get_error_stats() -> Dict[str, Dict[str, int]]:
    """获取错误统计信息 - 线程安全

    Returns:
        错误统计信息的副本
    """
    with _error_stats_lock:
        return {k: v.copy() for k, v in _error_stats.items()}


def reset_error_stats() -> None:
    """重置错误统计信息 - 线程安全"""
    global _error_stats
    with _error_stats_lock:
        _error_stats = {}


def with_context(context: Dict[str, Any]):
    """带上下文的错误处理装饰器

    Args:
        context: 上下文信息
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Error in {func.__name__}: {e}",
                    exc_info=True,
                    extra={
                        "function": func.__name__,
                        "context": context,
                        "func_args": str(args[:2]) + ("..." if len(args) > 2 else ""),
                        "func_kwargs": {
                            k: v
                            for k, v in kwargs.items()
                            if k not in ["password", "token"]
                        },
                    },
                )
                raise

        return wrapper

    return decorator


def handle_network_errors(default_return: Any = None, max_retries: Optional[int] = None):
    """网络操作错误处理装饰器

    .. deprecated::
        请使用 ``uniquant.shared.retry_decorator.retry`` 配合 ``@handle_errors`` 代替。
        此包装器将在后续版本移除。
    """
    warnings.warn(
        "handle_network_errors 已弃用，请使用 retry_decorator.retry 配合 @handle_errors 代替",
        DeprecationWarning,
        stacklevel=2,
    )
    network_exceptions = (
        requests.RequestException,
        urllib3.exceptions.HTTPError,
        ConnectionError,
        TimeoutError,
    )

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        @handle_errors(
            *network_exceptions,
            default_return=default_return,
            error_type="network",
            log_level=logging.WARNING,
            reraise=False,
        )
        @retry_on_exception(
            max_retries=max_retries,
            retry_exceptions=network_exceptions,
        )
        def wrapper(*args, **kwargs) -> Any:
            return func(*args, **kwargs)

        return wrapper

    return decorator


def handle_file_errors(default_return: Any = None):
    """文件操作错误处理装饰器

    .. deprecated::
        请使用 ``@handle_errors`` 捕获对应的文件异常代替。
        此包装器将在后续版本移除。
    """
    warnings.warn(
        "handle_file_errors 已弃用，请直接使用 @handle_errors 代替",
        DeprecationWarning,
        stacklevel=2,
    )
    file_exceptions = (
        FileNotFoundError,
        PermissionError,
        IsADirectoryError,
        NotADirectoryError,
        IOError,
    )

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        @handle_errors(
            *file_exceptions,
            default_return=default_return,
            error_type="file",
            log_level=logging.ERROR,
            reraise=False,
        )
        def wrapper(*args, **kwargs) -> Any:
            return func(*args, **kwargs)

        return wrapper

    return decorator


def handle_data_errors(default_return: Any = None):
    """数据处理错误处理装饰器

    .. deprecated::
        请使用 ``@handle_errors`` 捕获对应的数据异常代替。
        此包装器将在后续版本移除。
    """
    warnings.warn(
        "handle_data_errors 已弃用，请直接使用 @handle_errors 代替",
        DeprecationWarning,
        stacklevel=2,
    )
    data_exceptions = (
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        ValueError,
        TypeError,
        KeyError,
    )

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        @handle_errors(
            *data_exceptions,
            default_return=default_return,
            error_type="data",
            log_level=logging.ERROR,
            reraise=False,
        )
        def wrapper(*args, **kwargs) -> Any:
            return func(*args, **kwargs)

        return wrapper

    return decorator


def handle_api_errors(default_return: Any = None, max_retries: int = 3):
    """API操作错误处理装饰器

    .. deprecated::
        请使用 ``uniquant.shared.retry_decorator.retry`` 配合 ``@handle_errors`` 代替。
        此包装器将在后续版本移除。
    """
    warnings.warn(
        "handle_api_errors 已弃用，请使用 retry_decorator.retry 配合 @handle_errors 代替",
        DeprecationWarning,
        stacklevel=2,
    )
    api_exceptions = (
        requests.RequestException,
        ValueError,
        KeyError,
    )

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        @handle_errors(
            *api_exceptions,
            default_return=default_return,
            error_type="api",
            log_level=logging.ERROR,
            reraise=False,
        )
        @retry_on_exception(
            max_retries=max_retries,
            retry_exceptions=api_exceptions,
        )
        def wrapper(*args, **kwargs) -> Any:
            return func(*args, **kwargs)

        return wrapper

    return decorator
