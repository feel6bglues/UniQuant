"""数据相关常量"""


REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]
PARQUET_COMPRESSION = "snappy"


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


class DataServiceConstants:
    """数据服务相关常量"""

    # 缓存过期时间（秒）
    CACHE_TTL_STOCK = 3600  # 股票数据 1小时
    CACHE_TTL_INDEX = 3600  # 指数数据 1小时
    CACHE_TTL_ETF = 3600  # ETF数据 1小时
    CACHE_TTL_REALTIME = 60  # 实时数据 1分钟
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
    CACHE_TTL_INDEX = 3600  # 指数数据 1小时
    CACHE_TTL_ETF = 3600  # ETF数据 1小时
    CACHE_TTL_REALTIME = 60  # 实时数据 1分钟
    CACHE_TTL_INDUSTRY = 86400  # 行业数据 1天
    CACHE_TTL_CONCEPT = 86400  # 概念数据 1天
    CACHE_TTL_GENERAL = 3600  # 通用数据 1小时

    # 其他TTL常量 (兼容旧代码)
    CACHE_TTL_DAILY = 86400  # 日线数据 1天
    CACHE_TTL_MINUTE = 300  # 分钟线数据 5分钟
    CACHE_TTL_WEEKLY = 604800  # 周线数据 1周
    CACHE_TTL_MONTHLY = 2592000  # 月线数据 30天


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
