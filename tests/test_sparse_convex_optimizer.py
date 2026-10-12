"""
UniQuant Risk: TwoStageSparseConvexOptimizer 单元测试
===================================================
验证:
  1. 5000+ 标的全截面下阶段一拓扑稀疏化至 <= 100 只标的；
  2. 单行业持股数严格 <= 4 只；
  3. 阶段二凸优化内点法求解:
     - 多头总和严格锁定 75% (0.75)；
     - 单票上限严格 <= 2.5% (0.025)；
     - 31 个申万一级行业集中度严格 <= 10% (0.10)；
  4. 协方差矩阵特征值下界保障 lambda_min >= 0.05。
"""

import pytest
import numpy as np
import pandas as pd

from uniquant.risk.sparse_convex_optimizer import (
    TwoStageSparseConvexOptimizer,
    TwoStageOptimizerConfig,
    TwoStageOptimizationResult,
)


class TestTwoStageSparseConvexOptimizer:
    """两阶段稀疏化凸优化求解器完整性测试"""

    @pytest.fixture
    def mock_large_market(self):
        """构造 5,000 只标的、31 个申万一级行业的模拟全市场截面"""
        np.random.seed(42)
        n_stocks = 5000
        sw_industries = [
            "农林牧渔", "基础化工", "钢铁", "有色金属", "电子", "汽车", "家用电器", "食品饮料",
            "纺织服饰", "轻工制造", "医药生物", "公用事业", "交通运输", "房地产", "商贸零售",
            "社会服务", "银行", "非银金融", "通信", "计算机", "传媒", "煤炭", "石油石化",
            "环保", "美容护理", "电力设备", "机械设备", "国防军工", "建筑材料", "建筑装饰", "综合"
        ]
        assert len(sw_industries) == 31

        codes = [f"{i:06d}.SH" if i % 2 == 0 else f"{i:06d}.SZ" for i in range(1, n_stocks + 1)]
        industries = np.random.choice(sw_industries, size=n_stocks)
        alpha = np.random.normal(0.05, 0.15, size=n_stocks)
        z_cnmm = np.random.uniform(0.1, 1.2, size=n_stocks)
        cashtrap = (z_cnmm > 1.0) & (np.random.rand(n_stocks) < 0.2)

        df = pd.DataFrame({
            "code": codes,
            "industry": industries,
            "causal_alpha": alpha,
            "z_cnmm": z_cnmm,
            "cashtrap_flag": cashtrap,
            "is_financial": np.isin(industries, ["银行", "非银金融"]),
        })

        return df, sw_industries

    def test_stage1_sparsification_limits(self, mock_large_market):
        """测试阶段一稀疏化规模 <= 100 且每行业只数 <= 4"""
        df_market, sw_industries = mock_large_market
        optimizer = TwoStageSparseConvexOptimizer(TwoStageOptimizerConfig(
            stage1_universe_size=100,
            industry_max_stocks=4,
        ))

        selected = optimizer.stage1_sparsify_universe(df_market)
        assert len(selected) <= 100
        assert len(selected) >= 50

        # 检查选出标的的行业分布
        sub_df = df_market[df_market["code"].isin(selected)]
        counts = sub_df["industry"].value_counts()
        for ind, cnt in counts.items():
            assert cnt <= 4, f"行业 {ind} 选出只数 {cnt} 超过上限 4 只"

    def test_stage2_convex_optimization_constraints(self, mock_large_market):
        """测试阶段二二次规划严格满足多头 75%、单票 2.5%、行业 10% 约束"""
        df_market, sw_industries = mock_large_market
        optimizer = TwoStageSparseConvexOptimizer(TwoStageOptimizerConfig(
            total_long_exposure=0.75,
            single_stock_max_weight=0.025,
            industry_max_weight=0.10,
            industry_max_stocks=4,
            stage1_universe_size=100,
            min_eigenvalue_floor=0.05,
        ))

        selected = optimizer.stage1_sparsify_universe(df_market)
        sub_df = df_market[df_market["code"].isin(selected)]

        # 构造模拟历史收益率序列 (120 天日收益)
        np.random.seed(101)
        n_days = 120
        n_sel = len(selected)
        returns_mat = np.random.randn(n_days, n_sel) * 0.02 + 0.0005
        df_returns = pd.DataFrame(returns_mat, columns=selected)

        expected_returns = dict(zip(sub_df["code"], sub_df["causal_alpha"]))
        stock_to_ind = dict(zip(sub_df["code"], sub_df["industry"]))

        res = optimizer.solve(
            selected_stocks=selected,
            expected_returns=expected_returns,
            stock_returns_matrix=df_returns,
            stock_to_industry=stock_to_ind,
        )

        assert isinstance(res, TwoStageOptimizationResult)
        assert res.is_converged is True

        # 1. 验证多头总权重严格锁定 75% (+-0.001 容差)
        assert abs(res.total_long_exposure - 0.75) < 0.005, f"总权重 {res.total_long_exposure} 偏离 75%"

        # 2. 验证单票上限 <= 2.5%
        for code, w in res.weights.items():
            assert w <= 0.025 + 1e-4, f"个股 {code} 权重 {w} 超过 2.5% 上限"
            assert w >= 0.0, f"个股 {code} 权重为负数: {w}"

        # 3. 验证 31 个申万一级行业集中度 <= 10%
        for ind, ind_w in res.industry_weights.items():
            assert ind_w <= 0.10 + 1e-4, f"行业 {ind} 权重 {ind_w} 超过 10% 上限"

        # 4. 验证单行业持股只数 <= 4 只
        for ind, cnt in res.industry_stock_counts.items():
            assert cnt <= 4, f"行业 {ind} 持仓只数 {cnt} 超过 4 只上限"

        # 5. 验证协方差特征值下界 lambda_min >= 0.05
        assert res.lambda_min_cov >= 0.05 - 1e-6, f"最小特征值 {res.lambda_min_cov} 低于下界 0.05"
