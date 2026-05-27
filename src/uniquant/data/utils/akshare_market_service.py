from typing import Any, Callable, Optional

import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class AkshareMarketService:
    """Market-data oriented AkShare method wrappers."""

    def __init__(self, call: Callable[..., Optional[Any]]):
        self._call = call

    def fetch_stock_daily(
        self, symbol: str, start_date: str, end_date: str, adjust: str = "qfq"
    ) -> Optional[pd.DataFrame]:
        clean_symbol = symbol.split(".")[0] if "." in symbol else symbol
        tx_symbol = f"sh{clean_symbol}" if clean_symbol.startswith("6") else f"sz{clean_symbol}"
        methods = [
            (
                "stock_zh_a_daily",
                {"symbol": clean_symbol, "start_date": start_date, "end_date": end_date},
            ),
            (
                "stock_zh_a_hist",
                {
                    "symbol": clean_symbol,
                    "period": "daily",
                    "start_date": start_date,
                    "end_date": end_date,
                    "adjust": adjust,
                },
            ),
            (
                "stock_zh_a_hist_tx",
                {
                    "symbol": tx_symbol,
                    "start_date": start_date.replace("-", ""),
                    "end_date": end_date.replace("-", ""),
                },
            ),
        ]

        for method_name, kwargs in methods:
            try:
                result = self._call(method_name, **kwargs)
                if result is None:
                    continue
                if hasattr(result, "empty") and not result.empty:
                    if "日期" not in result.columns and "date" not in result.columns:
                        logger.warning("方法 %s 返回的数据缺少日期列", method_name)
                        continue
                    logger.info("成功使用方法 %s 获取股票数据", method_name)
                    return result
                if not hasattr(result, "empty"):
                    logger.info("成功使用方法 %s 获取股票数据", method_name)
                    return result
            except Exception as exc:
                logger.warning("方法 %s 执行失败: %s", method_name, exc)
        logger.warning("所有方法都失败，返回None")
        return None

    def fetch_stock_spot(self, source: str = "sina") -> Optional[pd.DataFrame]:
        method_map = {
            "sina": "stock_zh_a_spot",
            "em": "stock_zh_a_spot_em",
            "ths": "stock_zh_a_spot_ths",
        }
        method_name = method_map.get(source, "stock_zh_a_spot")
        result = self._call(method_name)
        if result is not None and not result.empty:
            return result

        for alt_source, alt_method in method_map.items():
            if alt_source == source:
                continue
            result = self._call(alt_method)
            if result is not None and not result.empty:
                logger.info("Fell back to %s for stock spot data", alt_source)
                return result
        return None

    def fetch_stock_daily_sina(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        return self._call(
            "stock_zh_a_daily", symbol=symbol, start_date=start_date, end_date=end_date
        )

    def fetch_etf_hist(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        return self._call(
            "fund_etf_hist_em",
            symbol=symbol,
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )

    def fetch_index_daily(self, symbol: str) -> Optional[pd.DataFrame]:
        logger.info("开始获取指数 %s 数据", symbol)
        result = self._call("stock_zh_index_daily", symbol=symbol)
        if result is not None and not result.empty:
            logger.info("成功获取指数 %s 数据: %d 条记录", symbol, len(result))
        else:
            logger.warning("获取指数 %s 数据为空", symbol)
        return result

    def fetch_minute_data(
        self,
        symbol: str,
        period: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
    ) -> Optional[pd.DataFrame]:
        logger.info(
            "开始获取 %s 分钟K线数据: 周期=%s分钟, 时间范围=%s~%s, 复权=%s",
            symbol,
            period,
            start_date,
            end_date,
            adjust,
        )
        result = self._call(
            "stock_zh_a_hist_min_em",
            symbol=symbol,
            period=period,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        if result is not None and not result.empty:
            logger.info("成功获取 %s 分钟K线数据: %d 条记录", symbol, len(result))
        else:
            logger.warning("获取 %s 分钟K线数据为空", symbol)
        return result

    def fetch_fund_flow(self, stock: str, market: str = "sh") -> Optional[pd.DataFrame]:
        logger.info("开始获取 %s.%s 资金流向数据", market, stock)
        result = self._call("stock_individual_fund_flow", stock=stock, market=market)
        if result is not None and not result.empty:
            logger.info("成功获取 %s.%s 资金流向数据: %d 条记录", market, stock, len(result))
        else:
            logger.warning("获取 %s.%s 资金流向数据为空", market, stock)
        return result

    def fetch_dragon_tiger_list(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        logger.info("开始获取 %s 龙虎榜数据: %s~%s", symbol, start_date, end_date)
        result = self._call(
            "stock_lhb_detail_em", start_date=start_date, end_date=end_date
        )
        if result is None or result.empty:
            logger.info("获取 %s 龙虎榜数据为空(可能未上榜)", symbol)
            return pd.DataFrame()

        clean_symbol = symbol.replace(".SH", "").replace(".SZ", "")
        if "代码" in result.columns:
            result = result[result["代码"].astype(str).str.contains(clean_symbol)]
        elif "symbol" in result.columns:
            result = result[result["symbol"].astype(str).str.contains(clean_symbol)]
        logger.info("成功获取 %s 龙虎榜数据: %d 条记录", symbol, len(result))
        return result

    def fetch_tick_data(self, symbol: str) -> Optional[pd.DataFrame]:
        logger.info("开始获取 %s 逐笔成交数据", symbol)
        result = self._call("stock_zh_a_tick_tx_js", symbol=symbol)
        if result is not None and not result.empty:
            logger.info("成功获取 %s 逐笔成交数据: %d 条记录", symbol, len(result))
        else:
            logger.warning("获取 %s 逐笔成交数据为空", symbol)
        return result
