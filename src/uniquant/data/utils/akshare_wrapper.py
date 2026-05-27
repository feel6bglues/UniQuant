import importlib
import logging
import random
import time
import urllib.error
from typing import Any, Dict, Optional

import pandas as pd
import requests.exceptions

from ...shared.error_handling import handle_errors
from ...shared.exceptions import DataFetchError, DataValidationError
from ...shared.logger_factory import get_logger
from ...shared.retry_decorator import retry
from .akshare_market_service import AkshareMarketService
from .akshare_reference_service import AkshareReferenceService

logger = get_logger(__name__)


class AkShareWrapper:
    """
    AkShare包装器，提供统一的错误处理、重试机制和连接管理
    """

    def __init__(self):
        """
        初始化AkShare包装器
        """
        self._ak = None
        self._initialized = False
        self._init_akshare()
        self._last_call_time = 0
        self._min_interval = 0.5  # 最小请求间隔
        self._method_stats: Dict[str, Dict[str, Any]] = {}  # 方法调用统计
        self._request_headers = self._generate_request_headers()
        self.market_service = AkshareMarketService(self.call)
        self.reference_service = AkshareReferenceService(self.call)

    def _generate_request_headers(self) -> Dict[str, str]:
        """
        生成随机请求头，减少被反爬的概率
        """
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.2; rv:109.0) Gecko/20100101 Firefox/120.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        ]

        return {
            "User-Agent": random.choice(user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://quote.eastmoney.com/",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }

    def _init_akshare(self):
        """
        初始化AkShare模块
        """
        try:
            import akshare as ak

            self._ak = ak

            # 配置AkShare
            if hasattr(ak, "set_option"):
                try:
                    ak.set_option("use_ssl", True)
                    ak.set_option("timeout", 30)
                except Exception as e:
                    logger.warning(f"Error setting AkShare options: {e}")

                # 设置请求头
                if hasattr(ak, "set_headers"):
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
                        "Accept-Encoding": "gzip, deflate",
                        "Connection": "close",
                        "Referer": "https://quote.eastmoney.com/",
                    }
                    try:
                        ak.set_headers(headers)
                        logger.info("已设置优化后的请求头")
                    except Exception as e:
                        logger.warning(f"Error setting AkShare headers: {e}")

            self._initialized = True
            logger.info("AkShare initialized successfully")
        except (ImportError, KeyError, ValueError, TypeError) as e:
            logger.error(f"Failed to initialize akshare: {e}")
            self._initialized = False
        except Exception as e:
            logger.error(f"Unexpected error initializing akshare: {e}")
            self._initialized = False

    def is_initialized(self) -> bool:
        """
        检查AkShare是否初始化成功

        Returns:
            bool: AkShare初始化状态
        """
        return self._initialized

    def _control_request_rate(self):
        """
        控制请求速率，避免请求过于频繁
        """
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            wait_time = self._min_interval - elapsed
            random_delay = random.uniform(0.3, 0.7)
            total_wait = wait_time + random_delay
            logger.debug(f"请求速率控制: 等待 {total_wait:.2f} 秒")
            time.sleep(total_wait)
        self._last_call_time = time.time()

    def _update_method_stats(
        self, method_name: str, success: bool, duration: float = 0
    ):
        """
        更新方法调用统计
        """
        if method_name not in self._method_stats:
            self._method_stats[method_name] = {
                "total": 0,
                "success": 0,
                "failed": 0,
                "avg_duration": 0,
                "last_called": 0,
            }

        stats = self._method_stats[method_name]
        stats["total"] += 1
        stats["last_called"] = time.time()

        if success:
            stats["success"] += 1
            stats["avg_duration"] = (
                (stats["avg_duration"] * (stats["success"] - 1)) + duration
            ) / stats["success"]
        else:
            stats["failed"] += 1

    @retry(max_retries=5, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @handle_errors(
        urllib.error.URLError,
        requests.exceptions.RequestException,
        DataFetchError,
        DataValidationError,
        default_return=None,
        log_level=logging.ERROR,
    )
    def call(self, method_name: str, **kwargs) -> Optional[Any]:
        """
        调用AkShare方法，自动处理错误和重试

        Args:
            method_name: AkShare方法名
            **kwargs: 方法参数

        Returns:
            Optional[Any]: 方法返回值，失败返回None
        """
        if not self._initialized:
            logger.info(
                f"AkShare not initialized, trying to reinitialize for {method_name}"
            )
            self._init_akshare()

            if not self._initialized:
                logger.error(f"Failed to initialize AkShare, cannot call {method_name}")
                self._update_method_stats(method_name, False)
                return None

        try:
            self._control_request_rate()

            headers = self._generate_request_headers()
            if hasattr(self._ak, "set_headers"):
                self._ak.set_headers(headers)
                logger.debug(f"Set AkShare headers: {headers}")

            method = getattr(self._ak, method_name)
            logger.debug(f"Calling ak.{method_name} with kwargs: {kwargs}")

            start_time = time.time()
            result = method(**kwargs)
            end_time = time.time()
            duration = end_time - start_time

            logger.info(f"Successfully called ak.{method_name} in {duration:.2f}s")
            self._update_method_stats(method_name, True, duration)
            return result

        except AttributeError as e:
            logger.error(f"AkShare method not found: {method_name}")
            self._update_method_stats(method_name, False)
            return None
        except Exception as e:
            logger.error(f"Error calling ak.{method_name}: {e}")
            self._initialized = False
            self._update_method_stats(method_name, False)
            time.sleep(random.uniform(2, 5))
            return None

    def get_method_stats(self, method_name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取方法调用统计

        Args:
            method_name: 方法名，None表示获取所有方法的统计

        Returns:
            Dict[str, Any]: 方法调用统计
        """
        if method_name:
            return self._method_stats.get(method_name, {})
        return self._method_stats

    def clear_method_stats(self):
        """
        清除方法调用统计
        """
        self._method_stats.clear()

    def fetch_stock_daily(
        self, symbol: str, start_date: str, end_date: str, adjust: str = "qfq"
    ) -> Optional[pd.DataFrame]:
        return self.market_service.fetch_stock_daily(symbol, start_date, end_date, adjust)

    def fetch_stock_spot(self, source: str = "sina") -> Optional[pd.DataFrame]:
        return self.market_service.fetch_stock_spot(source)

    def fetch_stock_daily_sina(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        return self.market_service.fetch_stock_daily_sina(symbol, start_date, end_date)

    def fetch_etf_hist(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        return self.market_service.fetch_etf_hist(symbol, start_date, end_date)

    def fetch_industry_list(self) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_industry_list()

    def fetch_concept_list(self) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_concept_list()

    def fetch_concept_relation(self, symbol: str) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_concept_relation(symbol)

    def fetch_financial_breakfast(self) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_financial_breakfast()

    def fetch_stock_zt_pool_dtgc(self, date: str) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_stock_zt_pool_dtgc(date)

    def fetch_stock_zt_pool_previous(self, date: str) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_stock_zt_pool_previous(date)

    def fetch_stock_lhb_jgmmtj(
        self, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_stock_lhb_jgmmtj(start_date, end_date)

    def fetch_fund_hold_detail(self, symbol: str, date: str) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_fund_hold_detail(symbol, date)

    def fetch_hsgt_board_rank(
        self, symbol: str, indicator: str = "今日"
    ) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_hsgt_board_rank(symbol, indicator)

    def fetch_ipo_tutor(self) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_ipo_tutor()

    def fetch_dzjy_hyyybtj(self, symbol: str = "近3日") -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_dzjy_hyyybtj(symbol)

    def fetch_global_news(self, source: str = "em") -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_global_news(source)

    def fetch_stock_news(self, symbol: str) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_stock_news(symbol)

    def fetch_stock_yjyg(self) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_stock_yjyg()

    def fetch_stock_yysj(self) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_stock_yysj()

    def fetch_index_daily(self, symbol: str) -> Optional[pd.DataFrame]:
        return self.market_service.fetch_index_daily(symbol)

    def fetch_minute_data(
        self,
        symbol: str,
        period: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
    ) -> Optional[pd.DataFrame]:
        return self.market_service.fetch_minute_data(
            symbol, period, start_date, end_date, adjust
        )

    def fetch_fund_flow(self, stock: str, market: str = "sh") -> Optional[pd.DataFrame]:
        return self.market_service.fetch_fund_flow(stock, market)

    def fetch_dragon_tiger_list(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        return self.market_service.fetch_dragon_tiger_list(symbol, start_date, end_date)

    def fetch_tick_data(self, symbol: str) -> Optional[pd.DataFrame]:
        return self.market_service.fetch_tick_data(symbol)

    def fetch_concept_list_ths(self) -> Optional[pd.DataFrame]:
        return self.reference_service.fetch_concept_list_ths()


# 全局AkShare包装器实例
akshare_wrapper = AkShareWrapper()
