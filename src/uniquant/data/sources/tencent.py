import logging
import random
import time
import urllib.error
from typing import Optional, Dict, Any

import pandas as pd
import requests
import requests.exceptions

from ...shared.constants import DataSourceConstants, NetworkConstants
from ...shared.error_handling import handle_errors
from ...shared.exceptions import DataFetchError, DataValidationError
from ...shared.logger_factory import get_logger
from ...shared.retry_decorator import retry

from ..utils.request_utils import with_request_control
from ..utils.akshare_wrapper import akshare_wrapper
from .base import DataSource

logger = get_logger(__name__)


class TencentSource(DataSource):
    def __init__(self):
        super().__init__()
        self.session = self._create_session()
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
        ]

    def _create_session(self):
        """创建请求会话"""
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(
                total=5,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS"],
            )
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.timeout = NetworkConstants.LONG_TIMEOUT
        return session

    def _get_headers(self):
        """获取随机请求头"""
        return {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "http://finance.qq.com/",
            "Connection": "close",
            "Cache-Control": "no-cache",
            "DNT": "1",
            "Sec-GPC": "1",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }

    @property
    def name(self) -> str:
        return "tencent"

    def _convert_symbol(self, symbol: str) -> str:
        """转换股票代码格式为腾讯格式"""
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")

        if clean_symbol.startswith(("6", "5")):
            return f"sh{clean_symbol}"
        elif clean_symbol.startswith(("0", "3")):
            return f"sz{clean_symbol}"
        elif clean_symbol.startswith(("000", "399")):
            return f"sh{clean_symbol}"
        else:
            return clean_symbol

    @retry(
        max_retries=DataSourceConstants.MAX_RETRIES,
        delay=DataSourceConstants.RETRY_DELAY,
        backoff=DataSourceConstants.RETRY_BACKOFF,
        exceptions=(Exception,),
    )
    @with_request_control(
        min_interval=DataSourceConstants.MIN_REQUEST_INTERVAL,
        max_retries=DataSourceConstants.MAX_RETRIES,
    )
    @handle_errors(
        urllib.error.URLError,
        requests.exceptions.RequestException,
        DataFetchError,
        DataValidationError,
        default_return=pd.DataFrame(),
        log_level=logging.ERROR,
    )
    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        使用 AkShare 的 stock_zh_a_hist_tx() 获取腾讯财经历史数据
        """
        tencent_symbol = self._convert_symbol(symbol)
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")

        logger.info(
            f"开始从腾讯获取 {symbol} 的日线数据，时间范围: {start_date} 至 {end_date}"
        )

        try:
            import akshare as ak

            df = ak.stock_zh_a_hist_tx(
                symbol=tencent_symbol,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",
            )

            if df is None or df.empty:
                logger.warning(f"AkShare 返回空数据: {symbol}")
                return pd.DataFrame()

            df = self._process_daily_data(df, clean_symbol)
            logger.info(f"成功使用 AkShare 获取 {symbol} 数据，共 {len(df)} 条记录")
            return df

        except ImportError:
            logger.error("未安装 akshare 库，请运行: pip install akshare")
            return pd.DataFrame()
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.error(f"使用 AkShare 获取腾讯数据失败 {symbol}: {e}")
            return pd.DataFrame()

    def _process_daily_data(self, df: pd.DataFrame, clean_symbol: str) -> pd.DataFrame:
        """处理日线数据"""
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date

        numeric_cols = ["open", "high", "low", "close", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        if "amount" in df.columns:
            df["volume"] = df["amount"] * 100
            df["amount"] = df["volume"] * df["close"]

        if (
            "amplitude" not in df.columns
            and "high" in df.columns
            and "low" in df.columns
            and "open" in df.columns
        ):
            open_price = df["open"].replace(0, 1)
            df["amplitude"] = ((df["high"] - df["low"]) / open_price * 100).fillna(0)

        if (
            "change_rate" not in df.columns
            and "close" in df.columns
            and "open" in df.columns
        ):
            df["change_rate"] = (
                (df["close"] - df["open"]) / df["open"] * 100
            ).fillna(0)

        df["code"] = clean_symbol

        from ..utils.normalizer import normalize_stock_data
        df = normalize_stock_data(df, "tencent")

        return df[
            [
                "date",
                "code",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "amplitude",
                "change_rate",
            ]
        ]

    @retry(max_retries=DataSourceConstants.MAX_RETRIES, delay=DataSourceConstants.RETRY_DELAY, backoff=DataSourceConstants.RETRY_BACKOFF, exceptions=(Exception,))
    @handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """
        获取实时数据

        Args:
            symbol: 股票代码，None则获取全部

        Returns:
            pd.DataFrame: 实时数据，失败返回空DataFrame
        """
        try:
            if not symbol:
                logger.warning("Tencent原生接口仅支持单只股票获取")
                return pd.DataFrame()

            return self._fetch_single_real_time(symbol)
        except requests.exceptions.RequestException as e:
            logger.error(f"获取实时数据网络错误: {e}")
            return pd.DataFrame()
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"数据解析错误: {e}")
            return pd.DataFrame()
        except Exception as e:  # noqa: broad-except — 防御层，上方已有具体异常分支
            logger.critical(f"获取实时数据时发生未预期错误: {e}", exc_info=True)
            return pd.DataFrame()

    def _fetch_single_real_time(self, symbol: str) -> pd.DataFrame:
        """获取单个股票的实时数据"""
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")
        if clean_symbol.startswith(("6", "5")):
            tencent_symbol = f"sh{clean_symbol}"
        else:
            tencent_symbol = f"sz{clean_symbol}"

        from ...shared.constants import TencentConstants

        url = f"{TencentConstants.REALTIME_URL_PREFIX}{tencent_symbol}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "http://finance.qq.com/",
        }
        response = requests.get(url, headers=headers, timeout=NetworkConstants.SHORT_TIMEOUT)
        response.raise_for_status()

        return self._parse_real_time_response(response.text, symbol)

    def _parse_real_time_response(self, content: str, symbol: str) -> pd.DataFrame:
        """解析实时数据响应"""
        if "=" not in content:
            logger.warning("腾讯返回空数据")
            return pd.DataFrame()

        realtime_data: Dict[str, Any] = {}
        parts = content.split("=")
        if len(parts) == 2:
            values = parts[1].strip('"').split("~")
            if len(values) >= 11:
                realtime_data = self._extract_realtime_values(values, symbol)

        if realtime_data:
            df = pd.DataFrame([realtime_data])
            logger.info(f"成功从腾讯获取实时数据，共 {len(df)} 条记录")
            return df
        else:
            logger.warning("腾讯返回空数据")
            return pd.DataFrame()

    def _extract_realtime_values(self, values: list, symbol: str) -> Dict[str, Any]:
        """从实时数据值中提取信息"""
        return {
            "symbol": symbol,
            "name": values[1],
            "price": float(values[3]) if values[3] else 0,
            "open": float(values[4]) if values[4] else 0,
            "prev_close": float(values[5]) if values[5] else 0,
            "high": float(values[6]) if values[6] else 0,
            "low": float(values[7]) if values[7] else 0,
            "volume": float(values[8]) if values[8] else 0,
            "amount": float(values[9]) if values[9] else 0,
            "change": float(values[3]) - float(values[5]) if values[3] and values[5] else 0,
            "change_rate": ((float(values[3]) - float(values[5])) / float(values[5])) * 100 if values[5] else 0,
        }

    @retry(max_retries=DataSourceConstants.MAX_RETRIES, delay=DataSourceConstants.RETRY_DELAY, backoff=DataSourceConstants.RETRY_BACKOFF, exceptions=(Exception,))
    def fetch_market_cap(self, symbol: str) -> float:
        try:
            mcap = self._try_fetch_market_cap_from_realtime(symbol)
            if mcap > 0:
                return mcap

            mcap = self._try_fetch_market_cap_from_xq(symbol)
            if mcap > 0:
                return mcap

        except (KeyError, IndexError, ValueError, TypeError) as e:
            logger.error(f"Failed to fetch market cap for {symbol}: {e}")
        except Exception as e:  # noqa: broad-except — 防御层，上方已有具体异常分支
            logger.critical(
                f"Unexpected error fetching market cap for {symbol}: {e}", exc_info=True
            )
        return 0.0

    def _try_fetch_market_cap_from_realtime(self, symbol: str) -> float:
        """从实时数据获取市值"""
        df = self.fetch_real_time(symbol)
        if df.empty:
            return 0.0

        if "market_cap" in df.columns:
            mcap = df.iloc[0]["market_cap"]
            return float(mcap) / 1e8 if not pd.isna(mcap) else 0.0
        elif "总市值" in df.columns:
            mcap = df.iloc[0]["总市值"]
            return float(mcap) / 1e8 if not pd.isna(mcap) else 0.0
        return 0.0

    def _try_fetch_market_cap_from_xq(self, symbol: str) -> float:
        """从雪球获取市值"""
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")
        market_prefix = "SH" if clean_symbol.startswith("60") else "SZ"
        xq_symbol = f"{market_prefix}{clean_symbol}"

        try:
            stock_info = akshare_wrapper.call(
                "stock_individual_spot_xq", symbol=xq_symbol
            )
            return self._extract_market_cap_from_info(stock_info)
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.warning(f"从雪球获取市值失败: {e}")
            return 0.0

    def _extract_market_cap_from_info(self, stock_info) -> float:
        """从股票信息中提取市值"""
        if stock_info is None:
            return 0.0

        if isinstance(stock_info, dict):
            for key in ["总市值", "market_cap"]:
                if key in stock_info:
                    mcap = stock_info[key]
                    return float(mcap) / 1e8 if not pd.isna(mcap) else 0.0
        elif hasattr(stock_info, "columns"):
            for key in ["总市值", "market_cap"]:
                if key in stock_info.columns:
                    latest_mcap = stock_info.iloc[-1][key]
                    return float(latest_mcap) / 1e8 if not pd.isna(latest_mcap) else 0.0
        return 0.0

    def fetch_tick_data(self, symbol: str) -> pd.DataFrame:
        """
        获取逐笔成交数据 (委托给AKShare)

        Args:
            symbol: 股票代码(如"600519.SH"或"000001.SZ")

        Returns:
            DataFrame包含: 成交时间,成交价格,价格变动,成交量,成交额,性质
        """
        try:
            tx_symbol = self._convert_symbol(symbol)
            logger.info(f"开始获取 {symbol} 逐笔成交数据")

            df = akshare_wrapper.fetch_tick_data(symbol=tx_symbol)

            if df is None or df.empty:
                logger.warning(f"获取 {symbol} 逐笔成交数据为空")
                return pd.DataFrame()

            logger.info(f"成功获取 {symbol} 逐笔成交数据: {len(df)} 条记录")
            return df

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, ImportError) as e:
            logger.error(f"获取 {symbol} 逐笔成交数据失败: {e}", exc_info=True)
            return pd.DataFrame()
