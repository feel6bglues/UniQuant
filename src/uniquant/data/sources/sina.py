import logging
import urllib.error
from typing import Optional, Dict, Any, Union

import pandas as pd
import requests
import requests.exceptions

from ...shared.constants import DataSourceConstants, NetworkConstants
from ...shared.error_handling import handle_errors
from ...shared.exceptions import DataFetchError, DataValidationError
from ...shared.logger_factory import get_logger
from ...shared.retry_decorator import retry

from ..utils.akshare_wrapper import akshare_wrapper
from ..utils.request_utils import with_request_control
from .base import DataSource

logger = get_logger(__name__)


class SinaSource(DataSource):
    @property
    def name(self) -> str:
        return "sina"

    def __init__(self):
        super().__init__()
        self.session = self._create_session()

    def close(self) -> None:
        """关闭会话资源"""
        if hasattr(self, 'session') and self.session is not None:
            try:
                self.session.close()
            except Exception as e:
                logger.debug(f"Error closing session: {e}")
            self.session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

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

    def _build_sina_symbol(self, symbol: str) -> tuple:
        """构建新浪股票代码"""
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")
        if any(
            clean_symbol.startswith(prefix)
            for prefix in DataSourceConstants.INDEX_PREFIXES
        ):
            sina_symbol = f"sh{clean_symbol}"
        elif any(
            clean_symbol.startswith(prefix)
            for prefix in DataSourceConstants.SH_PREFIXES
        ):
            sina_symbol = f"sh{clean_symbol}"
        else:
            sina_symbol = f"sz{clean_symbol}"
        return sina_symbol, clean_symbol

    @retry(
        max_retries=DataSourceConstants.MAX_RETRIES,
        delay=DataSourceConstants.RETRY_DELAY,
        backoff=DataSourceConstants.RETRY_BACKOFF,
        exceptions=(Exception,),
    )
    @with_request_control(
        min_interval=DataSourceConstants.SINA_MIN_REQUEST_INTERVAL,
        max_retries=DataSourceConstants.SINA_MAX_RETRIES,
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
        Fetch daily data from Sina using direct API.
        """
        sina_symbol, clean_symbol = self._build_sina_symbol(symbol)

        logger.info(
            f"开始从新浪获取 {symbol} 的日线数据，时间范围: {start_date} 至 {end_date}"
        )

        result = self._fetch_using_sina_api(
            sina_symbol, clean_symbol, start_date, end_date
        )

        if not result.empty:
            logger.info(
                f"成功从新浪原生 API 获取 {symbol} 数据，共 {len(result)} 条记录"
            )
            return result
        else:
            logger.error(f"新浪原生 API 返回空数据，无法获取 {symbol} 数据")
            raise DataFetchError(f"新浪原生 API 返回空数据，无法获取 {symbol} 数据")

    def _normalize_date_column(self, df: pd.DataFrame) -> pd.DataFrame:
        """处理日期列"""
        date_col = None
        for possible_col in ["date", "日期", "trade_date", "交易日期", "时间", "time"]:
            if possible_col in df.columns:
                date_col = possible_col
                break

        if date_col is None:
            if df.index.name in ["date", "日期", "trade_date", "交易日期"]:
                df = df.reset_index()
                date_col = df.index.name
            elif isinstance(df.index, pd.DatetimeIndex):
                df["date"] = df.index.date
                date_col = "date"
            else:
                raise ValueError(f"找不到日期列. 列名: {df.columns.tolist()}")

        if date_col != "date":
            df = df.rename(columns={date_col: "date"})

        try:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        except (ValueError, TypeError) as e:
            logger.warning(f"处理日期列时出错: {e}")
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        return df

    def _filter_by_date_range(
        self, df: pd.DataFrame, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """过滤日期范围"""
        start = pd.to_datetime(start_date).date()
        end = pd.to_datetime(end_date).date()
        df = df[(df["date"] >= start) & (df["date"] <= end)]

        if df.empty:
            raise ValueError("日期范围内无数据")
        return df

    def _ensure_required_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """确保标准列存在"""
        required_cols = ["date", "open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col not in df.columns:
                if col in ["open", "high", "low"] and "close" in df.columns:
                    df[col] = df["close"]
                elif col == "volume":
                    df["volume"] = 0
                else:
                    df[col] = 0

        if "amount" not in df.columns:
            df["amount"] = df.get("close", 0) * df.get("volume", 0)

        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df

    def _calculate_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算振幅和涨跌幅"""
        if "close" in df.columns and "high" in df.columns and "low" in df.columns:
            if "preclose" in df.columns:
                df["amplitude"] = (
                    (df["high"] - df["low"]) / df["preclose"] * 100
                ).fillna(0)
            elif "open" in df.columns:
                df["amplitude"] = (
                    (df["high"] - df["low"]) / df["open"] * 100
                ).fillna(0)
            else:
                df["amplitude"] = 0
        else:
            df["amplitude"] = 0

        if "close" in df.columns:
            if "preclose" in df.columns:
                df["change_rate"] = (
                    (df["close"] - df["preclose"]) / df["preclose"] * 100
                ).fillna(0)
            elif "open" in df.columns:
                df["change_rate"] = (
                    (df["close"] - df["open"]) / df["open"] * 100
                ).fillna(0)
            else:
                df["change_rate"] = 0
        else:
            df["change_rate"] = 0
        return df

    def _finalize_dataframe(
        self, df: pd.DataFrame, clean_symbol: str
    ) -> pd.DataFrame:
        """最终处理和标准化"""
        if "code" not in df.columns:
            df["code"] = clean_symbol

        df = df.sort_values("date").reset_index(drop=True)

        from ..utils.normalizer import normalize_stock_data

        df = normalize_stock_data(df, "sina")

        final_cols = [
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
        return df[final_cols]

    def _fetch_using_akshare(
        self, sina_symbol: str, clean_symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """使用 akshare 获取新浪数据"""
        df = akshare_wrapper.fetch_stock_daily_sina(
            symbol=sina_symbol, start_date=start_date, end_date=end_date
        )

        if df is None or df.empty:
            raise ValueError("akshare 返回空数据")

        df = self._normalize_date_column(df)
        df = self._filter_by_date_range(df, start_date, end_date)
        df = self._ensure_required_columns(df)
        df = self._calculate_metrics(df)
        return self._finalize_dataframe(df, clean_symbol)

    def _fetch_using_sina_api(
        self, sina_symbol: str, clean_symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """直接使用新浪 API 获取数据"""
        from ...shared.constants import NetworkConstants
        import json
        import random
        import time

        url = NetworkConstants.SINA_API_CONFIG["kline_url"]
        params: Dict[str, Union[str, int]] = {
            "symbol": sina_symbol,
            "scale": 240,
            "datalen": 2000,
            "ma": 5,
        }

        headers = NetworkConstants.SINA_API_CONFIG["headers"].copy()
        headers["User-Agent"] = NetworkConstants.USER_AGENT

        min_sleep = NetworkConstants.SINA_API_CONFIG.get("random_sleep_min", 1.5)
        max_sleep = NetworkConstants.SINA_API_CONFIG.get("random_sleep_max", 3.0)
        time.sleep(random.uniform(min_sleep, max_sleep))

        timeout = NetworkConstants.SINA_API_CONFIG.get("timeout", 15)
        logger.info(f"请求新浪 API: {url}，参数: {params}")
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        logger.info(f"新浪 API 返回状态码: {response.status_code}")

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.error(f"解析新浪 API 返回数据失败: {e}")
            logger.error(f"返回数据: {response.text[:500]}")
            raise

        if not data:
            logger.warning(f"新浪 API 返回空数据，symbol: {sina_symbol}")
            raise ValueError("新浪 API 返回空数据")

        logger.debug(f"新浪 API 返回数据条数: {len(data)}")
        return self._process_sina_api_data(data, clean_symbol, start_date, end_date)

    def _process_sina_api_data(
        self, data: list, clean_symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """处理新浪 API 返回的数据"""
        df = pd.DataFrame(data)

        if df.empty:
            logger.warning(f"新浪 API 返回空 DataFrame")
            raise ValueError("新浪 API 返回空数据")

        df = self._rename_sina_columns(df)
        df = self._parse_sina_dates(df)
        df = self._filter_and_validate_data(df, start_date, end_date)
        df = self._add_amount_column(df)
        df = self._convert_numeric_columns(df)

        if "code" not in df.columns:
            df["code"] = clean_symbol

        from ..utils.normalizer import normalize_stock_data
        df = normalize_stock_data(df, "sina")

        final_cols = [
            "date", "code", "open", "high", "low",
            "close", "volume", "amount", "amplitude", "change_rate",
        ]
        for col in final_cols:
            if col not in df.columns:
                df[col] = 0
                logger.warning(f"添加缺失列 {col}，值设为 0")
        return df[final_cols]

    def _rename_sina_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """重命名新浪数据列"""
        column_mapping = {
            "day": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        }

        required_cols = list(column_mapping.keys())
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning(f"新浪 API 返回数据缺少必要列: {missing_cols}")
            alternative_mapping = {
                "date": "date",
                "trade_date": "date",
                "开盘": "open",
                "开盘价": "open",
                "最高": "high",
                "最高价": "high",
                "最低": "low",
                "最低价": "low",
                "收盘": "close",
                "收盘价": "close",
                "成交量": "volume",
            }
            for alt_col, std_col in alternative_mapping.items():
                if alt_col in df.columns and std_col not in df.columns:
                    df[std_col] = df[alt_col]
                    logger.info(f"使用替代列 {alt_col} 作为 {std_col}")

        return df.rename(columns=column_mapping)

    def _parse_sina_dates(self, df: pd.DataFrame) -> pd.DataFrame:
        """解析新浪日期格式"""
        try:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        except ValueError as e:
            logger.warning(f"处理日期格式失败: {e}")
            df["date"] = pd.to_datetime(
                df["date"], format="%Y-%m-%d", errors="coerce"
            ).dt.date
        return df

    def _filter_and_validate_data(
        self, df: pd.DataFrame, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """过滤和验证数据"""
        try:
            start = pd.to_datetime(start_date).date()
            end = pd.to_datetime(end_date).date()
            df = df[(df["date"] >= start) & (df["date"] <= end)]
        except ValueError as e:
            logger.warning(f"过滤日期范围失败: {e}")

        if df.empty:
            if "date" in df.columns:
                min_date = df["date"].min() if not df["date"].isna().all() else "N/A"
                max_date = df["date"].max() if not df["date"].isna().all() else "N/A"
                logger.warning(f"新浪 API 返回数据日期范围: {min_date} 至 {max_date}")
            raise ValueError("日期范围内无数据")
        return df

    def _add_amount_column(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加成交额列"""
        try:
            df["amount"] = df["close"].astype(float) * df["volume"].astype(float)
        except (ValueError, TypeError) as e:
            logger.warning(f"计算成交额失败: {e}")
            df["amount"] = 0
        return df

    def _convert_numeric_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """转换数值类型列"""
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                try:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
                except (ValueError, TypeError) as e:
                    logger.warning(f"转换 {col} 为数值失败: {e}")
                    df[col] = 0

        try:
            df = df.sort_values("date").reset_index(drop=True)
        except (ValueError, TypeError) as e:
            logger.warning(f"排序数据失败: {e}")
        return df

    @retry(
        max_retries=DataSourceConstants.MAX_RETRIES,
        delay=DataSourceConstants.RETRY_DELAY,
        backoff=DataSourceConstants.RETRY_BACKOFF,
        exceptions=(requests.exceptions.RequestException,),
    )
    @with_request_control(
        min_interval=DataSourceConstants.MIN_REQUEST_INTERVAL,
        max_retries=DataSourceConstants.MAX_RETRIES,
    )
    @handle_errors(
        requests.exceptions.RequestException,
        ValueError,
        TypeError,
        KeyError,
        default_return=pd.DataFrame(),
        log_level=logging.ERROR,
    )
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
                logger.warning("Sina原生接口仅支持单只股票获取")
                return pd.DataFrame()

            return self._fetch_single_real_time(symbol)
        except requests.exceptions.Timeout as e:
            logger.error(f"获取实时数据超时: {e}")
            return pd.DataFrame()
        except requests.exceptions.ConnectionError as e:
            logger.error(f"获取实时数据连接错误: {e}")
            return pd.DataFrame()
        except requests.exceptions.HTTPError as e:
            logger.error(f"获取实时数据HTTP错误: {e}")
            return pd.DataFrame()
        except (ValueError, TypeError) as e:
            logger.error(f"数据格式错误: {e}")
            return pd.DataFrame()
        except KeyError as e:
            logger.error(f"数据解析错误: {e}")
            return pd.DataFrame()
        except Exception as e:  # noqa: broad-except — 防御层，上方已有具体异常分支
            logger.critical(f"获取实时数据时发生未预期错误: {e}", exc_info=True)
            return pd.DataFrame()

    def _fetch_single_real_time(self, symbol: str) -> pd.DataFrame:
        """获取单个股票的实时数据"""
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")
        if any(
            clean_symbol.startswith(prefix)
            for prefix in DataSourceConstants.SH_PREFIXES
        ):
            sina_symbol = f"sh{clean_symbol}"
        else:
            sina_symbol = f"sz{clean_symbol}"

        from ...shared.constants import NetworkConstants

        url_prefix = NetworkConstants.SINA_API_CONFIG.get(
            "realtime_url_prefix", "http://hq.sinajs.cn/list="
        )
        url = f"{url_prefix}{sina_symbol}"

        headers = NetworkConstants.SINA_API_CONFIG["headers"].copy()
        headers["Referer"] = "https://finance.sina.com.cn/"
        headers["Accept"] = "*/*"

        timeout = NetworkConstants.SINA_API_CONFIG.get("timeout", 10)
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        return self._parse_real_time_response(response.text, symbol)

    def _parse_real_time_response(self, content: str, symbol: str) -> pd.DataFrame:
        """解析实时数据响应"""
        if "=" not in content:
            logger.warning("Sina返回空数据")
            return pd.DataFrame()

        realtime_data: Dict[str, Any] = {}
        lines = content.split("\n")
        for line in lines:
            if "=" in line:
                parts = line.split("=")
                if len(parts) == 2:
                    values = parts[1].strip('"').split(",")
                    if len(values) >= 4:
                        realtime_data = self._extract_realtime_values(values, symbol)
                        break

        if realtime_data:
            df = pd.DataFrame([realtime_data])
            logger.info(f"成功从Sina获取实时数据，共 {len(df)} 条记录")
            return df
        else:
            logger.warning("Sina返回空数据")
            return pd.DataFrame()

    def _extract_realtime_values(self, values: list, symbol: str) -> Dict[str, Any]:
        """从实时数据值中提取信息"""
        return {
            "symbol": symbol,
            "name": values[0],
            "price": float(values[3]) if values[3] else 0,
            "change": float(values[4]) if values[4] else 0,
            "change_rate": float(values[5]) if values[5] else 0,
            "volume": float(values[8]) if values[8] else 0,
            "amount": float(values[9]) if values[9] else 0,
        }

    @retry(
        max_retries=DataSourceConstants.MAX_RETRIES,
        delay=DataSourceConstants.RETRY_DELAY,
        backoff=DataSourceConstants.RETRY_BACKOFF,
        exceptions=(requests.exceptions.RequestException,),
    )
    def fetch_market_cap(self, symbol: str) -> float:
        try:
            df = self.fetch_real_time(symbol)
            if not df.empty and "market_cap" in df.columns:
                mcap = df.iloc[0]["market_cap"]
                return float(mcap) / 1e8 if not pd.isna(mcap) else 0.0
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to fetch market cap for {symbol}: {e}")
        except (ValueError, TypeError) as e:
            logger.error(f"Data format error fetching market cap for {symbol}: {e}")
        except Exception as e:  # noqa: broad-except — 防御层，上方已有具体异常分支
            logger.critical(
                f"Unexpected error fetching market cap for {symbol}: {e}", exc_info=True
            )
        return 0.0

    def fetch_minute_data(
        self,
        symbol: str,
        period: str = "5",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """
        获取分钟级K线数据 (委托给AKShare API)

        Args:
            symbol: 股票代码(如"600519.SH")
            period: K线周期('1','5','15','30','60')
            start_date: 开始日期(YYYY-MM-DD)
            end_date: 结束日期(YYYY-MM-DD)
            adjust: 复权方式

        Returns:
            DataFrame包含分钟K线数据
        """
        try:
            clean_symbol = (
                symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            )
            logger.info(f"开始获取 {symbol} 分钟K线数据(via AKShare)")

            start_fmt = start_date.replace("-", "") if start_date else ""
            end_fmt = end_date.replace("-", "") if end_date else ""

            df = akshare_wrapper.fetch_minute_data(
                symbol=clean_symbol,
                period=period,
                start_date=start_fmt,
                end_date=end_fmt,
                adjust=adjust,
            )

            return df if df is not None else pd.DataFrame()
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, ImportError) as e:
            logger.error(f"获取分钟K线失败: {e}", exc_info=True)
            return pd.DataFrame()
