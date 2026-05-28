import threading
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..shared.constants import RiskCalculationConstants
from ..shared.exceptions import RiskCalculationError
from ..shared.logger_factory import get_logger


RECOVERABLE_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

logger = get_logger("HistoricalSimulationRisk")

class HistoricalSimulationRisk:
    """
    Historical Simulation based risk calculator.
    
    Uses historical percentile method (np.percentile) for VaR and CVaR calculation.
    Thread-safe implementation with lock-protected cache.
    
    Note: This is NOT true Extreme Value Theory (GPD fitting).
    For true EVT with GPD, use scipy.stats.genpareto.
    """

    def __init__(self):
        self._metrics_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = threading.Lock()

    @property
    def metrics_cache(self) -> Dict[str, Dict[str, Any]]:
        """Thread-safe cache access (read-only view)"""
        with self._cache_lock:
            return self._metrics_cache.copy()

    def _get_cached_metrics(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Thread-safe cache read"""
        with self._cache_lock:
            return self._metrics_cache.get(cache_key)

    def _set_cached_metrics(self, cache_key: str, metrics: Dict[str, Any]) -> None:
        """Thread-safe cache write"""
        with self._cache_lock:
            self._metrics_cache[cache_key] = metrics

    def clear_cache(self) -> None:
        """Thread-safe cache clear"""
        with self._cache_lock:
            self._metrics_cache.clear()

    def calculate_metrics(self, returns: pd.Series) -> Dict[str, Any]:
        """
        Calculate risk metrics using EVT.

        Args:
            returns: Series of returns

        Returns:
            Dictionary of risk metrics
        """
        try:
            cache_key = self._generate_cache_key(returns)

            cached = self._get_cached_metrics(cache_key)
            if cached is not None:
                logger.info("EVT metrics cache hit")
                return cached

            var_95 = self.calculate_var(returns, 0.95)
            var_99 = self.calculate_var(returns, 0.99)
            cvar_95 = self.calculate_cvar(returns, 0.95)
            cvar_99 = self.calculate_cvar(returns, 0.99)

            regime = self.detect_regime(returns)

            max_drawdown = self.calculate_max_drawdown(returns)

            ntf_signal = self.calculate_ntf_signal(var_95, max_drawdown, regime)

            summary = self.generate_summary(regime, var_95, max_drawdown, ntf_signal)

            metrics = {
                "var_95": var_95,
                "var_99": var_99,
                "cvar_95": cvar_95,
                "cvar_99": cvar_99,
                "max_drawdown": max_drawdown,
                "regime": regime,
                "ntf_signal": ntf_signal,
                "summary": summary,
            }

            self._set_cached_metrics(cache_key, metrics)

            return metrics
        except RiskCalculationError as e:
            logger.error(f"Risk calculation failed: {e}")
            return self._get_default_metrics()
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid input data: {e}")
            return self._get_default_metrics()
        except RECOVERABLE_ERRORS as e:
            logger.critical(
                f"Unexpected error in calculate_metrics: {e}", exc_info=True
            )
            return self._get_default_metrics()

    def _generate_cache_key(self, returns: pd.Series) -> str:
        """
        Generate a cache key for returns series.
        """
        if returns.empty:
            return "empty"

        mean = returns.mean()
        std = returns.std()
        skew = returns.skew()
        kurt = returns.kurtosis()

        return f"{mean:.4f}_{std:.4f}_{skew:.4f}_{kurt:.4f}_{len(returns)}"

    def calculate_var(self, returns: pd.Series, confidence: float) -> float:
        """
        Calculate Value at Risk (VaR).
        """
        try:
            if returns.empty:
                raise RiskCalculationError("Empty returns series")

            var = -np.percentile(returns, (1 - confidence) * 100)
            return float(var)
        except RiskCalculationError as e:
            logger.error(f"Failed to calculate VaR: {e}")
            return RiskCalculationConstants.VAR_THRESHOLD_HIGH
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid input for VaR calculation: {e}")
            return RiskCalculationConstants.VAR_THRESHOLD_HIGH
        except RECOVERABLE_ERRORS as e:
            logger.critical(f"Unexpected error in calculate_var: {e}", exc_info=True)
            return RiskCalculationConstants.VAR_THRESHOLD_HIGH

    def calculate_cvar(self, returns: pd.Series, confidence: float) -> float:
        """
        Calculate Conditional Value at Risk (CVaR).
        CVaR is the expected loss given that loss exceeds VaR.
        Mathematical guarantee: CVaR >= VaR.
        """
        try:
            if returns.empty:
                raise RiskCalculationError("Empty returns series")

            var = self.calculate_var(returns, confidence)
            tail_returns = returns[returns <= -var]
            if tail_returns.empty:
                # 空尾部时 CVaR 至少等于 VaR
                return float(var)
            cvar = -tail_returns.mean()
            return float(cvar)
        except RiskCalculationError as e:
            logger.error(f"Failed to calculate CVaR: {e}")
            return RiskCalculationConstants.CVAR_THRESHOLD_HIGH
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid input for CVaR calculation: {e}")
            return RiskCalculationConstants.CVAR_THRESHOLD_HIGH
        except RECOVERABLE_ERRORS as e:
            logger.critical(f"Unexpected error in calculate_cvar: {e}", exc_info=True)
            return RiskCalculationConstants.CVAR_THRESHOLD_HIGH

    def detect_regime(self, returns: pd.Series) -> str:
        """
        Detect market regime based on returns characteristics.
        """
        try:
            if returns.empty:
                raise RiskCalculationError("Empty returns series")

            volatility = returns.std() * np.sqrt(252)

            sharpe = (
                returns.mean() / returns.std() * np.sqrt(252)
                if returns.std() > 0
                else 0
            )

            if volatility > RiskCalculationConstants.VOLATILITY_HIGH:
                return "CRISIS"
            elif volatility > RiskCalculationConstants.VOLATILITY_MEDIUM:
                return "HIGH_VOL"
            elif sharpe > RiskCalculationConstants.SHARPE_RATIO_BULL:
                return "BULL"
            elif sharpe < RiskCalculationConstants.SHARPE_RATIO_BEAR:
                return "BEAR"
            else:
                return "NORMAL"
        except RiskCalculationError as e:
            logger.error(f"Failed to detect regime: {e}")
            return "NORMAL"
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid input for regime detection: {e}")
            return "NORMAL"
        except RECOVERABLE_ERRORS as e:
            logger.critical(f"Unexpected error in detect_regime: {e}", exc_info=True)
            return "NORMAL"

    def calculate_max_drawdown(self, returns: pd.Series) -> float:
        """
        Calculate maximum drawdown.
        """
        try:
            if returns.empty:
                raise RiskCalculationError("Empty returns series")

            cum_returns = (1 + returns).cumprod()

            running_max = cum_returns.cummax()

            drawdowns = (cum_returns - running_max) / running_max

            max_drawdown = -drawdowns.min()
            return float(max_drawdown)
        except RiskCalculationError as e:
            logger.error(f"Failed to calculate max drawdown: {e}")
            return RiskCalculationConstants.MAX_DRAWDOWN_THRESHOLD
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid input for max drawdown calculation: {e}")
            return RiskCalculationConstants.MAX_DRAWDOWN_THRESHOLD
        except RECOVERABLE_ERRORS as e:
            logger.critical(
                f"Unexpected error in calculate_max_drawdown: {e}", exc_info=True
            )
            return RiskCalculationConstants.MAX_DRAWDOWN_THRESHOLD

    def calculate_ntf_signal(self, var: float, max_drawdown: float, regime: str) -> str:
        """
        Calculate NTF (Nowcasting Trend Factor) signal.
        """
        try:
            if regime == "CRISIS" or max_drawdown > RiskCalculationConstants.VOLATILITY_HIGH:
                return "极度风险"
            elif regime == "HIGH_VOL" or var > RiskCalculationConstants.VAR_THRESHOLD_HIGH:
                return "高风险"
            elif regime == "BEAR":
                return "风险"
            elif regime == "BULL":
                return "机会"
            else:
                return "中性"
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid input for NTF signal calculation: {e}")
            return "中性"
        except RECOVERABLE_ERRORS as e:
            logger.critical(
                f"Unexpected error in calculate_ntf_signal: {e}", exc_info=True
            )
            return "中性"

    def generate_summary(
        self, regime: str, var: float, max_drawdown: float, ntf_signal: str
    ) -> str:
        """
        Generate risk summary.
        """
        try:
            summary = f"市场状态: {regime}\n"
            summary += f"95% VaR: {var:.2%}\n"
            summary += f"最大回撤: {max_drawdown:.2%}\n"
            summary += f"NTF信号: {ntf_signal}\n"
            summary += "宏观环境分析完成"
            return summary
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid input for summary generation: {e}")
            return "宏观环境分析完成"
        except RECOVERABLE_ERRORS as e:
            logger.critical(f"Unexpected error in generate_summary: {e}", exc_info=True)
            return "宏观环境分析完成"

    def _get_default_metrics(self) -> Dict[str, Any]:
        """
        Get default risk metrics when calculation fails.
        """
        return {
            "var_95": 0.02,
            "var_99": 0.04,
            "cvar_95": 0.03,
            "cvar_99": 0.06,
            "max_drawdown": 0.2,
            "regime": "NORMAL",
            "ntf_signal": "中性",
            "summary": "宏观环境分析完成",
        }

    def calculate_stress_test(
        self, returns: pd.Series, scenarios: List[str]
    ) -> Dict[str, float]:
        """
        Calculate stress test results for different scenarios.
        
        修复: 使用历史崩盘场景进行真正的压力测试，而非简单的收益放大
        
        Args:
            returns: 收益率序列
            scenarios: 压力测试场景列表
            
        Returns:
            Dict[str, float]: 各场景下的压力测试结果
        """
        try:
            if returns.empty:
                logger.warning("Empty returns series for stress test")
                return {}
            
            stress_results = {}
            current_value = 1.0
            
            all_scenarios = {
                **RiskCalculationConstants.CRASH_SCENARIOS,
                **RiskCalculationConstants.RATE_HIKE_SCENARIOS,
                **RiskCalculationConstants.RECESSION_SCENARIOS,
            }
            
            for scenario in scenarios:
                if scenario in all_scenarios:
                    crash_pct = all_scenarios[scenario]
                    stressed_value = current_value * (1 + crash_pct)
                    volatility_adj = returns.std() * np.sqrt(252)
                    stressed_value *= (1 - volatility_adj * 0.5)
                    stress_results[scenario] = float(stressed_value - current_value)
                elif scenario == "market_crash":
                    crash_pct = RiskCalculationConstants.CRASH_SCENARIOS["market_crash_2015"]
                    stressed_value = current_value * (1 + crash_pct)
                    stress_results[scenario] = float(stressed_value - current_value)
                elif scenario == "interest_rate_hike":
                    rate_impact = RiskCalculationConstants.RATE_HIKE_SCENARIOS["rate_hike_50bp"]
                    stressed_value = current_value * (1 + rate_impact)
                    stress_results[scenario] = float(stressed_value - current_value)
                elif scenario == "recession":
                    recession_pct = RiskCalculationConstants.RECESSION_SCENARIOS["moderate_recession"]
                    stressed_value = current_value * (1 + recession_pct)
                    stress_results[scenario] = float(stressed_value - current_value)
                else:
                    logger.warning(f"Unknown stress test scenario: {scenario}")
            
            return stress_results
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid input for stress test calculation: {e}")
            return {}
        except RECOVERABLE_ERRORS as e:
            logger.critical(
                f"Unexpected error in calculate_stress_test: {e}", exc_info=True
            )
            return {}

    def calculate_correlation_matrix(
        self, assets_returns: Dict[str, pd.Series]
    ) -> Optional[pd.DataFrame]:
        """
        Calculate correlation matrix for multiple assets.
        """
        try:
            if not assets_returns:
                raise RiskCalculationError("No assets returns provided")

            df = pd.DataFrame(assets_returns)

            corr_matrix = df.corr()
            return corr_matrix
        except RiskCalculationError as e:
            logger.error(f"Failed to calculate correlation matrix: {e}")
            return None
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid input for correlation matrix calculation: {e}")
            return None
        except RECOVERABLE_ERRORS as e:
            logger.critical(
                f"Unexpected error in calculate_correlation_matrix: {e}", exc_info=True
            )
            return None


EVTRisk = HistoricalSimulationRisk
