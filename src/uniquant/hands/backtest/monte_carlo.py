from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ...shared.cost_model import calculate_sharpe_ratio
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class MonteCarloSimulator:
    """
    Monte Carlo 回测模拟器
    
    提供:
    - 随机排列 Monte Carlo (shuffle)
    - Bootstrap 重采样 Monte Carlo
    - 置信区间计算
    """

    def __init__(self, n_simulations: int = 1000, confidence_level: float = 0.95):
        """
        Args:
            n_simulations: 模拟次数
            confidence_level: 置信水平 (默认 0.95)
        """
        self.n_simulations = n_simulations
        self.confidence_level = confidence_level

    def run_shuffle(self, returns: pd.Series) -> Dict[str, Any]:
        """
        随机排列 Monte Carlo 模拟
        
        对收益率序列随机打乱，破坏时序依赖性，
        评估策略表现是否显著优于随机排列。
        
        Args:
            returns: 策略日收益率序列
            
        Returns:
            包含模拟结果统计和置信区间的字典
        """
        if returns.empty or len(returns) < 10:
            logger.warning("收益率数据过少，无法进行 Monte Carlo 模拟")
            return {"error": "收益率数据过少"}

        returns = returns.dropna().values
        n = len(returns)
        observed_sharpe = calculate_sharpe_ratio(returns)

        simulated_sharpes: List[float] = []

        for i in range(self.n_simulations):
            shuffled = np.random.permutation(returns)
            sim_sharpe = calculate_sharpe_ratio(shuffled)
            simulated_sharpes.append(sim_sharpe)

        simulated_sharpes = np.array(simulated_sharpes)
        p_value = np.mean(simulated_sharpes >= observed_sharpe)

        lower_tail = (1 - self.confidence_level) / 2
        upper_tail = 1 - lower_tail
        ci_lower = np.percentile(simulated_sharpes, lower_tail * 100)
        ci_upper = np.percentile(simulated_sharpes, upper_tail * 100)

        return {
            "method": "shuffle",
            "n_simulations": self.n_simulations,
            "observed_sharpe": observed_sharpe,
            "mean_simulated_sharpe": float(np.mean(simulated_sharpes)),
            "std_simulated_sharpe": float(np.std(simulated_sharpes)),
            "p_value": float(p_value),
            "is_significant": bool(p_value < (1 - self.confidence_level)),
            "confidence_interval": {
                "level": self.confidence_level,
                "lower": float(ci_lower),
                "upper": float(ci_upper),
            },
            "percentiles": {
                "5": float(np.percentile(simulated_sharpes, 5)),
                "25": float(np.percentile(simulated_sharpes, 25)),
                "50": float(np.percentile(simulated_sharpes, 50)),
                "75": float(np.percentile(simulated_sharpes, 75)),
                "95": float(np.percentile(simulated_sharpes, 95)),
            },
        }

    def run_bootstrap(self, equity_curve: pd.Series) -> Dict[str, Any]:
        """
        Bootstrap Monte Carlo 模拟
        
        对权益曲线进行有放回重采样，
        评估最终权益的分布特征。
        
        Args:
            equity_curve: 策略权益曲线
            
        Returns:
            包含 Bootstrap 统计结果和置信区间的字典
        """
        if equity_curve.empty or len(equity_curve) < 10:
            logger.warning("权益曲线数据过少，无法进行 Bootstrap 模拟")
            return {"error": "权益曲线数据过少"}

        returns = equity_curve.pct_change().dropna().values
        observed_final = equity_curve.iloc[-1]
        observed_return = (observed_final - equity_curve.iloc[0]) / equity_curve.iloc[0]

        simulated_finals: List[float] = []
        simulated_returns: List[float] = []

        n = len(returns)

        for i in range(self.n_simulations):
            bootstrap_returns = np.random.choice(returns, size=n, replace=True)
            sim_equity = equity_curve.iloc[0] * np.prod(1 + bootstrap_returns)
            simulated_finals.append(sim_equity)
            simulated_returns.append((sim_equity - equity_curve.iloc[0]) / equity_curve.iloc[0])

        simulated_finals = np.array(simulated_finals)
        simulated_returns = np.array(simulated_returns)

        lower_tail = (1 - self.confidence_level) / 2
        upper_tail = 1 - lower_tail

        return {
            "method": "bootstrap",
            "n_simulations": self.n_simulations,
            "observed_final_equity": float(observed_final),
            "observed_total_return": float(observed_return),
            "mean_simulated_final": float(np.mean(simulated_finals)),
            "std_simulated_final": float(np.std(simulated_finals)),
            "mean_simulated_return": float(np.mean(simulated_returns)),
            "final_equity_ci": {
                "level": self.confidence_level,
                "lower": float(np.percentile(simulated_finals, lower_tail * 100)),
                "upper": float(np.percentile(simulated_finals, upper_tail * 100)),
            },
            "return_ci": {
                "level": self.confidence_level,
                "lower": float(np.percentile(simulated_returns, lower_tail * 100)),
                "upper": float(np.percentile(simulated_returns, upper_tail * 100)),
            },
            "percentiles": {
                "5": float(np.percentile(simulated_finals, 5)),
                "25": float(np.percentile(simulated_finals, 25)),
                "50": float(np.percentile(simulated_finals, 50)),
                "75": float(np.percentile(simulated_finals, 75)),
                "95": float(np.percentile(simulated_finals, 95)),
            },
        }

    def get_confidence_intervals(self, simulations: np.ndarray) -> Dict[str, float]:
        """
        从模拟结果中提取置信区间
        
        Args:
            simulations: 模拟结果数组 (n_simulations, n_periods)
            
        Returns:
            包含各置信水平区间的字典
        """
        if simulations.size == 0:
            return {"error": "模拟结果为空"}

        means = np.mean(simulations, axis=1)

        result = {}
        for level in [0.90, 0.95, 0.99]:
            lower_tail = (1 - level) / 2
            upper_tail = 1 - lower_tail
            result[f"ci_{int(level * 100)}"] = {
                "level": level,
                "lower": float(np.percentile(means, lower_tail * 100)),
                "upper": float(np.percentile(means, upper_tail * 100)),
            }

        result["mean"] = float(np.mean(means))
        result["std"] = float(np.std(means))
        result["median"] = float(np.median(means))

        return result
