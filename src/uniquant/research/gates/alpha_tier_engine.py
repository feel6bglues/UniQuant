"""
QTR-OS Research Control Plane: Alpha Candidate Four-Tier Promotion Engine
File: uniquant/research/gates/alpha_tier_engine.py

Orchestrates Class A -> Class D sequential gates with rigorous statistical
and econometric hurdles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import scipy.stats as stats

from uniquant.research.ledger.degrees_of_freedom import (
    DegreesOfFreedomLedger,
    SearchSpaceSpec,
    StatisticType,
    TrialRecord,
)


class AlphaTier(str, Enum):
    TIER_UNRATED = "UNRATED"
    TIER_A = "TIER_A_STATISTICALLY_SUPPORTED"
    TIER_B = "TIER_B_ECONOMICALLY_PLAUSIBLE"
    TIER_C = "TIER_C_TRADABLE_CANDIDATE"
    TIER_D = "TIER_D_REPLICATED_STRATEGY"


@dataclass
class GateResult:
    gate_name: str
    passed: bool
    metrics: Dict[str, float]
    thresholds: Dict[str, float]
    details: str = ""


@dataclass
class PromotionReport:
    factor_name: str
    final_tier: AlphaTier
    passed_class_a: bool = False
    passed_class_b: bool = False
    passed_class_c: bool = False
    passed_class_d: bool = False
    gate_results: List[GateResult] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    audit_metadata: Dict[str, Any] = field(default_factory=dict)


# =========================================================================
# 1. Class A Evaluator: Statistical Significance & Overfitting
# =========================================================================
class ClassAEvaluator:
    @staticmethod
    def compute_newey_west_t(ic_series: np.ndarray, forecast_horizon: int = 5) -> Tuple[float, float, float]:
        arr = np.asarray(ic_series, dtype=np.float64)
        arr = arr[np.isfinite(arr)]
        t_len = len(arr)
        if t_len < 10:
            return 0.0, 0.0, 1.0

        mean = float(np.mean(arr))
        demeaned = arr - mean
        max_lags = max(forecast_horizon - 1, int(np.floor(4.0 * (t_len / 100.0) ** (2.0 / 9.0))))

        gamma0 = float(np.mean(demeaned ** 2))
        gamma_sum = 0.0
        for lag in range(1, max_lags + 1):
            weight = 1.0 - lag / (max_lags + 1.0)
            cov_l = float(np.mean(demeaned[lag:] * demeaned[:-lag]))
            gamma_sum += 2.0 * weight * cov_l

        var_hac = (gamma0 + gamma_sum) / t_len
        if var_hac <= 1e-12:
            return mean, 0.0, 1.0

        se_hac = np.sqrt(var_hac)
        t_stat = mean / se_hac
        p_val = 2.0 * (1.0 - stats.norm.cdf(np.abs(t_stat)))
        return mean, float(t_stat), float(p_val)

    @classmethod
    def evaluate(
        cls,
        factor_name: str,
        ic_series: np.ndarray,
        residual_ic_series: np.ndarray,
        pbo_value: float,
        ledger: DegreesOfFreedomLedger,
        family_id: str,
        search_space: SearchSpaceSpec,
        forecast_horizon: int = 5,
        factor_corr_matrix: Optional[np.ndarray] = None,
    ) -> Tuple[bool, GateResult, TrialRecord]:
        mean_ic, t_nw, p_raw = cls.compute_newey_west_t(ic_series, forecast_horizon)
        std_ic = float(np.std(ic_series)) if len(ic_series) > 1 else 1e-6
        icir = (mean_ic / max(std_ic, 1e-8)) * np.sqrt(252.0 / forecast_horizon)

        mean_res_ic = float(np.mean(residual_ic_series)) if len(residual_ic_series) else 0.0
        pos_res_ratio = (
            float(np.mean(residual_ic_series > 0)) if len(residual_ic_series) else 0.0
        )

        trial_rec = ledger.register_trial(
            experiment_id=f"exp_{factor_name}_{int(datetime.now().timestamp())}",
            hypothesis_id=f"alpha.{family_id}.{factor_name}",
            family_id=family_id,
            search_space=search_space,
            test_statistic_name=StatisticType.IC_NEWEY_WEST_T,
            raw_statistic_value=t_nw,
            sample_size_T=len(ic_series),
            cross_section_N=500,
            p_raw=p_raw,
            factor_correlation_matrix=factor_corr_matrix,
        )

        metrics = {
            "mean_ic": mean_ic,
            "t_newey_west": t_nw,
            "icir": icir,
            "mean_res_ic": mean_res_ic,
            "pos_res_ratio": pos_res_ratio,
            "pbo": pbo_value,
            "p_raw": p_raw,
            "p_adj_bh_fdr": trial_rec.p_adj_bh_fdr,
            "p_adj_bonf": trial_rec.p_adj_bonferroni,
        }

        thresholds = {
            "min_abs_ic": 0.025,
            "min_abs_t_nw": 3.00,
            "min_icir": 0.70,
            "min_res_ic": 0.015,
            "min_pos_res_ratio": 0.65,
            "max_pbo": 0.20,
            "max_p_adj_bh": 0.05,
        }

        passed = (
            abs(mean_ic) >= thresholds["min_abs_ic"]
            and abs(t_nw) >= thresholds["min_abs_t_nw"]
            and abs(icir) >= thresholds["min_icir"]
            and (mean_res_ic * np.sign(mean_ic)) >= thresholds["min_res_ic"]
            and pos_res_ratio >= thresholds["min_pos_res_ratio"]
            and pbo_value <= thresholds["max_pbo"]
            and trial_rec.p_adj_bh_fdr <= thresholds["max_p_adj_bh"]
        )

        gate_res = GateResult(
            gate_name="Class A (Statistically Supported)",
            passed=passed,
            metrics=metrics,
            thresholds=thresholds,
            details=f"p_raw={p_raw:.4e}, p_adj_bh={trial_rec.p_adj_bh_fdr:.4f}, t_NW={t_nw:.2f}",
        )
        return passed, gate_res, trial_rec


# =========================================================================
# 2. Class B Evaluator: Economic & Style Plausibility (Neutralization)
# =========================================================================
class ClassBEvaluator:
    @staticmethod
    def wls_orthogonalize(
        factor_vals: np.ndarray,
        industry_dummies: np.ndarray,
        log_caps: np.ndarray,
        weights: np.ndarray,
    ) -> Tuple[np.ndarray, float]:
        """
        截面加权最小二乘 WLS 回归：剥离 31 个行业哑变量和对数市值。
        """
        n = len(factor_vals)
        x_mat = np.column_stack([np.ones(n), industry_dummies, log_caps])
        w_sqrt = np.sqrt(weights)[:, None]
        x_w = x_mat * w_sqrt
        y_w = factor_vals * np.sqrt(weights)

        beta, _, _, _ = np.linalg.lstsq(x_w, y_w, rcond=None)
        pred = x_mat @ beta
        resid = factor_vals - pred

        w_mean = np.average(factor_vals, weights=weights)
        ss_tot = np.sum(weights * (factor_vals - w_mean) ** 2)
        ss_res = np.sum(weights * resid ** 2)
        r2 = 1.0 - (ss_res / max(ss_tot, 1e-12))
        return resid, max(0.0, float(r2))

    @classmethod
    def evaluate(
        cls,
        raw_ic_mean: float,
        pure_ic_series: np.ndarray,
        r2_series: np.ndarray,
        size_corr_series: np.ndarray,
        top_industry_weights: np.ndarray,
    ) -> Tuple[bool, GateResult]:
        pure_ic_mean = float(np.mean(pure_ic_series))
        pure_ic_nw_t = float(
            pure_ic_mean / max(np.std(pure_ic_series) / np.sqrt(len(pure_ic_series)), 1e-8)
        )
        irr_ic = abs(pure_ic_mean) / max(abs(raw_ic_mean), 1e-8)
        mean_r2 = float(np.mean(r2_series))
        mean_size_corr = float(np.mean(np.abs(size_corr_series)))

        max_ind_weight = float(np.max(top_industry_weights))
        hhi_ind = float(np.sum(top_industry_weights ** 2))

        metrics = {
            "irr_ic": irr_ic,
            "pure_ic_mean": pure_ic_mean,
            "pure_ic_nw_t": pure_ic_nw_t,
            "r2_explained": mean_r2,
            "abs_size_corr": mean_size_corr,
            "max_ind_weight": max_ind_weight,
            "hhi_industry": hhi_ind,
        }

        thresholds = {
            "min_irr_ic": 0.50,
            "min_pure_ic": 0.015,
            "min_pure_ic_t": 2.50,
            "max_r2": 0.35,
            "max_size_corr": 0.30,
            "max_ind_weight": 0.25,
            "max_hhi": 0.15,
        }

        passed = (
            irr_ic >= thresholds["min_irr_ic"]
            and abs(pure_ic_mean) >= thresholds["min_pure_ic"]
            and abs(pure_ic_nw_t) >= thresholds["min_pure_ic_t"]
            and mean_r2 <= thresholds["max_r2"]
            and mean_size_corr <= thresholds["max_size_corr"]
            and max_ind_weight <= thresholds["max_ind_weight"]
            and hhi_ind <= thresholds["max_hhi"]
        )

        gate_res = GateResult(
            gate_name="Class B (Economically Plausible)",
            passed=passed,
            metrics=metrics,
            thresholds=thresholds,
            details=f"IRR_IC={irr_ic:.3f}, R^2={mean_r2:.3f}, MaxInd={max_ind_weight:.3f}",
        )
        return passed, gate_res


# =========================================================================
# 3. Class C Evaluator: Tradable Candidate (Frictions & Regimes)
# =========================================================================
class ClassCEvaluator:
    @classmethod
    def evaluate(
        cls,
        net_cagr: float,
        net_sharpe: float,
        gross_sharpe: float,
        net_mdd: float,
        daily_turnover: float,
        regime_sharpes: Dict[str, float],
        portfolio_median_adv: float,
        calculated_capacity: float,
    ) -> Tuple[bool, GateResult]:
        calmar = net_cagr / max(abs(net_mdd), 1e-6)
        sharpe_retention = net_sharpe / max(gross_sharpe, 1e-6)

        min_regime_sharpe = min(regime_sharpes.values()) if regime_sharpes else -999.0
        positive_regimes = sum(1 for sr in regime_sharpes.values() if sr > 0.0)

        metrics = {
            "net_cagr": net_cagr,
            "net_sharpe": net_sharpe,
            "gross_sharpe": gross_sharpe,
            "net_mdd": net_mdd,
            "calmar": calmar,
            "daily_turnover": daily_turnover,
            "sharpe_retention": sharpe_retention,
            "min_regime_sharpe": min_regime_sharpe,
            "positive_regimes_count": positive_regimes,
            "median_adv_rmb": portfolio_median_adv,
            "strategy_capacity_rmb": calculated_capacity,
        }

        thresholds = {
            "min_net_cagr": 0.12,
            "min_net_sharpe": 1.00,
            "max_net_mdd": 0.18,
            "min_calmar": 0.70,
            "max_turnover": 0.15,
            "min_sharpe_retention": 0.65,
            "min_allowed_regime_sharpe": -0.50,
            "min_positive_regimes": 2,
            "min_median_adv": 20_000_000.0,
            "min_capacity": 30_000_000.0,
        }

        passed = (
            net_cagr >= thresholds["min_net_cagr"]
            and net_sharpe >= thresholds["min_net_sharpe"]
            and abs(net_mdd) <= thresholds["max_net_mdd"]
            and calmar >= thresholds["min_calmar"]
            and daily_turnover <= thresholds["max_turnover"]
            and sharpe_retention >= thresholds["min_sharpe_retention"]
            and min_regime_sharpe > thresholds["min_allowed_regime_sharpe"]
            and positive_regimes >= thresholds["min_positive_regimes"]
            and portfolio_median_adv >= thresholds["min_median_adv"]
            and calculated_capacity >= thresholds["min_capacity"]
        )

        gate_res = GateResult(
            gate_name="Class C (Tradable Candidate)",
            passed=passed,
            metrics=metrics,
            thresholds=thresholds,
            details=f"Net Sharpe={net_sharpe:.2f}, MDD={net_mdd:.1%}, Cap={calculated_capacity/1e7:.1f}kw",
        )
        return passed, gate_res


# =========================================================================
# 4. Class D Evaluator: Cleanroom Replicated Strategy
# =========================================================================
class ClassDEvaluator:
    @staticmethod
    def compute_deflated_sharpe_ratio(
        sr_candidate: float,
        n_trials: int,
        var_sr: float,
        sample_length_t: int,
        skew: float = 0.0,
        kurt: float = 3.0,
    ) -> float:
        """
        Bailey & Lopez de Prado (2014): Deflated Sharpe Ratio (DSR).
        """
        if n_trials <= 1:
            sr_benchmark = 0.0
        else:
            gamma = 0.5772156649  # Euler-Mascheroni
            sr_benchmark = np.sqrt(var_sr) * (
                (1.0 - gamma) * stats.norm.ppf(1.0 - 1.0 / n_trials)
                + gamma * stats.norm.ppf(1.0 - 1.0 / (n_trials * np.e))
            )

        denom = np.sqrt(
            (1.0 - skew * sr_candidate + ((kurt - 1.0) / 4.0) * (sr_candidate ** 2))
            / max(sample_length_t - 1, 1)
        )
        if denom <= 1e-12:
            return 0.0

        z_stat = (sr_candidate - sr_benchmark) / denom
        return float(stats.norm.cdf(z_stat))

    @classmethod
    def evaluate(
        cls,
        cleanroom_rank_corr: float,
        is_sharpe: float,
        quarantine_oos_sharpe: float,
        adversarial_sharpe: float,
        ledger_total_trials: int,
        sharpe_variance: float,
        sample_length_t: int,
        skew: float = 0.0,
        kurt: float = 3.0,
    ) -> Tuple[bool, GateResult]:
        dsr = cls.compute_deflated_sharpe_ratio(
            sr_candidate=quarantine_oos_sharpe,
            n_trials=ledger_total_trials,
            var_sr=sharpe_variance,
            sample_length_t=sample_length_t,
            skew=skew,
            kurt=kurt,
        )

        oos_sharpe_decay = quarantine_oos_sharpe / max(is_sharpe, 1e-6)
        adv_sharpe_decay = adversarial_sharpe / max(quarantine_oos_sharpe, 1e-6)

        metrics = {
            "cleanroom_rank_corr": cleanroom_rank_corr,
            "dsr": dsr,
            "quarantine_oos_sharpe": quarantine_oos_sharpe,
            "oos_sharpe_decay": oos_sharpe_decay,
            "adversarial_sharpe": adversarial_sharpe,
            "adversarial_decay": adv_sharpe_decay,
        }

        thresholds = {
            "min_cleanroom_corr": 0.999,
            "min_dsr": 0.95,
            "min_quarantine_sharpe": 0.80,
            "min_oos_decay": 0.60,
            "min_adversarial_decay": 0.80,
        }

        passed = (
            cleanroom_rank_corr >= thresholds["min_cleanroom_corr"]
            and dsr >= thresholds["min_dsr"]
            and quarantine_oos_sharpe >= thresholds["min_quarantine_sharpe"]
            and oos_sharpe_decay >= thresholds["min_oos_decay"]
            and adv_sharpe_decay >= thresholds["min_adversarial_decay"]
        )

        gate_res = GateResult(
            gate_name="Class D (Replicated Strategy)",
            passed=passed,
            metrics=metrics,
            thresholds=thresholds,
            details=f"DSR={dsr:.4f}, CleanCorr={cleanroom_rank_corr:.4f}, OOS_SR={quarantine_oos_sharpe:.2f}",
        )
        return passed, gate_res


# =========================================================================
# 5. Master Tier Engine Orchestrator
# =========================================================================
class AlphaTierEngine:
    """
    QTR-OS Alpha 候选四级晋升调度引擎：严密协调 Tier A -> Tier D 逐级检验与报告输出。
    """

    def __init__(self, ledger: DegreesOfFreedomLedger) -> None:
        self.ledger = ledger

    def promote_candidate(
        self,
        factor_name: str,
        family_id: str,
        search_space: SearchSpaceSpec,
        data_a: Dict[str, Any],
        data_b: Dict[str, Any],
        data_c: Dict[str, Any],
        data_d: Dict[str, Any],
    ) -> PromotionReport:
        report = PromotionReport(
            factor_name=factor_name,
            final_tier=AlphaTier.TIER_UNRATED,
            audit_metadata={
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
                "platform_cumulative_trials": self.ledger.total_trials,
            },
        )

        # ---------------- Gate 1: Class A ----------------
        passed_a, res_a, _ = ClassAEvaluator.evaluate(
            factor_name=factor_name,
            ic_series=data_a["ic_series"],
            residual_ic_series=data_a["residual_ic_series"],
            pbo_value=data_a["pbo_value"],
            ledger=self.ledger,
            family_id=family_id,
            search_space=search_space,
            forecast_horizon=data_a.get("forecast_horizon", 5),
            factor_corr_matrix=data_a.get("factor_corr_matrix"),
        )
        report.gate_results.append(res_a)
        report.passed_class_a = passed_a
        if not passed_a:
            report.rejection_reason = "未能通过 Class A 统计显著与动量残差/PBO 门槛"
            return report
        report.final_tier = AlphaTier.TIER_A

        # ---------------- Gate 2: Class B ----------------
        passed_b, res_b = ClassBEvaluator.evaluate(
            raw_ic_mean=res_a.metrics["mean_ic"],
            pure_ic_series=data_b["pure_ic_series"],
            r2_series=data_b["r2_series"],
            size_corr_series=data_b["size_corr_series"],
            top_industry_weights=data_b["top_industry_weights"],
        )
        report.gate_results.append(res_b)
        report.passed_class_b = passed_b
        if not passed_b:
            report.rejection_reason = "未能通过 Class B 行业与对数市值中性化剥离纯度门槛"
            return report
        report.final_tier = AlphaTier.TIER_B

        # ---------------- Gate 3: Class C ----------------
        passed_c, res_c = ClassCEvaluator.evaluate(
            net_cagr=data_c["net_cagr"],
            net_sharpe=data_c["net_sharpe"],
            gross_sharpe=data_c["gross_sharpe"],
            net_mdd=data_c["net_mdd"],
            daily_turnover=data_c["daily_turnover"],
            regime_sharpes=data_c["regime_sharpes"],
            portfolio_median_adv=data_c["portfolio_median_adv"],
            calculated_capacity=data_c["calculated_capacity"],
        )
        report.gate_results.append(res_c)
        report.passed_class_c = passed_c
        if not passed_c:
            report.rejection_reason = "未能通过 Class C 真实微观摩擦、Regime 稳定性或容量门槛"
            return report
        report.final_tier = AlphaTier.TIER_C

        # ---------------- Gate 4: Class D ----------------
        passed_d, res_d = ClassDEvaluator.evaluate(
            cleanroom_rank_corr=data_d["cleanroom_rank_corr"],
            is_sharpe=data_d["is_sharpe"],
            quarantine_oos_sharpe=data_d["quarantine_oos_sharpe"],
            adversarial_sharpe=data_d["adversarial_sharpe"],
            ledger_total_trials=self.ledger.total_trials,
            sharpe_variance=data_d.get("sharpe_variance", 0.25),
            sample_length_t=data_d.get("sample_length_t", 252),
            skew=data_d.get("skew", 0.0),
            kurt=data_d.get("kurt", 3.0),
        )
        report.gate_results.append(res_d)
        report.passed_class_d = passed_d
        if not passed_d:
            report.rejection_reason = "未能通过 Class D 隔离干净室独立复现或紧缩夏普比率 (DSR) 门槛"
            return report
        report.final_tier = AlphaTier.TIER_D

        return report
