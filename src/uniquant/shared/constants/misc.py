"""杂项常量 (服务、UI、测试、工具等)"""


ENABLE_JOBLIB_PARALLEL = True


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


class PrecisionConstants:
    """精度和误差控制常量"""

    PRICE_DECIMALS = 2       # 价格保留2位小数
    RATE_DECIMALS = 4        # 收益率保留4位小数
    PCT_DECIMALS = 4         # 百分比保留4位小数
    VOLUME_DECIMALS = 0      # 成交量保留整数
    AMOUNT_DECIMALS = 2      # 成交额保留2位小数
    WEIGHT_DECIMALS = 4      # 权重保留4位小数
    FLOAT_TOLERANCE = 1e-6   # 浮点数比较容差比较精度


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


class UATConstants:
    """UAT 测试相关常量"""

    # 测试配置
    UAT_TEST_DAYS = 365  # UAT 测试天数
    UAT_TEST_COUNT = 3  # UAT 测试次数
    UAT_TEST_INTERVAL = 5  # UAT 测试间隔
    UAT_TEST_THRESHOLD = 3  # UAT 测试阈值
