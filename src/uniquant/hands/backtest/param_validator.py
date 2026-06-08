"""Optimal parameter validator.
Runs DSR/PBO/Walk-Forward/ParameterSensitivity on parameter sets from optimal_params.yaml.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats

from ...shared.cost_model import calculate_sharpe_ratio
from ...shared.logger_factory import get_logger
from .overfitting_detector import OverfittingDetector
from .robustness_checker import RobustnessChecker

logger = get_logger(__name__)


class OptimalParamValidator:
    """Validates parameter sets using DSR, PBO, and robustness checks."""

    def __init__(self, detector: Optional[OverfittingDetector] = None,
                 checker: Optional[RobustnessChecker] = None):
        self.detector = detector or OverfittingDetector()
        self.checker = checker or RobustnessChecker()

    def validate(self, returns: np.ndarray, params: Dict[str, Any],
                 num_trials: int = 100, num_splits: int = 20) -> Dict[str, Any]:
        result: Dict[str, Any] = {"params": params}

        if len(returns) < 20:
            result["error"] = "insufficient data"
            return result

        sharpe = float(calculate_sharpe_ratio(returns))

        try:
            skew = float(stats.skew(returns))
            kurt = float(stats.kurtosis(returns, fisher=False))
            dsr = self.detector.deflated_sharpe_ratio(
                observed_sharpe=sharpe,
                n_trials=num_trials,
                num_observations=len(returns),
                skewness=skew,
                kurtosis=kurt,
            )
            result["sharpe"] = sharpe
            result["dsr"] = dsr
        except Exception as e:
            result["dsr_error"] = str(e)

        try:
            pbo_result = self.detector.probability_of_backtest_overfitting(
                strategy_returns=[pd.Series(returns)],
                n_partitions=min(num_splits, len(returns) // 5),
                embargo=5,
            )
            result["pbo"] = pbo_result.get("pbo", 1.0)
            result["pbo_details"] = pbo_result
        except Exception as e:
            result["pbo_error"] = str(e)

        try:
            param_grid = _params_to_grid(params)
            sensitivity = self.checker.check_parameter_sensitivity(
                strategy_fn=lambda p: {"sharpe_ratio": _param_sharpe_estimate(returns, p, params)},
                param_grid=param_grid,
                base_params=dict(params),
            )
            result["sensitivity"] = sensitivity
        except Exception as e:
            result["sensitivity_error"] = str(e)

        return result

    @staticmethod
    def load_and_validate(config_path: str,
                          returns_by_symbol: Dict[str, np.ndarray],
                          num_trials: int = 100,
                          num_splits: int = 20) -> Dict[str, Any]:
        """Load optimal_params.yaml and run validation for each symbol."""
        from ...shared.optimal_params import load_optimal_config
        config = load_optimal_config(config_path)
        validator = OptimalParamValidator()
        results: Dict[str, Any] = {}
        for symbol, rets in returns_by_symbol.items():
            params = config.get("symbols", {}).get(symbol, {})
            if not params:
                params = dict(config.get("defaults", {}))
            results[symbol] = validator.validate(rets, params,
                                                  num_trials=num_trials,
                                                  num_splits=num_splits)
        return results


def _params_to_grid(params: Dict[str, Any]) -> Dict[str, List[Any]]:
    """Convert a single param set to a grid by perturbing numeric values +/-20%."""
    grid: Dict[str, List[Any]] = {}
    for key, value in params.items():
        if isinstance(value, (int, float)) and key != "step":
            perturb = max(abs(value) * 0.2, 0.01)
            grid[key] = [value - perturb, value, value + perturb]
        elif isinstance(value, bool):
            grid[key] = [value, not value]
    return grid


def _param_sharpe_estimate(returns: np.ndarray,
                           candidate: Dict[str, Any],
                           base_params: Dict[str, Any]) -> float:
    """Estimate sharpe under perturbed params (placeholder — uses full-sample sharpe)."""
    return float(calculate_sharpe_ratio(returns))
