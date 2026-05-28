"""共享常量定义

该模块包含系统中使用的所有常量定义，按功能模块分组。
"""

from uniquant.shared.constants.market import (
    DateConstants,
    TimeConstants,
    MarketConstants,
    MarketCapThresholds,
    TimeWindows,
    MarketHours,
    MAJOR_INDEXES,
)

from uniquant.shared.constants.technical import (
    WindowConfig,
    WINDOW_CONFIG,
    IndicatorThresholds,
    NTFConstants,
    LPPLConstants,
    RegimeConstants,
    ENABLE_NUMBA_JIT,
    M_BOUNDS,
    W_BOUNDS,
    RANDOM_SEED,
    TRUE_RANGE_COLUMN,
    SPRING_LOW_FACTOR,
    SPRING_CLOSE_FACTOR,
    MIN_RR_RATIO,
    MIN_WYCKOFF_DATA_ROWS,
    BC_LOOKBACK_WINDOW,
    SPRING_FREEZE_DAYS,
    WYCKOFF_OUTPUT_DIR,
    TR_MAX_RANGE_PCT,
    TR_MAX_SHORT_TREND,
)

from uniquant.shared.constants.risk import (
    RiskThresholds,
    RiskCalculationConstants,
    BacktestConstants,
)

from uniquant.shared.constants.data import (
    DataSourceConstants,
    THSConstants,
    DataLakeConstants,
    DataValidationConstants,
    DataServiceConstants,
    CacheConstants,
    NetworkConstants,
    REQUIRED_COLUMNS,
    PARQUET_COMPRESSION,
)

from uniquant.shared.constants.path import (
    PathConstants,
    PROJECT_ROOT,
    TDX_DIR,
    DATA_DIR,
    LAKE_QUOTES_DIR,
    LAKE_FINANCIAL_DIR,
    LAKE_INDEX_DIR,
    STOCK_LIST_FILE,
    OUTPUT_DIR,
)

from uniquant.shared.constants.misc import (
    AnalysisServiceConstants,
    PerformanceConstants,
    PrecisionConstants,
    UIConstants,
    ToolConstants,
    ResultsConstants,
    TestConstants,
    UATConstants,
    ENABLE_JOBLIB_PARALLEL,
)

__all__ = [
    # market
    "DateConstants",
    "TimeConstants",
    "MarketConstants",
    "MarketCapThresholds",
    "TimeWindows",
    "MarketHours",
    "MAJOR_INDEXES",
    # technical
    "WindowConfig",
    "WINDOW_CONFIG",
    "IndicatorThresholds",
    "NTFConstants",
    "LPPLConstants",
    "RegimeConstants",
    "ENABLE_NUMBA_JIT",
    "M_BOUNDS",
    "W_BOUNDS",
    "RANDOM_SEED",
    "TRUE_RANGE_COLUMN",
    "SPRING_LOW_FACTOR",
    "SPRING_CLOSE_FACTOR",
    "MIN_RR_RATIO",
    "MIN_WYCKOFF_DATA_ROWS",
    "BC_LOOKBACK_WINDOW",
    "SPRING_FREEZE_DAYS",
    "WYCKOFF_OUTPUT_DIR",
    "TR_MAX_RANGE_PCT",
    "TR_MAX_SHORT_TREND",
    # risk
    "RiskThresholds",
    "RiskCalculationConstants",
    "BacktestConstants",
    # data
    "DataSourceConstants",
    "THSConstants",
    "DataLakeConstants",
    "DataValidationConstants",
    "DataServiceConstants",
    "CacheConstants",
    "NetworkConstants",
    "REQUIRED_COLUMNS",
    "PARQUET_COMPRESSION",
    # path
    "PathConstants",
    "PROJECT_ROOT",
    "TDX_DIR",
    "DATA_DIR",
    "LAKE_QUOTES_DIR",
    "LAKE_FINANCIAL_DIR",
    "LAKE_INDEX_DIR",
    "STOCK_LIST_FILE",
    "OUTPUT_DIR",
    # misc
    "AnalysisServiceConstants",
    "PerformanceConstants",
    "PrecisionConstants",
    "UIConstants",
    "ToolConstants",
    "ResultsConstants",
    "TestConstants",
    "UATConstants",
    "ENABLE_JOBLIB_PARALLEL",
]
