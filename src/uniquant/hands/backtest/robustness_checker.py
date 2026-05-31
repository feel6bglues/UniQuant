from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from ...shared.cost_model import calculate_sharpe_ratio
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class RobustnessChecker:
    """
    策略稳健性检查器
    
    检查策略在不同市场条件下的表现稳健性:
    - 市场状态稳定性
    - 参数敏感性
    - 子区间一致性
    - 交易成本敏感性
    """

    def __init__(self):
        pass

    def check_market_regime_stability(
        self,
        strategy_returns: pd.Series,
        market_regime: pd.Series,
    ) -> Dict[str, Any]:
        """
        检查策略在不同市场状态下的表现稳定性
        
        Args:
            strategy_returns: 策略日收益率
            market_regime: 市场状态标签 (如 "bull", "bear", "sideways")
            
        Returns:
            各市场状态下的绩效统计
        """
        if strategy_returns.empty or market_regime.empty:
            return {"error": "输入数据为空"}

        combined = pd.DataFrame({
            "return": strategy_returns,
            "regime": market_regime,
        }).dropna()

        if combined.empty:
            return {"error": "合并后无有效数据"}

        regimes = combined["regime"].unique()
        regime_stats: Dict[str, Any] = {}

        for regime in regimes:
            regime_ret = combined[combined["regime"] == regime]["return"]
            if len(regime_ret) < 5:
                continue

            sharpe = calculate_sharpe_ratio(regime_ret.tolist())
            regime_stats[str(regime)] = {
                "n_observations": len(regime_ret),
                "mean_return": float(np.mean(regime_ret)),
                "std_return": float(np.std(regime_ret)),
                "sharpe_ratio": float(sharpe),
                "cumulative_return": float(np.prod(1 + regime_ret) - 1),
                "win_rate": float(np.mean(regime_ret > 0)),
            }

        all_sharpes = [v["sharpe_ratio"] for v in regime_stats.values()]
        stability_score = float(np.std(all_sharpes)) if all_sharpes else 0

        return {
            "regime_stats": regime_stats,
            "stability_score": stability_score,
            "n_regimes": len(regime_stats),
        }

    def check_parameter_sensitivity(
        self,
        strategy_fn: Callable,
        param_grid: Dict[str, List[Any]],
        base_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        检查策略对参数变化的敏感性
        
        Args:
            strategy_fn: 策略函数，接收参数字典返回绩效指标
            param_grid: 参数网格，参数名到取值列表的映射
            base_params: 基准参数
            
        Returns:
            各参数的敏感性分析
        """
        if base_params is None:
            base_params = {k: v[0] for k, v in param_grid.items() if v}

        base_result = strategy_fn(base_params)
        base_metric = base_result.get("sharpe_ratio", 0) if isinstance(base_result, dict) else base_result

        sensitivities: Dict[str, Any] = {}

        for param_name, param_values in param_grid.items():
            if len(param_values) < 2:
                continue

            metrics = []
            for val in param_values:
                params = dict(base_params)
                params[param_name] = val
                result = strategy_fn(params)
                metric = result.get("sharpe_ratio", 0) if isinstance(result, dict) else result
                metrics.append(metric)

            metrics = np.array(metrics)
            sensitivities[param_name] = {
                "values": param_values,
                "metrics": metrics.tolist(),
                "mean_metric": float(np.mean(metrics)),
                "std_metric": float(np.std(metrics)),
                "min_metric": float(np.min(metrics)),
                "max_metric": float(np.max(metrics)),
                "sensitivity": float(np.std(metrics) / max(abs(base_metric), 1e-10)),
            }

        return {
            "base_metric": base_metric,
            "sensitivities": sensitivities,
            "most_sensitive": max(sensitivities, key=lambda k: sensitivities[k]["sensitivity"]) if sensitivities else None,
        }

    def check_subperiod_consistency(
        self,
        strategy_returns: pd.Series,
        n_splits: int = 4,
    ) -> Dict[str, Any]:
        """
        检查策略在不同子区间的一致性
        
        Args:
            strategy_returns: 策略日收益率
            n_splits: 分割区间数
            
        Returns:
            各子区间的绩效对比
        """
        if strategy_returns.empty or len(strategy_returns) < n_splits * 10:
            return {"error": "数据不足以分割"}

        splits = np.array_split(strategy_returns, n_splits)
        period_stats = []

        for i, split in enumerate(splits):
            if len(split) < 5:
                continue
            sharpe = calculate_sharpe_ratio(split.tolist())
            period_stats.append({
                "period": i + 1,
                "n_observations": len(split),
                "mean_return": float(np.mean(split)),
                "volatility": float(np.std(split)),
                "sharpe_ratio": float(sharpe),
                "cumulative_return": float(np.prod(1 + split) - 1),
                "win_rate": float(np.mean(split > 0)),
            })

        sharpes = [p["sharpe_ratio"] for p in period_stats]
        n_positive = sum(1 for s in sharpes if s > 0)

        return {
            "period_stats": period_stats,
            "mean_sharpe": float(np.mean(sharpes)) if sharpes else 0,
            "std_sharpe": float(np.std(sharpes)) if sharpes else 0,
            "min_sharpe": float(np.min(sharpes)) if sharpes else 0,
            "max_sharpe": float(np.max(sharpes)) if sharpes else 0,
            "n_positive_periods": n_positive,
            "consistency_ratio": n_positive / len(sharpes) if sharpes else 0,
        }

    def check_transaction_cost_sensitivity(
        self,
        strategy_returns: pd.Series,
        cost_levels: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """
        检查策略对交易成本的敏感性
        
        Args:
            strategy_returns: 策略日收益率
            cost_levels: 交易成本水平列表 (如 [0, 0.001, 0.002, 0.003])
            
        Returns:
            各成本水平下的绩效
        """
        if strategy_returns.empty:
            return {"error": "收益率为空"}

        if cost_levels is None:
            cost_levels = [0, 0.0005, 0.001, 0.002, 0.003, 0.005]

        cost_metrics = []
        for cost in cost_levels:
            adjusted = strategy_returns - cost * np.sign(strategy_returns)
            sharpe = calculate_sharpe_ratio(adjusted.tolist())
            total_ret = float(np.prod(1 + adjusted) - 1)
            cost_metrics.append({
                "cost_level": cost,
                "sharpe_ratio": float(sharpe),
                "total_return": total_ret,
            })

        if len(cost_metrics) >= 2:
            base_sharpe = cost_metrics[0]["sharpe_ratio"]
            last_sharpe = cost_metrics[-1]["sharpe_ratio"]
            decay = (base_sharpe - last_sharpe) / max(abs(base_sharpe), 1e-10)
        else:
            decay = 0

        breakeven_cost = None
        for cm in cost_metrics:
            if cm["sharpe_ratio"] <= 0:
                breakeven_cost = cm["cost_level"]
                break

        return {
            "cost_metrics": cost_metrics,
            "cost_decay": float(decay),
            "breakeven_cost": breakeven_cost,
            "base_sharpe": cost_metrics[0]["sharpe_ratio"] if cost_metrics else 0,
        }
