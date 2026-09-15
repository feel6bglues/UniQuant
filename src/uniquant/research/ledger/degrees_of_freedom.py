"""
QTR-OS Research Control Plane: Degrees of Freedom Ledger
File: uniquant/research/ledger/degrees_of_freedom.py

Implements dynamic multiple testing corrections (Bonferroni, Nyholt-Li-Ji M_eff,
Benjamini-Hochberg FDR, Benjamini-Yekutieli, and Foster-Stine Alpha-Wealth tracking).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


class StatisticType(str, Enum):
    IC_NEWEY_WEST_T = "IC_NEWEY_WEST_T"
    ANNUALIZED_SHARPE_T = "ANNUALIZED_SHARPE_T"
    REGRESSION_T = "REGRESSION_T"
    STUDENT_T = "STUDENT_T"


@dataclass(frozen=True)
class SearchSpaceSpec:
    name: str
    dimension: int
    parameter_grid: Dict[str, List[Any]] = field(default_factory=dict)
    continuous_bounds: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    @property
    def discrete_cardinality(self) -> int:
        if not self.parameter_grid:
            return 1
        card = 1
        for vals in self.parameter_grid.values():
            card *= max(1, len(vals))
        return card


@dataclass
class TrialRecord:
    experiment_id: str
    hypothesis_id: str
    family_id: str
    trial_index: int
    search_space: SearchSpaceSpec
    test_statistic_name: StatisticType
    raw_statistic_value: float
    sample_size_T: int
    cross_section_N: int
    p_raw: float
    effective_m: float = 1.0
    p_adj_bonferroni: float = 1.0
    p_adj_bh_fdr: float = 1.0
    p_adj_by_fdr: float = 1.0
    alpha_wealth_spent: float = 0.0
    passed_bonferroni: bool = False
    passed_bh_fdr: bool = False
    code_git_sha: str = ""
    data_snapshot_hash: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = field(default_factory=dict)


class DegreesOfFreedomLedger:
    """
    科研自由度账本：审计跟踪假设空间膨胀，并动态施加多重假设检验校正。
    """

    def __init__(
        self,
        alpha_nominal: float = 0.05,
        fdr_nominal: float = 0.10,
        initial_alpha_wealth: float = 0.05,
    ) -> None:
        self.alpha_nominal = alpha_nominal
        self.fdr_nominal = fdr_nominal
        self.initial_alpha_wealth = initial_alpha_wealth
        self.current_alpha_wealth = initial_alpha_wealth
        self.trials: List[TrialRecord] = []
        self._family_map: Dict[str, List[TrialRecord]] = {}
        self._lock = threading.RLock()

    @property
    def total_trials(self) -> int:
        with self._lock:
            return len(self.trials)

    def compute_effective_m(
        self, family_id: str, corr_matrix: Optional[np.ndarray] = None
    ) -> float:
        """
        基于因子相关矩阵特征谱，计算 Nyholt-Li-Ji 有效独立试验次数 M_eff。
        精确归一化边界：M_eff in [1.0, k]。
        当完全共线时 M_eff = 1.0；当完全正交时 M_eff = k。
        """
        with self._lock:
            family_trials = self._family_map.get(family_id, [])
            m = len(family_trials) + 1
            if corr_matrix is None or corr_matrix.shape[0] < 2:
                return float(m)

            evals = np.linalg.eigvalsh(corr_matrix)
            evals = np.clip(evals, 0.0, None)
            k = len(evals)
            if k <= 1:
                return 1.0

            var_evals = float(np.var(evals))
            max_var = float(k - 1)  # 最大可能方差 (lambda_1=k, 其余=0)
            norm_var = min(1.0, var_evals / max(max_var, 1e-12))
            m_eff = 1.0 + (k - 1.0) * (1.0 - norm_var)
            return max(1.0, min(float(k), float(m_eff)))

    def register_trial(
        self,
        experiment_id: str,
        hypothesis_id: str,
        family_id: str,
        search_space: SearchSpaceSpec,
        test_statistic_name: StatisticType,
        raw_statistic_value: float,
        sample_size_T: int,
        cross_section_N: int,
        p_raw: float,
        factor_correlation_matrix: Optional[np.ndarray] = None,
        alpha_wealth_bid: float = 0.001,
        code_git_sha: str = "",
        data_snapshot_hash: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TrialRecord:
        """
        向账本注册一次试验，扣减 Alpha-Wealth，并动态更新该假设族的多重检验校正阈值。
        """
        with self._lock:
            if self.current_alpha_wealth < alpha_wealth_bid:
                raise PermissionError(
                    f"Alpha Wealth 耗尽 (当前余额: {self.current_alpha_wealth:.6f} < 申请配额: {alpha_wealth_bid})。"
                    "由于历史过拟合与无效检验过多，已被 QTR-OS 科研控制平面锁定！"
                )

            self.current_alpha_wealth -= alpha_wealth_bid
            n_trials = len(self.trials) + 1
            m_eff = self.compute_effective_m(family_id, factor_correlation_matrix)

            rec = TrialRecord(
                experiment_id=experiment_id,
                hypothesis_id=hypothesis_id,
                family_id=family_id,
                trial_index=n_trials,
                search_space=search_space,
                test_statistic_name=test_statistic_name,
                raw_statistic_value=raw_statistic_value,
                sample_size_T=sample_size_T,
                cross_section_N=cross_section_N,
                p_raw=p_raw,
                effective_m=m_eff,
                alpha_wealth_spent=alpha_wealth_bid,
                code_git_sha=code_git_sha,
                data_snapshot_hash=data_snapshot_hash,
                metadata=metadata or {},
            )

            self.trials.append(rec)
            self._family_map.setdefault(family_id, []).append(rec)

            self._recompute_family_adjustments(family_id)

            # 若通过 BH-FDR 检验，予以奖励恢复 Alpha-Wealth
            if rec.passed_bh_fdr:
                reward = self.alpha_nominal * self.fdr_nominal
                self.current_alpha_wealth += reward

            return rec

    def _recompute_family_adjustments(self, family_id: str) -> None:
        """
        对族系内部全量试验动态执行 Step-up BH-FDR 与 Bonferroni 校正。
        """
        records = self._family_map[family_id]
        m = len(records)
        if m == 0:
            return

        # 1. Bonferroni Adjustment (基于族系累积试验数 m 或自适应 m_eff)
        for r in records:
            effective_trials = max(float(m), r.effective_m)
            r.p_adj_bonferroni = min(1.0, float(r.p_raw * effective_trials))
            r.passed_bonferroni = bool(r.p_adj_bonferroni <= self.alpha_nominal)

        # 2. Benjamini-Hochberg (BH) Step-Up Procedure
        p_vals = np.array([r.p_raw for r in records], dtype=np.float64)
        sort_indices = np.argsort(p_vals)
        sorted_p = p_vals[sort_indices]

        ranks = np.arange(1, m + 1, dtype=np.float64)
        raw_adjusted = (m / ranks) * sorted_p

        # 逆序求累积最小值以保证单调性: min_{j >= k} raw_adjusted[j]
        cum_min = np.minimum.accumulate(raw_adjusted[::-1])[::-1]
        sorted_q_bh = np.clip(cum_min, 0.0, 1.0)

        q_bh = np.empty(m, dtype=np.float64)
        q_bh[sort_indices] = sorted_q_bh

        # 3. Benjamini-Yekutieli (BY) 任意依赖修正
        c_m = float(np.sum(1.0 / np.arange(1, m + 1, dtype=np.float64)))
        q_by = np.clip(q_bh * c_m, 0.0, 1.0)

        for idx, r in enumerate(records):
            r.p_adj_bh_fdr = float(q_bh[idx])
            r.p_adj_by_fdr = float(q_by[idx])
            r.passed_bh_fdr = bool(r.p_adj_bh_fdr <= self.fdr_nominal)

    def get_hurdle_report(self, family_id: str) -> Dict[str, Any]:
        """
        返回本族的审计门槛汇总报告。
        """
        with self._lock:
            records = self._family_map.get(family_id, [])
            return {
                "family_id": family_id,
                "cumulative_trials": len(records),
                "total_platform_trials": len(self.trials),
                "current_alpha_wealth": round(self.current_alpha_wealth, 6),
                "significant_bh_count": sum(1 for r in records if r.passed_bh_fdr),
                "significant_bonf_count": sum(1 for r in records if r.passed_bonferroni),
            }
