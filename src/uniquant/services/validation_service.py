import logging
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from ..shared.constants import PrecisionConstants
from ..shared.exceptions import ValidationError
from ..shared.logger_factory import get_logger

logger = get_logger("ValidationService")


class ValidationService:
    """
    验证服务，用于与标准计算方法的对比和验证
    """

    def __init__(self):
        """
        初始化验证服务
        """
        self.precision = PrecisionConstants.FLOAT_TOLERANCE

    def validate_risk_metrics(
        self, calculated: Dict[str, Any], expected: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证风险指标计算结果

        Args:
            calculated: 计算的风险指标
            expected: 预期的风险指标

        Returns:
            验证结果，包含每个指标的差异和验证状态
        """
        try:
            validation_results = {}
            all_valid = True

            # 验证VaR值
            for var_key in ["var_95", "var_99"]:
                if var_key in calculated and var_key in expected:
                    calc_value = calculated[var_key]
                    exp_value = expected[var_key]
                    diff = abs(calc_value - exp_value)
                    valid = diff < self.precision or diff / max(exp_value, 1e-10) < 0.01
                    validation_results[var_key] = {
                        "calculated": calc_value,
                        "expected": exp_value,
                        "difference": diff,
                        "valid": valid,
                    }
                    if not valid:
                        all_valid = False
                        logger.warning(
                            "VaR validation failed for {}: calculated={}, expected={}", var_key, calc_value, exp_value
                        )

            # 验证CVaR值
            for cvar_key in ["cvar_95", "cvar_99"]:
                if cvar_key in calculated and cvar_key in expected:
                    calc_value = calculated[cvar_key]
                    exp_value = expected[cvar_key]
                    diff = abs(calc_value - exp_value)
                    valid = diff < self.precision or diff / max(exp_value, 1e-10) < 0.01
                    validation_results[cvar_key] = {
                        "calculated": calc_value,
                        "expected": exp_value,
                        "difference": diff,
                        "valid": valid,
                    }
                    if not valid:
                        all_valid = False
                        logger.warning(
                            "CVaR validation failed for {}: calculated={}, expected={}", cvar_key, calc_value, exp_value
                        )

            # 验证最大回撤
            if "max_drawdown" in calculated and "max_drawdown" in expected:
                calc_value = calculated["max_drawdown"]
                exp_value = expected["max_drawdown"]
                diff = abs(calc_value - exp_value)
                valid = diff < self.precision or diff / max(exp_value, 1e-10) < 0.01
                validation_results["max_drawdown"] = {
                    "calculated": calc_value,
                    "expected": exp_value,
                    "difference": diff,
                    "valid": valid,
                }
                if not valid:
                    all_valid = False
                    logger.warning(
                        "Max drawdown validation failed: calculated={}, expected={}", calc_value, exp_value
                    )

            # 验证市场状态
            if "regime" in calculated and "regime" in expected:
                valid = calculated["regime"] == expected["regime"]
                validation_results["regime"] = {
                    "calculated": calculated["regime"],
                    "expected": expected["regime"],
                    "valid": valid,
                }
                if not valid:
                    all_valid = False
                    logger.warning(
                        "Regime validation failed: calculated={}, expected={}", calculated['regime'], expected['regime']
                    )

            return {"all_valid": all_valid, "results": validation_results}

        except (ValueError, KeyError, TypeError) as e:
            logger.error("Error validating risk metrics: %s", e)
            return {"all_valid": False, "results": {}, "error": str(e)}

    def calculate_standard_var(self, returns: pd.Series, confidence: float) -> float:
        """
        使用标准方法计算Value at Risk (VaR)

        Args:
            returns: 收益率序列
            confidence: 置信水平

        Returns:
            VaR值
        """
        try:
            if returns.empty:
                raise ValidationError("Empty returns series")

            var = -np.percentile(returns, (1 - confidence) * 100)
            return float(var)
        except ValidationError as e:
            logger.error("Failed to calculate standard VaR: %s", e)
            return 0.0
        except (ValueError, TypeError) as e:
            logger.error("Error calculating standard VaR: %s", e)
            return 0.0

    def calculate_standard_cvar(self, returns: pd.Series, confidence: float) -> float:
        """
        使用标准方法计算Conditional Value at Risk (CVaR)

        Args:
            returns: 收益率序列
            confidence: 置信水平

        Returns:
            CVaR值
        """
        try:
            if returns.empty:
                raise ValidationError("Empty returns series")

            var = self.calculate_standard_var(returns, confidence)
            cvar = -returns[returns <= -var].mean()
            return float(cvar)
        except ValidationError as e:
            logger.error("Failed to calculate standard CVaR: %s", e)
            return 0.0
        except (ValueError, TypeError) as e:
            logger.error("Error calculating standard CVaR: %s", e)
            return 0.0

    def calculate_standard_max_drawdown(self, returns: pd.Series) -> float:
        """
        使用标准方法计算最大回撤

        Args:
            returns: 收益率序列

        Returns:
            最大回撤值
        """
        try:
            if returns.empty:
                raise ValidationError("Empty returns series")

            # 计算累计收益率
            cum_returns = (1 + returns).cumprod()
            # 计算运行最大值
            running_max = cum_returns.cummax()
            # 计算回撤
            drawdowns = (cum_returns - running_max) / running_max
            # 计算最大回撤
            max_drawdown = -drawdowns.min()
            return float(max_drawdown)
        except ValidationError as e:
            logger.error("Failed to calculate standard max drawdown: %s", e)
            return 0.0
        except (ValueError, TypeError) as e:
            logger.error("Error calculating standard max drawdown: %s", e)
            return 0.0

    def validate_technical_indicators(
        self, calculated: Dict[str, Any], expected: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证技术指标计算结果

        Args:
            calculated: 计算的技术指标
            expected: 预期的技术指标

        Returns:
            验证结果
        """
        try:
            validation_results = {}
            all_valid = True

            # 验证信号强度
            if "signal_strength" in calculated and "signal_strength" in expected:
                calc_value = calculated["signal_strength"]
                exp_value = expected["signal_strength"]
                diff = abs(calc_value - exp_value)
                valid = diff < self.precision or diff / max(exp_value, 1e-10) < 0.05
                validation_results["signal_strength"] = {
                    "calculated": calc_value,
                    "expected": exp_value,
                    "difference": diff,
                    "valid": valid,
                }
                if not valid:
                    all_valid = False
                    logger.warning(
                        "Signal strength validation failed: calculated={}, expected={}", calc_value, exp_value
                    )

            # 验证止损和止盈价格
            for price_key in ["stop_loss", "take_profit"]:
                if price_key in calculated and price_key in expected:
                    calc_value = calculated[price_key]
                    exp_value = expected[price_key]
                    diff = abs(calc_value - exp_value)
                    valid = diff < self.precision or diff / max(exp_value, 1e-10) < 0.01
                    validation_results[price_key] = {
                        "calculated": calc_value,
                        "expected": exp_value,
                        "difference": diff,
                        "valid": valid,
                    }
                    if not valid:
                        all_valid = False
                        logger.warning(
                            "Price validation failed for {}: calculated={}, expected={}", price_key, calc_value, exp_value
                        )

            return {"all_valid": all_valid, "results": validation_results}

        except (ValueError, KeyError, TypeError) as e:
            logger.error("Error validating technical indicators: %s", e)
            return {"all_valid": False, "results": {}, "error": str(e)}

    def compare_calculation_methods(self, returns: pd.Series) -> Dict[str, Any]:
        """
        比较不同计算方法的结果

        Args:
            returns: 收益率序列

        Returns:
            比较结果
        """
        try:
            # 计算标准方法的结果
            standard_results = {
                "var_95": self.calculate_standard_var(returns, 0.95),
                "var_99": self.calculate_standard_var(returns, 0.99),
                "cvar_95": self.calculate_standard_cvar(returns, 0.95),
                "cvar_99": self.calculate_standard_cvar(returns, 0.99),
                "max_drawdown": self.calculate_standard_max_drawdown(returns),
            }

            # 计算替代方法的结果（例如使用不同的分位数计算方法）
            alternative_results = {
                "var_95": self._calculate_alternative_var(returns, 0.95),
                "var_99": self._calculate_alternative_var(returns, 0.99),
                "cvar_95": self._calculate_alternative_cvar(returns, 0.95),
                "cvar_99": self._calculate_alternative_cvar(returns, 0.99),
                "max_drawdown": self._calculate_alternative_max_drawdown(returns),
            }

            # 验证两种方法的结果
            validation_result = self.validate_risk_metrics(
                alternative_results, standard_results
            )

            return {
                "standard_method": standard_results,
                "alternative_method": alternative_results,
                "validation": validation_result,
            }

        except (ValueError, KeyError, TypeError) as e:
            logger.error("Error comparing calculation methods: %s", e)
            return {"error": str(e)}

    def _calculate_alternative_var(
        self, returns: pd.Series, confidence: float
    ) -> float:
        """
        使用替代方法计算VaR（例如使用排序方法）

        Args:
            returns: 收益率序列
            confidence: 置信水平

        Returns:
            VaR值
        """
        try:
            if returns.empty:
                return 0.0

            # 使用排序方法计算分位数
            sorted_returns = np.sort(returns)
            index = int((1 - confidence) * len(sorted_returns))
            var = -sorted_returns[index]
            return float(var)
        except (ValueError, TypeError, IndexError) as e:
            logger.error("Error calculating alternative VaR: %s", e)
            return 0.0

    def _calculate_alternative_cvar(
        self, returns: pd.Series, confidence: float
    ) -> float:
        """
        使用替代方法计算CVaR

        Args:
            returns: 收益率序列
            confidence: 置信水平

        Returns:
            CVaR值
        """
        try:
            if returns.empty:
                return 0.0

            var = self._calculate_alternative_var(returns, confidence)
            tail_returns = returns[returns <= -var]
            if tail_returns.empty:
                return var
            cvar = -tail_returns.mean()
            return float(cvar)
        except (ValueError, TypeError, IndexError) as e:
            logger.error("Error calculating alternative CVaR: %s", e)
            return 0.0

    def _calculate_alternative_max_drawdown(self, returns: pd.Series) -> float:
        """
        使用替代方法计算最大回撤

        Args:
            returns: 收益率序列

        Returns:
            最大回撤值
        """
        try:
            if returns.empty:
                return 0.0

            # 计算累计收益率
            cum_returns = (1 + returns).cumprod()
            # 计算每个点的回撤
            drawdowns = []
            peak = cum_returns.iloc[0]
            for value in cum_returns:
                if value > peak:
                    peak = value
                drawdown = (value - peak) / peak
                drawdowns.append(drawdown)
            max_drawdown = -min(drawdowns)
            return float(max_drawdown)
        except (ValueError, TypeError, ZeroDivisionError) as e:
            logger.error("Error calculating alternative max drawdown: %s", e)
            return 0.0

    def generate_validation_report(self, validation_results: Dict[str, Any]) -> str:
        """
        生成验证报告

        Args:
            validation_results: 验证结果

        Returns:
            验证报告字符串
        """
        try:
            report = "=== 计算方法验证报告 ===\n"
            report += f"整体验证状态: {'通过' if validation_results.get('all_valid', False) else '失败'}\n\n"

            results = validation_results.get("results", {})
            for metric, result in results.items():
                report += f"指标: {metric}\n"
                report += f"  计算值: {result.get('calculated', 'N/A')}\n"
                report += f"  预期值: {result.get('expected', 'N/A')}\n"
                if "difference" in result:
                    report += f"  差异: {result['difference']}\n"
                report += f"  验证状态: {'通过' if result.get('valid', False) else '失败'}\n\n"

            if "error" in validation_results:
                report += f"错误信息: {validation_results['error']}\n"

            report += "=== 报告结束 ==="
            return report

        except (ValueError, KeyError, TypeError) as e:
            logger.error("Error generating validation report: %s", e)
            return f"生成验证报告时出错: {e}"
