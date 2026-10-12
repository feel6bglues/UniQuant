"""Baostock 私有客户端模块（D5 解耦, 2026-10-12）

从 `sources/baostock.py` 的 `BaostockSource` 内联而来（仅登录/登出/拉股票列表/拉日历四能力，
去 DataSource 继承）。`sources/baostock.py` 随后删除，本模块为两 manager 的唯一 baostock 入口。

纪律：本模块为 **在线主数据生产链**（`create_baostock_cache` 写 `data/all_stock_codes.csv`），
在 TDX 代码表字段等价性核验（Step5 前置门）通过前**不得剪除**。
"""
import time
from typing import Optional

import pandas as pd

from ...shared.error_handling import handle_errors
from ...shared.logger_factory import get_logger
from ...shared.retry_decorator import retry

logger = get_logger(__name__)

_logged_in = False
_bs = None


def login() -> bool:
    """登录 BaoStock"""
    global _logged_in, _bs
    if _logged_in and _bs is not None:
        return True

    try:
        import baostock as bs

        _bs = bs
        result = bs.login()
        if result.error_code == "0":
            _logged_in = True
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


def logout() -> None:
    """登出 BaoStock"""
    global _logged_in
    if _logged_in and _bs is not None:
        try:
            _bs.logout()
            _logged_in = False
            logger.info("BaoStock登出成功")
        except (RuntimeError, ConnectionError, OSError) as e:
            logger.warning(f"BaoStock登出异常: {e}")


@retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
@handle_errors(Exception, default_return=pd.DataFrame(), log_level=30)
def fetch_stock_list(
    date: Optional[str] = None, include_delisted: bool = True
) -> pd.DataFrame:
    """
    获取股票列表

    Args:
        date: 查询日期，格式 "YYYY-MM-DD"，默认当前日期
        include_delisted: 是否包含已退市股票，默认True包含全量（回测/研究应包含退市股票以消除幸存者偏差）；
                         仅在实盘交易时可根据需要设为False排除退市股票。

    Returns:
        pd.DataFrame: 股票列表
    """
    if not login():
        return pd.DataFrame()

    try:
        # 使用query_stock_basic获取更完整的基础数据
        rs = _bs.query_stock_basic()

        if rs.error_code != "0":
            logger.error(f"BaoStock查询股票基本资料错误: {rs.error_msg}")
            return pd.DataFrame()

        data_list = []
        while rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            return pd.DataFrame()

        df = pd.DataFrame(data_list, columns=rs.fields)

        # 筛选正常上市的股票（status=1），除非显式要求包含退市股票
        if not include_delisted and "status" in df.columns:
            df = df[df["status"] == "1"]

        logger.info(f"成功从BaoStock获取股票列表，共 {len(df)} 只股票")

        # 添加延迟
        time.sleep(0.1)

        return df

    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.error(f"从BaoStock获取股票列表失败: {e}")
        return pd.DataFrame()


@retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
@handle_errors(Exception, default_return=pd.DataFrame(), log_level=30)
def fetch_calendar(start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取交易日历

    Args:
        start_date: 开始日期，格式 "YYYY-MM-DD"
        end_date: 结束日期，格式 "YYYY-MM-DD"

    Returns:
        pd.DataFrame: 包含 trade_date 和 is_trading_day 的交易日历数据
    """
    if not login():
        return pd.DataFrame()

    try:
        # 使用Baostock的query_trade_dates方法获取交易日历
        rs = _bs.query_trade_dates(start_date=start_date, end_date=end_date)

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
