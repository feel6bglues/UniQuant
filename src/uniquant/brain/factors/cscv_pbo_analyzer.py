"""
策略组合对称交叉验证 (CSCV) 与回测过拟合概率 (PBO) 生产级分析器
=============================================================================
标准参考文献：
  1. Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. V. (2015).
     "The Probability of Backtest Overfitting."
     Journal of Computational Finance, 20(4), 39-69.
  2. López de Prado, M. (2018).
     "Advances in Financial Machine Learning." John Wiley & Sons, Inc.
     Chapter 11: The Probability of Backtest Overfitting (PBO).
=============================================================================
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger("CSCVAndPBOAnalyzer")


@dataclass
class CSCVPBOResult:
    """CSCV 与 PBO 评价结果结构体"""
    pbo: float
    pbo_pct: float
    pbo_gate_passed: bool
    total_combinations: int
    n_slices: int
    n_strategies: int
    strategies: List[str]
    mean_relative_rank: float
    median_relative_rank: float
    mean_logit_lambda: float
    median_logit_lambda: float
    prob_loss_oos: float
    mean_is_sr: float
    mean_oos_sr: float
    mean_degradation: float
    ols_alpha: float
    ols_beta: float
    calculation_time_sec: float
    winner_frequency: Dict[str, Dict[str, Any]]
    conditional_pbo: Optional[float] = None
    conditional_strategy: Optional[str] = None


class CSCVAndPBOAnalyzer:
    """
    组合对称交叉验证 (CSCV) 与 PBO 严密测算器 (López de Prado 规范)
    
    参数:
        n_slices: 时序切片数 S (必须为偶数，默认 16，对应 C(16, 8) = 12,870 组对称组合)
        risk_free_rate: 年化无风险利率 (默认 0.025 即 2.5%)
        annualization_factor: 年化因子 (日频为 252.0，年度调仓为 1.0)
    """

    def __init__(
        self,
        n_slices: int = 16,
        risk_free_rate: float = 0.025,
        annualization_factor: float = 252.0,
    ):
        if n_slices % 2 != 0:
            raise ValueError(f"划分切片数 S 必须为偶数，当前传入: {n_slices}")
        self.S = n_slices
        self.k = n_slices // 2
        self.rf = float(risk_free_rate)
        self.ann_factor = float(annualization_factor)

        # 生成所有组合 C(S, k)
        self.combos = list(itertools.combinations(range(self.S), self.k))
        self.C = len(self.combos)

        # 构造密集布尔组合矩阵 B in {0, 1}^{C x S} 用于 BLAS 矩阵乘法加速
        self.B = np.zeros((self.C, self.S), dtype=np.float64)
        for i, c in enumerate(self.combos):
            self.B[i, list(c)] = 1.0

        logger.info(f"CSCVAndPBOAnalyzer initialized: S={self.S}, k={self.k}, C={self.C}")

    def evaluate(
        self,
        df_returns: pd.DataFrame,
        target_conditional_strategy: Optional[str] = None,
        pbo_threshold: float = 0.10,
    ) -> CSCVPBOResult:
        """
        对 T x N 策略收益矩阵执行全量 CSCV 向量化计算
        
        Args:
            df_returns: 形状为 (T, N) 的收益率矩阵 DataFrame
            target_conditional_strategy: 目标指定策略名称 (用于计算条件 PBO)
            pbo_threshold: PBO 门禁判定阈值 (默认 0.10)
            
        Returns:
            CSCVPBOResult 结构体
        """
        T, N = df_returns.shape
        if T < self.S:
            raise ValueError(f"时间期数 T ({T}) 小于切片数 S ({self.S})")
        if N < 2:
            raise ValueError(f"候选策略维度 N ({N}) 必须至少为 2")

        strat_names = list(df_returns.columns)
        t0 = time.time()

        # 1. 划分 S 个时序连续切片
        slice_indices = np.array_split(np.arange(T), self.S)

        # 2. 预计算每个切片的统计量: 一阶和与二阶和
        S1_slices = np.zeros((self.S, N), dtype=np.float64)
        S2_slices = np.zeros((self.S, N), dtype=np.float64)
        counts = np.zeros(self.S, dtype=np.float64)

        X = df_returns.values.astype(np.float64)
        for s in range(self.S):
            idx = slice_indices[s]
            sub = X[idx, :]
            S1_slices[s, :] = np.sum(sub, axis=0)
            S2_slices[s, :] = np.sum(sub ** 2, axis=0)
            counts[s] = len(idx)

        # 3. BLAS 矩阵乘法瞬间生成全量 C 组训练集 (IS) 与测试集 (OOS) 统计量
        S1_IS = self.B @ S1_slices           # (C, N)
        S2_IS = self.B @ S2_slices           # (C, N)
        n_IS = self.B @ counts               # (C,)

        S1_total = np.sum(S1_slices, axis=0)
        S2_total = np.sum(S2_slices, axis=0)
        n_total = np.sum(counts)

        S1_OOS = S1_total[None, :] - S1_IS   # (C, N)
        S2_OOS = S2_total[None, :] - S2_IS   # (C, N)
        n_OOS = n_total - n_IS               # (C,)

        # 4. 计算 IS 与 OOS 年化夏普比率
        rf_per_period = self.rf / self.ann_factor if self.ann_factor > 1 else self.rf

        mean_IS = S1_IS / n_IS[:, None]
        var_IS = np.maximum((S2_IS - n_IS[:, None] * (mean_IS ** 2)) / (n_IS[:, None] - 1.0), 1e-12)
        std_IS = np.sqrt(var_IS)
        sr_IS = np.sqrt(self.ann_factor) * (mean_IS - rf_per_period) / std_IS

        mean_OOS = S1_OOS / n_OOS[:, None]
        var_OOS = np.maximum((S2_OOS - n_OOS[:, None] * (mean_OOS ** 2)) / (n_OOS[:, None] - 1.0), 1e-12)
        std_OOS = np.sqrt(var_OOS)
        sr_OOS = np.sqrt(self.ann_factor) * (mean_OOS - rf_per_period) / std_OOS

        # 5. 确定样本内最优策略配置
        best_IS_idx = np.argmax(sr_IS, axis=1)  # (C,)
        row_indices = np.arange(self.C)

        best_is_sr = sr_IS[row_indices, best_IS_idx]
        best_oos_sr = sr_OOS[row_indices, best_IS_idx]

        # 6. 计算样本外相对排名与 Logits
        ranks = np.sum(sr_OOS <= best_oos_sr[:, None], axis=1).astype(np.float64)
        rel_ranks = ranks / (N + 1.0)
        rel_ranks = np.clip(rel_ranks, 1e-6, 1.0 - 1e-6)
        logits = np.log(rel_ranks / (1.0 - rel_ranks))

        calc_time = time.time() - t0

        # 7. 计算 PBO 与核心统计量
        is_overfit = (rel_ranks <= 0.50)
        pbo = float(np.mean(is_overfit))

        prob_loss = float(np.mean(best_oos_sr <= 0.0))
        degradation = best_oos_sr - best_is_sr
        mean_degradation = float(np.mean(degradation))

        # OLS 绩效衰减回归
        X_reg = np.column_stack([np.ones(self.C), best_is_sr])
        beta_coeffs, _, _, _ = np.linalg.lstsq(X_reg, best_oos_sr, rcond=None)
        alpha_reg = float(beta_coeffs[0])
        beta_reg = float(beta_coeffs[1])

        # 样本内优胜频次
        winner_counts = {}
        for idx_strat, count in zip(*np.unique(best_IS_idx, return_counts=True)):
            strat = strat_names[idx_strat]
            winner_counts[strat] = {
                "count": int(count),
                "frequency_pct": round(float(count / self.C * 100.0), 2),
            }

        # 条件 PBO (针对目标指定策略)
        cond_pbo = None
        if target_conditional_strategy and target_conditional_strategy in strat_names:
            tgt_idx = strat_names.index(target_conditional_strategy)
            mask_tgt = (best_IS_idx == tgt_idx)
            if mask_tgt.sum() > 0:
                cond_pbo = float(np.mean(is_overfit[mask_tgt]))

        return CSCVPBOResult(
            pbo=round(pbo, 6),
            pbo_pct=round(pbo * 100.0, 2),
            pbo_gate_passed=bool(pbo < pbo_threshold),
            total_combinations=self.C,
            n_slices=self.S,
            n_strategies=N,
            strategies=strat_names,
            mean_relative_rank=round(float(np.mean(rel_ranks)), 4),
            median_relative_rank=round(float(np.median(rel_ranks)), 4),
            mean_logit_lambda=round(float(np.mean(logits)), 4),
            median_logit_lambda=round(float(np.median(logits)), 4),
            prob_loss_oos=round(prob_loss, 6),
            mean_is_sr=round(float(np.mean(best_is_sr)), 4),
            mean_oos_sr=round(float(np.mean(best_oos_sr)), 4),
            mean_degradation=round(mean_degradation, 4),
            ols_alpha=round(alpha_reg, 4),
            ols_beta=round(beta_reg, 4),
            calculation_time_sec=round(calc_time, 4),
            winner_frequency=winner_counts,
            conditional_pbo=round(cond_pbo, 6) if cond_pbo is not None else None,
            conditional_strategy=target_conditional_strategy,
        )
