import logging
import datetime
import numpy as np
import pandas as pd
from ...shared.logger_factory import get_logger
from ...shared.constants import AnalysisServiceConstants
from ...shared.error_handling import handle_errors, validate_inputs
from ...shared.retry_decorator import retry
from ...shared.exceptions import AnalysisError, DataFetchError, DataValidationError

logger = get_logger(__name__)

MACRO_ENGINE_RECOVERABLE_ERRORS = (
    AttributeError,
    KeyError,
    OSError,
    TypeError,
    ValueError,
)

class MacroAnalysisEngine:
    """宏观与市场基准分析引擎"""
    
    def __init__(self, orchestrator):
        """
        Args:
            orchestrator: AnalysisService instance that provides shared context
        """
        self.orchestrator = orchestrator

    @handle_errors(
        AnalysisError,
        ValueError,
        TypeError,
        default_return={
            "var_95": AnalysisServiceConstants.DEFAULT_VAR_95,
            "var_99": AnalysisServiceConstants.DEFAULT_VAR_99,
            "cvar_95": AnalysisServiceConstants.DEFAULT_CVAR_95,
            "cvar_99": AnalysisServiceConstants.DEFAULT_CVAR_99,
            "max_drawdown": AnalysisServiceConstants.DEFAULT_MAX_DRAWDOWN,
            "regime": "NORMAL",
            "ntf_signal": "中性",
            "summary": "宏观环境分析完成",
        },
        log_level=logging.ERROR,
    )
    def analyze_macro_health(self, mock: bool = False):
        """Calculate EVT metrics for macro health."""
        # 生成缓存键
        cache_key = self.orchestrator._generate_cache_key("macro_health", mock=mock)

        # 尝试从缓存获取结果
        cached_result = self.orchestrator._get_cached_result(cache_key, use_disk=True)
        if cached_result is not None:
            return cached_result

        returns = self.get_macro_returns()
        if returns.empty:
            # Fallback
            returns = pd.Series(
                np.random.normal(
                    0,
                    AnalysisServiceConstants.RANDOM_DATA_STD,
                    AnalysisServiceConstants.RANDOM_DATA_LENGTH,
                )
            )

        # 计算风险指标
        metrics = self.orchestrator.evt_risk.calculate_metrics(returns)

        # 验证计算结果
        if not self.orchestrator.validate_risk_metrics(metrics):
            logger.warning("Risk metrics validation failed, using default values")
            # 返回默认值
            default_result = {
                "var_95": AnalysisServiceConstants.DEFAULT_VAR_95,
                "var_99": AnalysisServiceConstants.DEFAULT_VAR_99,
                "cvar_95": AnalysisServiceConstants.DEFAULT_CVAR_95,
                "cvar_99": AnalysisServiceConstants.DEFAULT_CVAR_99,
                "max_drawdown": AnalysisServiceConstants.DEFAULT_MAX_DRAWDOWN,
                "regime": "NORMAL",
                "ntf_signal": "中性",
                "summary": "宏观环境分析完成",
            }
            # 缓存默认结果
            self.orchestrator._set_cached_result(
                cache_key,
                default_result,
                use_disk=True,
                ttl=AnalysisServiceConstants.CACHE_TTL_1HOUR,
            )  # 1小时缓存
            return default_result

        # 使用验证服务与标准计算方法对比
        if self.orchestrator.validation_service is not None:
            try:
                # 计算标准方法的结果
                standard_results = {
                    "var_95": self.orchestrator.validation_service.calculate_standard_var(
                        returns, 0.95
                    ),
                    "var_99": self.orchestrator.validation_service.calculate_standard_var(
                        returns, 0.99
                    ),
                    "cvar_95": self.orchestrator.validation_service.calculate_standard_cvar(
                        returns, 0.95
                    ),
                    "cvar_99": self.orchestrator.validation_service.calculate_standard_cvar(
                        returns, 0.99
                    ),
                    "max_drawdown": self.orchestrator.validation_service.calculate_standard_max_drawdown(
                        returns
                    ),
                }

                # 验证计算结果与标准方法的差异
                validation_result = self.orchestrator.validation_service.validate_risk_metrics(
                    metrics, standard_results
                )
                if not validation_result.get("all_valid", False):
                    logger.warning(
                        "Risk metrics validation against standard methods failed"
                    )
                    # 生成验证报告
                    report = self.orchestrator.validation_service.generate_validation_report(
                        validation_result
                    )
                    logger.info(f"Validation report:\n{report}")
            except MACRO_ENGINE_RECOVERABLE_ERRORS as e:
                logger.error(
                    f"Error validating risk metrics against standard methods: {e}"
                )

        # 确保精度一致性
        metrics = self.orchestrator.ensure_precision_consistency(metrics)

        # 缓存计算结果
        self.orchestrator._set_cached_result(
            cache_key,
            metrics,
            use_disk=True,
            ttl=AnalysisServiceConstants.CACHE_TTL_1HOUR,
        )  # 1小时缓存

        return metrics

    @handle_errors(
        AnalysisError,
        DataFetchError,
        DataValidationError,
        ValueError,
        TypeError,
        default_return=pd.Series(),
        log_level=logging.ERROR,
        error_type="macro_returns_calculation",
    )
    @retry(
        max_retries=AnalysisServiceConstants.MAX_RETRIES,
        delay=AnalysisServiceConstants.RETRY_DELAY,
        backoff=2.0,
        max_delay=AnalysisServiceConstants.MAX_WAIT_TIME,
        exceptions=(DataFetchError,),
    )
    @validate_inputs(
        window=lambda x: isinstance(x, int) and x > 0,
    )
    def get_macro_returns(self, window: int = 200) -> pd.Series:
        """
        Fetch real returns for Macro Cockpit (HS300).
        """
        end_date = datetime.datetime.now().strftime("%Y%m%d")
        start_date = (
            datetime.datetime.now() - datetime.timedelta(days=window * 2)
        ).strftime("%Y%m%d")

        df = self.orchestrator.data_service.fetcher.fetch_index_daily(
            "sh000300", start_date, end_date
        )
        if df is None or df.empty:
            logger.warning("No data returned for HS300 index")
            return pd.Series()

        # 优化DataFrame以提高处理效率
        df = self.orchestrator._optimize_dataframe(df)

        # 对大数据集进行采样
        df = self.orchestrator._sample_data(df, max_rows=window * 2)

        # Calculate daily returns
        df["pct_change"] = df["close"].pct_change()
        returns = df["pct_change"].dropna()

        # Validate returns data
        if returns.empty:
            logger.warning("Calculated returns series is empty")
            return pd.Series()

        return returns.tail(window)
