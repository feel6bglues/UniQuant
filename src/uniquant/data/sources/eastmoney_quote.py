import logging
import urllib.error
from typing import Optional

import pandas as pd
import requests
import requests.exceptions

from ...shared.constants import DataSourceConstants, NetworkConstants
from ...shared.error_handling import handle_errors
from ...shared.exceptions import DataValidationError
from ...shared.logger_factory import get_logger
from ...shared.retry_decorator import retry

from ..utils.request_utils import with_request_control
from .eastmoney_base import EastmoneyBase

logger = get_logger(__name__)


class EastmoneyQuoteSource(EastmoneyBase):
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
    def _fetch_daily_internal(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        if "." in symbol:
            clean_symbol = symbol.split(".")[0]
        else:
            clean_symbol = symbol

        logger.info(
            f"开始获取 {symbol} 的日线数据，时间范围: {start_date} 至 {end_date}"
        )

        try:
            market, code = self._convert_symbol(symbol)
            secid = f"{market}.{code}"

            start_date_fmt = start_date.replace("-", "")
            end_date_fmt = end_date.replace("-", "")

            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "secid": secid,
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101",
                "fqt": "1",
                "beg": start_date_fmt,
                "end": end_date_fmt,
                "smplmt": "1000",
            }

            data = self._request(url, params=params)

            if data.get("rc") != 0:
                logger.error(f"东方财富API返回错误: {data.get('msg', 'Unknown error')}")
                return pd.DataFrame()

            kline_data = data.get("data", {})
            if not kline_data:
                logger.warning(f"东方财富API返回空数据: {symbol}")
                return pd.DataFrame()

            klines = kline_data.get("klines", [])
            if not klines:
                logger.warning(f"东方财富API返回空K线数据: {symbol}")
                return pd.DataFrame()

            data_list = []
            for kline in klines:
                parts = kline.split(",")
                if len(parts) >= 6:
                    data_list.append({
                        "date": parts[0],
                        "open": float(parts[1]),
                        "close": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "volume": float(parts[5]),
                        "amount": float(parts[6]) if len(parts) > 6 else 0,
                        "amplitude": float(parts[7]) if len(parts) > 7 else 0,
                        "change_rate": float(parts[8]) if len(parts) > 8 else 0,
                    })

            if not data_list:
                logger.warning(f"解析K线数据失败: {symbol}")
                return pd.DataFrame()

            df = pd.DataFrame(data_list)
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df["code"] = clean_symbol

            logger.info(f"成功使用东方财富API获取 {symbol} 数据，共 {len(df)} 条记录")

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

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.error(f"使用东方财富API获取数据失败 {symbol}: {e}")
            return pd.DataFrame()

    @handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            return self._fetch_daily_internal(symbol, start_date, end_date)
        except (
            ValueError,
            TypeError,
            KeyError,
            DataValidationError,
            urllib.error.URLError,
            requests.exceptions.RequestException,
        ) as e:
            logger.warning(f"Error fetching data from eastmoney for {symbol}: {e}.")
            return pd.DataFrame()
        except Exception as e:
            logger.warning(
                f"Unexpected error fetching data from eastmoney for {symbol}: {e}."
            )
            return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        try:
            if symbol:
                return self._fetch_real_time_single(symbol)
            return self._fetch_real_time_all()

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.error(f"获取实时数据时发生错误: {e}")
            return pd.DataFrame()

    def _fetch_real_time_single(self, symbol: str) -> pd.DataFrame:
        market, code = self._convert_symbol(symbol)
        secid = f"{market}.{code}"

        url = "https://push.eastmoney.com/api/qt/stock/get"
        params = {
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fltt": "2",
            "invt": "2",
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f116,f117,f170",
            "secid": secid,
        }

        data = self._request(url, params=params)

        if data.get("rc") != 0:
            logger.error(f"东方财富API返回错误: {data.get('msg', 'Unknown error')}")
            return pd.DataFrame()

        stock_data = data.get("data", {})
        if not stock_data:
            logger.warning(f"东方财富API返回空数据: {symbol}")
            return pd.DataFrame()

        df_data = {
            "symbol": [code],
            "name": [stock_data.get("f58", "")],
            "price": [float(stock_data.get("f43", 0)) / 100 if stock_data.get("f43") else 0],
            "open": [float(stock_data.get("f46", 0)) / 100 if stock_data.get("f46") else 0],
            "high": [float(stock_data.get("f44", 0)) / 100 if stock_data.get("f44") else 0],
            "low": [float(stock_data.get("f45", 0)) / 100 if stock_data.get("f45") else 0],
            "pre_close": [float(stock_data.get("f60", 0)) / 100 if stock_data.get("f60") else 0],
            "volume": [float(stock_data.get("f47", 0))],
            "amount": [float(stock_data.get("f48", 0))],
            "change_rate": [float(stock_data.get("f170", 0))],
            "market_cap": [float(stock_data.get("f116", 0))],
            "circulating_market_cap": [float(stock_data.get("f117", 0))],
        }

        df = pd.DataFrame(df_data)
        logger.info(f"成功获取 {symbol} 实时数据")
        return df

    def _fetch_real_time_all(self) -> pd.DataFrame:
        url = "https://push.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "5000",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:13,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f2,f3,f4,f5,f6,f8,f20,f21,f23",
        }

        data = self._request(url, params=params)

        if data.get("rc") != 0:
            logger.error(f"东方财富API返回错误: {data.get('msg', 'Unknown error')}")
            return pd.DataFrame()

        items = data.get("data", {}).get("diff", [])
        if not items:
            logger.warning("东方财富API返回空数据")
            return pd.DataFrame()

        df = pd.DataFrame(items)

        column_mapping = {
            "f12": "symbol",
            "f14": "name",
            "f2": "price",
            "f3": "change_rate",
            "f4": "change",
            "f5": "volume",
            "f6": "amount",
            "f8": "turnover_rate",
            "f20": "market_cap",
            "f21": "circulating_market_cap",
        }

        df = df.rename(columns=column_mapping)

        needed_cols = list(column_mapping.values())
        df = df[[col for col in needed_cols if col in df.columns]]

        numeric_cols = [
            "price", "change", "change_rate", "volume", "amount",
            "turnover_rate", "market_cap", "circulating_market_cap",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.info(f"成功获取实时数据，共 {len(df)} 条记录")
        return df

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @with_request_control(min_interval=2, max_retries=3)
    def fetch_market_cap(self, symbol: str) -> float:
        logger.info(f"开始获取 {symbol} 的市值数据...")

        try:
            market, code = self._convert_symbol(symbol)
            secid = f"{market}.{code}"

            url = "https://push.eastmoney.com/api/qt/stock/get"
            params = {
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                "fltt": "2",
                "invt": "2",
                "fields": "f116,f57,f58",
                "secid": secid,
            }

            data = self._request(url, params=params)

            if data.get("rc") != 0:
                logger.error(f"东方财富API返回错误: {data.get('msg', 'Unknown error')}")
                return 0.0

            stock_data = data.get("data", {})
            if not stock_data:
                logger.warning(f"东方财富API返回空数据: {symbol}")
                return 0.0

            if "f116" in stock_data:
                mcap = stock_data["f116"]
                result = float(mcap) / 1e8 if mcap else 0.0
                logger.info(f"成功获取市值: {result:.2f} 亿元")
                return result
            else:
                logger.warning(f"API返回数据中不包含市值字段: {symbol}")
                return 0.0

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.error(f"获取市值失败 {symbol}: {e}")
            return 0.0

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @with_request_control(min_interval=2, max_retries=3)
    def fetch_basic_info(self, symbol: str) -> pd.DataFrame:
        base_urls = [
            "https://push2.eastmoney.com/api/qt/stock/get",
            "https://push.eastmoney.com/api/qt/stock/get",
            "https://quote.eastmoney.com/api/qt/stock/get",
        ]

        market, code = self._convert_symbol(symbol)
        secid = f"{market}.{code}"

        params = {
            "fltt": "2",
            "invt": "2",
            "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43,f44,f45,f46,f47,f48,f168,f169,f170",
            "secid": secid,
        }

        last_error = None
        for url in base_urls:
            try:
                data = self._request(url, params=params, timeout=NetworkConstants.MEDIUM_TIMEOUT)

                if data.get("rc") != 0:
                    logger.warning(f"东方财富API返回错误 ({url}): {data.get('msg', 'Unknown error')}")
                    continue

                stock_data = data.get("data", {})
                if not stock_data:
                    logger.warning(f"东方财富API返回空数据 ({url}): {symbol}")
                    continue

                field_mapping = {
                    "f57": "股票代码",
                    "f58": "股票名称",
                    "f84": "总股本",
                    "f85": "流通股",
                    "f127": "行业",
                    "f116": "总市值",
                    "f117": "流通市值",
                    "f189": "上市时间",
                    "f43": "最新价",
                    "f44": "最高价",
                    "f45": "最低价",
                    "f46": "开盘价",
                    "f47": "成交量",
                    "f48": "成交额",
                    "f168": "换手率",
                    "f169": "涨跌额",
                    "f170": "涨跌幅",
                }

                basic_info = {}
                for field, name in field_mapping.items():
                    if field in stock_data:
                        basic_info[name] = stock_data[field]

                df = pd.DataFrame([basic_info])

                if not df.empty:
                    logger.info(f"成功获取 {symbol} 基本信息 (使用 {url})")
                    return df

            except Exception as e:
                last_error = e
                logger.warning(f"域名 {url} 请求失败: {e}")
                continue

        logger.error(f"所有域名都无法获取 {symbol} 基本信息: {last_error}")
        return pd.DataFrame()

    def fetch_minute_data(
        self,
        symbol: str,
        period: str = "5",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        try:
            clean_symbol = (
                symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            )

            logger.info(
                f"开始获取 {symbol} 分钟K线数据,周期:{period}分钟,时间范围:{start_date}~{end_date}"
            )

            from ..utils.akshare_wrapper import akshare_wrapper

            start_date_fmt = start_date.replace("-", "") if start_date else ""
            end_date_fmt = end_date.replace("-", "") if end_date else ""

            df = akshare_wrapper.fetch_minute_data(
                symbol=clean_symbol,
                period=period,
                start_date=start_date_fmt,
                end_date=end_date_fmt,
                adjust=adjust,
            )

            if df is None or df.empty:
                logger.warning(f"获取 {symbol} 分钟K线数据为空")
                return pd.DataFrame()

            column_mapping = {
                "时间": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "振幅": "amplitude",
                "涨跌幅": "change_rate",
                "涨跌额": "change",
                "换手率": "turnover",
            }

            df = df.rename(columns=column_mapping)

            logger.info(f"成功获取 {symbol} 分钟K线数据: {len(df)} 条记录")
            return df

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, ImportError) as e:
            logger.error(f"获取 {symbol} 分钟K线数据失败: {e}", exc_info=True)
            return pd.DataFrame()