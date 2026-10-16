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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "dimension": int(self.dimension),
            "parameter_grid": {k: list(v) for k, v in self.parameter_grid.items()},
            "continuous_bounds": {k: list(v) for k, v in self.continuous_bounds.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SearchSpaceSpec":
        return cls(
            name=str(data["name"]),
            dimension=int(data.get("dimension", 1)),
            parameter_grid={
                k: list(v) for k, v in (data.get("parameter_grid") or {}).items()
            },
            continuous_bounds={
                k: (float(v[0]), float(v[1]))
                for k, v in (data.get("continuous_bounds") or {}).items()
            },
        )


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

    def to_dict(self) -> Dict[str, Any]:
        stat = self.test_statistic_name
        return {
            "experiment_id": self.experiment_id,
            "hypothesis_id": self.hypothesis_id,
            "family_id": self.family_id,
            "trial_index": int(self.trial_index),
            "search_space": self.search_space.to_dict(),
            "test_statistic_name": stat.value if isinstance(stat, StatisticType) else str(stat),
            "raw_statistic_value": float(self.raw_statistic_value),
            "sample_size_T": int(self.sample_size_T),
            "cross_section_N": int(self.cross_section_N),
            "p_raw": float(self.p_raw),
            "effective_m": float(self.effective_m),
            "p_adj_bonferroni": float(self.p_adj_bonferroni),
            "p_adj_bh_fdr": float(self.p_adj_bh_fdr),
            "p_adj_by_fdr": float(self.p_adj_by_fdr),
            "alpha_wealth_spent": float(self.alpha_wealth_spent),
            "passed_bonferroni": bool(self.passed_bonferroni),
            "passed_bh_fdr": bool(self.passed_bh_fdr),
            "code_git_sha": self.code_git_sha,
            "data_snapshot_hash": self.data_snapshot_hash,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrialRecord":
        stat_name = data.get("test_statistic_name")
        if isinstance(stat_name, StatisticType):
            stat = stat_name
        else:
            stat = StatisticType(str(stat_name))
        return cls(
            experiment_id=str(data["experiment_id"]),
            hypothesis_id=str(data["hypothesis_id"]),
            family_id=str(data["family_id"]),
            trial_index=int(data.get("trial_index", 0)),
            search_space=SearchSpaceSpec.from_dict(data["search_space"]),
            test_statistic_name=stat,
            raw_statistic_value=float(data.get("raw_statistic_value", 0.0)),
            sample_size_T=int(data.get("sample_size_T", 0)),
            cross_section_N=int(data.get("cross_section_N", 0)),
            p_raw=float(data.get("p_raw", 1.0)),
            effective_m=float(data.get("effective_m", 1.0)),
            p_adj_bonferroni=float(data.get("p_adj_bonferroni", 1.0)),
            p_adj_bh_fdr=float(data.get("p_adj_bh_fdr", 1.0)),
            p_adj_by_fdr=float(data.get("p_adj_by_fdr", 1.0)),
            alpha_wealth_spent=float(data.get("alpha_wealth_spent", 0.0)),
            passed_bonferroni=bool(data.get("passed_bonferroni", False)),
            passed_bh_fdr=bool(data.get("passed_bh_fdr", False)),
            code_git_sha=str(data.get("code_git_sha", "")),
            data_snapshot_hash=str(data.get("data_snapshot_hash", "")),
            created_at=str(data.get("created_at", "")),
            metadata=dict(data.get("metadata") or {}),
        )


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

    def to_state(self) -> Dict[str, Any]:
        """序列化账本状态（试验记录 + Alpha-Wealth 余额），用于跨进程累积。"""
        with self._lock:
            return {
                "version": 1,
                "alpha_nominal": float(self.alpha_nominal),
                "fdr_nominal": float(self.fdr_nominal),
                "initial_alpha_wealth": float(self.initial_alpha_wealth),
                "current_alpha_wealth": float(self.current_alpha_wealth),
                "trials": [rec.to_dict() for rec in self.trials],
            }

    @classmethod
    def from_state(cls, state: Dict[str, Any]) -> "DegreesOfFreedomLedger":
        """从 ``to_state()`` 产出的字典重建账本。

        Alpha-Wealth 余额直接还原（不重放奖励，避免二次计息）；族系多重检验
        校正按已落盘 raw p 值重新推导，保证内部一致性。
        """
        ledger = cls(
            alpha_nominal=float(state.get("alpha_nominal", 0.05)),
            fdr_nominal=float(state.get("fdr_nominal", 0.10)),
            initial_alpha_wealth=float(state.get("initial_alpha_wealth", 0.05)),
        )
        ledger.current_alpha_wealth = float(
            state.get("current_alpha_wealth", ledger.initial_alpha_wealth)
        )
        for raw in state.get("trials", []) or []:
            rec = TrialRecord.from_dict(raw)
            ledger.trials.append(rec)
            ledger._family_map.setdefault(rec.family_id, []).append(rec)
        for family_id in list(ledger._family_map):
            ledger._recompute_family_adjustments(family_id)
        return ledger

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
            m_eff = self.compute_effective_m(family_id, factor_correlation_matrix)
            # 如果提供了相关性矩阵且包含多个检验，按 Cheverud-Nyholt M_eff / K 折算自由度损耗
            if factor_correlation_matrix is not None and factor_correlation_matrix.shape[0] > 1:
                k = float(factor_correlation_matrix.shape[0])
                actual_bid = alpha_wealth_bid * (m_eff / k)
            else:
                actual_bid = alpha_wealth_bid

            if self.current_alpha_wealth < actual_bid:
                raise PermissionError(
                    f"Alpha Wealth 耗尽 (当前余额: {self.current_alpha_wealth:.6f} < 申请配额: {actual_bid:.6f})。"
                    "由于历史过拟合与无效检验过多，已被 QTR-OS 科研控制平面锁定！"
                )

            self.current_alpha_wealth -= actual_bid
            n_trials = len(self.trials) + 1

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
                alpha_wealth_spent=actual_bid,
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

    def register_sweep(
        self,
        experiment_id: str,
        hypothesis_id: str,
        family_id: str,
        search_space: SearchSpaceSpec,
        trials_data: List[Dict[str, Any]],
        factor_correlation_matrix: Optional[np.ndarray] = None,
        family_budget: float = 0.005,
        code_git_sha: str = "",
        data_snapshot_hash: str = "",
    ) -> List[TrialRecord]:
        """
        向账本批量注册参数寻优族 (Hyperparameter Sweep / GP Evolution)。
        使用 Cheverud-Nyholt M_eff 统一折算探索成本，单次整体扣减，杜绝单次尝试累加导致过早熔断。
        """
        with self._lock:
            k = len(trials_data)
            if k == 0:
                return []

            m_eff = self.compute_effective_m(family_id, factor_correlation_matrix)
            discount_ratio = (m_eff / float(k)) if k > 1 and factor_correlation_matrix is not None else 1.0
            actual_sweep_cost = family_budget * discount_ratio

            if self.current_alpha_wealth < actual_sweep_cost:
                raise PermissionError(
                    f"Alpha Wealth 耗尽 (当前余额: {self.current_alpha_wealth:.6f} < 参数寻优预算: {actual_sweep_cost:.6f})。"
                    "已被 QTR-OS 科研控制平面锁定！"
                )

            self.current_alpha_wealth -= actual_sweep_cost
            per_trial_cost = actual_sweep_cost / float(k)

            records: List[TrialRecord] = []
            for t_data in trials_data:
                n_trials = len(self.trials) + 1
                rec = TrialRecord(
                    experiment_id=experiment_id,
                    hypothesis_id=hypothesis_id,
                    family_id=family_id,
                    trial_index=n_trials,
                    search_space=search_space,
                    test_statistic_name=t_data["test_statistic_name"],
                    raw_statistic_value=t_data["raw_statistic_value"],
                    sample_size_T=t_data["sample_size_T"],
                    cross_section_N=t_data["cross_section_N"],
                    p_raw=t_data["p_raw"],
                    effective_m=m_eff,
                    alpha_wealth_spent=per_trial_cost,
                    code_git_sha=code_git_sha,
                    data_snapshot_hash=data_snapshot_hash,
                    metadata=t_data.get("metadata", {}),
                )
                self.trials.append(rec)
                self._family_map.setdefault(family_id, []).append(rec)
                records.append(rec)

            self._recompute_family_adjustments(family_id)

            # 若有试验通过 FDR，予以财富奖励
            rewards = sum(
                (self.alpha_nominal * self.fdr_nominal)
                for r in records if r.passed_bh_fdr
            )
            self.current_alpha_wealth += rewards
            return records

    def register_hypothesis(
        self,
        hypothesis_id: str,
        family_id: str,
        description: str,
        base_bid: float = 0.005,
    ) -> Dict[str, Any]:
        """向科研控制平面注册一个顶层独立经济学假说。"""
        with self._lock:
            if self.current_alpha_wealth < base_bid:
                raise PermissionError(
                    f"Alpha Wealth 耗尽，无法注册新假说 {hypothesis_id} "
                    f"({self.current_alpha_wealth:.6f} < {base_bid:.6f})"
                )
            self.current_alpha_wealth -= base_bid
            return {
                "hypothesis_id": hypothesis_id,
                "family_id": family_id,
                "description": description,
                "base_bid": base_bid,
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }

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
