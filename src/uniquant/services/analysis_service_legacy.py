import logging
import threading
import warnings
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..shared.cache.cache_factory import CacheFactory
from ..shared.config_loader import get_config
from ..shared.constants import (
    AnalysisServiceConstants,
    IndicatorThresholds,
    MarketConstants,
    PrecisionConstants,
    ResultsConstants,
    TimeConstants,
)
from ..shared.error_handling import handle_errors, validate_inputs
from ..shared.retry_decorator import retry
from ..shared.exceptions import (
    AnalysisError,
    DataAccessError,
    DataFetchError,
    DataValidationError,
    ServiceError,
)
from ..shared.logger_factory import get_logger
from .data_service import DataService
from .validation_service import ValidationService

RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    ModuleNotFoundError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

logger = get_logger("AnalysisService")


class AnalysisService:
    """分析服务 — 通过 AnalysisEngineFactory 延迟初始化依赖，无循环依赖。"""

    def __init__(
        self,
        data_service: DataService,
        engine_factory=None,
        evt_risk=None,
        sizer=None,
        validation_service=None,
    ):
        warnings.warn("AnalysisService (v1) is deprecated, use analysis_service_v2", DeprecationWarning, stacklevel=2)
        self.data_service = data_service
        self.evt_risk = evt_risk
        self.sizer = sizer
        self.validation_service = validation_service

        self.report_root = get_config().ROOT_DIR / ResultsConstants.HANDS_DIR_NAME / ResultsConstants.REPORTS_DIR_NAME
        self.report_root.mkdir(parents=True, exist_ok=True)

        self.etf_list = get_config().get("markets.etfs.default_list", [])
        self.reporter = None

        self._market_cache_date: Optional[str] = None
        self._market_regime: Optional[str] = None
        self._market_regime_details: Optional[Dict[str, Any]] = None
        self._ntf_signals: Optional[Dict[str, Any]] = None
        self._benchmark_data: Optional[pd.DataFrame] = None
        self._sector_data_cache: Dict[str, pd.DataFrame] = {}

        if engine_factory is None:
            from .analysis.engine_factory import AnalysisEngineFactory
            engine_factory = AnalysisEngineFactory(orchestrator=self)
        self._factory = engine_factory

        self._initialize_cache()
        self._initialize_validation_service()

    @property
    def fsm_engine(self):
        return self._factory.fsm

    @property
    def czsc_engine(self):
        return self._factory.czsc

    @property
    def lppl_engine(self):
        return self._factory.lppl

    @property
    def regime_engine(self):
        return self._factory.regime

    @property
    def ntf_engine(self):
        return self._factory.ntf

    @property
    def macro_engine(self):
        return self._factory.macro

    @property
    def report_engine(self):
        if "report" not in self._factory._engines:
            from .analysis.report_generator_engine import ReportGeneratorEngine
            self._factory._engines["report"] = ReportGeneratorEngine(orchestrator=self)
        return self._factory._engines["report"]

    @property
    def brain(self):
        return self._factory.brain

    @property
    def wyckoff_engine(self):
        return self._factory.wyckoff

    def _initialize_dependencies(self):
        """Deprecated — engines are lazily initialized via AnalysisEngineFactory."""
        pass

    def _initialize_cache(self):
        """
        初始化缓存系统
        """
        try:
            # 创建内存缓存用于频繁访问的计算结果
            self.memory_cache = CacheFactory.create(
                "memory", max_size=AnalysisServiceConstants.MEMORY_CACHE_MAX_SIZE
            )

            # 创建磁盘缓存用于长期存储的计算结果
            self.disk_cache = CacheFactory.create(
                "disk", cache_dir="data/cache/analysis"
            )

            logger.info("Cache system initialized successfully")
        except (ImportError, ModuleNotFoundError) as e:
            logger.error(f"Failed to initialize cache system: {e}")
            self.memory_cache = None
            self.disk_cache = None

        self._init_market_level_cache()

    def _init_market_level_cache(self) -> None:
        """
        初始化市场级缓存
        用于存储全市场共享的计算结果，避免重复计算
        
        Thread-safe implementation with lock-protected cache.
        """
        self._market_cache_date: Optional[str] = None
        self._market_regime: Optional[str] = None
        self._market_regime_details: Optional[Dict[str, Any]] = None
        self._ntf_signals: Optional[Dict[str, Any]] = None
        self._benchmark_data: Optional[pd.DataFrame] = None
        self._sector_data_cache: Dict[str, pd.DataFrame] = {}
        self._cache_lock = threading.Lock()
        logger.info("Market-level cache initialized with thread lock")

    def clear_market_cache(self) -> None:
        """
        清除市场级缓存 - Thread-safe
        
        用于强制刷新市场数据，如跨日分析或数据更新后
        """
        with self._cache_lock:
            self._market_cache_date = None
            self._market_regime = None
            self._market_regime_details = None
            self._ntf_signals = None
            self._benchmark_data = None
            self._sector_data_cache.clear()
        logger.info("Market-level cache cleared (thread-safe)")

    def get_cache_status(self) -> Dict[str, Any]:
        """
        获取缓存状态信息 - Thread-safe
        
        Returns:
            缓存状态字典
        """
        with self._cache_lock:
            return {
                "cache_date": self._market_cache_date,
                "has_regime": self._market_regime is not None,
                "has_ntf_signals": self._ntf_signals is not None,
                "has_benchmark_data": self._benchmark_data is not None,
                "sector_cache_count": len(self._sector_data_cache),
            }

    def _initialize_validation_service(self):
        """
        初始化验证服务
        """
        try:
            if self.validation_service is None:
                self.validation_service = ValidationService()
            logger.info("Validation service initialized successfully")
        except (ImportError, ModuleNotFoundError) as e:
            logger.error(f"Failed to initialize validation service: {e}")
            self.validation_service = None

    def validate_risk_metrics(self, metrics: Dict[str, Any]) -> bool:
        """
        验证风险指标的合理性

        Args:
            metrics: 风险指标字典

        Returns:
            bool: 验证是否通过
        """
        try:
            # 验证VAR值范围
            var_95 = metrics.get("var_95")
            if var_95 is not None:
                if var_95 < 0 or var_95 > 1:
                    logger.warning(f"Invalid VaR 95% value: {var_95}")
                    return False

            var_99 = metrics.get("var_99")
            if var_99 is not None:
                if var_99 < 0 or var_99 > 1:
                    logger.warning(f"Invalid VaR 99% value: {var_99}")
                    return False
                # 验证VAR 99% 大于 VAR 95%
                if var_95 is not None and var_99 < var_95:
                    logger.warning(
                        f"VaR 99% ({var_99}) should be greater than VaR 95% ({var_95})"
                    )
                    return False

            # 验证CVAR值范围
            cvar_95 = metrics.get("cvar_95")
            if cvar_95 is not None:
                if cvar_95 < 0 or cvar_95 > 1:
                    logger.warning(f"Invalid CVaR 95% value: {cvar_95}")
                    return False
                # 验证CVAR 95% 大于 VAR 95%
                if var_95 is not None and cvar_95 < var_95:
                    logger.warning(
                        f"CVaR 95% ({cvar_95}) should be greater than VaR 95% ({var_95})"
                    )
                    return False

            cvar_99 = metrics.get("cvar_99")
            if cvar_99 is not None:
                if cvar_99 < 0 or cvar_99 > 1:
                    logger.warning(f"Invalid CVaR 99% value: {cvar_99}")
                    return False
                # 验证CVAR 99% 大于 VAR 99%
                if var_99 is not None and cvar_99 < var_99:
                    logger.warning(
                        f"CVaR 99% ({cvar_99}) should be greater than VaR 99% ({var_99})"
                    )
                    return False

            # 验证最大回撤范围
            max_drawdown = metrics.get("max_drawdown")
            if max_drawdown is not None:
                if max_drawdown < 0 or max_drawdown > 1:
                    logger.warning(f"Invalid max drawdown value: {max_drawdown}")
                    return False

            # 验证置信度范围
            confidence = metrics.get("confidence")
            if confidence is not None:
                if confidence < 0 or confidence > 1:
                    logger.warning(f"Invalid confidence value: {confidence}")
                    return False

            return True
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            logger.error(f"Error validating risk metrics: {e}")
            return False

    def validate_position_sizing(self, sizing_result: Dict[str, Any]) -> bool:
        """
        验证仓位计算结果的合理性

        Args:
            sizing_result: 仓位计算结果字典

        Returns:
            bool: 验证是否通过
        """
        try:
            # 验证建议仓位
            suggested_shares = sizing_result.get("建议仓位")
            if suggested_shares is not None:
                if suggested_shares < 0:
                    logger.warning(
                        f"Invalid suggested shares value: {suggested_shares}"
                    )
                    return False

            # 验证止损价格
            stop_loss = sizing_result.get("止损价格") or sizing_result.get("执行止损")
            if stop_loss is not None:
                if stop_loss <= 0:
                    logger.warning(f"Invalid stop loss value: {stop_loss}")
                    return False

            # 验证资金占用
            total_value = sizing_result.get("资金占用")
            if total_value is not None:
                if total_value < 0:
                    logger.warning(f"Invalid total value: {total_value}")
                    return False

            return True
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            logger.error(f"Error validating position sizing: {e}")
            return False

    def validate_analysis_result(self, result: Dict[str, Any]) -> bool:
        """
        验证分析结果的合理性

        Args:
            result: 分析结果字典

        Returns:
            bool: 验证是否通过
        """
        try:
            # 验证状态
            status = result.get("status")
            if status not in ["success", "failed"]:
                logger.warning(f"Invalid status value: {status}")
                return False

            # 验证信号强度
            signal_strength = result.get("signal_strength")
            if signal_strength is not None:
                if signal_strength < 0 or signal_strength > 1:
                    logger.warning(f"Invalid signal strength value: {signal_strength}")
                    return False

            # 验证止损和止盈价格
            stop_loss = result.get("stop_loss")
            if stop_loss is not None:
                if stop_loss <= 0:
                    logger.warning(f"Invalid stop loss value: {stop_loss}")
                    return False

            take_profit = result.get("take_profit")
            if take_profit is not None:
                if take_profit <= 0:
                    logger.warning(f"Invalid take profit value: {take_profit}")
                    return False
                # 验证止盈价格大于止损价格
                if stop_loss is not None and take_profit <= stop_loss:
                    logger.warning(
                        f"Take profit ({take_profit}) should be greater than stop loss ({stop_loss})"
                    )
                    return False

            return True
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            logger.error(f"Error validating analysis result: {e}")
            return False

    def validate_comprehensive_result(self, result: Dict[str, Any]) -> bool:
        """
        验证综合分析结果的合理性

        Args:
            result: 综合分析结果字典

        Returns:
            bool: 验证是否通过
        """
        try:
            # 验证状态
            status = result.get("status")
            if status not in ["success", "failed"]:
                logger.warning(f"Invalid status value: {status}")
                return False

            # 验证各个分析模块的结果
            for analysis_type in ["lppl", "czsc", "fsm"]:
                analysis_result = result.get(analysis_type, {})
                if not self.validate_analysis_result(analysis_result):
                    logger.warning(f"Invalid {analysis_type} analysis result")
                    return False

            return True
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            logger.error(f"Error validating comprehensive result: {e}")
            return False

    def round_to_precision(self, value: float, precision_type: str) -> float:
        """
        根据精度类型对值进行四舍五入

        Args:
            value: 需要四舍五入的值
            precision_type: 精度类型 (price/ratio/percentage/var/cvar/drawdown)

        Returns:
            float: 四舍五入后的值
        """
        try:
            if precision_type == "price":
                return round(value, PrecisionConstants.PRICE_DECIMALS)
            elif precision_type == "ratio":
                return round(value, PrecisionConstants.PCT_DECIMALS)
            elif precision_type == "percentage":
                return round(value, PrecisionConstants.PCT_DECIMALS)
            elif precision_type == "var" or precision_type == "cvar":
                return round(value, PrecisionConstants.PCT_DECIMALS)
            elif precision_type == "drawdown":
                return round(value, PrecisionConstants.PCT_DECIMALS)
            else:
                return value
        except (TypeError, ValueError, AttributeError) as e:
            logger.error(f"Error rounding value: {e}")
            return value

    def ensure_precision_consistency(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        确保数据中所有数值的精度一致性

        Args:
            data: 包含数值的数据字典

        Returns:
            精度一致的数据字典
        """
        try:
            result: Dict[str, Any] = {}
            for key, value in data.items():
                if isinstance(value, float):
                    # 根据键名自动判断精度类型
                    if key in ["var_95", "var_99", "cvar_95", "cvar_99"]:
                        result[key] = self.round_to_precision(value, "var")
                    elif key in ["max_drawdown"]:
                        result[key] = self.round_to_precision(value, "drawdown")
                    elif key in ["signal_strength", "confidence", "amplitude"]:
                        result[key] = self.round_to_precision(value, "ratio")
                    elif key in [
                        "stop_loss",
                        "take_profit",
                        "close",
                        "open",
                        "high",
                        "low",
                    ]:
                        result[key] = self.round_to_precision(value, "price")
                    else:
                        result[key] = value
                elif isinstance(value, dict):
                    # 递归处理嵌套字典
                    result[key] = self.ensure_precision_consistency(value)
                else:
                    result[key] = value
            return result
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error ensuring precision consistency: {e}")
            return data

    def _generate_cache_key(self, prefix: str, **kwargs) -> str:
        """
        生成缓存键

        Args:
            prefix: 缓存键前缀
            **kwargs: 缓存键参数

        Returns:
            str: 生成的缓存键
        """
        try:
            # 排序参数以确保一致性
            sorted_params = sorted(kwargs.items())
            param_str = "_".join([f"{k}={v}" for k, v in sorted_params])
            return f"{prefix}:{param_str}"
        except (AttributeError, KeyError, TypeError, OSError) as e:
            logger.error(f"Error generating cache key: {e}")
            return f"{prefix}:unknown"

    def _get_cached_result(self, cache_key: str, use_disk: bool = False) -> Any:
        """
        获取缓存结果

        Args:
            cache_key: 缓存键
            use_disk: 是否使用磁盘缓存

        Returns:
            Any: 缓存的结果，如果没有缓存则返回None
        """
        try:
            # 优先从内存缓存获取
            if self.memory_cache:
                result = self.memory_cache.get(cache_key)
                if result is not None:
                    logger.debug(f"Cache hit in memory for key: {cache_key}")
                    return result

            # 如果指定使用磁盘缓存，则从磁盘缓存获取
            if use_disk and self.disk_cache:
                result = self.disk_cache.get(cache_key)
                if result is not None:
                    logger.debug(f"Cache hit in disk for key: {cache_key}")
                    # 将结果也存入内存缓存，提高后续访问速度
                    if self.memory_cache:
                        self.memory_cache.set(cache_key, result)
                    return result

            logger.debug(f"Cache miss for key: {cache_key}")
            return None
        except (ImportError, ModuleNotFoundError) as e:
            logger.error(f"Error getting cached result: {e}")
            return None

    def _set_cached_result(
        self, cache_key: str, result: Any, use_disk: bool = False, ttl: Optional[int] = None
    ) -> bool:
        """
        设置缓存结果

        Args:
            cache_key: 缓存键
            result: 要缓存的结果
            use_disk: 是否使用磁盘缓存
            ttl: 缓存过期时间（秒）

        Returns:
            bool: 是否成功设置缓存
        """
        try:
            # 存入内存缓存
            if self.memory_cache:
                self.memory_cache.set(cache_key, result, ttl)

            # 如果指定使用磁盘缓存，则存入磁盘缓存
            if use_disk and self.disk_cache:
                self.disk_cache.set(cache_key, result, ttl)

            return True
        except (ImportError, ModuleNotFoundError) as e:
            logger.error(f"Error setting cached result: {e}")
            return False

    def _sample_data(self, df: pd.DataFrame, max_rows: Optional[int] = None) -> pd.DataFrame:
        """
        对大数据集进行采样，保留代表性数据

        Args:
            df: 原始DataFrame
            max_rows: 最大保留行数

        Returns:
            pd.DataFrame: 采样后的DataFrame
        """
        try:
            if max_rows is None:
                max_rows = AnalysisServiceConstants.SAMPLE_MAX_ROWS_DEFAULT

            if len(df) <= max_rows:
                return df

            # 计算采样间隔
            sample_interval = len(df) // max_rows

            # 确保至少采样一定比例的数据
            min_interval = max(
                1, int(len(df) * AnalysisServiceConstants.MIN_SAMPLE_INTERVAL_RATIO)
            )
            sample_interval = min(sample_interval, min_interval)

            # 进行采样
            sampled_df = df.iloc[::sample_interval]

            # 确保包含最新数据
            if len(sampled_df) > 0 and not sampled_df.iloc[-1].equals(df.iloc[-1]):
                sampled_df = pd.concat([sampled_df, df.iloc[[-1]]])

            logger.info(f"Sampled data from {len(df)} rows to {len(sampled_df)} rows")
            return sampled_df
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error sampling data: {e}")
            return df

    def _process_in_chunks(
        self, df: pd.DataFrame, chunk_size: Optional[int] = None, process_func=None
    ) -> pd.DataFrame:
        """
        分块处理大数据集

        Args:
            df: 原始DataFrame
            chunk_size: 每块的大小
            process_func: 处理函数，接收DataFrame块并返回处理后的块

        Returns:
            pd.DataFrame: 处理后的DataFrame
        """
        try:
            if process_func is None:
                return df

            if chunk_size is None:
                chunk_size = AnalysisServiceConstants.CHUNK_SIZE

            if len(df) <= chunk_size:
                return process_func(df)

            # 分块处理
            chunks = []
            for i in range(0, len(df), chunk_size):
                chunk = df.iloc[i : i + chunk_size]
                processed_chunk = process_func(chunk)
                chunks.append(processed_chunk)

            # 合并结果
            result = pd.concat(chunks)
            logger.info(f"Processed data in {len(chunks)} chunks")
            return result
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error processing data in chunks: {e}")
            return df

    def _optimize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        优化DataFrame以提高处理效率

        Args:
            df: 原始DataFrame

        Returns:
            pd.DataFrame: 优化后的DataFrame
        """
        try:
            # 复制DataFrame以避免修改原始数据
            df = df.copy()

            # 优化数据类型
            for col in df.columns:
                if pd.api.types.is_integer_dtype(df[col]):
                    df[col] = pd.to_numeric(df[col], downcast="integer")
                elif pd.api.types.is_float_dtype(df[col]):
                    df[col] = pd.to_numeric(df[col], downcast="float")
                elif pd.api.types.is_object_dtype(df[col]):
                    # 尝试转换为类别类型以减少内存使用
                    if df[col].nunique() < len(df) * 0.5:
                        df[col] = df[col].astype("category")

            # 确保索引是排序的
            if "date" in df.columns:
                df = df.sort_values("date").reset_index(drop=True)

            logger.info(
                f"Optimized DataFrame memory usage: {df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB"
            )
            return df
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Error optimizing DataFrame: {e}")
            return df

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
        return self.macro_engine.analyze_macro_health(mock=mock)

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
        return self.macro_engine.get_macro_returns(window=window)

    @handle_errors(
        AnalysisError,
        DataFetchError,
        DataValidationError,
        ServiceError,
        ValueError,
        TypeError,
        default_return=False,
        log_level=logging.ERROR,
        error_type="ticker_analysis",
    )
    @validate_inputs(
        ticker=lambda x: isinstance(x, str) and bool(x.strip()),
    )
    def analyze_ticker(self, ticker: str) -> bool:
        """
        全流程分析单只股票
        """
        data_pack = self._prepare_data_for_analysis(ticker)
        if data_pack is None:
            return False

        if not self._run_engine_analysis(ticker, data_pack):
            return False

        decision_result = self._make_decision(ticker, data_pack)
        if decision_result is None:
            return False

        filepath = self._save_analysis_result(ticker, data_pack, decision_result)

        return self._generate_analysis_report(ticker, data_pack, decision_result, filepath)

    def _prepare_data_for_analysis(self, ticker: str) -> Optional[Dict[str, Any]]:
        """准备分析数据"""
        try:
            data_pack = self.data_service.fetch_for_brain(ticker)

            if not data_pack:
                logger.error(f"{ticker} 数据不足，跳过分析")
                return None

            if "stock" not in data_pack or data_pack["stock"].empty:
                logger.error(f"{ticker} 股票数据为空，跳过分析")
                return None

            return data_pack
        except RECOVERABLE_ERRORS as e:
            logger.error(f"获取 {ticker} 数据失败: {e}")
            return None

    def _run_engine_analysis(self, ticker: str, data_pack: Dict[str, Any]) -> bool:
        """运行所有引擎分析"""
        try:
            self._run_regime_detection(ticker, data_pack)
            self._run_lppl_detection(data_pack)
            self._run_ntf_detection(ticker, data_pack)
            self._run_czsc_detection(ticker, data_pack)
            self._run_wyckoff_detection(ticker, data_pack)
            self._run_alpha_analysis(data_pack)
            self._calculate_ma_status(data_pack)
            self._calculate_returns(data_pack)
            self._calculate_price_and_stop(data_pack)
            self._calculate_technical_indicators(data_pack)

            data_pack["symbol"] = ticker
            data_pack["market"] = "CN"

            return True
        except RECOVERABLE_ERRORS as e:
            logger.error(f"引擎分析失败: {e}")
            return False

    def _run_regime_detection(self, ticker: str, data_pack: Dict[str, Any]) -> None:
        """
        运行 RegimeDetector 分析（带市场级缓存 - Thread-safe）
        
        市场状态是全市场共享的，只需计算一次
        """
        try:
            today = pd.Timestamp.now().strftime("%Y-%m-%d")
            
            with self._cache_lock:
                if self._market_cache_date == today and self._market_regime is not None:
                    data_pack["regime"] = self._market_regime
                    if self._market_regime_details:
                        data_pack["entropy"] = self._market_regime_details.get("entropy", 0.0)
                        data_pack["turnover_z"] = self._market_regime_details.get("turnover_z", 0.0)
                    return
            
            from ..brain.regime.regime_detector import RegimeDetector

            regime_detector = RegimeDetector()
            # Migrate from deprecated detect_from_data to get_summary
            # Load data via data service instead of fetcher
            df = self.data_service.lake.read_data(
                MarketConstants.INDEX_HS300, data_type="index", market="cn"
            )
            if df is not None and not df.empty:
                regime_result = regime_detector.get_summary(df)
            else:
                regime_result = {"regime": "NORMAL", "entropy": 0.0, "turnover_z": 0.0}
            
            with self._cache_lock:
                self._market_regime = regime_result.get("regime", "NORMAL")
                self._market_regime_details = regime_result
                self._market_cache_date = today
            
            data_pack["regime"] = self._market_regime
            data_pack["entropy"] = regime_result.get("entropy", 0.0)
            data_pack["turnover_z"] = regime_result.get("turnover_z", 0.0)
            
            logger.debug(f"Market regime cached: {self._market_regime}")
        except (ImportError, ModuleNotFoundError) as e:
            logger.warning(f"RegimeDetector 分析失败: {e}")
            data_pack["regime"] = "NORMAL"

    def _run_lppl_detection(self, data_pack: Dict[str, Any]) -> None:
        """Run LPPLEngine analysis (via service layer engine)"""
        try:
            symbol = data_pack.get("symbol", "unknown")
            lppl_result = self.lppl_engine.run_lppl_analysis(symbol=symbol, df=data_pack.get("stock"))
            data_pack["risk"] = lppl_result.get("risk_level", "Safe")
            data_pack["bubble_confidence"] = lppl_result.get("confidence", 0.0)
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"LPPLEngine 分析失败: {e}")
            logger.exception("LPPLEngine 分析详情: ")
            data_pack["risk"] = "Safe"
            data_pack["bubble_confidence"] = 0.0

    def _run_ntf_detection(self, ticker: str, data_pack: Dict[str, Any]) -> None:
        """
        运行 NTFEngine 分析（带市场级缓存 - Thread-safe）
        
        国家队干预信号是全市场共享的，只需计算一次
        """
        try:
            today = pd.Timestamp.now().strftime("%Y-%m-%d")
            
            with self._cache_lock:
                if self._market_cache_date == today and self._ntf_signals is not None:
                    data_pack["ntf_side"] = self._ntf_signals.get("side", "NONE")
                    data_pack["ntf_intensity"] = self._ntf_signals.get("intensity", 0.0)
                    data_pack["ntf_action"] = self._ntf_signals.get("action", "")
                    return

            from ..brain.ntf.ntf_engine import NTFEngine
            from ..data.data_fetcher import DataFetcher

            fetcher = DataFetcher()
            end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
            start_date = (pd.Timestamp.now() - pd.DateOffset(days=TimeConstants.DAYS_MONTH * 3)).strftime("%Y-%m-%d")

            ntf_engine = NTFEngine()
            
            primary_etf = "510300.SH"
            ntf_result = ntf_engine.detect_intervention_from_data(
                fetcher, primary_etf, start_date, end_date
            )
            
            with self._cache_lock:
                self._ntf_signals = ntf_result
                if self._market_cache_date != today:
                    self._market_cache_date = today
            
            data_pack["ntf_side"] = ntf_result.get("side", "NONE")
            data_pack["ntf_intensity"] = ntf_result.get("intensity", 0.0)
            data_pack["ntf_action"] = ntf_result.get("action", "")
            
            logger.debug(f"NTF signals cached: {data_pack['ntf_side']}")
        except (ImportError, ModuleNotFoundError) as e:
            logger.warning(f"NTFEngine 分析失败: {e}")
            data_pack["ntf_side"] = "NONE"
            data_pack["ntf_intensity"] = 0.0

    def _run_czsc_detection(self, ticker: str, data_pack: Dict[str, Any]) -> None:
        """Run CZSCEngine analysis (via service layer engine)"""
        try:
            czsc_result = self.czsc_engine.run_czsc_analysis(symbol=ticker, df=data_pack.get("stock"))
            data_pack["is_3rd_buy"] = czsc_result.get("is_3rd_buy", False)
            data_pack["bi_count"] = czsc_result.get("bi_count", 0)
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"CZSCEngine 分析失败: {e}")
            data_pack["is_3rd_buy"] = False
            data_pack["bi_count"] = 0

    def _run_wyckoff_detection(self, ticker: str, data_pack: Dict[str, Any]) -> None:
        """Run Wyckoff analysis (via service layer engine)"""
        try:
            wyckoff_result = self.wyckoff_engine.run_wyckoff_analysis(
                symbol=ticker, df=data_pack.get("stock")
            )
            data_pack["wyckoff_phase"] = wyckoff_result.get("phase", "unknown")
            data_pack["wyckoff_confidence"] = wyckoff_result.get("confidence", 0.0)
            data_pack["wyckoff_accumulation"] = wyckoff_result.get("accumulation_score", 0.0)
            data_pack["wyckoff_distribution"] = wyckoff_result.get("distribution_score", 0.0)
            data_pack["wyckoff_spring"] = wyckoff_result.get("spring_detected", False)
            data_pack["wyckoff_utad"] = wyckoff_result.get("utad_detected", False)
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"Wyckoff 分析失败: {e}")
            data_pack["wyckoff_phase"] = "unknown"
            data_pack["wyckoff_confidence"] = 0.0

    def _run_alpha_analysis(self, data_pack: Dict[str, Any]) -> None:
        """
        运行 AlphaDecoupler 分析（带基准数据缓存 - Thread-safe）
        
        基准数据（沪深300、中证500）是全市场共享的，只需获取一次
        """
        try:
            from ..brain.alpha_decoupler.alpha_decoupler import AlphaDecoupler
            from ..data.lake.storage_manager import StorageManager

            stock_df = data_pack.get("stock")
            if stock_df is None or stock_df.empty:
                data_pack["alpha_score"] = 0.0
                return

            storage = StorageManager()
            
            bench_df = storage.read_data("000300.SH", "index")
            if bench_df is None or bench_df.empty:
                bench_df = storage.read_data("000300", "index")
            
            sector_df = storage.read_data("000905.SH", "index")
            if sector_df is None or sector_df.empty:
                sector_df = storage.read_data("000905", "index")

            if bench_df is None or bench_df.empty:
                logger.warning("AlphaDecoupler: 无法获取基准数据")
                data_pack["alpha_score"] = 0.0
                return

            data_pack["alpha_score"] = AlphaDecoupler.get_alpha_score(stock_df, bench_df, sector_df)
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"AlphaDecoupler 分析失败: {e}")
            data_pack["alpha_score"] = 0.0

    def _calculate_ma_status(self, data_pack: Dict[str, Any]) -> None:
        """计算 MA 状态"""
        try:
            from ..brain.indicators.indicators import Indicators
            indicators = Indicators()
            ma_short = indicators.calc_ma(data_pack["stock"], window=IndicatorThresholds.MA_SHORT)
            ma_long = indicators.calc_ma(data_pack["stock"], window=IndicatorThresholds.MA_MEDIUM)
            if not ma_short.empty and not ma_long.empty:
                if ma_short.iloc[-1] > ma_long.iloc[-1]:
                    data_pack["ma_status"] = "MA20 > MA60"
                else:
                    data_pack["ma_status"] = "MA20 <= MA60"
            else:
                data_pack["ma_status"] = "DATA_INSUFFICIENT"
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"MA 状态计算失败: {e}")
            data_pack["ma_status"] = "DATA_INSUFFICIENT"

    def _calculate_returns(self, data_pack: Dict[str, Any]) -> None:
        """计算收益率"""
        try:
            data_pack["returns"] = data_pack["stock"]["close"].pct_change().dropna()
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"returns 计算失败: {e}")
            data_pack["returns"] = None

    def _calculate_price_and_stop(self, data_pack: Dict[str, Any]) -> None:
        """计算价格和止损"""
        try:
            data_pack["price"] = data_pack["stock"].iloc[-1]["close"]
            from ..brain.indicators.indicators import Indicators
            indicators = Indicators()
            atr = indicators.calc_atr(data_pack["stock"])
            if not atr.empty:
                data_pack["atr_stop"] = data_pack["price"] - atr.iloc[-1] * 2
            else:
                data_pack["atr_stop"] = data_pack["price"] * 0.95
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"价格和止损计算失败: {e}")
            data_pack["price"] = 0
            data_pack["atr_stop"] = 0

    def _calculate_technical_indicators(self, data_pack: Dict[str, Any]) -> None:
        """计算技术指标用于报告展示"""
        try:
            from ..brain.indicators.indicators import Indicators
            indicators = Indicators()
            stock_df = data_pack.get("stock")
            
            if stock_df is None or stock_df.empty:
                logger.warning("股票数据为空，跳过技术指标计算")
                return
            
            indicators_dict: Dict[str, float] = {}
            
            ma20 = indicators.calc_ma(stock_df, window=20)
            indicators_dict["ma20"] = float(ma20.iloc[-1]) if len(ma20) >= 20 and not ma20.empty else 0.0
            
            ma60 = indicators.calc_ma(stock_df, window=60)
            indicators_dict["ma60"] = float(ma60.iloc[-1]) if len(ma60) >= 60 and not ma60.empty else 0.0
            
            ema20 = indicators.calc_ema(stock_df, window=20)
            indicators_dict["ema20"] = float(ema20.iloc[-1]) if len(ema20) >= 20 and not ema20.empty else 0.0
            
            rsi = indicators.calc_rsi(stock_df, window=14)
            indicators_dict["rsi"] = float(rsi.iloc[-1]) if not rsi.empty and not pd.isna(rsi.iloc[-1]) else 50.0
            
            macd_result = indicators.calc_macd(stock_df)
            if not macd_result.empty:
                indicators_dict["macd"] = float(macd_result["macd"].iloc[-1]) if not pd.isna(macd_result["macd"].iloc[-1]) else 0.0
                indicators_dict["macd_signal"] = float(macd_result["signal"].iloc[-1]) if not pd.isna(macd_result["signal"].iloc[-1]) else 0.0
                indicators_dict["macd_hist"] = float(macd_result["hist"].iloc[-1]) if not pd.isna(macd_result["hist"].iloc[-1]) else 0.0
            else:
                indicators_dict["macd"] = 0.0
                indicators_dict["macd_signal"] = 0.0
                indicators_dict["macd_hist"] = 0.0
            
            atr = indicators.calc_atr(stock_df, window=14)
            indicators_dict["atr"] = float(atr.iloc[-1]) if not atr.empty and not pd.isna(atr.iloc[-1]) else 0.0
            
            bollinger = indicators.calc_bollinger(stock_df, window=20)
            if not bollinger.empty:
                indicators_dict["bollinger_upper"] = float(bollinger["bollinger_upper"].iloc[-1]) if not pd.isna(bollinger["bollinger_upper"].iloc[-1]) else 0.0
                indicators_dict["bollinger_middle"] = float(bollinger["bollinger_middle"].iloc[-1]) if not pd.isna(bollinger["bollinger_middle"].iloc[-1]) else 0.0
                indicators_dict["bollinger_lower"] = float(bollinger["bollinger_lower"].iloc[-1]) if not pd.isna(bollinger["bollinger_lower"].iloc[-1]) else 0.0
            else:
                indicators_dict["bollinger_upper"] = 0.0
                indicators_dict["bollinger_middle"] = 0.0
                indicators_dict["bollinger_lower"] = 0.0
            
            vol_ratio = indicators.calc_vol_ratio(stock_df)
            indicators_dict["vol_ratio"] = float(vol_ratio.iloc[-1]) if not vol_ratio.empty and not pd.isna(vol_ratio.iloc[-1]) else 1.0
            
            market_entropy = indicators.calc_market_entropy(stock_df)
            indicators_dict["market_entropy"] = float(market_entropy.iloc[-1]) if not market_entropy.empty and not pd.isna(market_entropy.iloc[-1]) else 0.0
            
            turnover_z = indicators.calc_turnover_z(stock_df)
            indicators_dict["turnover_z"] = float(turnover_z.iloc[-1]) if not turnover_z.empty and not pd.isna(turnover_z.iloc[-1]) else 0.0
            
            data_pack["indicators"] = indicators_dict
            logger.debug(f"技术指标计算完成: {list(indicators_dict.keys())}")
            
        except RECOVERABLE_ERRORS as e:
            logger.warning(f"技术指标计算失败: {e}")
            data_pack["indicators"] = {}

    def _make_decision(self, ticker: str, data_pack: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """调用大脑进行决策"""
        try:
            return self.brain.make_decision(data_pack)
        except RECOVERABLE_ERRORS as e:
            logger.error(f"{ticker} 决策计算失败: {e}")
            return None

    def _save_analysis_result(
        self, ticker: str, data_pack: Dict[str, Any], decision_result: Dict[str, Any]
    ) -> Optional[str]:
        """保存分析结果到 JSON 文件 (hands/results/YYYY-MM-DD/)"""
        try:
            import json

            date_str = pd.Timestamp.now().strftime(ResultsConstants.DATE_FOLDER_FORMAT)
            
            if ResultsConstants.USE_DATE_FOLDERS:
                result_dir = get_config().ROOT_DIR / ResultsConstants.HANDS_DIR_NAME / ResultsConstants.RESULTS_DIR_NAME / date_str
                filename = f"{ticker}{ResultsConstants.RESULTS_FILE_SUFFIX}"
            else:
                result_dir = get_config().ROOT_DIR / ResultsConstants.HANDS_DIR_NAME / ResultsConstants.RESULTS_DIR_NAME
                date_suffix = pd.Timestamp.now().strftime(ResultsConstants.RESULTS_DATE_FORMAT)
                filename = f"{ticker}_{date_suffix}{ResultsConstants.RESULTS_FILE_SUFFIX}"
            
            result_dir.mkdir(parents=True, exist_ok=True)
            filepath = result_dir / filename

            result_data = {
                "symbol": ticker,
                "date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                "decision_result": decision_result,
                "indicators": data_pack.get("indicators", {}),
                "data_pack": {
                    "regime": data_pack.get("regime", "NORMAL"),
                    "risk": data_pack.get("risk", "Safe"),
                    "bubble_confidence": data_pack.get("bubble_confidence", 0.0),
                    "ntf_side": data_pack.get("ntf_side", "NONE"),
                    "ntf_intensity": data_pack.get("ntf_intensity", 0.0),
                    "is_3rd_buy": data_pack.get("is_3rd_buy", False),
                    "bi_count": data_pack.get("bi_count", 0),
                    "alpha_score": data_pack.get("alpha_score", 0.0),
                    "ma_status": data_pack.get("ma_status", "DATA_INSUFFICIENT"),
                }
            }

            with open(filepath, "w", encoding=ResultsConstants.ENCODING) as f:
                json.dump(result_data, f, ensure_ascii=False, indent=ResultsConstants.JSON_INDENT)

            logger.info(f"计算结果已保存到: {filepath}")
            return str(filepath)
        except (IOError, OSError) as e:
            logger.error(f"保存计算结果失败 (IO错误): {e}")
            return None
        except RECOVERABLE_ERRORS as e:
            logger.error(f"保存计算结果失败: {e}")
            return None

    def _generate_analysis_report(
        self, ticker: str, data_pack: Dict[str, Any],
        decision_result: Dict[str, Any], filepath: Optional[str]
    ) -> bool:
        """生成分析报告"""
        return self.report_engine._generate_analysis_report(ticker, data_pack, decision_result, filepath)

    def list_reports(self) -> List[Dict[str, Any]]:
        """List all generated research reports."""
        return self.report_engine.list_reports()

    def read_report(self, file_path: str) -> str:
        """
        Read content of a report for preview.
        """
        return self.report_engine.read_report(file_path=file_path)

    @handle_errors(
        AnalysisError,
        ServiceError,
        ValueError,
        TypeError,
        default_return=False,
        log_level=logging.ERROR,
        error_type="report_generation",
    )
    @validate_inputs(
        ticker=lambda x: isinstance(x, str) and bool(x.strip()),
    )
    def generate_report(self, ticker: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        生成个股研究报告
        """
        return self.report_engine.generate_report(ticker=ticker, data=data)

    def generate_reports_from_results(
        self,
        symbols: Optional[List[str]] = None,
        date: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, bool]:
        """
        从计算结果批量生成报告（快速模式）

        此方法跳过计算阶段，直接从已保存的结果文件生成报告。
        适用于：
        - 计算已完成，只需重新生成报告
        - 报告模板更新后批量重新生成

        Args:
            symbols: 股票代码列表，None 表示全部
            date: 日期过滤，格式 'YYYYMMDD'
            force: 是否强制重新生成（即使报告已存在）

        Returns:
            股票代码 -> 是否成功的映射
        """
        return self.report_engine.generate_reports_from_results(
            symbols=symbols, date=date, force=force
        )

    def list_available_results(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出可用的计算结果文件

        Args:
            symbol: 股票代码过滤

        Returns:
            结果文件信息列表
        """
        return self.report_engine.list_available_results(symbol=symbol)

    def scan_etfs(self) -> pd.DataFrame:
        """
        扫描ETF并返回分析结果 (优化版：批量预加载)
        """
        try:
            etfs = self.etf_list
            if not etfs:
                etfs = AnalysisServiceConstants.DEFAULT_ETF_LIST

            etf_data = []

            etf_dfs = self.data_service.lake.batch_read_data(
                etfs, data_type="stock", market="cn"
            )

            for etf in etfs:
                try:
                    df = etf_dfs.get(etf)
                    if df is None or df.empty:
                        logger.warning(f"No data available for ETF: {etf}")
                        continue

                    etf_name = self.data_service.get_stock_name(etf)
                    if not etf_name:
                        etf_name = "未知"

                    latest_data = df.iloc[-1].to_dict()
                    etf_data.append(
                        {"code": etf, "name": etf_name, "latest_data": latest_data}
                    )

                except RECOVERABLE_ERRORS as e:
                    logger.error(f"Error analyzing ETF {etf}: {e}")
                    continue

            if not etf_data:
                return pd.DataFrame()

            # 创建DataFrame进行向量化计算
            etf_df = pd.DataFrame(etf_data)

            # 提取所需字段
            def extract_field(row, field):
                return row["latest_data"].get(field, None)

            # 向量化提取字段
            etf_df["close"] = etf_df.apply(
                lambda row: extract_field(row, "close"), axis=1
            )
            etf_df["open"] = etf_df.apply(
                lambda row: extract_field(row, "open"), axis=1
            )
            etf_df["high"] = etf_df.apply(
                lambda row: extract_field(row, "high"), axis=1
            )
            etf_df["pct_change"] = etf_df.apply(
                lambda row: extract_field(row, "pct_change"), axis=1
            )

            # 1. 计算信号：基于收盘价与开盘价的比较
            etf_df["signal"] = np.where(
                (etf_df["close"] > etf_df["open"]),
                "BUY",
                np.where(
                    (etf_df["close"].isnull()) | (etf_df["open"].isnull()),
                    "UNKNOWN",
                    "WAIT",
                ),
            )

            # 2. 计算强度：基于涨跌幅
            etf_df["strength"] = np.where(
                etf_df["pct_change"].notnull(),
                (etf_df["pct_change"] / 100.0).round(4),
                np.where(
                    (etf_df["close"].notnull()) & (etf_df["open"].notnull()),
                    ((etf_df["close"] - etf_df["open"]) / etf_df["open"]).round(4),
                    0.0,
                ),
            )

            # 3. 计算CZSC状态：基于收盘价与最高价的比较
            etf_df["czsc_state"] = np.where(
                (etf_df["close"].notnull()) & (etf_df["high"].notnull()),
                np.where(etf_df["close"] > etf_df["high"] * 0.9, "3rd_BUY", "None"),
                "None",
            )

            # 构建结果DataFrame
            result_df = etf_df[
                ["code", "name", "signal", "strength", "czsc_state"]
            ].rename(
                columns={
                    "code": "Code",
                    "name": "Name",
                    "signal": "Signal",
                    "strength": "Strength",
                    "czsc_state": "CZSC_State",
                }
            )

            return result_df
        except AnalysisError as e:
            logger.error(f"ETF scanning failed: {e}")
            return pd.DataFrame()
        except RECOVERABLE_ERRORS as e:
            logger.critical(f"Unexpected error in scan_etfs: {e}", exc_info=True)
            return pd.DataFrame()

    def run_lppl_analysis(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Run LPPL (Log Periodic Power Law) analysis for bubble detection

        Args:
            symbol: Stock symbol
            df: Optional DataFrame with stock data

        Returns:
            LPPL analysis results
        """
        return self.lppl_engine.run_lppl_analysis(symbol=symbol, df=df)

    def _fallback_lppl_analysis(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """
        降级处理：当LPPL引擎不可用时使用基本统计分析

        Args:
            symbol: Stock symbol
            df: DataFrame with stock data

        Returns:
            Fallback LPPL analysis results
        """
        return self.lppl_engine._fallback_lppl_analysis(symbol=symbol, df=df)

    def run_czsc_analysis(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Run CZSC (缠论) analysis for technical analysis

        Args:
            symbol: Stock symbol
            df: Optional DataFrame with stock data

        Returns:
            CZSC analysis results
        """
        return self.czsc_engine.run_czsc_analysis(symbol=symbol, df=df)

    def _fallback_czsc_analysis(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """
        降级处理：当CZSC引擎不可用时使用基本技术分析

        Args:
            symbol: Stock symbol
            df: DataFrame with stock data

        Returns:
            Fallback CZSC analysis results
        """
        return self.czsc_engine._fallback_czsc_analysis(symbol=symbol, df=df)

    def run_regime_detection(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Run regime detection for market state analysis

        Args:
            symbol: Stock symbol
            df: Optional DataFrame with stock data

        Returns:
            Regime detection results
        """
        return self.regime_engine.run_regime_detection(symbol=symbol, df=df)

    def run_ntf_detection(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Run NTF (National Team Fund) detection for policy intervention analysis

        Args:
            symbol: Stock symbol
            df: Optional DataFrame with stock data

        Returns:
            NTF detection results
        """
        return self.ntf_engine.run_ntf_detection(symbol=symbol, df=df)

    def run_fsm_analysis(self, symbol: str, df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Run FSM (Finite State Machine) analysis for trading logic

        Args:
            symbol: Stock symbol
            df: Optional DataFrame with stock data

        Returns:
            FSM analysis results
        """
        return self.fsm_engine.run_fsm_analysis(symbol=symbol, df=df)

    def _map_decision_to_recommendation(self, decision: str) -> str:
        """
        将FSM决策映射为推荐操作

        Args:
            decision: FSM决策结果

        Returns:
            推荐操作字符串
        """
        return self.fsm_engine._map_decision_to_recommendation(decision=decision)

    def _fallback_fsm_analysis(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """
        降级处理：当FSM引擎不可用时使用基本交易逻辑

        Args:
            symbol: Stock symbol
            df: DataFrame with stock data

        Returns:
            Fallback FSM analysis results
        """
        return self.fsm_engine._fallback_fsm_analysis(symbol=symbol, df=df)

    @handle_errors(
        AnalysisError,
        DataAccessError,
        ValueError,
        TypeError,
        default_return={"error": "分析失败", "status": "failed"},
        log_level=logging.ERROR,
        error_type="comprehensive_analysis",
    )
    @validate_inputs(
        symbol=lambda x: isinstance(x, str) and bool(x.strip()),
    )
    def run_comprehensive_analysis(self, symbol: str) -> Dict[str, Any]:
        """
        Run comprehensive analysis including all models

        Args:
            symbol: Stock symbol

        Returns:
            Comprehensive analysis results
        """
        # 生成缓存键
        cache_key = self._generate_cache_key("comprehensive_analysis", symbol=symbol)

        # 尝试从缓存获取结果
        cached_result = self._get_cached_result(cache_key, use_disk=True)
        if cached_result is not None:
            return cached_result

        # 使用数据湖中的数据，避免网络请求
        df = self.data_service.lake.read_data(symbol, data_type="stock", market="cn")
        if df is None or df.empty:
            logger.warning(f"No data available for {symbol}")
            return {"error": "数据不足", "status": "failed"}

        # 优化DataFrame以提高处理效率
        df = self._optimize_dataframe(df)

        # 对大数据集进行采样
        df = self._sample_data(df, max_rows=2000)

        # Run all analyses with error handling
        analysis_results = {}

        # Run LPPL analysis
        try:
            analysis_results["lppl"] = self.run_lppl_analysis(symbol, df)
        except RECOVERABLE_ERRORS as e:
            logger.error(f"LPPL analysis failed for {symbol}: {e}")
            analysis_results["lppl"] = {"error": "LPPL分析失败", "status": "failed"}

        # Run CZSC analysis
        try:
            analysis_results["czsc"] = self.run_czsc_analysis(symbol, df)
        except RECOVERABLE_ERRORS as e:
            logger.error(f"CZSC analysis failed for {symbol}: {e}")
            analysis_results["czsc"] = {"error": "CZSC分析失败", "status": "failed"}

        # Run FSM analysis
        try:
            analysis_results["fsm"] = self.run_fsm_analysis(symbol, df)
        except RECOVERABLE_ERRORS as e:
            logger.error(f"FSM analysis failed for {symbol}: {e}")
            analysis_results["fsm"] = {"error": "FSM分析失败", "status": "failed"}

        # Run Wyckoff analysis
        try:
            analysis_results["wyckoff"] = self.wyckoff_engine.run_wyckoff_analysis(
                symbol=symbol, df=df
            )
        except RECOVERABLE_ERRORS as e:
            logger.error(f"Wyckoff analysis failed for {symbol}: {e}")
            analysis_results["wyckoff"] = {"error": "Wyckoff分析失败", "status": "failed"}

        # Determine overall recommendation
        fsm_result = analysis_results.get("fsm", {})
        overall_recommendation = fsm_result.get("recommendation", "中性")

        # Combine results
        result = {
            "symbol": symbol,
            "status": "success",
            "lppl": analysis_results.get("lppl", {}),
            "czsc": analysis_results.get("czsc", {}),
            "fsm": analysis_results.get("fsm", {}),
            "wyckoff": analysis_results.get("wyckoff", {}),
            "overall_recommendation": overall_recommendation,
            "summary": "综合分析完成",
        }

        # 验证综合分析结果
        if not self.validate_comprehensive_result(result):
            logger.warning("Comprehensive analysis result validation failed")
            # 虽然验证失败，仍然返回结果，但标记为需要关注
            result["status"] = "warning"
            result["summary"] = "综合分析完成，但部分结果可能存在问题"

        # 生成缓存键
        cache_key = self._generate_cache_key("comprehensive_analysis", symbol=symbol)

        # 缓存计算结果
        self._set_cached_result(cache_key, result, use_disk=True, ttl=7200)  # 2小时缓存

        return result

    @handle_errors(
        DataValidationError,
        ValueError,
        TypeError,
        default_return=pd.DataFrame(),
        log_level=logging.ERROR,
        error_type="lake_data_enrichment",
    )
    @validate_inputs(
        df_raw=lambda x: x is not None,
    )
    def enrich_lake_data(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        """
        Enrich raw lake data with calculated metrics (Signals, Strength, CZSC).
        Moved from AssetManager to ensure proper encapsulation.

        Args:
            df_raw: Raw DataFrame from data lake

        Returns:
            Enriched DataFrame with UI-friendly column names
        """
        if df_raw is None or df_raw.empty:
            logger.warning("Empty DataFrame provided for enrichment")
            return pd.DataFrame()

        # Ensure we have a copy to avoid SettingWithCopyWarning
        df = df_raw.copy()

        # 优化DataFrame以提高处理效率
        df = self._optimize_dataframe(df)

        # 对大数据集进行采样
        df = self._sample_data(df, max_rows=5000)

        # 1. Enrich with Name
        # Ensure stock map is populated
        if not self.data_service.stock_map:
            try:
                self.data_service.refresh_stock_map()
            except RECOVERABLE_ERRORS as e:
                logger.warning(f"Failed to refresh stock map: {e}")

        if "code" not in df.columns and "symbol" in df.columns:
            df["code"] = df["symbol"]

        # Safe get name
        if "code" in df.columns:
            # 向量化获取股票名称
            def get_stock_name_vectorized(code):
                return self.data_service.get_stock_name(code)

            # 使用向量化操作
            df["name"] = df["code"].apply(get_stock_name_vectorized)
        else:
            logger.warning("No 'code' or 'symbol' column found in DataFrame")
            df["name"] = "未知"

        # 2. Enrich with basic metrics
        # Signal: Simple moving average comparison or just close > open for now
        if "close" in df.columns and "open" in df.columns:
            # 向量化计算信号
            df["signal"] = np.where(df["close"] > df["open"], "BUY", "WAIT")
        else:
            df["signal"] = "UNKNOWN"

        # Strength: Pct Change
        if "pct_change" in df.columns:
            # 向量化计算强度
            df["strength"] = (df["pct_change"] / 100.0).round(4)
        elif "close" in df.columns and "open" in df.columns:
            # 向量化计算强度，防御 open == 0
            df["strength"] = ((df["close"] - df["open"]) / df["open"].replace(0, np.nan)).round(4)
        else:
            df["strength"] = 0.0

        # CZSC Stat: Based on close vs high
        if "close" in df.columns and "high" in df.columns:
            # 向量化计算CZSC状态
            df["czsc_stat"] = np.where(
                df["close"] > df["high"] * 0.9, "3rd_BUY", "None"
            )
        else:
            df["czsc_stat"] = "None"

        # 3. Select and Rename for UI
        required_cols = [
            "code",
            "name",
            "signal",
            "strength",
            "czsc_stat",
            "close",
            "volume",
            "date",
        ]

        # Filter only existing columns
        available_cols = [c for c in required_cols if c in df.columns]
        if not available_cols:
            logger.warning("No required columns found in DataFrame")
            return pd.DataFrame()

        final_df = df[available_cols]

        # Renaming map
        rename_map = {
            "code": "Code",
            "name": "Name",
            "signal": "Signal",
            "strength": "Strength",
            "czsc_stat": "CZSC",
            "close": "Price",
            "volume": "Volume",
            "date": "Date",
        }

        # Only rename existing columns
        final_rename_map = {
            k: v for k, v in rename_map.items() if k in final_df.columns
        }
        final_df = final_df.rename(columns=final_rename_map)

        return final_df
