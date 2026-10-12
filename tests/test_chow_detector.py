"""
UniQuant Brain Regime: ChowDetector 单元测试
"""

import numpy as np

from uniquant.brain.regime.chow_detector import (
    ChowDetector,
    ChowTestResult,
    SupChowResult,
    PriorResetResult,
)


class TestChowDetector:
    """ChowDetector 单元测试"""

    def test_known_breakpoint_with_true_shift(self):
        """测试在存在真实结构断裂时已知断裂点 Chow 检验"""
        np.random.seed(42)
        n1, n2 = 100, 100
        x1 = np.linspace(-2, 2, n1)
        x2 = np.linspace(-2, 2, n2)
        # Regime 1: slope 1.0; Regime 2: slope -2.0 (强突变)
        y1 = 1.0 + 1.0 * x1 + np.random.normal(0, 0.2, n1)
        y2 = 1.0 - 2.0 * x2 + np.random.normal(0, 0.2, n2)

        y = np.concatenate([y1, y2])
        X = np.concatenate([x1, x2])

        detector = ChowDetector(f_critical=15.0)
        res = detector.test_known_breakpoint(y, X, break_index=100)

        assert isinstance(res, ChowTestResult)
        assert res.f_stat > 15.0, f"F 统计量 {res.f_stat} 未突破 15.0 临界值"
        assert res.p_value < 1e-4
        assert res.is_break is True
        assert res.break_index == 100

    def test_sup_chow_unknown_breakpoint_detection(self):
        """测试 Andrews Sup-Chow 未知断裂点自动扫描"""
        np.random.seed(123)
        n = 200
        t_break = 80
        x = np.random.normal(0, 1, n)
        # 前 80 期 slope = 0.5，后 120 期 slope = 2.5
        y = np.zeros(n)
        y[:t_break] = 0.5 * x[:t_break] + np.random.normal(0, 0.3, t_break)
        y[t_break:] = 2.5 * x[t_break:] + np.random.normal(0, 0.3, n - t_break)

        detector = ChowDetector(f_critical=15.0, trimming_pct=0.15)
        res = detector.test_sup_chow(y, x)

        assert isinstance(res, SupChowResult)
        assert res.sup_f > 15.0
        assert res.is_break is True
        # 扫描出的断裂点应接近真实断裂点 80
        assert abs(res.break_index - t_break) <= 10
        assert "【突变触发】" in res.verdict

    def test_sup_chow_no_break_stationary(self):
        """测试在无突变平稳序列下 Sup-Chow 维持平稳"""
        np.random.seed(999)
        n = 150
        x = np.random.normal(0, 1, n)
        y = 1.0 + 0.8 * x + np.random.normal(0, 0.5, n)

        detector = ChowDetector(f_critical=15.0)
        res = detector.test_sup_chow(y, x)

        assert res.is_break is False
        assert res.sup_f <= 15.0
        assert "【状态平稳】" in res.verdict

    def test_prior_reset_engine_on_break(self):
        """测试先验重置器在突变触发时的重置动作"""
        sup_res = SupChowResult(
            sup_f=28.5,
            p_value=1e-6,
            is_break=True,
            break_index=75,
            break_date="2024-03-15",
            k_params=2,
            n_obs=200,
        )

        reset_res = ChowDetector.reset_empirical_bayes_priors(
            sup_res,
            current_prior_mean=0.55,
            current_prior_tau2=0.010,
            current_window_len=60,
        )

        assert isinstance(reset_res, PriorResetResult)
        assert reset_res.regime_break_detected is True
        assert reset_res.reset_prior_mean == 0.40
        assert reset_res.reset_prior_tau2 > reset_res.original_prior_tau2
        assert reset_res.reset_window_len == 30  # 60 * 0.5
        assert reset_res.covariance_shrinkage_boost == 0.25
        assert "⚠️ 突变断裂重置生效" in reset_res.action_log

    def test_prior_reset_engine_on_no_break(self):
        """测试先验重置器在无突变时的维持机制"""
        sup_res = SupChowResult(
            sup_f=8.2,
            p_value=0.05,
            is_break=False,
            break_index=50,
            break_date=None,
        )

        reset_res = ChowDetector.reset_empirical_bayes_priors(
            sup_res,
            current_prior_mean=0.48,
            current_prior_tau2=0.012,
            current_window_len=60,
        )

        assert reset_res.regime_break_detected is False
        assert reset_res.reset_prior_mean == 0.48
        assert reset_res.reset_prior_tau2 == 0.012
        assert reset_res.reset_window_len == 60
        assert reset_res.covariance_shrinkage_boost == 0.0
