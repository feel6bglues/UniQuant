"""技术指标相关常量"""


ENABLE_NUMBA_JIT = True
M_BOUNDS = (0.1, 0.9)
W_BOUNDS = (6.0, 13.0)
RANDOM_SEED = 42
TRUE_RANGE_COLUMN = "true_range"

# Wyckoff 常量 (from LPPL standalone)
SPRING_LOW_FACTOR = 1.01
SPRING_CLOSE_FACTOR = 1.0
MIN_RR_RATIO = 2.5
MIN_WYCKOFF_DATA_ROWS = 200
BC_LOOKBACK_WINDOW = 20
SPRING_FREEZE_DAYS = 3
WYCKOFF_OUTPUT_DIR = "data/state/wyckoff"
TR_MAX_RANGE_PCT = 0.20
TR_MAX_SHORT_TREND = 0.05


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
    FSM_MA_SHORT = 20  # FSM短期MA周期
    FSM_MA_LONG = 60  # FSM长期MA周期
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
    SAMPLE_MAX_ROWS_WYCKOFF = 800


class NTFConstants:
    """NTF引擎相关常量"""

    # 偏离度阈值
    HEAT_THRESHOLD = 0.8  # 分位数高于80%视为过热
    PANIC_THRESHOLD = 0.1  # 分位数低于10%视为恐慌

    # 成交量脉冲阈值
    VOLUME_RATIO_THRESHOLD = 2.0  # 成交量脉冲阈值

    # 计算窗口
    WINDOW = 5  # 计算成交量均值的窗口大小

    # 置信度阈值
    CONFIDENCE_SUPPORT = 0.85  # 支撑信号的置信度
    CONFIDENCE_RESISTANCE = 0.80  # 阻力信号的置信度
    CONFIDENCE_LIQUIDITY = 0.40  # 流动性脉冲的置信度


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


class RegimeConstants:
    """市场状态检测器相关常量"""

    # 熵值阈值
    ENTROPY_PERCENTILE_THRESHOLD = 0.2  # 熵值分位数阈值，低于此值视为FROZEN状态

    # 成交量Z-Score阈值
    TURNOVER_Z_SCORE_THRESHOLD = 3.0  # 成交量Z-Score阈值，绝对值超过此值视为STRESSED状态

    # 数据要求
    MIN_DATA_POINTS = 30  # 最小数据点数

    # 计算窗口
    ENTROPY_WINDOW = 60  # 熵值计算窗口
    TURNOVER_Z_PERIOD = 20  # 成交量Z-Score计算周期
