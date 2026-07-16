import logging
import urllib.error
from typing import Optional

import pandas as pd
import requests
import requests.exceptions
from bs4 import BeautifulSoup

from ...shared.constants import DataSourceConstants, NetworkConstants
from ...shared.error_handling import handle_errors
from ...shared.exceptions import DataFetchError, DataValidationError
from ...shared.logger_factory import get_logger
from ...shared.retry_decorator import retry

from ..utils.akshare_wrapper import akshare_wrapper
from ..utils.js_executor import get_ths_headers
from ..utils.request_utils import with_request_control
from .base import DataSource

logger = get_logger(__name__)


class ThsSource(DataSource):
    @property
    def name(self) -> str:
        return "ths"

    def __init__(self):
        super().__init__()
        self.session = self._create_session()

    @retry(
        max_retries=DataSourceConstants.MAX_RETRIES,
        delay=DataSourceConstants.RETRY_DELAY,
        backoff=DataSourceConstants.RETRY_BACKOFF,
        exceptions=(Exception,),
    )
    @with_request_control(min_interval=DataSourceConstants.MIN_REQUEST_INTERVAL, max_retries=DataSourceConstants.MAX_RETRIES)
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
        Fetch daily data from THS (同花顺) using direct API.
        """
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")

        logger.info(
            f"开始从同花顺获取 {symbol} 的日线数据，时间范围: {start_date} 至 {end_date}"
        )

        df = self._fetch_using_ths_api(clean_symbol, start_date, end_date)

        if df is not None and not df.empty:
            logger.info(f"成功从同花顺原生 API 获取 {symbol} 数据，共 {len(df)} 条记录")
            return df
        else:
            logger.error(f"同花顺原生 API 返回空数据，无法获取 {symbol} 数据")
            raise DataFetchError(f"同花顺原生 API 返回空数据，无法获取 {symbol} 数据")

    def _fetch_using_akshare(
        self, clean_symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """使用 akshare 获取同花顺数据"""
        try:
            df = self._fetch_akshare_data(clean_symbol, start_date, end_date)
            if df is None or (hasattr(df, "empty") and df.empty):
                raise ValueError("akshare 返回空数据")

            df = self._normalize_date_column(df)
            df = self._filter_by_date_range(df, start_date, end_date)
            df = self._ensure_required_columns(df)
            df = self._calculate_metrics(df)
            return self._finalize_dataframe(df, clean_symbol, source_name="ths")
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, ImportError) as e:
            logger.error(f"使用 akshare 获取同花顺数据失败: {e}")
            raise

    def _fetch_akshare_data(
        self, clean_symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """从 akshare 获取原始数据"""
        if clean_symbol.startswith(("6", "5")):
            symbol_with_prefix = f"sh{clean_symbol}"
        else:
            symbol_with_prefix = f"sz{clean_symbol}"

        df = akshare_wrapper.fetch_stock_daily(
            symbol=symbol_with_prefix,
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )

        if df is None or (hasattr(df, "empty") and df.empty):
            df = akshare_wrapper.fetch_stock_daily(
                symbol=clean_symbol,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
        return df

    def _fetch_using_ths_api(
        self, clean_symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """直接使用同花顺 API 获取数据"""
        headers = get_ths_headers()
        logger.debug(f"Generated THS headers: {headers}")

        try:
            df = self._fetch_ths_raw_data(clean_symbol, start_date, end_date, headers)
            if df is None:
                return self._fetch_using_akshare(clean_symbol, start_date, end_date)

            df = self._normalize_date_column(df)
            df = self._filter_by_date_range(df, start_date, end_date)
            df = self._ensure_required_columns(df)
            df = self._calculate_metrics(df)
            return self._finalize_dataframe(df, clean_symbol, source_name="ths")
        except requests.exceptions.RequestException as e:
            logger.error(f"THS API request failed: {e}")
            return self._fetch_using_akshare(clean_symbol, start_date, end_date)
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"Error fetching data from THS API: {e}")
            return self._fetch_using_akshare(clean_symbol, start_date, end_date)

    def _fetch_ths_raw_data(
        self, clean_symbol: str, start_date: str, end_date: str, headers: dict
    ) -> pd.DataFrame:
        """从 THS API 获取原始数据"""
        from ...shared.constants import THSConstants
        from io import StringIO

        url = THSConstants.HISTORICAL_URL.format(symbol=clean_symbol)
        params = {
            "start": start_date.replace("-", ""),
            "end": end_date.replace("-", ""),
            "type": "qfq",
        }

        response = requests.get(
            url, params=params, headers=headers, timeout=THSConstants.TIMEOUT
        )
        response.raise_for_status()

        if response.status_code == 200:
            try:
                dfs = pd.read_html(StringIO(response.text))
                if dfs:
                    df = dfs[0]
                    logger.info(
                        f"Successfully fetched data from THS API, shape: {df.shape}"
                    )
                    return df
                else:
                    raise ValueError("No tables found in THS API response")
            except (ValueError, TypeError, pd.errors.ParserError) as e:
                logger.error(f"Failed to parse THS API response: {e}")
                return None
        else:
            raise ValueError(
                f"THS API returned non-200 status code: {response.status_code}"
            )

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
            df = self._try_fetch_real_time(symbol)
            if df is not None and not df.empty:
                return df

            headers = get_ths_headers()
            logger.debug(f"Using THS headers for real-time data: {headers}")
            return self._fetch_real_time_using_ths_api(symbol, headers)
        except requests.exceptions.RequestException as e:
            logger.error(f"获取实时数据网络错误: {e}")
            return pd.DataFrame()
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"数据解析错误: {e}")
            return pd.DataFrame()
        except Exception as e:  # noqa: E722 — 防御层，上方已有具体异常分支
            logger.critical(f"获取实时数据时发生未预期错误: {e}", exc_info=True)
            return pd.DataFrame()

    def _try_fetch_real_time(self, symbol: Optional[str]) -> pd.DataFrame:
        """尝试从 akshare 获取实时数据"""
        try:
            if symbol:
                return self._fetch_single_real_time(symbol)
            else:
                df = akshare_wrapper.fetch_stock_spot(source="em")
                if df is not None and not df.empty:
                    logger.info(
                        f"成功从东方财富获取全部实时数据，共 {len(df)} 条记录"
                    )
                return df
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, ImportError) as e:
            logger.warning(f"使用akshare获取同花顺实时数据失败: {e}")
            return pd.DataFrame()

    def _fetch_single_real_time(self, symbol: str) -> pd.DataFrame:
        """获取单个股票的实时数据"""
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")
        market_prefix = "SH" if clean_symbol.startswith("60") else "SZ"
        xq_symbol = f"{market_prefix}{clean_symbol}"
        try:
            stock_info = akshare_wrapper.call(
                "stock_individual_spot_xq", symbol=xq_symbol
            )
        except Exception as e:
            logger.warning(f"AkShare 获取 {symbol} 实时数据失败: {e}")
            return pd.DataFrame()
        if stock_info is None:
            return pd.DataFrame()

        if isinstance(stock_info, dict):
            df = pd.DataFrame([stock_info])
        elif hasattr(stock_info, "columns"):
            df = stock_info
        else:
            return pd.DataFrame()

        return self._process_real_time_df(df, symbol, clean_symbol)

    def _process_real_time_df(
        self, df: pd.DataFrame, symbol: str, clean_symbol: str
    ) -> pd.DataFrame:
        """处理实时数据 DataFrame"""
        column_mapping = {
            "代码": "symbol",
            "名称": "name",
            "最新价": "price",
            "涨跌额": "change",
            "涨跌幅": "change_rate",
            "成交量": "volume",
            "成交额": "amount",
            "换手率": "turnover_rate",
            "市盈率(动)": "pe",
            "市净率": "pb",
            "总市值": "market_cap",
        }

        available_columns = [
            col for col in column_mapping.keys() if col in df.columns
        ]
        df = df[available_columns].rename(
            columns={
                k: v
                for k, v in column_mapping.items()
                if k in available_columns
            }
        )

        if "symbol" in df.columns:
            df = df[df["symbol"] == clean_symbol]
            if not df.empty:
                df["symbol"] = symbol
            else:
                logger.warning(f"同花顺实时数据中未找到标的: {symbol}")
                return pd.DataFrame()

        numeric_cols = [
            "price",
            "change",
            "change_rate",
            "volume",
            "amount",
            "pe",
            "pb",
            "market_cap",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.info(f"成功从同花顺获取实时数据，共 {len(df)} 条记录")
        return df

    def _fetch_real_time_using_ths_api(
        self, symbol: Optional[str], headers: dict
    ) -> pd.DataFrame:
        """直接使用同花顺 API 获取实时数据"""
        try:
            if not symbol:
                return pd.DataFrame()

            clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")
            from ...shared.constants import THSConstants

            api_urls = [
                url.format(symbol=clean_symbol)
                for url in THSConstants.REALTIME_API_URLS
            ]

            for url in api_urls:
                df = self._try_ths_realtime_url(url, headers, symbol)
                if df is not None and not df.empty:
                    return df

            logger.warning("同花顺 API 返回空实时数据")
            return pd.DataFrame()
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.error(f"使用同花顺 API 获取实时数据失败: {e}")
            return pd.DataFrame()

    def _try_ths_realtime_url(
        self, url: str, headers: dict, symbol: str
    ) -> pd.DataFrame:
        """尝试从单个 THS API URL 获取实时数据"""
        try:
            logger.debug(f"尝试使用实时数据 API 地址: {url}")
            response = requests.get(url, headers=headers, timeout=NetworkConstants.SOCKET_TIMEOUT)
            response.raise_for_status()

            if response.status_code == 200:
                logger.info(f"成功访问同花顺实时数据 API: {url}")
                return self._parse_ths_realtime_html(response.text, symbol)
        except (requests.exceptions.RequestException, ValueError, TypeError) as e:
            logger.warning(f"实时数据 API 地址 {url} 访问失败: {e}")
        return pd.DataFrame()

    def _parse_ths_realtime_html(self, html_text: str, symbol: str) -> pd.DataFrame:
        """解析 THS 实时数据 HTML"""
        soup = BeautifulSoup(html_text, "html.parser")

        name_elem = soup.find("h1", class_="name")
        price_elem = soup.find("div", class_="price")

        if not (name_elem and price_elem):
            logger.warning("无法从 HTML 中提取股票信息")
            return pd.DataFrame()

        name = name_elem.text.strip()
        price = price_elem.text.strip()
        logger.info(f"从 HTML 中提取到股票信息: {name}, 价格: {price}")

        realtime_data = {
            "symbol": symbol,
            "name": name,
            "price": float(price) if price else 0,
            "change": 0,
            "change_rate": 0,
            "volume": 0,
            "amount": 0,
            "turnover_rate": 0,
            "pe": 0,
            "pb": 0,
            "market_cap": 0,
        }

        self._extract_extra_realtime_data(soup, realtime_data)

        df = pd.DataFrame([realtime_data])
        logger.info(f"成功从同花顺 HTML 中提取实时数据，共 {len(df)} 条记录")
        return df

    def _extract_extra_realtime_data(
        self, soup: BeautifulSoup, realtime_data: dict
    ) -> None:
        """提取额外的实时数据"""
        try:
            change_elem = soup.find("div", class_="change")
            if change_elem:
                change_text = change_elem.text.strip()
                realtime_data["change"] = float(change_text) if change_text else 0

            change_rate_elem = soup.find("div", class_="change-rate")
            if change_rate_elem:
                change_rate_text = change_rate_elem.text.strip().replace("%", "")
                realtime_data["change_rate"] = (
                    float(change_rate_text) if change_rate_text else 0
                )
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"提取额外数据失败: {e}")

    @retry(max_retries=DataSourceConstants.MAX_RETRIES, delay=DataSourceConstants.RETRY_DELAY, backoff=DataSourceConstants.RETRY_BACKOFF, exceptions=(Exception,))
    def fetch_market_cap(self, symbol: str) -> float:
        try:
            mcap = self._try_fetch_market_cap_from_realtime(symbol)
            if mcap > 0:
                return mcap

            mcap = self._try_fetch_market_cap_from_xq(symbol)
            if mcap > 0:
                return mcap

            mcap = self._try_fetch_market_cap_from_em(symbol)
            if mcap > 0:
                return mcap

        except (KeyError, IndexError, ValueError, TypeError) as e:
            logger.error(f"Failed to fetch market cap for {symbol}: {e}")
        except Exception as e:  # noqa: E722 — 防御层，上方已有具体异常分支
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

    def _try_fetch_market_cap_from_em(self, symbol: str) -> float:
        """从东方财富获取市值"""
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")

        try:
            stock_info = akshare_wrapper.call(
                "stock_individual_info_em", symbol=clean_symbol
            )
            return self._extract_market_cap_from_info(stock_info)
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.warning(f"从东方财富获取市值失败: {e}")
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

    def fetch_concept_list(self) -> pd.DataFrame:
        """
        获取概念板块列表 (委托给AKShare)

        Returns:
            DataFrame包含: 板块代码,板块名称
        """
        try:
            logger.info("开始获取同花顺概念板块列表")

            df = akshare_wrapper.fetch_concept_list()

            if df is None or df.empty:
                logger.warning("获取概念板块列表为空")
                return pd.DataFrame()

            logger.info(f"成功获取概念板块列表: {len(df)} 个板块")
            return df

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, ImportError) as e:
            logger.error(f"获取概念板块列表失败: {e}", exc_info=True)
            return pd.DataFrame()
