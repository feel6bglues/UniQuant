"""市场相关常量"""

import datetime
from typing import Optional, Set

from uniquant.shared.logger_factory import get_logger
from uniquant.shared.time_provider import get_time_provider


class DateConstants:
    """日期相关常量"""
    DEFAULT_START_DATE = "2000-01-01"
    DEFAULT_START_DATE_COMPACT = "20000101"
    FORMAT_DASH = "%Y-%m-%d"
    FORMAT_COMPACT = "%Y%m%d"
    FORMAT_DATETIME = "%Y-%m-%d %H:%M:%S"


class TimeConstants:
    """时间跨度常量"""
    DAYS_1_YEAR = 365
    DAYS_MONTH = 30
    DAYS_QUARTER = 90
    DATA_WINDOW_30DAYS = 30
    DATA_WINDOW_365DAYS = 365


class MarketConstants:
    """市场相关常量"""

    # 市场类型
    MARKET_CN = "cn"
    MARKET_HK = "hk"
    MARKET_US = "us"

    # 交易所
    EXCHANGE_SSE = "SSE"  # 上海证券交易所
    EXCHANGE_SZSE = "SZSE"  # 深圳证券交易所
    EXCHANGE_BSE = "BSE"  # 北京证券交易所

    # 指数代码
    INDEX_HS300 = "000300.SH"  # 沪深300
    INDEX_SZ50 = "000016.SH"  # 上证50
    INDEX_ZZ500 = "000905.SH"  # 中证500
    INDEX_SZ = "000001.SH"  # 上证指数
    INDEX_SZSE = "399001.SZ"  # 深证成指
    INDEX_GEM = "399006.SZ"  # 创业板指
    INDEX_ZZ1000 = "000852.SH"  # 中证1000
    INDEX_ZZ2000 = "932000.SH"  # 中证2000

    # 主要指数字典 (代码 -> 名称)
    MAJOR_INDEXES = {
        "000001.SH": "上证综指",
        "399001.SZ": "深证成指",
        "399006.SZ": "创业板指",
        "000016.SH": "上证50",
        "000300.SH": "沪深300",
        "000905.SH": "中证500",
        "000852.SH": "中证1000",
        "932000.SH": "中证2000",
    }

    # 市场状态
    MARKET_STATUS_OPEN = "open"
    MARKET_STATUS_CLOSED = "closed"
    MARKET_STATUS_HALT = "halt"

    # 板块前缀 (兼容旧代码)
    BOARD_PREFIX = {
        "st": ["ST", "*ST"],  # ST股前缀
        "sci_tech": ["688", "689"],  # 科创板
        "gem": ["300", "301", "302"],  # 创业板
        "beijing": ["83", "87", "920"],  # 北交所 (不含新三板)
        "main": ["600", "601", "603", "605", "000", "001", "002"],  # 主板
    }

    # 涨跌停比例 (兼容旧代码) - 使用价格比例格式
    # 格式: (涨停价/前收盘价, 跌停价/前收盘价)
    LIMIT_RATIO = {
        "st": (1.05, 0.95),  # ST股 ±5%
        "sci_tech": (1.20, 0.80),  # 科创板 ±20%
        "gem": (1.20, 0.80),  # 创业板 ±20%
        "beijing": (1.30, 0.70),  # 北交所 ±30%
        "main": (1.10, 0.90),  # 主板 ±10%
    }

    # 价格容差 (兼容旧代码)
    PRICE_TOLERANCE = 0.001  # 价格比较容差 0.1%


class MarketCapThresholds:
    """市值分级阈值 (单位: 亿元)"""

    LARGE_CAP = 500  # 大盘股
    MID_CAP = 100  # 中盘股
    SMALL_CAP = 50  # 小盘股
    MICRO_CAP = 10  # 微盘股


class TimeWindows:
    """分析时间窗口常量"""

    SHORT_TERM = 20  # 短期 (1个月)
    MEDIUM_TERM = 60  # 中期 (3个月)
    LONG_TERM = 120  # 长期 (6个月)
    VERY_LONG_TERM = 252  # 超长期 (1年)

    # 计算窗口
    VOLATILITY_WINDOW = 20  # 波动率计算窗口
    TREND_WINDOW = 60  # 趋势计算窗口
    REGIME_WINDOW = 120  # 市场状态计算窗口
    MACRO_WINDOW = 252  # 宏观收益计算窗口


class MarketHours:
    """A股市场时间相关常量和方法"""

    # 交易时间 (北京时间)
    MORNING_START_HOUR = 9
    MORNING_START_MINUTE = 30
    MORNING_END_HOUR = 11
    MORNING_END_MINUTE = 30
    AFTERNOON_START_HOUR = 13
    AFTERNOON_START_MINUTE = 0
    AFTERNOON_END_HOUR = 15
    AFTERNOON_END_MINUTE = 0

    # 集合竞价时间 (北京时间)
    MORNING_AUCTION_START_HOUR = 9
    MORNING_AUCTION_START_MINUTE = 15
    MORNING_AUCTION_END_HOUR = 9
    MORNING_AUCTION_END_MINUTE = 25
    CLOSING_AUCTION_START_HOUR = 14
    CLOSING_AUCTION_START_MINUTE = 57
    CLOSING_AUCTION_END_HOUR = 15
    CLOSING_AUCTION_END_MINUTE = 0

    # 交易日 (周一到周五)
    TRADING_DAYS = [0, 1, 2, 3, 4]  # Monday=0, Friday=4

    # A股节假日 (非交易日)
    _CN_HOLIDAYS: Set[str] = {
        "2024-01-01",
        "2024-02-09", "2024-02-10", "2024-02-11", "2024-02-12",
        "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16", "2024-02-17",
        "2024-04-04", "2024-04-05", "2024-04-06",
        "2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-05",
        "2024-06-08", "2024-06-09", "2024-06-10",
        "2024-09-15", "2024-09-16", "2024-09-17",
        "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04",
        "2024-10-05", "2024-10-06", "2024-10-07",
        "2025-01-01",
        "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
        "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",
        "2025-04-04", "2025-04-05", "2025-04-06",
        "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
        "2025-05-31", "2025-06-01", "2025-06-02",
        "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04",
        "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
        "2026-01-01",
        "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
        "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
        "2026-04-04", "2026-04-05", "2026-04-06",
        "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
        "2026-06-19", "2026-06-20", "2026-06-21",
        "2026-09-26", "2026-09-27", "2026-09-28",
        "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
        "2026-10-05", "2026-10-06", "2026-10-07",
    }

    # 调休工作日 (周末但实际交易)
    _CN_SPECIAL_WORKDAYS: Set[str] = {
        "2024-02-04",
        "2024-02-18",
        "2024-04-07",
        "2024-09-29",
        "2024-10-12",
        "2025-01-26",
        "2025-02-08",
        "2025-09-28",
        "2025-10-11",
    }

    _holidays_loaded: bool = False

    @classmethod
    def _ensure_holidays_loaded(cls) -> None:
        if not cls._holidays_loaded:
            cls.refresh_holidays()
            cls._holidays_loaded = True

    @classmethod
    def refresh_holidays(cls, min_year: int = 2000, max_year: int = 2026) -> None:
        try:
            import akshare as ak

            trade_cal = ak.tool_trade_date_hist()
            cls._CN_HOLIDAYS.clear()
            cls._CN_SPECIAL_WORKDAYS.clear()
            for row in trade_cal.itertuples(index=False):
                date_str = str(row.trade_date)[:10]
                is_open = getattr(row, "open", getattr(row, "is_open", 1))
                if not is_open:
                    cls._CN_HOLIDAYS.add(date_str)
                else:
                    dt = datetime.date.fromisoformat(date_str)
                    if dt.weekday() >= 5:
                        cls._CN_SPECIAL_WORKDAYS.add(date_str)
            cls._CN_HOLIDAYS -= cls._CN_SPECIAL_WORKDAYS
            logger = get_logger(__name__)
            logger.info(f"刷新节假日日历: {len(cls._CN_HOLIDAYS)} 假日, {len(cls._CN_SPECIAL_WORKDAYS)} 调休")
        except Exception:
            logger = get_logger(__name__)
            logger.warning("刷新节假日日历失败", exc_info=True)

    @classmethod
    def is_market_open(cls, dt: Optional[datetime.datetime] = None) -> bool:
        """
        检查市场是否开放

        Args:
            dt: 要检查的日期时间 (None表示当前时间)

        Returns:
            bool: 市场是否开放
        """
        if dt is None:
            dt = get_time_provider().now()

        # 检查是否为交易日（考虑节假日和调休）
        if not cls.is_trading_day(dt.date() if isinstance(dt, datetime.datetime) else dt):
            return False

        # 检查时间是否在交易时段
        time = dt.time()

        # 上午时段: 9:30 - 11:30
        morning_start = datetime.time(cls.MORNING_START_HOUR, cls.MORNING_START_MINUTE)
        morning_end = datetime.time(cls.MORNING_END_HOUR, cls.MORNING_END_MINUTE)

        # 下午时段: 13:00 - 15:00
        afternoon_start = datetime.time(cls.AFTERNOON_START_HOUR, cls.AFTERNOON_START_MINUTE)
        afternoon_end = datetime.time(cls.AFTERNOON_END_HOUR, cls.AFTERNOON_END_MINUTE)

        in_morning = morning_start <= time <= morning_end
        in_afternoon = afternoon_start <= time <= afternoon_end

        return in_morning or in_afternoon

    @classmethod
    def get_next_open_time(cls, dt: Optional[datetime.datetime] = None) -> datetime.datetime:
        """
        获取下一个市场开放时间

        Args:
            dt: 起始日期时间 (None表示当前时间)

        Returns:
            datetime.datetime: 下一个市场开放时间
        """
        if dt is None:
            dt = get_time_provider().now()

        # 如果是交易日且还没到下午收盘，可能是当天
        if cls.is_trading_day(dt.date() if isinstance(dt, datetime.datetime) else dt):
            afternoon_end = datetime.time(cls.AFTERNOON_END_HOUR, cls.AFTERNOON_END_MINUTE)
            if dt.time() < afternoon_end:
                # 检查是否在交易时间之前
                morning_start = datetime.time(cls.MORNING_START_HOUR, cls.MORNING_START_MINUTE)
                if dt.time() < morning_start:
                    # 开盘前，返回当天开盘时间
                    return dt.replace(hour=cls.MORNING_START_HOUR, minute=cls.MORNING_START_MINUTE, second=0, microsecond=0)

                # 检查是否在午休时间
                morning_end = datetime.time(cls.MORNING_END_HOUR, cls.MORNING_END_MINUTE)
                afternoon_start = datetime.time(cls.AFTERNOON_START_HOUR, cls.AFTERNOON_START_MINUTE)
                if morning_end < dt.time() < afternoon_start:
                    # 午休时间，返回下午开盘时间
                    return dt.replace(hour=cls.AFTERNOON_START_HOUR, minute=cls.AFTERNOON_START_MINUTE, second=0, microsecond=0)

        # 找下一个交易日
        next_day = dt + datetime.timedelta(days=1)
        while not cls.is_trading_day(next_day):
            next_day += datetime.timedelta(days=1)

        return next_day.replace(hour=cls.MORNING_START_HOUR, minute=cls.MORNING_START_MINUTE, second=0, microsecond=0)

    @classmethod
    def get_market_status(cls, dt: Optional[datetime.datetime] = None) -> str:
        """
        获取市场状态描述

        Args:
            dt: 要检查的日期时间 (None表示当前时间)

        Returns:
            str: 市场状态描述
        """
        if dt is None:
            dt = get_time_provider().now()

        if cls.is_market_open(dt):
            return "交易中"

        if dt.weekday() not in cls.TRADING_DAYS:
            return "休市(周末)"

        time = dt.time()
        morning_start = datetime.time(cls.MORNING_START_HOUR, cls.MORNING_START_MINUTE)
        afternoon_end = datetime.time(cls.AFTERNOON_END_HOUR, cls.AFTERNOON_END_MINUTE)

        if time < morning_start:
            return "开盘前"
        elif time > afternoon_end:
            return "已收盘"
        else:
            return "午休"

    @classmethod
    def is_trading_day(cls, dt: Optional[datetime.date] = None) -> bool:
        """
        检查是否为交易日（考虑节假日和调休）

        Args:
            dt: 要检查的日期 (None表示今天)

        Returns:
            bool: 是否为交易日
        """
        cls._ensure_holidays_loaded()

        if dt is None:
            dt = get_time_provider().today()

        if isinstance(dt, datetime.datetime):
            dt = dt.date()

        iso = dt.isoformat()

        # 调休工作日优先：周末但实际交易
        if iso in cls._CN_SPECIAL_WORKDAYS:
            return True

        # 周末不交易
        if dt.weekday() >= 5:
            return False

        # 节假日不交易
        return iso not in cls._CN_HOLIDAYS

    @classmethod
    def is_call_auction(cls, dt: Optional[datetime.datetime] = None,
                        exchange: Optional[str] = None) -> bool:
        """
        Check if currently in call auction period.

        SH exchange: morning auction 9:15-9:25, closing auction at 15:00
        SZ exchange: morning auction 9:15-9:25, closing auction 14:57-15:00
        BJ exchange: same as SZ

        Args:
            dt: 要检查的日期时间 (None表示当前时间)
            exchange: 交易所代码 (SH/SZ/BJ, None默认SZ)

        Returns:
            bool: 是否在集合竞价时段
        """
        if dt is None:
            dt = get_time_provider().now()

        if not cls.is_trading_day(dt):
            return False

        t = dt.time()

        # 早盘集合竞价: 9:15-9:25 (all exchanges)
        morning_auction_start = datetime.time(
            cls.MORNING_AUCTION_START_HOUR, cls.MORNING_AUCTION_START_MINUTE
        )
        morning_auction_end = datetime.time(
            cls.MORNING_AUCTION_END_HOUR, cls.MORNING_AUCTION_END_MINUTE
        )
        if morning_auction_start <= t <= morning_auction_end:
            return True

        # 收盘集合竞价 differs by exchange
        if exchange == "SH":
            # SH: closing call auction at 15:00 (one-time match)
            closing_end = datetime.time(15, 0)
            closing_start = datetime.time(14, 57)
        else:
            # SZ/BJ: 14:57-15:00
            closing_end = datetime.time(15, 0)
            closing_start = datetime.time(14, 57)

        return closing_start <= t <= closing_end


MAJOR_INDEXES: dict = {
    "000001.SH": "上证综指",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000016.SH": "上证50",
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "932000.SH": "中证2000",
}
