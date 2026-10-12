"""
CSCVAndPBOAnalyzer 单元测试与门禁验证
=============================================================================
验证:
  1. 16 切片 12,870 组对称组合几何约束与 BLAS 矩阵乘法加速;
  2. 真实优势策略在 CSCV 下的超低过拟合概率 PBO < 0.10;
  3. 纯白噪声策略在 CSCV 下退化为 PBO ≈ 0.50 随机对称基线;
  4. 条件 PBO 计算与 OLS 绩效衰减回归。
=============================================================================
"""

import pytest
import numpy as np
import pandas as pd

from uniquant.brain.factors.cscv_pbo_analyzer import (
    CSCVAndPBOAnalyzer,
    CSCVPBOResult,
)


class TestCSCVAndPBOAnalyzer:
    """CSCV 交叉验证与 PBO 分析器测试"""

    def test_combinatorial_geometry_and_matrix_shapes(self):
        """测试 1: 切片划分组合几何形状与布尔矩阵投影约束"""
        analyzer = CSCVAndPBOAnalyzer(n_slices=16)
        assert analyzer.S == 16
        assert analyzer.k == 8
        assert analyzer.C == 12870
        assert analyzer.B.shape == (12870, 16)
        # 每一行必须恰好包含 8 个 1.0
        assert np.all(np.sum(analyzer.B, axis=1) == 8.0)

    def test_invalid_parameters_handling(self):
        """测试 2: 奇数切片或超小样本异常防御"""
        with pytest.raises(ValueError, match="划分切片数 S 必须为偶数"):
            CSCVAndPBOAnalyzer(n_slices=15)

        analyzer = CSCVAndPBOAnalyzer(n_slices=8) # C(8, 4) = 70
        df_short = pd.DataFrame(np.random.randn(5, 3))
        with pytest.raises(ValueError, match="时间期数 T"):
            analyzer.evaluate(df_short)

        df_single = pd.DataFrame(np.random.randn(20, 1))
        with pytest.raises(ValueError, match="候选策略维度 N"):
            analyzer.evaluate(df_single)

    def test_robust_strategy_low_pbo_and_conditional_pbo(self):
        """测试 3: 构造具备真实显著 Alpha 的优势策略，PBO 必须严格通过门禁 (<0.10)"""
        np.random.seed(42)
        T, N = 1000, 10
        # 9 个普通/随机策略 (年化收益 ~ 3%, 波动 ~ 15%)
        noise_rets = np.random.normal(0.0001, 0.01, size=(T, N - 1))
        # 1 个真 Alpha 策略 (年化收益 ~ 25%, 波动 ~ 10%, 高夏普)
        alpha_rets = np.random.normal(0.0010, 0.007, size=(T, 1))

        all_rets = np.hstack([noise_rets, alpha_rets])
        cols = [f"strat_noise_{i}" for i in range(N - 1)] + ["strat_flagship_alpha"]
        df_rets = pd.DataFrame(all_rets, columns=cols)

        analyzer = CSCVAndPBOAnalyzer(n_slices=16, risk_free_rate=0.02, annualization_factor=252.0)
        res = analyzer.evaluate(df_rets, target_conditional_strategy="strat_flagship_alpha")

        assert res.total_combinations == 12870
        assert res.pbo_gate_passed is True
        assert res.pbo < 0.05, f"真实 Alpha 策略全局 PBO 应远低于 0.10，实测: {res.pbo}"
        assert res.mean_relative_rank > 0.80
        assert res.prob_loss_oos < 0.02, f"样本外亏损概率必须极低，实测: {res.prob_loss_oos}"

        # 条件 PBO 检验
        assert res.conditional_pbo is not None
        assert res.conditional_pbo == 0.0
        assert res.winner_frequency["strat_flagship_alpha"]["frequency_pct"] > 95.0

    def test_pure_noise_generates_high_pbo_due_to_selection_bias(self):
        """测试 4: 构造纯白噪声策略群，多重测试选择偏差必然导致 PBO 显著高企 (>0.50)"""
        np.random.seed(123)
        T, N = 800, 15
        pure_noise = np.random.normal(0.0, 0.01, size=(T, N))
        df_noise = pd.DataFrame(pure_noise, columns=[f"noise_{i}" for i in range(N)])

        # 为降低耗时选用 S=10 (C=252)
        analyzer = CSCVAndPBOAnalyzer(n_slices=10)
        res = analyzer.evaluate(df_noise)

        # 在纯白噪声随机漫步下，由于 15 种候选策略的选择偏差，样本内最优策略在样本外均值回归，PBO > 0.50
        assert res.pbo > 0.50, f"白噪声多重比较下 PBO 必须表现出显著过拟合 (>0.50)，实测: {res.pbo}"
        assert res.pbo_gate_passed is False
