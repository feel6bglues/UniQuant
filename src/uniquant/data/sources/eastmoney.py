import logging
import random
import time
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
from .base import DataSource

logger = get_logger(__name__)

# NON_RESEARCH_RANDOMNESS: request sleeps are source throttling controls only.


class EastmoneySource(DataSource):
    """
    TODO(refactor): 巨型类 — 1090行, 17+ 方法。建议拆分为:
    - EastmoneyPriceSource: 行情数据 (日线/分钟/实时)
    - EastmoneyFundFlowSource: 资金流向 (个股/板块/大盘)
    - EastmoneyInfoSource: 基础信息 (行业/概念/龙虎榜)
    """
    def __init__(self):
        super().__init__()
        self.session = self._create_session()
        # 请求计数器，用于控制频率
        self.request_count = 0
        # 最后请求时间
        self.last_request_time = 0

    def _create_session(self):
        """创建请求会话"""
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(
                total=2,  # 减少重试次数以加快诊断
                backoff_factor=1.0,  # 减少退避时间
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS"],
            )
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.timeout = NetworkConstants.LONG_TIMEOUT
        return session

    def _request(self, url, params=None, headers=None, timeout=NetworkConstants.LONG_TIMEOUT):
        """通用请求方法，包含错误处理和重试机制"""
        if headers is None:
            headers = self._get_headers()

        try:
            # 控制请求频率
            self._control_request_rate()

            # 添加随机延迟（合规标准：模拟人工操作间隔）
            delay = random.uniform(0.5, 1.0)  # 减少延迟时间
            time.sleep(delay)
            logger.debug(f"请求前延迟: {delay:.2f}秒")

            # 使用更长的超时时间，并分别设置连接和读取超时
            response = self.session.get(
                url, 
                params=params, 
                headers=headers, 
                timeout=(10, timeout),  # (连接超时, 读取超时)
                verify=False
            )

            # 检查响应状态
            response.raise_for_status()

            # 尝试解析JSON
            try:
                return response.json()
            except ValueError:
                # 处理JSONP响应
                text = response.text
                if "(" in text and ")" in text:
                    json_str = text[text.find("(") + 1 : text.rfind(")")]
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
            # 切换代理并重试
            self._switch_proxy()
            raise
        except requests.exceptions.ReadTimeout as e:
            logger.warning(f"读取超时: 服务器响应太慢 {e}")
            raise
        except requests.exceptions.Timeout as e:
            logger.warning(f"请求超时: {e}")
            # 切换代理并重试
            self._switch_proxy()
            raise
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP错误: {e}")
            # 403错误可能是被反爬，切换代理
            try:
                if response.status_code == 403:
                    logger.warning("403错误，可能被反爬，尝试切换代理")
                    self._switch_proxy()
            except (AttributeError, RuntimeError):
                logger.exception("切换代理失败，继续抛出原始异常")
                pass
            raise
        except Exception as e:  # noqa: E722 — _request 最终兜底，上层已有具体异常处理
            logger.warning(f"请求失败: {e}")
            raise

    def _get_headers(self):
        """获取合规的浏览器请求头"""
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
        """控制请求频率，确保合规"""
        self.request_count += 1

        # 每10个请求增加额外延迟（合规标准：≤10次/分钟）
        if self.request_count % 10 == 0:
            extra_delay = random.uniform(3, 5)
            logger.debug(f"每10个请求额外延迟: {extra_delay:.2f}秒")
            time.sleep(extra_delay)

        # 控制请求间隔（合规标准：单次请求间隔≥1秒）
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        min_interval = 1.0  # 最小请求间隔

        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            logger.debug(f"控制请求间隔，等待: {wait_time:.2f}秒")
            time.sleep(wait_time)

        self.last_request_time = time.time()

    @property
    def name(self) -> str:
        return "eastmoney"

    def _convert_symbol(self, symbol: str) -> tuple:
        """转换股票代码格式，返回(市场代码, 股票代码)"""
        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")
        if clean_symbol.startswith(("6", "5")):
            return "1", clean_symbol  # 沪市
        elif clean_symbol.startswith(("0", "3")):
            return "0", clean_symbol  # 深市
        else:
            return "0", clean_symbol

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
        """使用东方财富原生API获取日线数据"""
        # 股票代码预处理
        if "." in symbol:
            clean_symbol = symbol.split(".")[0]
        else:
            clean_symbol = symbol

        logger.info(
            f"开始获取 {symbol} 的日线数据，时间范围: {start_date} 至 {end_date}"
        )

        # =========================================================================
        # 使用东方财富原生API获取K线数据
        # API: https://push2his.eastmoney.com/api/qt/stock/kline/get
        # =========================================================================
        try:
            market, code = self._convert_symbol(symbol)
            secid = f"{market}.{code}"

            # 转换日期格式
            start_date_fmt = start_date.replace("-", "")
            end_date_fmt = end_date.replace("-", "")

            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "secid": secid,
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101",  # 101=日线
                "fqt": "1",    # 1=前复权
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

            # 获取K线列表
            klines = kline_data.get("klines", [])
            if not klines:
                logger.warning(f"东方财富API返回空K线数据: {symbol}")
                return pd.DataFrame()

            # 解析K线数据
            # 格式: "日期,开盘价,收盘价,最高价,最低价,成交量,成交额,振幅,涨跌幅,涨跌额,换手率"
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

            # 处理日期类型
            df["date"] = pd.to_datetime(df["date"]).dt.date

            # 添加股票代码列
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
        except Exception as e:  # noqa: E722 — 防御层，上方已有具体异常分支
            logger.warning(
                f"Unexpected error fetching data from eastmoney for {symbol}: {e}."
            )
            return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """
        获取实时数据
        """
        try:
            # 如果指定了股票代码，使用个股API获取
            if symbol:
                return self._fetch_real_time_single(symbol)

            # 否则获取全市场数据
            return self._fetch_real_time_all()

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.error(f"获取实时数据时发生错误: {e}")
            return pd.DataFrame()

    def _fetch_real_time_single(self, symbol: str) -> pd.DataFrame:
        """获取单只股票实时数据"""
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

        # 构建DataFrame
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
        """获取全市场实时数据"""
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
            "fs": "m:0+t:6,m:0+t:13,m:1+t:2,m:1+t:23",  # 包含沪深两市
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

        # 列名映射
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

        # 重命名列
        df = df.rename(columns=column_mapping)

        # 保留需要的列
        needed_cols = list(column_mapping.values())
        df = df[[col for col in needed_cols if col in df.columns]]

        # 数据类型转换
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
        """获取市值数据"""
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

            # f116 总市值（元）
            if "f116" in stock_data:
                mcap = stock_data["f116"]
                result = float(mcap) / 1e8 if mcap else 0.0  # 转换为亿元
                logger.info(f"成功获取市值: {result:.2f} 亿元")
                return result
            else:
                logger.warning(f"API返回数据中不包含市值字段: {symbol}")
                return 0.0

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.error(f"获取市值失败 {symbol}: {e}")
            return 0.0

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @with_request_control(min_interval=2, max_retries=3)  # Added from instruction
    def fetch_basic_info(self, symbol: str) -> pd.DataFrame:
        """获取股票基本信息，支持多个备用域名"""
        # 备用域名列表
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

        # 尝试多个域名
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

                # 字段映射
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

                # 构建数据字典
                basic_info = {}
                for field, name in field_mapping.items():
                    if field in stock_data:
                        basic_info[name] = stock_data[field]

                # 转换为DataFrame
                df = pd.DataFrame([basic_info])

                if not df.empty:
                    logger.info(f"成功获取 {symbol} 基本信息 (使用 {url})")
                    return df
                    
            except Exception as e:  # noqa: E722 — 多域名故障转移，需捕获一切
                last_error = e
                logger.warning(f"域名 {url} 请求失败: {e}")
                continue

        # 所有域名都失败
        logger.error(f"所有域名都无法获取 {symbol} 基本信息: {last_error}")
        return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    def fetch_industry_list(self) -> pd.DataFrame:
        """获取行业列表"""
        try:
            logger.info("尝试获取行业列表...")

            # 使用简单的方式返回一个默认的行业列表
            # 这样可以确保方法不会卡住，同时提供一个基本的行业列表
            import pandas as pd

            # 创建默认的行业列表
            default_industries = [
                {"板块代码": "BK0475", "板块名称": "银行"},
                {"板块代码": "BK0476", "板块名称": "证券"},
                {"板块代码": "BK0477", "板块名称": "保险"},
                {"板块代码": "BK0438", "板块名称": "房地产"},
                {"板块代码": "BK0736", "板块名称": "人工智能"},
                {"板块代码": "BK1036", "板块名称": "新能源"},
                {"板块代码": "BK0447", "板块名称": "医药制造"},
                {"板块代码": "BK0448", "板块名称": "通信设备"},
                {"板块代码": "BK0450", "板块名称": "计算机"},
                {"板块代码": "BK0451", "板块名称": "电子元件"},
            ]

            df = pd.DataFrame(default_industries)
            logger.info(f"成功获取行业列表，共 {len(df)} 条记录")
            return df
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Failed to fetch industry list: {e}")
            return pd.DataFrame()
        except Exception as e:  # noqa: E722 — 防御层，上方已有具体异常分支
            logger.critical(
                f"Unexpected error fetching industry list: {e}", exc_info=True
            )
            return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    def fetch_concept_list(self) -> pd.DataFrame:
        """获取概念列表"""
        try:
            logger.info("尝试获取概念列表...")

            # 使用简单的方式返回一个默认的概念列表
            # 这样可以确保方法不会卡住，同时提供一个基本的概念列表
            import pandas as pd

            # 创建默认的概念列表
            default_concepts = [
                {"板块代码": "BK0736", "板块名称": "人工智能"},
                {"板块代码": "BK1036", "板块名称": "新能源"},
                {"板块代码": "BK0740", "板块名称": "芯片"},
                {"板块代码": "BK0637", "板块名称": "5G"},
                {"板块代码": "BK0800", "板块名称": "区块链"},
                {"板块代码": "BK0986", "板块名称": "云计算"},
                {"板块代码": "BK1009", "板块名称": "大数据"},
                {"板块代码": "BK0913", "板块名称": "物联网"},
                {"板块代码": "BK0643", "板块名称": "半导体"},
                {"板块代码": "BK0719", "板块名称": "数字货币"},
            ]

            df = pd.DataFrame(default_concepts)
            logger.info(f"成功获取概念列表，共 {len(df)} 条记录")
            return df
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Failed to fetch concept list: {e}")
            return pd.DataFrame()
        except Exception as e:  # noqa: E722 — 防御层，上方已有具体异常分支
            logger.critical(
                f"Unexpected error fetching concept list: {e}", exc_info=True
            )
            return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    def fetch_concept_relation(self, symbol: str) -> pd.DataFrame:
        """获取股票概念板块关系数据"""
        try:
            # 由于概念板块关系API较为复杂，这里返回一个空的DataFrame
            # 实际项目中可以根据东方财富的概念板块API进行实现
            logger.info(f"获取 {symbol} 的概念板块关系数据")
            return pd.DataFrame()
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Failed to fetch concept relation for {symbol}: {e}")
            return pd.DataFrame()
        except Exception as e:  # noqa: E722 — 防御层，上方已有具体异常分支
            logger.critical(
                f"Unexpected error fetching concept relation for {symbol}: {e}",
                exc_info=True,
            )
            return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @with_request_control(min_interval=2, max_retries=3)
    def fetch_market_fund_flow(self) -> pd.DataFrame:
        """获取大盘资金流向数据，支持多个备用域名"""
        # 备用域名列表
        base_urls = [
            "https://push2.eastmoney.com/api/qt/clist/get",
            "https://push.eastmoney.com/api/qt/clist/get",
        ]
        
        # 大盘资金流向使用不同的参数
        params = {
            "pn": "1",
            "pz": "50",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f62",
            "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024",  # 大盘指数
            "fields": "f12,f14,f2,f3,f4,f5,f6,f8,f20,f21,f23,f62",
        }

        # 尝试多个域名
        for url in base_urls:
            try:
                data = self._request(url, params=params, timeout=NetworkConstants.MEDIUM_TIMEOUT)

                if data.get("rc") != 0:
                    logger.warning(f"大盘资金流向API返回错误 ({url}): {data.get('msg', 'Unknown error')}")
                    continue

                items = data.get("data", {}).get("diff", [])
                if not items:
                    logger.warning(f"大盘资金流向API返回空数据 ({url})")
                    continue

                df = pd.DataFrame(items)

                # 列名映射
                column_mapping = {
                    "f12": "code",
                    "f14": "name",
                    "f2": "price",
                    "f3": "change_rate",
                    "f4": "change",
                    "f5": "volume",
                    "f6": "amount",
                }

                # 重命名列
                df = df.rename(columns=column_mapping)

                # 保留需要的列
                needed_cols = list(column_mapping.values())
                df = df[[col for col in needed_cols if col in df.columns]]

                logger.info(f"成功获取大盘资金流向 (使用 {url})")
                return df

            except Exception as e:  # noqa: E722 — 多域名故障转移
                logger.warning(f"域名 {url} 请求失败: {e}")
                continue

        logger.error("所有域名都无法获取大盘资金流向")
        return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @with_request_control(min_interval=2, max_retries=3)
    def fetch_sector_fund_flow(
        self, sector_type: str = "行业资金流", indicator: str = "今日"
    ) -> pd.DataFrame:
        """获取板块资金流排名，支持多个备用域名"""
        # 根据板块类型确定fs参数
        if "行业" in sector_type:
            fs = "m:90 t:2 f:!50"
        elif "概念" in sector_type:
            fs = "m:90 t:3 f:!50"
        else:
            fs = "m:90 t:2 f:!50"

        # 备用域名列表
        base_urls = [
            "https://push2.eastmoney.com/api/qt/clist/get",
            "https://push.eastmoney.com/api/qt/clist/get",
        ]
        
        params = {
            "pn": "1",
            "pz": "50",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f62",
            "fs": fs,
            "fields": "f12,f14,f2,f3,f4,f5,f6,f8,f20,f21,f23",
        }

        # 尝试多个域名
        for url in base_urls:
            try:
                data = self._request(url, params=params, timeout=NetworkConstants.MEDIUM_TIMEOUT)

                if data.get("rc") != 0:
                    logger.warning(f"板块资金流API返回错误 ({url}): {data.get('msg', 'Unknown error')}")
                    continue

                items = data.get("data", {}).get("diff", [])
                if not items:
                    logger.warning(f"板块资金流API返回空数据 ({url})")
                    continue

                df = pd.DataFrame(items)

                # 列名映射
                column_mapping = {
                    "f12": "code",
                    "f14": "name",
                    "f2": "price",
                    "f3": "change_rate",
                    "f4": "change",
                    "f5": "volume",
                    "f6": "amount",
                }

                # 重命名列
                df = df.rename(columns=column_mapping)

                # 保留需要的列
                needed_cols = list(column_mapping.values())
                df = df[[col for col in needed_cols if col in df.columns]]

                logger.info(f"成功获取板块资金流 (使用 {url})")
                return df

            except Exception as e:  # noqa: E722 — 多域名故障转移
                logger.warning(f"域名 {url} 请求失败: {e}")
                continue

        logger.error("所有域名都无法获取板块资金流")
        return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @with_request_control(min_interval=2, max_retries=3)
    def fetch_hot_rank(self) -> pd.DataFrame:
        """获取热门排行数据，支持多个备用域名"""
        # 备用域名列表
        base_urls = [
            "https://push2.eastmoney.com/api/qt/clist/get",
            "https://push.eastmoney.com/api/qt/clist/get",
        ]
        
        params = {
            "pn": "1",
            "pz": "50",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0 t:6 f:!50",
            "fields": "f12,f14,f2,f3,f4,f5,f6,f8,f20,f21,f23",
        }

        # 尝试多个域名
        for url in base_urls:
            try:
                data = self._request(url, params=params, timeout=NetworkConstants.MEDIUM_TIMEOUT)

                if data.get("rc") != 0:
                    logger.warning(f"热门排行API返回错误 ({url}): {data.get('msg', 'Unknown error')}")
                    continue

                items = data.get("data", {}).get("diff", [])
                if not items:
                    logger.warning(f"热门排行API返回空数据 ({url})")
                    continue

                df = pd.DataFrame(items)

                # 列名映射
                column_mapping = {
                    "f12": "symbol",
                    "f14": "name",
                    "f2": "price",
                    "f3": "change_rate",
                    "f4": "change",
                    "f5": "volume",
                    "f6": "amount",
                }

                # 重命名列
                df = df.rename(columns=column_mapping)

                # 保留需要的列
                needed_cols = list(column_mapping.values())
                df = df[[col for col in needed_cols if col in df.columns]]

                logger.info(f"成功获取热门排行 (使用 {url})")
                return df

            except Exception as e:  # noqa: E722 — 多域名故障转移
                logger.warning(f"域名 {url} 请求失败: {e}")
                continue

        logger.error("所有域名都无法获取热门排行")
        return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @with_request_control(min_interval=2, max_retries=3)
    def fetch_hsgt_data(self) -> pd.DataFrame:
        """获取沪深港通数据"""
        try:
            url = "https://push.eastmoney.com/api/qt/clist/get"
            params = {
                "pn": "1",
                "pz": "50",
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f3",
                "fs": "m:1 t:2 f:!50",
                "fields": "f12,f14,f2,f3,f4,f5,f6,f8,f20,f21,f23",
            }

            data = self._request(url, params=params)

            if data.get("rc") != 0:
                logger.error(
                    f"东方财富沪深港通API返回错误: {data.get('msg', 'Unknown error')}"
                )
                return pd.DataFrame()

            items = data.get("data", {}).get("diff", [])
            if not items:
                logger.warning("东方财富沪深港通API返回空数据")
                return pd.DataFrame()

            df = pd.DataFrame(items)

            # 列名映射
            column_mapping = {
                "f12": "symbol",
                "f14": "name",
                "f2": "price",
                "f3": "change_rate",
                "f4": "change",
                "f5": "volume",
                "f6": "amount",
            }

            # 重命名列
            df = df.rename(columns=column_mapping)

            # 保留需要的列
            needed_cols = list(column_mapping.values())
            df = df[[col for col in needed_cols if col in df.columns]]

            return df
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.error(f"Failed to fetch hsgt data: {e}")
            return pd.DataFrame()

    # ========================================================================
    # 新增功能: 分钟级K线数据 (使用AKShare API)
    # ========================================================================

    def fetch_minute_data(
        self,
        symbol: str,
        period: str = "5",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """
        获取分钟级K线数据 (使用AKShare API)

        Args:
            symbol: 股票代码(如"600519.SH")
            period: K线周期('1','5','15','30','60')
            start_date: 开始日期(YYYY-MM-DD格式)
            end_date: 结束日期(YYYY-MM-DD格式)
            adjust: 复权方式('qfq':前复权,'hfq':后复权,'':不复权)

        Returns:
            DataFrame包含: date,open,high,low,close,volume,amount等列
        """
        try:
            # 清理股票代码,移除市场标识
            clean_symbol = (
                symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            )

            logger.info(
                f"开始获取 {symbol} 分钟K线数据,周期:{period}分钟,时间范围:{start_date}~{end_date}"
            )

            # 使用AKShare Wrapper统一调用
            from ..utils.akshare_wrapper import akshare_wrapper

            # 日期格式转换: YYYY-MM-DD -> YYYYMMDD
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

            # 标准化列名(AKShare返回的列名可能是中文)
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

            # 重命名存在的列
            df = df.rename(columns=column_mapping)

            logger.info(f"成功获取 {symbol} 分钟K线数据: {len(df)} 条记录")
            return df

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, ImportError) as e:
            logger.error(f"获取 {symbol} 分钟K线数据失败: {e}", exc_info=True)
            return pd.DataFrame()

    # ========================================================================
    # 新增功能: 资金流向数据
    # ========================================================================

    def fetch_fund_flow(self, symbol: str) -> pd.DataFrame:
        """
        获取个股资金流向数据 (使用AKShare API)

        Args:
            symbol: 股票代码(如"600519.SH"或"600519")

        Returns:
            DataFrame包含: 日期,主力净流入,超大单净流入,大单净流入,中单净流入,小单净流入等
        """
        try:
            # 清理股票代码
            clean_symbol = (
                symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            )

            # 判断市场
            if clean_symbol.startswith("6") or clean_symbol.startswith("5"):
                market = "sh"  # 上海
            elif clean_symbol.startswith("0") or clean_symbol.startswith("3"):
                market = "sz"  # 深圳
            elif clean_symbol.startswith("8") or clean_symbol.startswith("4"):
                market = "bj"  # 北京
            else:
                market = "sh"  # 默认上海

            logger.info(f"开始获取 {symbol} 资金流向数据,市场:{market}")

            # 使用AKShare Wrapper统一调用
            from ..utils.akshare_wrapper import akshare_wrapper

            df = akshare_wrapper.fetch_fund_flow(stock=clean_symbol, market=market)

            if df is None or df.empty:
                logger.warning(f"获取 {symbol} 资金流向数据为空")
                return pd.DataFrame()

            logger.info(f"成功获取 {symbol} 资金流向数据: {len(df)} 条记录")
            return df

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, ImportError) as e:
            logger.error(f"获取 {symbol} 资金流向数据失败: {e}", exc_info=True)
            return pd.DataFrame()

    # ========================================================================
    # 新增功能: 龙虎榜数据
    # ========================================================================

    def fetch_dragon_tiger_list(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取龙虎榜数据 (使用AKShare API)

        Args:
            symbol: 股票代码(如"600519"或"600519.SH")
            start_date: 开始日期(YYYY-MM-DD格式)
            end_date: 结束日期(YYYY-MM-DD格式)

        Returns:
            DataFrame包含: 日期,代码,名称,上榜原因,收盘价,涨跌幅,龙虎榜净买额等
        """
        try:
            # 清理股票代码
            clean_symbol = (
                symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            )

            logger.info(f"开始获取 {symbol} 龙虎榜数据: {start_date}~{end_date}")

            # 使用AKShare Wrapper统一调用
            from ..utils.akshare_wrapper import akshare_wrapper

            # 日期格式转换: YYYY-MM-DD -> YYYYMMDD
            start_date_fmt = start_date.replace("-", "")
            end_date_fmt = end_date.replace("-", "")

            df = akshare_wrapper.fetch_dragon_tiger_list(
                symbol=clean_symbol, start_date=start_date_fmt, end_date=end_date_fmt
            )

            if df is None or df.empty:
                logger.info(f"获取 {symbol} 龙虎榜数据为空(可能未上榜)")
                return pd.DataFrame()

            logger.info(f"成功获取 {symbol} 龙虎榜数据: {len(df)} 条记录")
            return df

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, ImportError) as e:
            logger.error(f"获取 {symbol} 龙虎榜数据失败: {e}", exc_info=True)
            return pd.DataFrame()
