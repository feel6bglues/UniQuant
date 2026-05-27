import logging
import time
from typing import Optional

import pandas as pd

from ...shared.error_handling import handle_errors
from ...shared.logger_factory import get_logger
from ...shared.retry_decorator import retry

from .base import DataSource

logger = get_logger(__name__)


class BaostockSource(DataSource):
    """
    BaoStock数据源实现
    特点：完全免费开源，支持前复权/后复权/不复权，数据质量高，适合价值投资研究
    """

    def __init__(self):
        self._logged_in = False
        self._bs = None

    @property
    def name(self) -> str:
        return "baostock"

    def _login(self) -> bool:
        """登录BaoStock"""
        if self._logged_in and self._bs is not None:
            return True

        try:
            import baostock as bs

            self._bs = bs
            result = bs.login()
            if result.error_code == "0":
                self._logged_in = True
                logger.info("BaoStock登录成功")
                return True
            else:
                logger.error(f"BaoStock登录失败: {result.error_msg}")
                return False
        except ImportError:
            logger.error("未安装baostock库，请运行: pip install baostock")
            return False
        except (RuntimeError, ConnectionError, OSError) as e:
            logger.error(f"BaoStock登录异常: {e}")
            return False

    def _logout(self):
        """登出BaoStock"""
        if self._logged_in and self._bs is not None:
            try:
                self._bs.logout()
                self._logged_in = False
                logger.info("BaoStock登出成功")
            except (RuntimeError, ConnectionError, OSError) as e:
                logger.warning(f"BaoStock登出异常: {e}")

    def _convert_symbol(self, symbol: str) -> str:
        """
        转换股票代码为BaoStock格式
        600519.SH -> sh.600519
        000001.SZ -> sz.000001
        """
        # 移除可能的空格
        symbol = symbol.strip()

        # 如果已经是baostock格式，直接返回
        if "." in symbol and (symbol.startswith("sh.") or symbol.startswith("sz.")):
            return symbol

        # 处理带后缀的格式
        if "." in symbol:
            code, suffix = symbol.split(".")
            if suffix.upper() == "SH":
                return f"sh.{code}"
            elif suffix.upper() == "SZ":
                return f"sz.{code}"

        # 根据代码规则判断市场
        if symbol.startswith("6") or symbol.startswith("5"):
            return f"sh.{symbol}"
        else:
            return f"sz.{symbol}"

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def fetch_daily(
        self, symbol: str, start_date: str, end_date: str, adjust: str = "qfq"
    ) -> pd.DataFrame:
        """
        获取日线数据

        Args:
            symbol: 股票代码，如 "600519.SH" 或 "600519"
            start_date: 开始日期，格式 "YYYY-MM-DD" 或 "YYYYMMDD"
            end_date: 结束日期，格式 "YYYY-MM-DD" 或 "YYYYMMDD"
            adjust: 复权类型，"qfq"(前复权), "hfq"(后复权), "none"(不复权)

        Returns:
            pd.DataFrame: 包含 date, open, high, low, close, volume, amount 列

        Note:
            adjust 参数为 Baostock 特有扩展，基类 DataSource 不含此参数。
        """
        if not self._login():
            return pd.DataFrame()

        # 转换代码格式
        bs_symbol = self._convert_symbol(symbol)

        # 转换日期格式为YYYY-MM-DD
        if len(start_date) == 8 and "-" not in start_date:
            start_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        if len(end_date) == 8 and "-" not in end_date:
            end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

        # 复权参数映射
        adjust_map = {
            "qfq": "2",  # 前复权
            "hfq": "1",  # 后复权
            "none": "3",  # 不复权
        }
        adjust_flag = adjust_map.get(adjust, "2")

        try:
            # 查询历史K线数据
            rs = self._bs.query_history_k_data_plus(
                bs_symbol,
                "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag=adjust_flag,
            )

            if rs.error_code != "0":
                logger.error(f"BaoStock查询错误: {rs.error_msg}")
                return pd.DataFrame()

            # 转换为DataFrame
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                logger.warning(f"BaoStock返回空数据: {symbol}")
                return pd.DataFrame()

            df = pd.DataFrame(data_list, columns=rs.fields)

            # 数据类型转换
            numeric_cols = [
                "open",
                "high",
                "low",
                "close",
                "preclose",
                "volume",
                "amount",
                "turn",
                "pctChg",
            ]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            # 处理日期
            df["date"] = pd.to_datetime(df["date"]).dt.date

            # 标准化列名
            df = df.rename(
                columns={
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                    "amount": "amount",
                }
            )

            # 确保必要列存在
            required_cols = ["date", "open", "high", "low", "close", "volume"]
            for col in required_cols:
                if col not in df.columns:
                    if col in ["open", "high", "low"] and "close" in df.columns:
                        df[col] = df["close"]
                    elif col == "volume":
                        df["volume"] = 0

            if "amount" not in df.columns:
                df["amount"] = df.get("close", 0) * df.get("volume", 0)

            # 过滤日期范围
            start = pd.to_datetime(start_date).date()
            end = pd.to_datetime(end_date).date()
            df = df[(df["date"] >= start) & (df["date"] <= end)]

            if df.empty:
                return pd.DataFrame()

            # 计算振幅和涨跌幅
            if (
                "close" in df.columns
                and "high" in df.columns
                and "low" in df.columns
                and "preclose" in df.columns
            ):
                df["amplitude"] = (
                    (df["high"] - df["low"]) / df["preclose"] * 100
                ).fillna(0)
                # 使用BaoStock返回的涨跌幅数据
                if "pctChg" in df.columns:
                    df["change_rate"] = df["pctChg"].fillna(0)
                else:
                    df["change_rate"] = (
                        (df["close"] - df["preclose"]) / df["preclose"] * 100
                    ).fillna(0)
            else:
                df["amplitude"] = 0
                df["change_rate"] = 0

            # 确保股票代码列存在
            if "code" not in df.columns:
                # 提取股票代码
                clean_symbol = symbol.split(".")[0] if "." in symbol else symbol
                df["code"] = clean_symbol

            # 排序和选择列
            df = df.sort_values("date").reset_index(drop=True)
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

            logger.info(f"成功从BaoStock获取 {symbol} 数据，共 {len(df)} 条记录")

            # 添加延迟避免请求过快
            time.sleep(0.1)

            return df[final_cols]

        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            logger.error(f"从BaoStock获取数据失败 {symbol}: {e}")
            return pd.DataFrame()

    @handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def fetch_real_time(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """
        获取实时数据
        注意：BaoStock不支持实时数据，返回空DataFrame
        """
        logger.warning("BaoStock不支持实时数据获取")
        return pd.DataFrame()

    @handle_errors(Exception, default_return=0.0, log_level=logging.ERROR)
    def fetch_market_cap(self, symbol: str) -> float:
        """
        获取市值数据
        注意：BaoStock不直接支持市值查询，返回0.0
        """
        logger.warning("BaoStock不支持市值查询")
        return 0.0

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def fetch_stock_list(self, date: Optional[str] = None) -> pd.DataFrame:
        """
        获取股票列表

        Args:
            date: 查询日期，格式 "YYYY-MM-DD"，默认当前日期

        Returns:
            pd.DataFrame: 股票列表
        """
        if not self._login():
            return pd.DataFrame()

        try:
            # 使用query_stock_basic获取更完整的基础数据
            rs = self._bs.query_stock_basic()

            if rs.error_code != "0":
                logger.error(f"BaoStock查询股票基本资料错误: {rs.error_msg}")
                return pd.DataFrame()

            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                return pd.DataFrame()

            df = pd.DataFrame(data_list, columns=rs.fields)

            # 筛选正常上市的股票（status=1）
            if "status" in df.columns:
                df = df[df["status"] == "1"]

            logger.info(f"成功从BaoStock获取股票列表，共 {len(df)} 只股票")

            # 添加延迟
            time.sleep(0.1)

            return df

        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            logger.error(f"从BaoStock获取股票列表失败: {e}")
            return pd.DataFrame()

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def fetch_minute_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        frequency: str = "5",
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """
        获取分钟级数据

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            frequency: 频率，"5"(5分钟), "15", "30", "60"
            adjust: 复权类型

        Returns:
            pd.DataFrame: 分钟线数据
        """
        if not self._login():
            return pd.DataFrame()

        bs_symbol = self._convert_symbol(symbol)

        adjust_map = {"qfq": "2", "hfq": "1", "none": "3"}
        adjust_flag = adjust_map.get(adjust, "2")

        try:
            rs = self._bs.query_history_k_data_plus(
                bs_symbol,
                "date,time,code,open,high,low,close,volume,amount",
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjustflag=adjust_flag,
            )

            if rs.error_code != "0":
                logger.error(f"BaoStock查询分钟线错误: {rs.error_msg}")
                return pd.DataFrame()

            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                logger.warning(f"BaoStock返回空分钟线数据: {symbol}")
                return pd.DataFrame()

            df = pd.DataFrame(data_list, columns=rs.fields)

            # 数据类型转换
            numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            logger.info(
                f"成功从BaoStock获取 {symbol} 的{frequency}分钟线数据，共 {len(df)} 条"
            )

            time.sleep(0.1)
            return df

        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            logger.error(f"从BaoStock获取分钟线数据失败 {symbol}: {e}")
            return pd.DataFrame()

    def __enter__(self):
        """上下文管理器进入方法"""
        self._login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出方法"""
        self._logout()
        return False

    @retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
    @handle_errors(Exception, default_return=pd.DataFrame(), log_level=logging.ERROR)
    def fetch_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取交易日历

        Args:
            start_date: 开始日期，格式 "YYYY-MM-DD"
            end_date: 结束日期，格式 "YYYY-MM-DD"

        Returns:
            pd.DataFrame: 包含 trade_date 和 is_trading_day 的交易日历数据
        """
        if not self._login():
            return pd.DataFrame()

        try:
            # 使用Baostock的query_trade_dates方法获取交易日历
            rs = self._bs.query_trade_dates(start_date=start_date, end_date=end_date)

            if rs.error_code != "0":
                logger.error(f"BaoStock查询交易日历错误: {rs.error_msg}")
                return pd.DataFrame()

            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                return pd.DataFrame()

            df = pd.DataFrame(data_list, columns=rs.fields)

            # 重命名列以符合统一接口
            if "calendar_date" in df.columns:
                df = df.rename(columns={"calendar_date": "trade_date"})
            if "is_trading_day" in df.columns:
                # 将0/1转换为布尔值
                df["is_trading_day"] = df["is_trading_day"].astype(int).astype(bool)

            logger.info(f"成功从BaoStock获取交易日历，共 {len(df)} 条记录")

            # 添加延迟
            time.sleep(0.1)

            return df

        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            logger.error(f"从BaoStock获取交易日历失败: {e}")
            return pd.DataFrame()

    def __del__(self):
        """析构时登出"""
        self._logout()
