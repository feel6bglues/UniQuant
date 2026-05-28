"""请求工具模块，实现指数退避重试和请求间隔控制"""

import random
import time
from functools import wraps
from typing import Any, Callable, List, Optional, TypeVar

import requests

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class RequestControlManager:
    """请求控制管理器"""

    def __init__(self):
        """初始化请求控制管理器"""
        self._last_request_time = 0
        self._default_min_interval = 3  # 增加默认间隔以减少服务器压力

    def get_last_request_time(self) -> float:
        """获取上次请求时间"""
        return self._last_request_time

    def set_last_request_time(self, timestamp: float) -> None:
        """设置上次请求时间"""
        self._last_request_time = timestamp

    def get_default_min_interval(self) -> int:
        """获取默认最小请求间隔"""
        return self._default_min_interval


# 创建全局请求控制管理器实例
request_control_manager = RequestControlManager()


def with_request_control(
    min_interval: int = 2, max_retries: int = 3, backoff_factor: float = 1.0
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    请求控制装饰器，实现：
    1. 请求间隔控制
    2. 智能指数退避重试机制
    3. 错误类型分析和处理

    Args:
        min_interval: 最小请求间隔（秒）
        max_retries: 最大重试次数
        backoff_factor: 退避因子，默认为1.0
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            retry_count = 0
            base_delay = 1  # 降低基础延迟，提高响应速度
            max_delay = 30  # 最大延迟，避免无限等待

            while True:
                try:
                    # 控制请求间隔
                    current_time = time.time()
                    elapsed = (
                        current_time - request_control_manager.get_last_request_time()
                    )
                    if elapsed < min_interval:
                        wait_time = min_interval - elapsed
                        # 添加随机延迟，使请求间隔更加自然
                        random_delay = random.uniform(0.5, 1.5)
                        total_wait = wait_time + random_delay
                        logger.debug(f"等待 {total_wait:.2f} 秒后发送请求")
                        time.sleep(total_wait)

                    # 执行请求

                    result = func(*args, **kwargs)
                    request_control_manager.set_last_request_time(time.time())
                    return result

                except requests.exceptions.Timeout as e:
                    retry_count += 1
                    if retry_count > max_retries:
                        logger.error(
                            f"达到最大重试次数 ({max_retries})，最后一次错误: 超时错误 - {e}"
                        )
                        raise

                    # 超时错误，使用更长的延迟
                    delay = min(
                        base_delay * (backoff_factor**retry_count)
                        + random.uniform(0, 1),
                        max_delay,
                    )
                    logger.warning(
                        f"请求超时: {e}，{delay:.2f}秒后进行第 {retry_count} 次重试..."
                    )
                    time.sleep(delay)
                    request_control_manager.set_last_request_time(time.time() + delay)

                except requests.exceptions.ConnectionError as e:
                    retry_count += 1
                    if retry_count > max_retries:
                        logger.error(
                            f"达到最大重试次数 ({max_retries})，最后一次错误: 连接错误 - {e}"
                        )
                        raise

                    # 连接错误，使用中等延迟
                    delay = min(
                        base_delay * (backoff_factor**retry_count)
                        + random.uniform(0, 1),
                        max_delay,
                    )
                    logger.warning(
                        f"连接失败: {e}，{delay:.2f}秒后进行第 {retry_count} 次重试..."
                    )
                    time.sleep(delay)
                    request_control_manager.set_last_request_time(time.time() + delay)

                except requests.exceptions.HTTPError as e:
                    retry_count += 1
                    if retry_count > max_retries:
                        logger.error(
                            f"达到最大重试次数 ({max_retries})，最后一次错误: HTTP错误 - {e}"
                        )
                        raise

                    # HTTP错误，根据状态码决定是否重试
                    status_code = e.response.status_code if e.response else 0
                    if status_code in [429, 500, 502, 503, 504]:
                        # 服务器错误，进行重试
                        delay = min(
                            base_delay * (backoff_factor**retry_count)
                            + random.uniform(0, 1),
                            max_delay,
                        )
                        logger.warning(
                            f"HTTP错误 ({status_code}): {e}，{delay:.2f}秒后进行第 {retry_count} 次重试..."
                        )
                        time.sleep(delay)
                        request_control_manager.set_last_request_time(
                            time.time() + delay
                        )
                    else:
                        # 客户端错误，直接抛出
                        logger.error(f"HTTP错误 ({status_code}): {e}，不进行重试")
                        raise

                except Exception as e:
                    retry_count += 1
                    if retry_count > max_retries:
                        logger.error(
                            f"达到最大重试次数 ({max_retries})，最后一次错误: 未知错误 - {e}"
                        )
                        raise

                    # 其他错误，使用标准延迟
                    delay = min(
                        base_delay * (backoff_factor**retry_count)
                        + random.uniform(0, 1),
                        max_delay,
                    )
                    logger.warning(
                        f"请求失败: {e}，{delay:.2f}秒后进行第 {retry_count} 次重试..."
                    )
                    time.sleep(delay)
                    request_control_manager.set_last_request_time(time.time() + delay)

        return wrapper

    return decorator


def check_data_integrity(data: Any, required_fields: List[str]) -> bool:
    """
    检查数据完整性

    Args:
        data: 要检查的数据
        required_fields: 必填字段列表

    Returns:
        bool: 数据是否完整
    """
    if data is None:
        return False

    if hasattr(data, "empty") and data.empty:
        return False

    if hasattr(data, "columns"):
        for field in required_fields:
            if field not in data.columns:
                logger.warning(f"数据缺失必填列: {field}")
                return False

    return True


def get_session() -> requests.Session:
    """
    获取请求会话，配置更真实的浏览器头和重试参数

    Returns:
        requests.Session: 请求会话对象
    """
    session = requests.Session()

    # 设置更像真实浏览器的头部
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Connection": "close",  # 强制关闭 Keep-Alive
        "Referer": "https://quote.eastmoney.com/",  # 添加 Referer
    }
    session.headers.update(headers)

    # 配置重试策略
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


@with_request_control(min_interval=2, max_retries=3, backoff_factor=1.5)
def make_request(
    url: str,
    method: str = "GET",
    params: Optional[dict] = None,
    data: Optional[dict] = None,
    timeout: int = 15,
) -> Optional[requests.Response]:
    """
    发送HTTP请求，已集成优化后的 Session 和请求控制

    Args:
        url: 请求URL
        method: 请求方法
        params: URL参数
        data: 请求数据
        timeout: 超时时间

    Returns:
        Optional[requests.Response]: 响应对象，失败返回None
    """

    session = get_session()
    try:
        logger.debug(f"发送 {method} 请求到: {url}")
        if params:
            logger.debug(f"请求参数: {params}")
        
        if method.upper() == "GET":
            response = session.get(url, params=params, timeout=timeout)
        elif method.upper() == "POST":
            response = session.post(url, data=data, timeout=timeout)
        else:
            logger.error(f"不支持的请求方法: {method}")
            return None

        response.raise_for_status()
        logger.debug(f"请求成功，状态码: {response.status_code}")
        return response
    except requests.RequestException as e:
        logger.error(f"请求失败 ({url}): {e}")
        raise
    finally:
        session.close()
