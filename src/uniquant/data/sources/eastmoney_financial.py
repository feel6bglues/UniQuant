# NON_RESEARCH_RANDOMNESS — 网络数据源, 包含非确定性网络请求

import pandas as pd
import requests
import requests.exceptions

from ...shared.constants import NetworkConstants
from ...shared.logger_factory import get_logger
from ...shared.retry_decorator import retry

from ..utils.request_utils import with_request_control
from .eastmoney_quote import EastmoneyQuoteSource

logger = get_logger(__name__)


class EastmoneySource(EastmoneyQuoteSource):
    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    def fetch_industry_list(self) -> pd.DataFrame:
        try:
            logger.info("尝试获取行业列表...")

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
        except Exception as e:
            logger.critical(
                f"Unexpected error fetching industry list: {e}", exc_info=True
            )
            return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    def fetch_concept_list(self) -> pd.DataFrame:
        try:
            logger.info("尝试获取概念列表...")

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
        except Exception as e:
            logger.critical(
                f"Unexpected error fetching concept list: {e}", exc_info=True
            )
            return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    def fetch_concept_relation(self, symbol: str) -> pd.DataFrame:
        try:
            logger.info(f"获取 {symbol} 的概念板块关系数据")
            return pd.DataFrame()
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Failed to fetch concept relation for {symbol}: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.critical(
                f"Unexpected error fetching concept relation for {symbol}: {e}",
                exc_info=True,
            )
            return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @with_request_control(min_interval=2, max_retries=3)
    def fetch_market_fund_flow(self) -> pd.DataFrame:
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
            "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024",
            "fields": "f12,f14,f2,f3,f4,f5,f6,f8,f20,f21,f23,f62",
        }

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

                column_mapping = {
                    "f12": "code",
                    "f14": "name",
                    "f2": "price",
                    "f3": "change_rate",
                    "f4": "change",
                    "f5": "volume",
                    "f6": "amount",
                }

                df = df.rename(columns=column_mapping)

                needed_cols = list(column_mapping.values())
                df = df[[col for col in needed_cols if col in df.columns]]

                logger.info(f"成功获取大盘资金流向 (使用 {url})")
                return df

            except Exception as e:
                logger.warning(f"域名 {url} 请求失败: {e}")
                continue

        logger.error("所有域名都无法获取大盘资金流向")
        return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @with_request_control(min_interval=2, max_retries=3)
    def fetch_sector_fund_flow(
        self, sector_type: str = "行业资金流", indicator: str = "今日"
    ) -> pd.DataFrame:
        if "行业" in sector_type:
            fs = "m:90 t:2 f:!50"
        elif "概念" in sector_type:
            fs = "m:90 t:3 f:!50"
        else:
            fs = "m:90 t:2 f:!50"

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

                column_mapping = {
                    "f12": "code",
                    "f14": "name",
                    "f2": "price",
                    "f3": "change_rate",
                    "f4": "change",
                    "f5": "volume",
                    "f6": "amount",
                }

                df = df.rename(columns=column_mapping)

                needed_cols = list(column_mapping.values())
                df = df[[col for col in needed_cols if col in df.columns]]

                logger.info(f"成功获取板块资金流 (使用 {url})")
                return df

            except Exception as e:
                logger.warning(f"域名 {url} 请求失败: {e}")
                continue

        logger.error("所有域名都无法获取板块资金流")
        return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @with_request_control(min_interval=2, max_retries=3)
    def fetch_hot_rank(self) -> pd.DataFrame:
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

                column_mapping = {
                    "f12": "symbol",
                    "f14": "name",
                    "f2": "price",
                    "f3": "change_rate",
                    "f4": "change",
                    "f5": "volume",
                    "f6": "amount",
                }

                df = df.rename(columns=column_mapping)

                needed_cols = list(column_mapping.values())
                df = df[[col for col in needed_cols if col in df.columns]]

                logger.info(f"成功获取热门排行 (使用 {url})")
                return df

            except Exception as e:
                logger.warning(f"域名 {url} 请求失败: {e}")
                continue

        logger.error("所有域名都无法获取热门排行")
        return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @with_request_control(min_interval=2, max_retries=3)
    def fetch_hsgt_data(self) -> pd.DataFrame:
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

            column_mapping = {
                "f12": "symbol",
                "f14": "name",
                "f2": "price",
                "f3": "change_rate",
                "f4": "change",
                "f5": "volume",
                "f6": "amount",
            }

            df = df.rename(columns=column_mapping)

            needed_cols = list(column_mapping.values())
            df = df[[col for col in needed_cols if col in df.columns]]

            return df
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            logger.error(f"Failed to fetch hsgt data: {e}")
            return pd.DataFrame()

    def fetch_fund_flow(self, symbol: str) -> pd.DataFrame:
        try:
            clean_symbol = (
                symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            )

            if clean_symbol.startswith("6") or clean_symbol.startswith("5"):
                market = "sh"
            elif clean_symbol.startswith("0") or clean_symbol.startswith("3"):
                market = "sz"
            elif clean_symbol.startswith("8") or clean_symbol.startswith("4"):
                market = "bj"
            else:
                market = "sh"

            logger.info(f"开始获取 {symbol} 资金流向数据,市场:{market}")

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

    def fetch_dragon_tiger_list(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        try:
            clean_symbol = (
                symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            )

            logger.info(f"开始获取 {symbol} 龙虎榜数据: {start_date}~{end_date}")

            from ..utils.akshare_wrapper import akshare_wrapper

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