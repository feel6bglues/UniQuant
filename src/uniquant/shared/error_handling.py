import functools
import inspect
import logging
import threading
import traceback
from typing import Any, Callable, Dict, Optional, Type

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
        default_return: 异常发生时的默认返回值。
            ⚠️ **仅在 ``reraise=False`` 时生效**：默认 ``reraise=True`` 会在记录
            日志后立即 ``raise``，从而短路 ``default_return``，使其永不返回
            （§7.4 #8：全仓约 30 处调用点传了非 None 的 ``default_return`` 却未传
            ``reraise=False``，这些默认值实际不生效 —— 属既有约定；此处只如实
            记录语义，**未改默认值**，以免静默改变这些调用点 fail-fast 的失败语义）。
        log_level: 日志级别
        reraise: 是否重新抛出异常（默认 True = 记录后抛出，fail-fast）
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
