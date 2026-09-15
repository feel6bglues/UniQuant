"""
Unit tests for QTR-OS Research Plane: Degrees of Freedom Ledger & Alpha Tier Engine.
File: tests/test_research_os_gates.py
"""

import numpy as np
import pytest

from uniquant.research.ledger.degrees_of_freedom import (
    DegreesOfFreedomLedger,
    SearchSpaceSpec,
    StatisticType,
)
from uniquant.research.gates.alpha_tier_engine import (
    AlphaTier,
    AlphaTierEngine,
    ClassAEvaluator,
    ClassBEvaluator,
    ClassDEvaluator,
)


@pytest.fixture
def empty_ledger():
    return DegreesOfFreedomLedger(alpha_nominal=0.05, fdr_nominal=0.10, initial_alpha_wealth=0.05)


@pytest.fixture
def mock_search_space():
    return SearchSpaceSpec(
        name="vol_reversal_grid",
        dimension=2,
        parameter_grid={"window": [5, 10, 20, 60], "quantile": [0.1, 0.2, 0.3]},
    )


def test_search_space_cardinality(mock_search_space):
    assert mock_search_space.discrete_cardinality == 12


def test_ledger_registration_and_bonferroni(empty_ledger, mock_search_space):
    # Trial 1: very significant
    rec1 = empty_ledger.register_trial(
        experiment_id="exp_01",
        hypothesis_id="alpha.test.f1",
        family_id="fam_01",
        search_space=mock_search_space,
        test_statistic_name=StatisticType.IC_NEWEY_WEST_T,
        raw_statistic_value=3.8,
        sample_size_T=500,
        cross_section_N=500,
        p_raw=0.0001,
        alpha_wealth_bid=0.001,
    )
    assert rec1.trial_index == 1
    assert rec1.effective_m == 1.0
    assert rec1.p_adj_bonferroni == 0.0001
    assert rec1.passed_bonferroni is True
    assert rec1.passed_bh_fdr is True

    # Register 10 more insignificant trials
    for i in range(2, 12):
        empty_ledger.register_trial(
            experiment_id=f"exp_{i:02d}",
            hypothesis_id=f"alpha.test.f{i}",
            family_id="fam_01",
            search_space=mock_search_space,
            test_statistic_name=StatisticType.IC_NEWEY_WEST_T,
            raw_statistic_value=1.2,
            sample_size_T=500,
            cross_section_N=500,
            p_raw=0.08,
            alpha_wealth_bid=0.001,
        )

    assert empty_ledger.total_trials == 11
    # Check that Bonferroni dynamically adjusted for trial 1
    # 11 trials in family -> p_adj_bonferroni = 0.0001 * 11 = 0.0011 <= 0.05
    assert empty_ledger.trials[0].p_adj_bonferroni == pytest.approx(0.0011, rel=1e-3)
    # insignificant trial: 0.08 * 11 = 0.88
    assert empty_ledger.trials[-1].p_adj_bonferroni == pytest.approx(0.88, rel=1e-3)
    assert empty_ledger.trials[-1].passed_bonferroni is False


def test_ledger_spectral_effective_m(empty_ledger, mock_search_space):
    # Test perfectly correlated factors -> M_eff should be ~1.0
    k = 5
    corr_perfect = np.ones((k, k))
    m_eff_perfect = empty_ledger.compute_effective_m("fam_corr", corr_perfect)
    assert m_eff_perfect == pytest.approx(1.0, abs=1e-3)

    # Test orthogonal factors -> M_eff should be ~k
    corr_ortho = np.eye(k)
    m_eff_ortho = empty_ledger.compute_effective_m("fam_ortho", corr_ortho)
    assert m_eff_ortho == pytest.approx(float(k), abs=1e-3)


def test_ledger_alpha_wealth_depletion():
    small_ledger = DegreesOfFreedomLedger(initial_alpha_wealth=0.002)
    spec = SearchSpaceSpec(name="test", dimension=1)

    # 1st trial consumes 0.001 -> left 0.001
    small_ledger.register_trial(
        experiment_id="exp_w1",
        hypothesis_id="h1",
        family_id="f1",
        search_space=spec,
        test_statistic_name=StatisticType.STUDENT_T,
        raw_statistic_value=0.5,
        sample_size_T=100,
        cross_section_N=100,
        p_raw=0.6,
        alpha_wealth_bid=0.001,
    )
    # 2nd trial consumes 0.001 -> left 0.000
    small_ledger.register_trial(
        experiment_id="exp_w2",
        hypothesis_id="h2",
        family_id="f1",
        search_space=spec,
        test_statistic_name=StatisticType.STUDENT_T,
        raw_statistic_value=0.5,
        sample_size_T=100,
        cross_section_N=100,
        p_raw=0.6,
        alpha_wealth_bid=0.001,
    )
    # 3rd trial should raise PermissionError
    with pytest.raises(PermissionError, match="Alpha Wealth 耗尽"):
        small_ledger.register_trial(
            experiment_id="exp_w3",
            hypothesis_id="h3",
            family_id="f1",
            search_space=spec,
            test_statistic_name=StatisticType.STUDENT_T,
            raw_statistic_value=0.5,
            sample_size_T=100,
            cross_section_N=100,
            p_raw=0.6,
            alpha_wealth_bid=0.001,
        )


def test_newey_west_hac_accuracy():
    np.random.seed(42)
    # Generate AR(1) with positive mean
    e = np.random.normal(0, 1, 300)
    x = np.zeros(300)
    for t in range(1, 300):
        x[t] = 0.5 * x[t - 1] + e[t]
    x += 0.05  # true positive mean

    mean, t_nw, p_val = ClassAEvaluator.compute_newey_west_t(x, forecast_horizon=5)
    assert mean == pytest.approx(np.mean(x), rel=1e-5)
    # Positive t-stat
    assert t_nw > 0
    # p-value valid
    assert 0.0 <= p_val <= 1.0


def test_wls_orthogonalization():
    n = 200
    k_ind = 10
    ind_dummies = np.zeros((n, k_ind))
    for i in range(n):
        ind_dummies[i, i % k_ind] = 1.0
    log_caps = np.linspace(20, 25, n)
    weights = np.sqrt(np.exp(log_caps - 20))

    # Factor strongly driven by log_caps
    factor = 0.8 * log_caps + np.random.normal(0, 0.2, n)
    resid, r2 = ClassBEvaluator.wls_orthogonalize(factor, ind_dummies, log_caps, weights)

    assert len(resid) == n
    assert r2 > 0.70  # Should explain substantial variance


def test_deflated_sharpe_ratio():
    # When trial = 1, sr = 1.5, T = 252 -> DSR should be very high (> 0.99)
    dsr_single = ClassDEvaluator.compute_deflated_sharpe_ratio(
        sr_candidate=1.5, n_trials=1, var_sr=0.25, sample_length_t=252
    )
    assert dsr_single > 0.99

    # When trials = 1000, sr = 0.8, T = 100 -> DSR should be low (< 0.50)
    dsr_swept = ClassDEvaluator.compute_deflated_sharpe_ratio(
        sr_candidate=0.8, n_trials=1000, var_sr=0.25, sample_length_t=100
    )
    assert dsr_swept < 0.50


def test_alpha_tier_engine_full_pass(empty_ledger, mock_search_space):
    engine = AlphaTierEngine(empty_ledger)
    np.random.seed(123)

    # Craft inputs that satisfy all 4 gates
    t_len = 250
    ic_seq = np.random.normal(0.04, 0.02, t_len)
    res_seq = np.random.normal(0.025, 0.015, t_len)

    data_a = {
        "ic_series": ic_seq,
        "residual_ic_series": res_seq,
        "pbo_value": 0.12,
        "forecast_horizon": 5,
    }

    pure_ic_seq = np.random.normal(0.03, 0.015, t_len)
    data_b = {
        "pure_ic_series": pure_ic_seq,
        "r2_series": np.array([0.15] * 20),
        "size_corr_series": np.array([0.10] * 20),
        "top_industry_weights": np.array([0.10, 0.12, 0.08, 0.05, 0.05]),
    }

    data_c = {
        "net_cagr": 0.18,
        "net_sharpe": 1.45,
        "gross_sharpe": 1.80,
        "net_mdd": -0.12,
        "daily_turnover": 0.08,
        "regime_sharpes": {
            "bull_low_vol": 1.8,
            "bull_high_vol": 1.2,
            "bear_low_vol": 0.4,
            "bear_high_vol": 0.2,
        },
        "portfolio_median_adv": 45_000_000.0,
        "calculated_capacity": 60_000_000.0,
    }

    data_d = {
        "cleanroom_rank_corr": 0.9995,
        "is_sharpe": 1.50,
        "quarantine_oos_sharpe": 1.35,
        "adversarial_sharpe": 1.20,
        "sharpe_variance": 0.20,
        "sample_length_t": 252,
    }

    report = engine.promote_candidate(
        factor_name="illiq_clean_alpha",
        family_id="liquidity_family",
        search_space=mock_search_space,
        data_a=data_a,
        data_b=data_b,
        data_c=data_c,
        data_d=data_d,
    )

    assert report.passed_class_a is True
    assert report.passed_class_b is True
    assert report.passed_class_c is True
    assert report.passed_class_d is True
    assert report.final_tier == AlphaTier.TIER_D
    assert report.rejection_reason is None
    assert len(report.gate_results) == 4


def test_alpha_tier_engine_rejection_at_class_b(empty_ledger, mock_search_space):
    engine = AlphaTierEngine(empty_ledger)
    np.random.seed(123)

    t_len = 250
    data_a = {
        "ic_series": np.random.normal(0.04, 0.02, t_len),
        "residual_ic_series": np.random.normal(0.025, 0.015, t_len),
        "pbo_value": 0.12,
        "forecast_horizon": 5,
    }

    # High R^2 (0.65 > 0.35) -> Should FAIL Class B
    data_b = {
        "pure_ic_series": np.random.normal(0.005, 0.015, t_len),  # weak pure IC
        "r2_series": np.array([0.65] * 20),
        "size_corr_series": np.array([0.55] * 20),
        "top_industry_weights": np.array([0.45, 0.20]),  # 45% in one industry
    }

    data_c = {}
    data_d = {}

    report = engine.promote_candidate(
        factor_name="microcap_hidden_factor",
        family_id="size_family",
        search_space=mock_search_space,
        data_a=data_a,
        data_b=data_b,
        data_c=data_c,
        data_d=data_d,
    )

    assert report.passed_class_a is True
    assert report.passed_class_b is False
    assert report.final_tier == AlphaTier.TIER_A
    assert "未能通过 Class B" in report.rejection_reason
