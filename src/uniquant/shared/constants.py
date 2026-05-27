"""共享常量定义

该模块包含系统中使用的所有常量定义，按功能模块分组。
"""

import datetime
from enum import Enum
from typing import Optional

# ============================================================================
# Numba JIT 优化开关
# ============================================================================
ENABLE_NUMBA_JIT = True
REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]
M_BOUNDS = (0.1, 0.9)
W_BOUNDS = (6.0, 13.0)
RANDOM_SEED = 42
TRUE_RANGE_COLUMN = "true_range"
OUTPUT_DIR = "hands/reports"
ENABLE_JOBLIB_PARALLEL = True


class WindowConfig:
    """LPPL窗口配置"""
    all_windows = [100, 150, 200, 250, 300, 400, 500, 600, 750]

    SHORT_MAX = 200
    MEDIUM_MAX = 400

    @classmethod
    def get_category(cls, window: int) -> str:
        if window <= cls.SHORT_MAX:
            return "short"
        elif window <= cls.MEDIUM_MAX:
            return "medium"
        return "long"


WINDOW_CONFIG = WindowConfig()


# ============================================================================
# 日期相关常量
# ============================================================================
class DateConstants:
    """日期相关常量"""
    DEFAULT_START_DATE = "2000-01-01"
    DEFAULT_START_DATE_COMPACT = "20000101"
    FORMAT_DASH = "%Y-%m-%d"
    FORMAT_COMPACT = "%Y%m%d"
    FORMAT_DATETIME = "%Y-%m-%d %H:%M:%S"


# ============================================================================
# 市场相关常量
# ============================================================================
class AnalysisServiceConstants:
    """分析服务相关常量"""
    MEMORY_CACHE_MAX_SIZE = 1000
    DEFAULT_VAR_95 = 0.05
    DEFAULT_VAR_99 = 0.08
    DEFAULT_CVAR_95 = 0.07
    DEFAULT_CVAR_99 = 0.10
    DEFAULT_MAX_DRAWDOWN = 0.15
    RANDOM_DATA_STD = 0.02
    RANDOM_DATA_LENGTH = 252
    CACHE_TTL_1HOUR = 3600
    CACHE_TTL_2HOURS = 7200
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0
    MAX_WAIT_TIME = 10.0
    DEFAULT_ETF_LIST = ["510300.SH"]
    SAMPLE_MAX_ROWS_DEFAULT = 5000
    MIN_SAMPLE_INTERVAL_RATIO = 0.01
    CHUNK_SIZE = 1000
    SAMPLE_MAX_ROWS_LPPL = 1000
    SAMPLE_MAX_ROWS_CZSC = 2000
    RECENT_HIGH_LOW_WINDOW = 20
    MA_WINDOW_SHORT = 5
    MA_WINDOW_MEDIUM = 20
    MA_WINDOW_LONG = 60
    TREND_STRONG_UP_THRESHOLD = 1.05
    TREND_STRONG_DOWN_THRESHOLD = 0.95
    SAMPLE_MAX_ROWS_FSM = 1000
    STOP_LOSS_RATIO = 0.95
    TAKE_PROFIT_RATIO = 1.10
    SIGNAL_STRENGTH_SCALE = 100.0
    SIGNAL_BUY = "buy"
    SIGNAL_SELL = "sell"
    RECOMMENDATION_MAP = {"buy": "买入", "sell": "卖出"}

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


# ============================================================================
# 市值阈值
# ============================================================================
class MarketCapThresholds:
    """市值分级阈值 (单位: 亿元)"""

    LARGE_CAP = 1000  # 大盘股
    MID_CAP = 300  # 中盘股
    SMALL_CAP = 50  # 小盘股
    MICRO_CAP = 10  # 微盘股


# ============================================================================
# 时间窗口常量
# ============================================================================
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


# ============================================================================
# 指标阈值
# ============================================================================
class IndicatorThresholds:
    """技术指标阈值"""

    # RSI阈值
    RSI_OVERBOUGHT = 70
    RSI_OVERSOLD = 30
    RSI_MID = 50

    # MACD阈值
    MACD_SIGNAL_THRESHOLD = 0.0

    # 布林带阈值
    BOLLINGER_UPPER = 2.0
    BOLLINGER_LOWER = -2.0

    # 移动平均线周期
    MA_SHORT = 5
    MA_MEDIUM = 20
    MA_LONG = 60

    # ATR周期 (兼容旧代码)
    ATR_PERIOD = 14
    DEFAULT_ATR_PERIOD = 14

    # 其他指标周期
    RSI_PERIOD = 14
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    BBANDS_PERIOD = 20
    BBANDS_STDDEV = 2.0
    BOLLINGER_PERIOD = 20  # 布林带周期 (兼容旧代码)

    # 滚动计算配置 (兼容旧代码)
    ROLLING_MIN_PERIODS_RATIO = 0.5  # 滚动最小周期比例
    ROLLING_MIN_PERIODS_MIN = 5  # 滚动最小周期最小值

    # 市场状态相关 (兼容旧代码)
    ENTROPY_WINDOW = 60  # 熵值计算窗口
    TURNOVER_Z_PERIOD = 20  # 成交量Z-Score计算周期
    VOLUME_MA_PERIOD = 20  # 成交量MA周期

    # FSM相关阈值 (兼容旧代码)
    FSM_MA_SHORT = 5  # FSM短期MA周期
    FSM_MA_LONG = 20  # FSM长期MA周期
    FSM_PULLBACK_UPPER = 1.05  # 回调上限
    FSM_PULLBACK_LOWER = 0.95  # 回调下限
    FSM_SCORE_CZSC = 20  # CZSC信号分数
    FSM_SCORE_TREND = 15  # 趋势分数
    FSM_SCORE_ALPHA = 10  # Alpha分数
    FSM_SCORE_NTF = 10  # NTF分数
    FSM_ALPHA_THRESHOLD = 0.6  # Alpha阈值
    FSM_SCORE_THRESHOLD_IDLE_TO_SIGNAL = 30  # IDLE到SIGNAL阈值
    FSM_SCORE_THRESHOLD_SIGNAL_TO_MONITOR = 50  # SIGNAL到MONITOR阈值
    FSM_SCORE_THRESHOLD_TO_EXIT = 20  # 退出阈值
    FSM_SCORE_THRESHOLD_TO_PYRAMID = 70  # 加仓阈值
    FSM_SCORE_THRESHOLD_EXIT = 10  # 退出阈值
    FSM_RISK_SCALER_CRITICAL = 2.0  # 风险缩放因子


# ============================================================================
# 风险阈值
# ============================================================================
class RiskThresholds:
    """风险控制阈值"""

    # VaR阈值
    VAR_DAILY_LIMIT = 0.02  # 日VaR限制 2%
    VAR_CONFIDENCE = 0.95  # VaR置信度

    # 回撤阈值
    MAX_DRAWDOWN_LIMIT = 0.15  # 最大回撤限制 15%

    # 仓位限制
    MAX_POSITION_PCT = 0.95  # 最大仓位 95%
    MIN_POSITION_PCT = 0.0  # 最小仓位 0%

    # 波动率限制
    VOLATILITY_LIMIT = 0.3  # 波动率限制 30%


# ============================================================================
# 风险计算常量 (兼容旧代码)
# ============================================================================
class RiskCalculationConstants:
    """风险计算相关常量"""

    # VaR阈值
    VAR_THRESHOLD_HIGH = 0.05  # 高VaR阈值 5%
    VAR_THRESHOLD_MEDIUM = 0.03  # 中VaR阈值 3%
    VAR_THRESHOLD_LOW = 0.01  # 低VaR阈值 1%

    # CVaR阈值
    CVAR_THRESHOLD_HIGH = 0.06  # 高CVaR阈值 6%
    CVAR_THRESHOLD_MEDIUM = 0.04  # 中CVaR阈值 4%
    CVAR_THRESHOLD_LOW = 0.02  # 低CVaR阈值 2%

    # 波动率阈值
    VOLATILITY_HIGH = 0.3  # 高波动率 30%
    VOLATILITY_MEDIUM = 0.2  # 中波动率 20%
    VOLATILITY_LOW = 0.1  # 低波动率 10%

    # 夏普比率阈值
    SHARPE_RATIO_BULL = 1.0  # 牛市夏普比率
    SHARPE_RATIO_BEAR = 0.0  # 熊市夏普比率

    # 最大回撤阈值
    MAX_DRAWDOWN_THRESHOLD = 0.2  # 最大回撤阈值 20%

    # 压力测试场景
    CRASH_SCENARIOS = {
        "market_crash_2008": -0.5,
        "market_crash_2015": -0.4,
        "flash_crash_2010": -0.1,
        "circuit_breaker_2020": -0.07,
        "financial_crisis_2008": -0.5,
    }

    RATE_HIKE_SCENARIOS = {
        "rate_hike_25bp": -0.02,
        "rate_hike_50bp": -0.05,
        "rate_hike_100bp": -0.1,
    }

    RECESSION_SCENARIOS = {
        "mild_recession": -0.15,
        "moderate_recession": -0.25,
        "severe_recession": -0.4,
    }


# ============================================================================
# 数据验证常量
# ============================================================================
class DataValidationConstants:
    """数据验证相关常量"""

    # 价格限制
    MIN_PRICE = 0.01  # 最小价格
    MAX_PRICE = 10000.0  # 最大价格

    # 成交量限制
    MIN_VOLUME = 0  # 最小成交量
    MAX_VOLUME = 1e12  # 最大成交量

    # 涨跌幅限制
    MAX_DAILY_CHANGE = 0.2  # 最大日涨跌幅 20% (科创板/创业板)
    MAX_DAILY_CHANGE_ST = 0.05  # ST股最大日涨跌幅 5%

    # 数据完整性
    MIN_DATA_POINTS = 30  # 最小数据点数
    MAX_MISSING_RATIO = 0.1  # 最大缺失值比例


# ============================================================================
# 精度常量
# ============================================================================
class PrecisionConstants:
    """精度和误差控制常量"""
    
    PRICE_DECIMALS = 2       # 价格保留2位小数
    RATE_DECIMALS = 4        # 收益率保留4位小数
    PCT_DECIMALS = 4         # 百分比保留4位小数
    VOLUME_DECIMALS = 0      # 成交量保留整数
    AMOUNT_DECIMALS = 2      # 成交额保留2位小数
    WEIGHT_DECIMALS = 4      # 权重保留4位小数
    FLOAT_TOLERANCE = 1e-6   # 浮点数比较容差比较精度


# ============================================================================
# 性能常量
# ============================================================================
class PerformanceConstants:
    """性能优化相关常量"""

    # 缓存配置
    DEFAULT_CACHE_TTL = 300  # 默认缓存时间 5分钟
    CACHE_TTL_SECONDS = 3600 # 缓存过期时间(秒)
    MAX_CACHE_SIZE = 1000  # 最大缓存条目数
    CACHE_MAX_SIZE = 5000  # 缓存最大大小 (兼容旧代码)

    # 批量处理
    BATCH_SIZE = 100  # 批量处理大小
    MAX_WORKERS = 4  # 最大工作线程数

    # 超时配置
    DEFAULT_TIMEOUT = 30  # 默认超时 30秒
    MAX_TIMEOUT = 300  # 最大超时 5分钟


# ============================================================================
# 网络常量
# ============================================================================
class NetworkConstants:
    """网络相关常量"""

    # 超时配置
    DEFAULT_TIMEOUT = 30  # 默认超时 30秒
    CONNECT_TIMEOUT = 10  # 连接超时 10秒
    READ_TIMEOUT = 30  # 读取超时 30秒
    SHORT_TIMEOUT = 10    # 短超时 10秒
    MEDIUM_TIMEOUT = 15   # 中超时 15秒
    LONG_TIMEOUT = 60     # 长超时 60秒
    SOCKET_TIMEOUT = 10   # Socket超时 10秒

    # 重试配置
    MAX_RETRIES = 3  # 最大重试次数
    RETRY_DELAY = 1.0  # 重试延迟(秒)
    RETRY_BACKOFF = 2.0  # 重试退避因子
    RETRY_DELAY_BASE = 2.0 # 重试基础延迟
    RETRY_JITTER_MIN = 0.5 # 最小抖动
    RETRY_JITTER_MAX = 1.5 # 最大抖动

    # 请求配置
    MAX_REDIRECTS = 5  # 最大重定向次数
    MAX_KEEPALIVE_CONNECTIONS = 20  # 最大保持连接数
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    # API 配置
    SINA_API_CONFIG = {
        "kline_url": "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
        "headers": {"Referer": "http://finance.sina.com.cn"},
        "random_sleep_min": 1.5,
        "random_sleep_max": 3.0,
        "timeout": 15
    }

    # HTTP状态码
    HTTP_OK = 200
    HTTP_NOT_FOUND = 404
    HTTP_RATE_LIMIT = 429
    HTTP_SERVER_ERROR = 500


# ============================================================================
# 缓存常量
# ============================================================================
class CacheConstants:
    """缓存相关常量"""

    # 默认配置
    DEFAULT_TTL = 300  # 默认缓存时间 5分钟
    DEFAULT_MAX_SIZE = 1000  # 默认最大缓存条目数
    DEFAULT_MAX_CACHE_SIZE = 1000  # 默认最大缓存条目数
    MAX_CACHE_AGE = 604800  # 默认最大缓存寿命 7天

    # 缓存类型
    CACHE_TYPE_MEMORY = "memory"
    CACHE_TYPE_DISK = "disk"
    CACHE_TYPE_REDIS = "redis"

    # 缓存策略
    POLICY_LRU = "lru"
    POLICY_LFU = "lfu"
    POLICY_FIFO = "fifo"

    # 特殊TTL值
    TTL_NO_EXPIRE = 0  # 永不过期
    TTL_FOREVER = -1  # 永久缓存

    # 数据服务TTL (兼容旧代码)
    CACHE_TTL_STOCK = 3600  # 股票数据 1小时
    CACHE_TTL_INDEX = 7200  # 指数数据 2小时
    CACHE_TTL_ETF = 3600  # ETF数据 1小时
    CACHE_TTL_REALTIME = 300  # 实时数据 5分钟
    CACHE_TTL_INDUSTRY = 86400  # 行业数据 1天
    CACHE_TTL_CONCEPT = 86400  # 概念数据 1天
    CACHE_TTL_GENERAL = 3600  # 通用数据 1小时

    # 其他TTL常量 (兼容旧代码)
    CACHE_TTL_DAILY = 86400  # 日线数据 1天
    CACHE_TTL_MINUTE = 300  # 分钟线数据 5分钟
    CACHE_TTL_WEEKLY = 604800  # 周线数据 1周
    CACHE_TTL_MONTHLY = 2592000  # 月线数据 30天


# ============================================================================
# 路径常量
# ============================================================================
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

class PathConstants:
    """路径相关常量"""

    DATA_DIR = PROJECT_ROOT / "data"
    RAW_DIR = PROJECT_ROOT / "data" / "raw"
    CLEAN_DIR = PROJECT_ROOT / "data" / "clean"
    LAKE_DIR = PROJECT_ROOT / "data" / "lake"
    REPORT_DIR = PROJECT_ROOT / "data" / "reports"
    LOG_DIR = PROJECT_ROOT / "logs"

    FILE_SUFFIX_CSV = ".csv"
    FILE_SUFFIX_PARQUET = ".parquet"
    FILE_SUFFIX_JSON = ".json"
    FILE_SUFFIX_LOG = ".log"

    CONFIG_FILE = "config.yaml"
    STOCK_LIST_FILE = PROJECT_ROOT / "data" / "stock_list.json"

    CSV_SUFFIX = ".csv"
    PARQUET_SUFFIX = ".parquet"
    JSON_SUFFIX = ".json"
    LOG_SUFFIX = ".log"


TDX_DIR = PROJECT_ROOT / "tdx"
DATA_DIR = PROJECT_ROOT / "data"
LAKE_QUOTES_DIR = PROJECT_ROOT / "data" / "lake" / "quotes"
LAKE_FINANCIAL_DIR = PROJECT_ROOT / "data" / "lake" / "financial"
LAKE_INDEX_DIR = PROJECT_ROOT / "data" / "lake" / "index"
STOCK_LIST_FILE = PROJECT_ROOT / "data" / "all_stock_codes.csv"
PARQUET_COMPRESSION = "snappy"

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


# ============================================================================
# 数据源常量
# ============================================================================
class DataSourceConstants:
    """数据源相关常量"""

    # 重试配置
    MAX_RETRIES = 3  # 最大重试次数
    RETRY_DELAY = 1.0  # 重试延迟(秒)
    RETRY_BACKOFF = 2.0  # 重试退避因子
    MIN_REQUEST_INTERVAL = 3  # 最小请求间隔(秒)

    # 数据验证
    MIN_DATA_POINTS = 30  # 最小数据点数
    MAX_MISSING_RATIO = 0.1  # 最大缺失值比例

    # 列名映射
    DATE_COLS = ["日期", "date", "trade_date", "交易日期", "时间", "time", "dividOperateDate"]
    OPEN_COLS = ["开盘", "open", "开盘价"]
    CLOSE_COLS = ["收盘", "close", "收盘价", "price"]
    HIGH_COLS = ["最高", "high", "最高价"]
    LOW_COLS = ["最低", "low", "最低价"]
    VOLUME_COLS = ["成交量", "volume", "vol", "trading_volume"]
    AMOUNT_COLS = ["成交额", "amount", "turnover", "trading_amount"]

    # 涨跌幅字段别名
    CHANGE_RATE_COLS = ["pct_change", "pctChg", "涨跌幅", "change_rate", "change_pct"]
    CHANGE_AMOUNT_COLS = ["涨跌额", "price_change", "change_amount"]

    # 前收盘价字段别名
    PRECLOSE_COLS = ["preclose", "pre_close", "prev_close", "前收盘", "昨收"]

    # 复权因子字段别名
    QFQ_FACTOR_COLS = ["qfq_factor", "foreAdjustFactor", "前复权因子"]
    HFQ_FACTOR_COLS = ["hfq_factor", "backAdjustFactor", "后复权因子"]
    ADJ_FACTOR_COLS = ["adj_factor", "adjustFactor", "复权因子"]

    # 元数据字段别名
    SECTOR_COLS = ["sector", "板块", "industry"]
    IPO_DATE_COLS = ["ipoDate", "ipo_date", "上市日期"]
    DELIST_DATE_COLS = ["outDate", "delist_date", "退市日期"]
    STOCK_TYPE_COLS = ["type", "stock_type", "证券类型"]
    STOCK_STATUS_COLS = ["status", "stock_status", "上市状态"]
    VOL_UNIT_COLS = ["volunit", "vol_unit", "交易单位"]
    DECIMAL_POINT_COLS = ["decimal_point", "小数位", "price_decimals"]

    # 股票名称字段别名
    NAME_COLS = ["name", "code_name", "股票名称", "名称"]

    # 单位转换常量
    VOLUME_UNITS = {
        "eastmoney": 100,  # 手 -> 股
        "tencent": 1,  # 股 -> 股
        "sina": 1,  # 股 -> 股
        "ths": 1,  # 股 -> 股
        "baostock": 1,  # 股 -> 股
        "stock": 10000,  # 万股 -> 股
    }

    AMOUNT_UNITS = {
        "eastmoney": 1,  # 元 -> 元
        "tencent": 1,  # 元 -> 元
        "sina": 1,  # 元 -> 元
        "ths": 1,  # 元 -> 元
        "baostock": 1,  # 元 -> 元
        "stock": 10000,  # 万元 -> 元
    }

    # 股票代码前缀
    INDEX_PREFIXES = ["000", "399", "880"]  # 指数代码前缀 (含中证)
    SH_PREFIXES = ["6", "5"]  # 上海股票前缀
    SZ_PREFIXES = ["0", "3"]  # 深圳股票前缀

    # 请求控制
    SINA_MIN_REQUEST_INTERVAL = 2  # 新浪数据源最小请求间隔(秒)
    SINA_MAX_RETRIES = 5  # 新浪数据源最大重试次数


class THSConstants:
    """同花顺数据源常量"""

    TIMEOUT = NetworkConstants.LONG_TIMEOUT

    # 历史页使用股票代码占位，解析由 ths.py 内部完成
    HISTORICAL_URL = "https://stockpage.10jqka.com.cn/{symbol}/"

    # 依次尝试多个实时页入口，避免单一地址失效
    REALTIME_API_URLS = [
        "https://stockpage.10jqka.com.cn/{symbol}/",
        "https://basic.10jqka.com.cn/{symbol}/",
    ]


# ============================================================================
# 数据湖相关常量
# ============================================================================
class DataLakeConstants:
    """数据湖相关常量"""

    # 目录路径
    DEFAULT_ROOT_PATH = "data/lake"  # 默认根目录路径
    QUARANTINE_PATH = "data/quarantine"  # 隔离区目录路径

    # 缓存配置
    DEFAULT_CACHE_SIZE = 100  # 默认缓存大小

    # 默认值
    DEFAULT_MARKET = "cn"  # 默认市场
    DEFAULT_DATA_TYPE = "stock"  # 默认数据类型

    # 批量处理
    MAX_WORKERS = 4  # 最大工作线程数


# ============================================================================
# UI 相关常量
# ============================================================================
class UIConstants:
    """UI 显示相关常量"""

    DASHBOARD_PORT = 8504
    DEFAULT_THEME = "dark"
    REFRESH_INTERVAL_MS = 10000  # 10秒
    MAX_DISPLAY_ROWS = 50
    CHART_HEIGHT = 600
    SIDEBAR_WIDTH = 300
    SUCCESS_COLOR = "#00C781"
    WARNING_COLOR = "#FF9D00"
    DANGER_COLOR = "#FF4B4B"
    INFO_COLOR = "#00A2FF"


# ============================================================================
# 测试相关常量
# ============================================================================
class TestConstants:
    """测试相关常量"""

    # 测试配置
    DEFAULT_TEST_DAYS = 365  # 默认测试天数
    DEFAULT_TEST_COUNT = 3  # 默认测试次数
    DEFAULT_TEST_THRESHOLD = 0.85  # 默认测试阈值
    DEFAULT_TEST_LOWER_THRESHOLD = 0.75  # 默认测试下限阈值

    # 风险测试参数
    RISK_TEST_CONFIDENCE = 0.95  # 风险测试置信水平
    RISK_TEST_PCT = 0.05  # 风险测试百分比
    RISK_TEST_VALUE = 100000.0  # 风险测试基础值
    RISK_TEST_PERCENTILE = 95.0  # 风险测试百分位

    # 服务测试参数
    SERVICE_TEST_DAYS = 120  # 服务测试天数
    SERVICE_TEST_START = 101  # 服务测试起始值
    SERVICE_TEST_END = 121  # 服务测试结束值
    SERVICE_TEST_INTERVAL = 30  # 服务测试间隔

    # 分析测试参数
    ANALYSIS_TEST_THRESHOLD = 0.3  # 分析测试阈值
    ANALYSIS_TEST_BASE = 1000000  # 分析测试基础值
    ANALYSIS_TEST_PCT = 0.02  # 分析测试百分比

    # 重试测试参数
    RETRY_TEST_COUNT = 3  # 重试测试次数
    RETRY_TEST_DELAY = 0.1  # 重试测试延迟(秒)
    RETRY_TEST_BACKOFF = 0.2  # 重试测试退避因子

    # 误差测试参数
    ERROR_TEST_THRESHOLD = 0.1  # 误差测试阈值
    ERROR_TEST_COUNT = 4  # 误差测试计数

    # 市场测试参数
    MARKET_TEST_THRESHOLD = 0.5  # 市场测试阈值
    MARKET_TEST_DAYS = 6  # 市场测试天数

    # 测试分析参数
    TEST_ANALYSIS_THRESHOLD = 0.3  # 测试分析阈值
    TEST_ANALYSIS_BASE = 1000000  # 测试分析基础值
    TEST_ANALYSIS_PCT = 0.02  # 测试分析百分比

    # 测试风险参数
    TEST_RISK_PCT = 0.05  # 测试风险百分比
    TEST_RISK_VALUE = 100000.0  # 测试风险值
    TEST_RISK_CONFIDENCE = 0.95  # 测试风险置信水平
    TEST_RISK_PERCENTILE = 95.0  # 测试风险百分位

    # 测试服务参数
    TEST_SERVICE_DAYS = 120  # 测试服务天数
    TEST_SERVICE_START = 101  # 测试服务起始值
    TEST_SERVICE_END = 121  # 测试服务结束值
    TEST_SERVICE_INTERVAL = 30  # 服务测试间隔

    # 测试重试参数
    TEST_RETRY_COUNT = 3  # 测试重试次数
    TEST_RETRY_DELAY = 0.1  # 测试重试延迟(秒)
    TEST_RETRY_BACKOFF = 0.2  # 测试重试退避因子

    # 测试误差参数
    TEST_ERROR_THRESHOLD = 0.1  # 测试误差阈值
    TEST_ERROR_COUNT = 4  # 测试误差计数

    # 测试市场参数
    TEST_MARKET_THRESHOLD = 0.5  # 测试市场阈值
    TEST_MARKET_DAYS = 6  # 测试市场天数

    # 测试缓存参数
    TEST_CACHE_TTL = 3600  # 测试缓存过期时间(秒)

    # 测试数据参数
    TEST_DATA_COUNT = 5  # 测试数据计数
    TEST_DATA_THRESHOLD = 0.85  # 测试数据阈值
    TEST_DATA_LOWER_THRESHOLD = 0.75  # 测试数据下限阈值

    # 测试执行参数
    TEST_EXECUTION_TIMEOUT = 300  # 测试执行超时时间(秒)
    TEST_EXECUTION_INTERVAL = 5  # 测试执行间隔(秒)

    # 测试结果参数
    TEST_RESULT_PASS_THRESHOLD = 0.8  # 测试结果通过阈值
    TEST_RESULT_WARNING_THRESHOLD = 0.6  # 测试结果警告阈值
    TEST_RESULT_FAIL_THRESHOLD = 0.4  # 测试结果失败阈值

    # 测试数据参数
    TEST_DATA_START_VALUE = 100  # 测试数据起始值
    TEST_DATA_END_VALUE = 120  # 测试数据结束值
    TEST_DATA_START_VALUE_LARGE = 1000  # 测试数据起始值(大)
    TEST_DATA_END_VALUE_LARGE = 1200  # 测试数据结束值(大)
    TEST_DATA_VOLUME_START = 1000  # 测试成交量起始值
    TEST_DATA_VOLUME_END = 2000  # 测试成交量结束值
    TEST_DATA_VOLUME_START_LARGE = 10000  # 测试成交量起始值(大)
    TEST_DATA_VOLUME_END_LARGE = 20000  # 测试成交量结束值(大)
    TEST_DATA_OFFSET = 1  # 测试数据偏移量
    TEST_DATA_OFFSET_LARGE = 10  # 测试数据偏移量(大)


# ============================================================================
# 工具相关常量
# ============================================================================
class ToolConstants:
    """工具相关常量"""

    # 分析配置
    ANALYSIS_MAX_WORKERS = 5  # 分析最大工作线程数
    ANALYSIS_TIMEOUT = 300  # 分析超时时间(秒)

    # 代码质量阈值
    CODE_QUALITY_MAX_LINES = 50  # 代码质量最大行数
    CODE_QUALITY_MAX_METHODS = 20  # 代码质量最大方法数
    CODE_QUALITY_MAX_ATTRIBUTES = 15  # 代码质量最大属性数
    CODE_QUALITY_MAX_IMPORTS = 20  # 代码质量最大导入数
    CODE_QUALITY_MAX_NESTING = 4  # 代码质量最大嵌套深度

    # 架构检查参数
    ARCHITECTURE_CHECK_LEVEL_1 = 3  # 架构检查级别1
    ARCHITECTURE_CHECK_LEVEL_2 = 4  # 架构检查级别2
    ARCHITECTURE_CHECK_LEVEL_3 = 5  # 架构检查级别3

    # 样式检查参数
    STYLE_CHECK_MAX_LINE_LENGTH = 500  # 样式检查最大行长度
    STYLE_CHECK_INDENT_THRESHOLD = 0.1  # 样式检查缩进阈值

    # 报告配置
    REPORT_LINE_LENGTH = 60  # 报告行长度

    # 分析配置
    ANALYSIS_MAX_ITEMS = 5  # 分析结果最大显示项数
    CODE_ANALYSIS_MIN_LINE_LENGTH = 20  # 代码分析最小行长度
    CODE_ANALYSIS_MAX_DISPLAY_LENGTH = 50  # 代码分析最大显示长度
    CODE_ANALYSIS_MAX_DUPLICATES = 5  # 代码分析最大重复项数


# ============================================================================
# 数据服务相关常量
# ============================================================================
class DataServiceConstants:
    """数据服务相关常量"""

    # 缓存过期时间（秒）
    CACHE_TTL_STOCK = 3600  # 股票数据 1小时
    CACHE_TTL_INDEX = 7200  # 指数数据 2小时
    CACHE_TTL_ETF = 3600  # ETF数据 1小时
    CACHE_TTL_REALTIME = 300  # 实时数据 5分钟
    CACHE_TTL_INDUSTRY = 86400  # 行业数据 1天
    CACHE_TTL_CONCEPT = 86400  # 概念数据 1天
    CACHE_TTL_GENERAL = 3600  # 通用数据 1小时

    # 数据质量评分阈值
    QUALITY_SCORE_EXCELLENT = 90  # 优秀
    QUALITY_SCORE_GOOD = 75  # 良好
    QUALITY_SCORE_FAIR = 60  # 一般

    # 时效性得分
    TIMELINESS_SCORE_TODAY = 1.0  # 今天
    TIMELINESS_SCORE_1_DAY = 0.9  # 1天内
    TIMELINESS_SCORE_3_DAYS = 0.7  # 3天内
    TIMELINESS_SCORE_7_DAYS = 0.5  # 7天内
    TIMELINESS_SCORE_30_DAYS = 0.3  # 30天内
    TIMELINESS_SCORE_OLD = 0.1  # 超过30天

    # 时效性天数阈值
    TIMELINESS_THRESHOLD_1_DAY = 1
    TIMELINESS_THRESHOLD_3_DAYS = 3
    TIMELINESS_THRESHOLD_7_DAYS = 7
    TIMELINESS_THRESHOLD_30_DAYS = 30


# ============================================================================
# NTF相关常量
# ============================================================================
class NTFConstants:
    """NTF引擎相关常量"""

    # 偏离度阈值
    HEAT_THRESHOLD = 0.8  # 分位数高于80%视为过热
    PANIC_THRESHOLD = 0.1  # 分位数低于10%视为恐慌

    # 成交量脉冲阈值
    VOLUME_RATIO_THRESHOLD = 2.0  # 成交量脉冲阈值

    # 计算窗口
    WINDOW = 20  # 计算成交量均值的窗口大小

    # 置信度阈值
    CONFIDENCE_SUPPORT = 0.85  # 支撑信号的置信度
    CONFIDENCE_RESISTANCE = 0.80  # 阻力信号的置信度
    CONFIDENCE_LIQUIDITY = 0.40  # 流动性脉冲的置信度


# ============================================================================
# LPPL相关常量
# ============================================================================
class LPPLConstants:
    """LPPL 泡沫检测相关常量"""
    # 优化器配置
    MAX_ITER = 500
    POP_SIZE = 10
    TOLERANCE = 0.01
    MUTATION_MIN = 0.5
    MUTATION_MAX = 1.0
    RECOMBINATION = 0.7
    SEED = 42
    WORKERS = 1

    # RMSE 阈值配置
    RMSE_REJECT_THRESHOLD = 0.1

    # 数据配置
    MIN_DATA_POINTS = 60
    TC_SEARCH_RANGE = 50
    TC_FUTURE_RANGE = 100

    # 参数边界配置
    TC_BACKWARD = 50
    TC_FORWARD = 100
    A_MULTIPLIER = 1.1
    B_MIN = -20
    B_MAX = 20
    C_MIN = -20
    C_MAX = 20
    PHI_MAX = 6.283185307179586

    # Sornette约束配置
    M_MIN = 0.1
    M_MAX = 0.9
    W_MIN = 6
    W_MAX = 13
    C_MIN_ABS = 0.01
    C_ABS_FOR_BUBBLE = 0.1

    # 置信度计算配置
    TC_WEIGHT = 0.4
    COST_WEIGHT = 0.4
    DATA_WEIGHT = 0.2
    DATA_REFERENCE = 200
    COST_SCALE = 0.1

    # 置信度阈值
    CONFIDENCE_THRESHOLD = 0.6
    CONFIDENCE_WARNING = 0.4

    # 风险等级阈值
    DANGER_DAYS = 10
    WARNING_DAYS = 20

    # 性能配置
    CACHE_ENABLED = True
    CACHE_PRECISION = 4
    EPSILON = 1e-10

    # 窗口配置
    WINDOWS_ALL = [100, 150, 200, 250, 300, 400, 500, 600, 750]
    WINDOWS_LIST = [200, 400, 600]

    # 回退默认值
    DATA_LENGTH_LARGE = 600
    TC_DAYS_DEFAULT_LARGE = 150
    DATA_LENGTH_MEDIUM = 300
    TC_DAYS_DEFAULT_MEDIUM = 80
    TC_DAYS_DEFAULT_SMALL = 40


# ============================================================================
# 市场状态相关常量
# ============================================================================
class RegimeConstants:
    """市场状态检测器相关常量"""

    # 熵值阈值
    ENTROPY_PERCENTILE_THRESHOLD = 0.1  # 熵值分位数阈值，低于此值视为FROZEN状态

    # 成交量Z-Score阈值
    TURNOVER_Z_SCORE_THRESHOLD = 2.5  # 成交量Z-Score阈值，绝对值超过此值视为STRESSED状态

    # 数据要求
    MIN_DATA_POINTS = 30  # 最小数据点数

    # 计算窗口
    ENTROPY_WINDOW = 60  # 熵值计算窗口
    TURNOVER_Z_PERIOD = 20  # 成交量Z-Score计算周期


# ============================================================================
# UAT 相关常量
# ============================================================================
class UATConstants:
    """UAT 测试相关常量"""

    # 测试配置
    UAT_TEST_DAYS = 365  # UAT 测试天数
    UAT_TEST_COUNT = 3  # UAT 测试次数
    UAT_TEST_INTERVAL = 5  # UAT 测试间隔
    UAT_TEST_THRESHOLD = 3  # UAT 测试阈值


class ResultsConstants:
    """计算结果管理相关常量"""

    RESULTS_DIR_NAME = "results"
    REPORTS_DIR_NAME = "reports"
    HANDS_DIR_NAME = "hands"
    REVIEW_DIR_NAME = "review"

    RESULTS_FILE_SUFFIX = ".json"
    REPORT_FILE_PREFIX = "Report_"
    REPORT_FILE_SUFFIX = ".md"

    RESULTS_DATE_FORMAT = "%Y%m%d"
    REPORT_DATE_FORMAT = "%Y-%m-%d"
    
    DATE_FOLDER_FORMAT = "%Y-%m-%d"
    USE_DATE_FOLDERS = True

    MAX_RESULTS_PER_SYMBOL = 30
    CLEANUP_THRESHOLD_DAYS = 30

    JSON_INDENT = 2
    ENCODING = "utf-8"


# ============================================================================
# 回测相关常量
# ============================================================================
class BacktestConstants:
    """回测引擎相关常量"""

    # 初始资金
    DEFAULT_INITIAL_CAPITAL = 100000.0  # 默认初始资金 10万

    # 交易成本
    DEFAULT_COMMISSION_RATE = 0.0003  # 佣金率 0.03%
    DEFAULT_STAMP_DUTY_RATE = 0.0005  # 印花税率 0.05% (万5, 仅卖出, 2024年起)
    DEFAULT_SLIPPAGE_RATE = 0.0005  # 滑点率 0.05% (万5, 与 cost_model.py 一致)
    DEFAULT_MIN_COMMISSION = 5.0  # 最低佣金 5元

    # 回测窗口
    DEFAULT_TRAIN_WINDOW = 252  # 默认训练窗口 (1年)
    DEFAULT_TEST_WINDOW = 63  # 默认测试窗口 (1季度)

    # 风险控制
    MAX_POSITION_PCT = 0.95  # 最大仓位比例
    MIN_CASH_RESERVE = 1000.0  # 最小现金保留


# ============================================================================
# 市场时间相关常量
# ============================================================================
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


# ============================================================================
# Wyckoff 常量 (from LPPL standalone)
# ============================================================================
SPRING_LOW_FACTOR = 1.01
SPRING_CLOSE_FACTOR = 1.0
MIN_RR_RATIO = 2.5
MIN_WYCKOFF_DATA_ROWS = 200
BC_LOOKBACK_WINDOW = 20
SPRING_FREEZE_DAYS = 3
WYCKOFF_OUTPUT_DIR = "data/state/wyckoff"
TR_MAX_RANGE_PCT = 0.20
TR_MAX_SHORT_TREND = 0.05
