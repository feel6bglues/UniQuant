"""
QTR-OS Research Control Plane: factor-chain bridge.

File: uniquant/research/ledger/bridge.py

Bridges the production factor analysis output (IC / ICIR / t-stat per factor
per holding period) into the :class:`DegreesOfFreedomLedger`, so the platform's
"strongest anti-overfitting defence" actually covers real factor production
instead of being an unreferenced island.

Deliberately dependency-free at the layer boundary: this module duck-types the
IC-result objects (reads ``ic_t_stat`` / ``n_periods`` / ``icir``) so the
``research`` plane never has to import from ``brain`` — the caller (services
layer) is the one that knows about :class:`FactorAnalyzer`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import scipy.stats as stats

from uniquant.research.ledger.degrees_of_freedom import (
    DegreesOfFreedomLedger,
    SearchSpaceSpec,
    StatisticType,
)


def ic_t_stat_to_p_value(t_stat: float, n_periods: int) -> float:
    """Two-sided Student-t p-value with ``df = n_periods - 1``.

    NOTE (honest limitation): ``FactorAnalyzer`` computes a *naive* t
    (``ic_mean / (ic_std / sqrt(n))``) with no autocorrelation adjustment, so
    daily-IC p-values are optimistic. That gap is partially absorbed by the
    multiple-testing correction below and is recorded in each trial's metadata
    (``autocorr_adjusted=False``) rather than silently overstated.
    """
    if n_periods <= 1 or not np.isfinite(t_stat):
        return 1.0
    try:
        return float(2.0 * stats.t.sf(abs(float(t_stat)), df=n_periods - 1))
    except (TypeError, ValueError):
        return 1.0


@dataclass
class FactorTrialAudit:
    """One registered (factor, holding-period) test and its adjusted verdicts."""

    factor: str
    holding_period: int
    statistic: float
    p_raw: float
    p_adj_bonferroni: float
    p_adj_bh_fdr: float
    p_adj_by_fdr: float
    passed_bonferroni: bool
    passed_bh_fdr: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "factor": self.factor,
            "holding_period": self.holding_period,
            "statistic": self.statistic,
            "p_raw": self.p_raw,
            "p_adj_bonferroni": self.p_adj_bonferroni,
            "p_adj_bh_fdr": self.p_adj_bh_fdr,
            "p_adj_by_fdr": self.p_adj_by_fdr,
            "passed_bonferroni": self.passed_bonferroni,
            "passed_bh_fdr": self.passed_bh_fdr,
        }


@dataclass
class LedgerAudit:
    """Aggregate verdict of one ledger registration sweep."""

    family_id: str
    experiment_id: str
    registered: int = 0
    skipped: int = 0
    alpha_wealth_exhausted: bool = False
    trials: List[FactorTrialAudit] = field(default_factory=list)
    per_factor: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    hurdle_report: Dict[str, Any] = field(default_factory=dict)
    total_platform_trials: int = 0
    alpha_wealth_remaining: float = 0.0

    @property
    def significant_factors(self) -> List[str]:
        return sorted(
            name
            for name, info in self.per_factor.items()
            if info.get("any_period_passed_bh_fdr")
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family_id": self.family_id,
            "experiment_id": self.experiment_id,
            "registered": self.registered,
            "skipped": self.skipped,
            "alpha_wealth_exhausted": self.alpha_wealth_exhausted,
            "total_platform_trials": self.total_platform_trials,
            "alpha_wealth_remaining": self.alpha_wealth_remaining,
            "significant_factors": self.significant_factors,
            "per_factor": self.per_factor,
            "trials": [t.to_dict() for t in self.trials],
            "hurdle_report": self.hurdle_report,
        }


def _collect_tests(
    ic_results: Dict[str, Dict[int, Any]],
) -> List[Tuple[str, int, float, int]]:
    """Flatten ``{factor: {period: result}}`` into ``(factor, period, t, n)``."""
    tests: List[Tuple[str, int, float, int]] = []
    for factor, period_results in (ic_results or {}).items():
        if not period_results:
            continue
        try:
            ordered = sorted(period_results.items(), key=lambda kv: int(kv[0]))
        except (TypeError, ValueError):
            ordered = list(period_results.items())
        for period, result in ordered:
            if result is None:
                continue
            n_periods = int(getattr(result, "n_periods", 0) or 0)
            if n_periods <= 0:
                continue
            t_stat = getattr(result, "ic_t_stat", None)
            if t_stat is None or not np.isfinite(_as_float(t_stat)):
                continue
            tests.append((str(factor), int(period), _as_float(t_stat), n_periods))
    return tests


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _aggregate_per_factor(trials: Sequence[FactorTrialAudit]) -> Dict[str, Dict[str, Any]]:
    per_factor: Dict[str, Dict[str, Any]] = {}
    for trial in trials:
        info = per_factor.setdefault(
            trial.factor,
            {"periods": {}, "min_q_bh": 1.0, "best_period_abs_t": -1.0, "best_period": None},
        )
        info["periods"][trial.holding_period] = {
            "statistic": trial.statistic,
            "p_raw": trial.p_raw,
            "p_adj_bh_fdr": trial.p_adj_bh_fdr,
            "passed_bh_fdr": trial.passed_bh_fdr,
        }
        info["min_q_bh"] = min(info["min_q_bh"], trial.p_adj_bh_fdr)
        if abs(trial.statistic) > info["best_period_abs_t"]:
            info["best_period_abs_t"] = abs(trial.statistic)
            info["best_period"] = trial.holding_period

    for info in per_factor.values():
        info["any_period_passed_bh_fdr"] = any(
            p["passed_bh_fdr"] for p in info["periods"].values()
        )
        info["best_period_abs_t"] = round(float(info["best_period_abs_t"]), 4)
    return per_factor


def register_factor_trials(
    ledger: DegreesOfFreedomLedger,
    ic_results: Dict[str, Dict[int, Any]],
    *,
    family_id: str,
    experiment_id: Optional[str] = None,
    search_space_name: str = "factor_scan",
    cross_section_N: int = 0,
    alpha_wealth_bid: float = 0.001,
    code_git_sha: str = "",
    data_snapshot_hash: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> LedgerAudit:
    """Register every ``(factor, holding-period)`` test in ``ic_results``.

    Each distinct test counts as one trial (a 13-factor × 3-horizon scan = 39
    trials), which is the honest size of the search actually performed. The
    ledger then applies Bonferroni / BH-FDR / BY-FDR across the family and
    charges Alpha-Wealth. When wealth is exhausted the sweep stops gracefully
    (``alpha_wealth_exhausted=True``) instead of raising into the caller.
    """
    experiment_id = experiment_id or (
        f"scan_{family_id}_{int(datetime.now(timezone.utc).timestamp())}"
    )
    tests = _collect_tests(ic_results)

    factor_names = sorted({t[0] for t in tests})
    periods = sorted({t[1] for t in tests})
    search_space = SearchSpaceSpec(
        name=search_space_name,
        dimension=2,
        parameter_grid={"factors": factor_names, "holding_periods": periods},
    )

    audit = LedgerAudit(family_id=family_id, experiment_id=experiment_id)
    base_metadata = dict(metadata or {})

    for factor, period, t_stat, n_periods in tests:
        p_raw = ic_t_stat_to_p_value(t_stat, n_periods)
        trial_metadata = dict(base_metadata)
        trial_metadata.update(
            {
                "factor": factor,
                "holding_period": period,
                "autocorr_adjusted": False,
            }
        )
        try:
            rec = ledger.register_trial(
                experiment_id=experiment_id,
                hypothesis_id=f"{factor}@{period}d",
                family_id=family_id,
                search_space=search_space,
                test_statistic_name=StatisticType.STUDENT_T,
                raw_statistic_value=t_stat,
                sample_size_T=n_periods,
                cross_section_N=int(cross_section_N),
                p_raw=p_raw,
                alpha_wealth_bid=alpha_wealth_bid,
                code_git_sha=code_git_sha,
                data_snapshot_hash=data_snapshot_hash,
                metadata=trial_metadata,
            )
        except PermissionError:
            audit.alpha_wealth_exhausted = True
            audit.skipped += 1
            break

        audit.registered += 1
        audit.trials.append(
            FactorTrialAudit(
                factor=factor,
                holding_period=period,
                statistic=t_stat,
                p_raw=rec.p_raw,
                p_adj_bonferroni=rec.p_adj_bonferroni,
                p_adj_bh_fdr=rec.p_adj_bh_fdr,
                p_adj_by_fdr=rec.p_adj_by_fdr,
                passed_bonferroni=rec.passed_bonferroni,
                passed_bh_fdr=rec.passed_bh_fdr,
            )
        )

    audit.per_factor = _aggregate_per_factor(audit.trials)
    audit.total_platform_trials = ledger.total_trials
    audit.alpha_wealth_remaining = round(float(ledger.current_alpha_wealth), 6)
    audit.hurdle_report = ledger.get_hurdle_report(family_id)
    return audit
