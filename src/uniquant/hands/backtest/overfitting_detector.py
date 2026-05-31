from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats

from ...shared.cost_model import calculate_sharpe_ratio
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class OverfittingDetector:
    """
    回测过拟合检测器
    
    实现 Bailey & Lopez de Prado 的过拟合检测方法:
    - Deflated Sharpe Ratio (DSR)
    - 最大回撤统计显著性
    - 有效试验次数估计
    - 回测过拟合概率 (PBO)
    """

    def __init__(self):
        pass

    @staticmethod
    def purged_kfold(n: int, k: int = 5, embargo: int = 5):
        """Sequential K-fold with purge period between train/test, preserving temporal order."""
        fold_size = n // k
        for i in range(k):
            test_start = i * fold_size
            test_end = test_start + fold_size if i < k - 1 else n
            train_end = max(0, test_start - embargo)
            train_idx = list(range(0, train_end))
            test_idx = list(range(test_start, test_end))
            yield train_idx, test_idx

    def deflated_sharpe_ratio(
        self,
        observed_sharpe: float,
        n_trials: int,
        num_observations: int,
        skewness: Optional[float] = None,
        kurtosis: Optional[float] = None,
    ) -> float:
        """
        计算 Deflated Sharpe Ratio (DSR)
        
        根据 Bailey & Lopez de Prado (2014) 的方法，
        对多重测试进行校正后的 Sharpe 比率。
        
        Args:
            observed_sharpe: 观察到的 Sharpe 比率
            n_trials: 独立试验次数
            num_observations: 观测值数量
            skewness: 收益率偏度 (可选)
            kurtosis: 收益率峰度 (可选)
            
        Returns:
            DSR 值，> 0 表示统计显著
        """
        if num_observations < 2 or n_trials < 1:
            return 0.0

        skew = skewness if skewness is not None else 0
        kurt = kurtosis if kurtosis is not None else 3

        gamma = 0.5772156649
        z_max = np.sqrt((1 - gamma) * stats.norm.ppf(1 - 1 / n_trials) + gamma * stats.norm.ppf(1 - 1 / (n_trials * np.e)))

        var_sharpe = (1 + 0.5 * observed_sharpe**2 - skew * observed_sharpe + (kurt - 3) * observed_sharpe**2 / 4) / (num_observations - 1)
        std_sharpe = np.sqrt(var_sharpe) if var_sharpe > 0 else 1e-10

        dsr = (observed_sharpe - z_max) / std_sharpe
        return float(dsr)

    def mdd_p_value(self, max_drawdown: float, n_observations: int) -> float:
        """
        最大回撤统计显著性 (p-value)
        
        使用 Magdon-Ismail & Atiya (2004) 的近似方法。
        
        Args:
            max_drawdown: 最大回撤 (0~1)
            n_observations: 观测值数量
            
        Returns:
            p-value，越低回撤越显著
        """
        if max_drawdown <= 0 or n_observations < 2:
            return 1.0

        p = 0.5 * (1 + stats.erf(max_drawdown / np.sqrt(2 * n_observations)))
        return float(p)

    def num_trials_metric(self, n_parameters: int, n_configs: int) -> float:
        """
        估计有效试验次数
        
        考虑参数数量和配置组合对多重测试的影响。
        
        Args:
            n_parameters: 策略参数数量
            n_configs: 测试的配置数量
            
        Returns:
            有效试验次数估计值
        """
        if n_parameters < 0 or n_configs < 1:
            return 1.0

        effective = n_configs * (1 + n_parameters / np.sqrt(n_configs))
        return float(effective)

    def probability_of_backtest_overfitting(
        self,
        strategy_returns: List[pd.Series],
        n_partitions: int = 10,
        embargo: int = 5,
    ) -> Dict[str, Any]:
        """
        计算回测过拟合概率 PBO
        
        基于 Lopez de Prado (2015) 的 Combinatorial Purged 
        Cross-Validation 方法，使用 purged K-fold 保持时间顺序。
        
        Args:
            strategy_returns: 各策略的收益率序列列表
            n_partitions: 交叉验证分区数
            embargo: 训练集与测试集之间的清洗期（交易日数）
            
        Returns:
            包含 PBO 及相关统计的字典
        """
        if len(strategy_returns) < 2:
            return {"pbo": 1.0, "error": "至少需要 2 个策略"}

        min_len = min(len(r) for r in strategy_returns)
        if min_len < n_partitions:
            return {"pbo": 1.0, "error": f"数据长度 {min_len} 小于分区数 {n_partitions}"}

        n_strategies = len(strategy_returns)
        aligned = np.array([r.iloc[:min_len].values for r in strategy_returns])

        rank_matrices = []
        for train_idx, test_idx in self.purged_kfold(min_len, n_partitions, embargo):
            if len(train_idx) == 0:
                continue

            train_sharpes = []
            test_sharpes = []
            for s in range(n_strategies):
                train_ret = aligned[s, train_idx]
                test_ret = aligned[s, test_idx]

                train_sharpe = calculate_sharpe_ratio(train_ret)
                test_sharpe = calculate_sharpe_ratio(test_ret)

                train_sharpes.append(train_sharpe)
                test_sharpes.append(test_sharpe)

            train_ranks = stats.rankdata(-np.array(train_sharpes), method="average")
            test_ranks = stats.rankdata(-np.array(test_sharpes), method="average")
            rank_matrices.append((train_ranks, test_ranks))

        logits = []
        for train_ranks, test_ranks in rank_matrices:
            for s in range(n_strategies):
                if train_ranks[s] <= n_strategies / 2:
                    logit = np.log(test_ranks[s] / (n_strategies + 1 - test_ranks[s]))
                    logits.append(logit)

        logits = np.array(logits)
        pbo = np.mean(logits > 0) if len(logits) > 0 else 1.0

        return {
            "pbo": float(pbo),
            "n_strategies": n_strategies,
            "n_partitions": n_partitions,
            "embargo": embargo,
            "mean_logit": float(np.mean(logits)) if len(logits) > 0 else 0,
            "std_logit": float(np.std(logits)) if len(logits) > 0 else 0,
            "is_overfit": bool(pbo > 0.5),
        }
