import random
import time

import requests
import requests.adapters
import requests.exceptions

from ...shared.constants import NetworkConstants
from ...shared.exceptions import DataValidationError
from ...shared.logger_factory import get_logger

from .base import DataSource, with_circuit_breaker

logger = get_logger(__name__)

# NON_RESEARCH_RANDOMNESS: request sleeps are source throttling controls only.


class EastmoneyBase(DataSource):
    def __init__(self):
        super().__init__()
        self.session = self._create_session()
        self.request_count = 0
        self.last_request_time = 0

    def _create_session(self):
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(
                total=2,
                backoff_factor=1.0,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS"],
            )
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.timeout = NetworkConstants.LONG_TIMEOUT
        return session

    @with_circuit_breaker(fail_max=5, reset_timeout=30)
    def _request(self, url, params=None, headers=None, timeout=NetworkConstants.LONG_TIMEOUT):
        if headers is None:
            headers = self._get_headers()

        try:
            self._control_request_rate()

            delay = random.uniform(0.5, 1.0)
            time.sleep(delay)
            logger.debug(f"请求前延迟: {delay:.2f}秒")

            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=(10, timeout),
                verify=True
            )

            response.raise_for_status()

            try:
                return response.json()
            except ValueError:
                text = response.text
                if "(" in text and ")" in text:
                    json_str = text[text.find("(") + 1: text.rfind(")")]
                    import json
                    return json.loads(json_str)
                else:
                    raise DataValidationError("Invalid response format")

        except requests.exceptions.ConnectTimeout as e:
            logger.error(f"连接超时: 无法连接到服务器 {url}. 错误: {e}")
            logger.error("可能原因: 网络问题、DNS解析失败、服务器不可达或被防火墙阻挡")
            raise
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"网络连接错误: {e}")
            self._switch_proxy()
            raise
        except requests.exceptions.ReadTimeout as e:
            logger.warning(f"读取超时: 服务器响应太慢 {e}")
            raise
        except requests.exceptions.Timeout as e:
            logger.warning(f"请求超时: {e}")
            self._switch_proxy()
            raise
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP错误: {e}")
            try:
                if response.status_code == 403:
                    logger.warning("403错误，可能被反爬，尝试切换代理")
                    self._switch_proxy()
            except (AttributeError, RuntimeError):
                logger.exception("切换代理失败，继续抛出原始异常")
                pass
            raise
        except Exception as e:
            logger.warning(f"请求失败: {e}")
            raise

    def _get_headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/center/gridlist.html",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-site",
        }

    def _control_request_rate(self):
        self.request_count += 1

        if self.request_count % 10 == 0:
            extra_delay = random.uniform(3, 5)
            logger.debug(f"每10个请求额外延迟: {extra_delay:.2f}秒")
            time.sleep(extra_delay)

        current_time = time.time()
        elapsed = current_time - self.last_request_time
        min_interval = 1.0

        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            logger.debug(f"控制请求间隔，等待: {wait_time:.2f}秒")
            time.sleep(wait_time)

        self.last_request_time = time.time()

    @property
    def name(self) -> str:
        return "eastmoney"

    def _convert_symbol(self, symbol: str) -> tuple:
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        if clean_symbol.startswith(("6", "5")):
            return "1", clean_symbol
        elif clean_symbol.startswith(("0", "3", "8", "4")):
            return "0", clean_symbol
        else:
            return "0", clean_symbol