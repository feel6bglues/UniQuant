"""风险控制相关常量"""


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
