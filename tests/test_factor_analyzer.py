"""
测试 FactorAnalyzer
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.factors.analyzer import (
    FactorAnalyzer,
    FactorICResult,
)


class TestFactorAnalyzer:
    """FactorAnalyzer 测试类"""
    
    @pytest.fixture
    def analyzer(self):
        return FactorAnalyzer()
    
    @pytest.fixture
    def sample_factor_df(self):
        """创建示例因子数据"""
        np.random.seed(42)
        n_stocks = 50
        n_dates = 100
        
        data = []
        for date in pd.date_range("2023-01-01", periods=n_dates):
            for i in range(n_stocks):
                data.append({
                    "date": date,
                    "code": f"{i:06d}.SZ",
                    "close": 10 + np.random.randn() * 2,
                    "factor_a": np.random.randn(),
                    "factor_b": np.random.randn() * 2,
                })
        
        return pd.DataFrame(data)
    
    def test_compute_rank_ic(self, analyzer):
        """测试 Rank IC 计算"""
        np.random.seed(42)
        factor_values = pd.Series(np.random.randn(100))
        forward_returns = pd.Series(np.random.randn(100))
        
        ic = analyzer.compute_rank_ic(factor_values, forward_returns)
        
        assert isinstance(ic, float)
        assert -1 <= ic <= 1 or np.isnan(ic)
    
    def test_compute_rank_ic_with_nan(self, analyzer):
        """测试包含 NaN 的 Rank IC 计算"""
        factor_values = pd.Series([1, 2, np.nan, 4, 5, 6, 7, 8, 9, 10])
        forward_returns = pd.Series([0.1, 0.2, 0.3, np.nan, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        
        ic = analyzer.compute_rank_ic(factor_values, forward_returns)
        
        assert isinstance(ic, float)
    
    def test_compute_rank_ic_insufficient_data(self, analyzer):
        """测试数据不足时的 Rank IC 计算"""
        factor_values = pd.Series([1, 2, 3])
        forward_returns = pd.Series([0.1, 0.2, 0.3])
        
        ic = analyzer.compute_rank_ic(factor_values, forward_returns)
        
        assert np.isnan(ic)

    def test_compute_rank_ic_constant_input(self, analyzer):
        factor_values = pd.Series([1, 1, 1, 1, 1, 1])
        forward_returns = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])

        ic = analyzer.compute_rank_ic(factor_values, forward_returns)

        assert np.isnan(ic)
    
    def test_compute_ic_ir(self, analyzer, sample_factor_df):
        """测试 IC/IR 计算"""
        results = analyzer.compute_ic_ir(
            sample_factor_df,
            factor_cols=["factor_a", "factor_b"],
            holding_periods=[1, 5]
        )
        
        assert "factor_a" in results or "factor_b" in results
        
        for factor, period_results in results.items():
            for period, result in period_results.items():
                assert isinstance(result, FactorICResult)
                assert result.factor_name == factor
                assert isinstance(result.ic_mean, float)
                assert isinstance(result.icir, float)
    
    def test_compute_factor_correlation(self, analyzer, sample_factor_df):
        """测试因子相关性矩阵"""
        corr_matrix = analyzer.compute_factor_correlation(
            sample_factor_df,
            factor_cols=["factor_a", "factor_b"]
        )
        
        assert not corr_matrix.empty
        assert corr_matrix.shape == (2, 2)
        assert np.allclose(np.diag(corr_matrix), 1.0)
    
    def test_compute_factor_correlation_single_factor(self, analyzer, sample_factor_df):
        """测试单因子相关性矩阵"""
        corr_matrix = analyzer.compute_factor_correlation(
            sample_factor_df,
            factor_cols=["factor_a"]
        )
        
        assert corr_matrix.empty
    
    def test_get_top_factors(self, analyzer):
        """测试获取 Top 因子"""
        analyzer.results = {
            "factor_a": FactorICResult(
                factor_name="factor_a",
                ic_mean=0.05,
                ic_std=0.1,
                icir=0.5,
                ic_positive_ratio=0.6,
                ic_t_stat=2.0,
                n_periods=100
            ),
            "factor_b": FactorICResult(
                factor_name="factor_b",
                ic_mean=0.03,
                ic_std=0.15,
                icir=0.2,
                ic_positive_ratio=0.55,
                ic_t_stat=1.5,
                n_periods=100
            ),
        }
        
        top_factors = analyzer.get_top_factors(metric="icir", top_n=2)
        
        assert len(top_factors) == 2
        assert top_factors[0][0] == "factor_a"
    
    def test_get_top_factors_empty(self, analyzer):
        """测试空结果获取 Top 因子"""
        analyzer.results = {}
        top_factors = analyzer.get_top_factors()
        
        assert top_factors == []
    
    def test_generate_report(self, analyzer):
        """测试生成报告"""
        analyzer.results = {
            "factor_a": FactorICResult(
                factor_name="factor_a",
                ic_mean=0.05,
                ic_std=0.1,
                icir=0.5,
                ic_positive_ratio=0.6,
                ic_t_stat=2.0,
                n_periods=100
            ),
        }
        
        report = analyzer.generate_report()
        
        assert "summary" in report
        assert "by_factor" in report
        assert "factor_a" in report["by_factor"]

    def test_pick_best_period_result(self, analyzer):
        result_1 = FactorICResult(
            factor_name="factor_a",
            ic_mean=0.05,
            ic_std=0.1,
            icir=0.5,
            ic_positive_ratio=0.6,
            ic_t_stat=2.0,
            n_periods=100
        )
        result_5 = FactorICResult(
            factor_name="factor_a",
            ic_mean=-0.08,
            ic_std=0.1,
            icir=-0.8,
            ic_positive_ratio=0.4,
            ic_t_stat=-3.0,
            n_periods=100
        )

        best_period, best_result = analyzer._pick_best_period_result({1: result_1, 5: result_5})

        assert best_period == 5
        assert best_result is result_5

    def test_generate_report_selects_best_period(self, analyzer):
        results = {
            "factor_a": {
                1: FactorICResult(
                    factor_name="factor_a",
                    ic_mean=0.02,
                    ic_std=0.1,
                    icir=0.2,
                    ic_positive_ratio=0.55,
                    ic_t_stat=1.0,
                    n_periods=10
                ),
                5: FactorICResult(
                    factor_name="factor_a",
                    ic_mean=-0.08,
                    ic_std=0.1,
                    icir=-0.8,
                    ic_positive_ratio=0.40,
                    ic_t_stat=-3.0,
                    n_periods=10
                ),
            }
        }

        report = analyzer.generate_report(results)

        assert report["by_factor"]["factor_a"]["best_period"] == 5
