"""市场相关常量"""

import datetime
from typing import Optional


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
        "sci_tech": ["688"],  # 科创板
        "gem": ["300", "301"],  # 创业板
        "beijing": ["8", "4"],  # 北交所/新三板
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

    LARGE_CAP = 1000  # 大盘股
    MID_CAP = 300  # 中盘股
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

    # 交易日 (周一到周五)
    TRADING_DAYS = [0, 1, 2, 3, 4]  # Monday=0, Friday=4

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
            dt = datetime.datetime.now()

        # 检查是否是工作日
        if dt.weekday() not in cls.TRADING_DAYS:
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
            dt = datetime.datetime.now()

        # 如果是交易日且还没到下午收盘，可能是当天
        if dt.weekday() in cls.TRADING_DAYS:
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
        while next_day.weekday() not in cls.TRADING_DAYS:
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
            dt = datetime.datetime.now()

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
