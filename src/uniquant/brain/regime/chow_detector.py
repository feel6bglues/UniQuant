#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
UniQuant Brain Regime: Chow 结构突变检验与先验重置器 (Chow Structural Break Detector)
================================================================================
模块路径: uniquant.brain.regime.chow_detector
学术文献:
  1. Chow, G. C. (1960). Tests of equality between sets of coefficients in two linear regressions.
     Econometrica, 28(3), 591-605.
  2. Andrews, D. W. (1993). Tests for parameter instability and structural change with unknown change point.
     Econometrica, 61(4), 821-856.

【数理计量经济学原理】：
1. 线性回归模型与原假设:
     受约束模型 (全样本 T): y = X \beta_c + \epsilon, 残差平方和 RSS_c
     未受约束模型 (分段 \tau):
       子区间 1 (t <= \tau, 样本量 T_1): y_1 = X_1 \beta_1 + \epsilon_1, 残差平方和 RSS_1
       子区间 2 (t > \tau, 样本量 T_2):  y_2 = X_2 \beta_2 + \epsilon_2, 残差平方和 RSS_2
     原假设 H_0: \beta_1 = \beta_2 (无结构突变)
     备择假设 H_1: \beta_1 != \beta_2 (存在结构性断裂)

2. 经典 Chow F 统计量:
     F(\tau) = \frac{(RSS_c - (RSS_1 + RSS_2)) / k}{(RSS_1 + RSS_2) / (T - 2k)}
   其中 k 为自变量维度 (含常数项)，在 H_0 下服从 F(k, T - 2k) 分布。

3. Andrews (1993) Sup-Chow 检验 (未知断裂点扫描):
     在剪裁区间 \tau \in [\lfloor \pi_0 T \rfloor, \lfloor (1 - \pi_0) T \rfloor] (\pi_0 = 0.15) 内网格化搜索:
     Sup-F = \sup_\tau F(\tau)
     断裂点估计: \hat{\tau} = \arg\max_\tau F(\tau)
     当 Sup-F > 15.0 时，以极高置信度 (p < 0.001) 判定发生宏观/微观制度突变。

4. 贝叶斯先验重置器 (Prior Reset Engine):
     一旦触发结构性突变，立即重置历史先验:
     - 放大先验方差 \tau^2，降低对陈旧历史样本的过度拟合；
     - 截断历史估计窗口，将有效半衰期缩减 50%；
     - 提升协方差靶向收缩强度，抵御突变期的病态流动性扰动。
================================================================================
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union, Any

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger("uniquant.brain.regime.chow")


@dataclass
class ChowTestResult:
    """单一给定候选断裂点 Chow 检验结果"""
    f_stat: float
    p_value: float
    is_break: bool
    break_index: int
    break_date: Optional[Union[str, int]] = None
    k_params: int = 1
    n_obs: int = 0
    rss_c: float = 0.0
    rss_u: float = 0.0


@dataclass
class SupChowResult:
    """Andrews (1993) Sup-Chow 未知断裂点扫描检验结果"""
    sup_f: float
    p_value: float
    is_break: bool
    break_index: int
    break_date: Optional[Union[str, int]] = None
    k_params: int = 1
    n_obs: int = 0
    candidate_indices: List[int] = field(default_factory=list)
    f_series: List[float] = field(default_factory=list)
    beta_before: Optional[np.ndarray] = None
    beta_after: Optional[np.ndarray] = None
    verdict: str = ""


@dataclass
class PriorResetResult:
    """先验重置状态输出契约"""
    regime_break_detected: bool
    trigger_sup_f: float
    break_index: int
    break_date: Optional[Union[str, int]]
    original_prior_mean: float
    reset_prior_mean: float
    original_prior_tau2: float
    reset_prior_tau2: float
    original_window_len: int
    reset_window_len: int
    covariance_shrinkage_boost: float
    action_log: str


class ChowDetector:
    """
    Chow 结构突变检验与先验重置器
    """

    DEFAULT_F_CRITICAL: float = 15.0     # 突变断裂判定刚性临界阈值 (F > 15.0)
    DEFAULT_TRIMMING_PCT: float = 0.15   # Andrews 经典 15% 两端剪裁比例

    def __init__(
        self,
        f_critical: float = DEFAULT_F_CRITICAL,
        trimming_pct: float = DEFAULT_TRIMMING_PCT,
    ):
        if trimming_pct <= 0 or trimming_pct >= 0.5:
            raise ValueError("trimming_pct 必须在 (0, 0.5) 开区间内")
        self.f_critical = f_critical
        self.trimming_pct = trimming_pct

    @staticmethod
    def _fit_ols_rss(y: np.ndarray, X: np.ndarray) -> Tuple[float, np.ndarray]:
        """求解 OLS 并返回残差平方和 RSS 与回归系数 beta"""
        # 使用伪逆保障奇异矩阵数值鲁棒性
        beta, residuals, rank, s = np.linalg.lstsq(X, y, rcond=None)
        pred = X @ beta
        rss = float(np.sum((y - pred) ** 2))
        return rss, beta

    def test_known_breakpoint(
        self,
        y: Union[np.ndarray, pd.Series],
        X: Union[np.ndarray, pd.DataFrame],
        break_index: int,
        dates: Optional[Union[np.ndarray, pd.Series, List[Any]]] = None,
    ) -> ChowTestResult:
        """
        在已知断裂点 break_index 处执行经典 Chow (1960) 检验
        """
        y_arr = np.asarray(y, dtype=float).ravel()
        X_arr = np.asarray(X, dtype=float)
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(-1, 1)

        # 补全截距项
        if not np.allclose(X_arr[:, 0], 1.0):
            X_arr = np.column_stack([np.ones(len(y_arr)), X_arr])

        T, k = X_arr.shape
        if T < 2 * k + 4:
            raise ValueError(f"样本观测数 T={T} 过少，无法满足 Chow 检验自由度要求 (2k+4={2*k+4})")

        tau = break_index
        if tau <= k or tau >= T - k:
            raise ValueError(f"断裂点索引 {tau} 距离样本边界过近，无法估计分段参数")

        # 1. 全样本受约束回归 (RSS_c)
        rss_c, _ = self._fit_ols_rss(y_arr, X_arr)

        # 2. 分段未受约束回归 (RSS_1, RSS_2)
        X1, y1 = X_arr[:tau], y_arr[:tau]
        X2, y2 = X_arr[tau:], y_arr[tau:]

        rss_1, _ = self._fit_ols_rss(y1, X1)
        rss_2, _ = self._fit_ols_rss(y2, X2)
        rss_u = rss_1 + rss_2

        # 3. 计算 Chow F 统计量
        df_num = k
        df_denom = T - 2 * k
        f_stat = ((rss_c - rss_u) / df_num) / (rss_u / df_denom)
        f_stat = max(0.0, float(f_stat))

        p_value = float(1.0 - stats.f.cdf(f_stat, df_num, df_denom))
        is_break = bool(f_stat > self.f_critical)

        break_dt = None
        if dates is not None and len(dates) == T:
            break_dt = dates[tau]

        return ChowTestResult(
            f_stat=f_stat,
            p_value=p_value,
            is_break=is_break,
            break_index=tau,
            break_date=break_dt,
            k_params=k,
            n_obs=T,
            rss_c=rss_c,
            rss_u=rss_u,
        )

    def test_sup_chow(
        self,
        y: Union[np.ndarray, pd.Series],
        X: Union[np.ndarray, pd.DataFrame],
        dates: Optional[Union[np.ndarray, pd.Series, List[Any]]] = None,
    ) -> SupChowResult:
        """
        执行 Andrews (1993) Sup-Chow 未知断裂点全区间扫描检验
        """
        y_arr = np.asarray(y, dtype=float).ravel()
        X_arr = np.asarray(X, dtype=float)
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(-1, 1)

        # 补全截距项
        if not np.allclose(X_arr[:, 0], 1.0):
            X_arr = np.column_stack([np.ones(len(y_arr)), X_arr])

        T, k = X_arr.shape
        start_idx = max(k + 2, int(np.floor(self.trimming_pct * T)))
        end_idx = min(T - k - 2, int(np.ceil((1.0 - self.trimming_pct) * T)))

        if start_idx >= end_idx:
            raise ValueError(f"样本有效区间不足以在剪裁比例 {self.trimming_pct} 下执行 Sup-Chow 扫描")

        # 全样本 RSS_c
        rss_c, _ = self._fit_ols_rss(y_arr, X_arr)

        df_num = k
        df_denom = T - 2 * k

        candidate_indices = []
        f_series = []
        best_tau = start_idx
        best_f = -1.0
        best_beta_before = None
        best_beta_after = None

        for tau in range(start_idx, end_idx):
            X1, y1 = X_arr[:tau], y_arr[:tau]
            X2, y2 = X_arr[tau:], y_arr[tau:]

            rss_1, b1 = self._fit_ols_rss(y1, X1)
            rss_2, b2 = self._fit_ols_rss(y2, X2)
            rss_u = rss_1 + rss_2

            if rss_u <= 1e-12:
                f_val = 0.0
            else:
                f_val = ((rss_c - rss_u) / df_num) / (rss_u / df_denom)
                f_val = max(0.0, float(f_val))

            candidate_indices.append(tau)
            f_series.append(f_val)

            if f_val > best_f:
                best_f = f_val
                best_tau = tau
                best_beta_before = b1
                best_beta_after = b2

        # 渐近 p 值 (保守采用 F 临界极值分布)
        p_val = float(1.0 - stats.f.cdf(best_f, df_num, df_denom))
        is_break = bool(best_f > self.f_critical)

        break_dt = None
        if dates is not None and len(dates) == T:
            break_dt = dates[best_tau]

        verdict = (
            f"【突变触发】Sup-Chow 统计量 F = {best_f:.2f} > {self.f_critical:.1f}，在索引 {best_tau} 处识别出结构性突变断裂！"
            if is_break
            else f"【状态平稳】Sup-Chow 统计量 Max-F = {best_f:.2f} <= {self.f_critical:.1f}，未检测到显著宏观结构断裂。"
        )

        return SupChowResult(
            sup_f=best_f,
            p_value=p_val,
            is_break=is_break,
            break_index=best_tau,
            break_date=break_dt,
            k_params=k,
            n_obs=T,
            candidate_indices=candidate_indices,
            f_series=f_series,
            beta_before=best_beta_before,
            beta_after=best_beta_after,
            verdict=verdict,
        )

    @classmethod
    def reset_empirical_bayes_priors(
        cls,
        sup_chow_res: SupChowResult,
        current_prior_mean: float = 0.45,
        current_prior_tau2: float = 0.015,
        current_window_len: int = 60,
    ) -> PriorResetResult:
        """
        先验重置器核心接口 (Prior Reset Interface)
        在判定 Sup-F > 15.0 突变断裂时，重置经验贝叶斯后验并调整状态参数
        """
        if not sup_chow_res.is_break:
            return PriorResetResult(
                regime_break_detected=False,
                trigger_sup_f=sup_chow_res.sup_f,
                break_index=sup_chow_res.break_index,
                break_date=sup_chow_res.break_date,
                original_prior_mean=current_prior_mean,
                reset_prior_mean=current_prior_mean,
                original_prior_tau2=current_prior_tau2,
                reset_prior_tau2=current_prior_tau2,
                original_window_len=current_window_len,
                reset_window_len=current_window_len,
                covariance_shrinkage_boost=0.0,
                action_log="未触发突变，维持既有经验贝叶斯先验与回溯窗口不变。",
            )

        # 触发结构突变断裂时的先验重置逻辑:
        # 1. 先验均值回归至全截面中枢 0.40 (防御性衰减)
        new_mean = 0.40
        # 2. 先验方差 tau^2 放大 2.5 倍 (承认不确定性激增，弱化历史样本强收缩)
        new_tau2 = max(0.040, current_prior_tau2 * 2.5)
        # 3. 回溯窗口缩减 50% (半衰期减半，抛弃断裂点前的陈旧数据)
        new_window = max(16, int(current_window_len * 0.5))
        # 4. 协方差结构靶向收缩提升 +0.25 (增强抗奇异性)
        cov_boost = 0.25

        log_msg = (
            f"⚠️ 突变断裂重置生效 (Sup-F={sup_chow_res.sup_f:.2f} > 15.0): "
            f"先验均值 {current_prior_mean:.3f}->{new_mean:.3f}, "
            f"先验方差 Tau^2 {current_prior_tau2:.5f}->{new_tau2:.5f}, "
            f"回溯窗口 {current_window_len}d->{new_window}d, "
            f"协方差收缩增量 +{cov_boost:.2f}。"
        )

        logger.warning(log_msg)

        return PriorResetResult(
            regime_break_detected=True,
            trigger_sup_f=sup_chow_res.sup_f,
            break_index=sup_chow_res.break_index,
            break_date=sup_chow_res.break_date,
            original_prior_mean=current_prior_mean,
            reset_prior_mean=new_mean,
            original_prior_tau2=current_prior_tau2,
            reset_prior_tau2=new_tau2,
            original_window_len=current_window_len,
            reset_window_len=new_window,
            covariance_shrinkage_boost=cov_boost,
            action_log=log_msg,
        )
