"""
PortfolioOptimizer 单元测试
"""

import pytest
import numpy as np
import pandas as pd

from uniquant.risk.portfolio_optimizer import PortfolioOptimizer, OptimizerConfig


class TestOptimizerConfig:
    """OptimizerConfig 测试"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = OptimizerConfig()
        assert config.risk_free_rate == 0.03
        assert config.max_weight == 0.40
        assert config.min_weight == 0.0
        assert config.max_iterations == 1000
    
    def test_custom_config(self):
        """测试自定义配置"""
        config = OptimizerConfig(
            risk_free_rate=0.05,
            max_weight=0.30,
            min_weight=0.05
        )
        assert config.risk_free_rate == 0.05
        assert config.max_weight == 0.30
        assert config.min_weight == 0.05


class TestPortfolioOptimizer:
    """PortfolioOptimizer 测试"""
    
    @pytest.fixture
    def optimizer(self):
        return PortfolioOptimizer()
    
    @pytest.fixture
    def sample_returns(self):
        """创建示例收益率数据"""
        np.random.seed(42)
        n_days = 252
        n_assets = 5
        
        returns = np.random.randn(n_days, n_assets) * 0.02 + 0.0005
        assets = [f"ASSET_{i}" for i in range(n_assets)]
        
        return pd.DataFrame(returns, columns=assets)
    
    def test_optimizer_creation(self, optimizer):
        """测试优化器创建"""
        assert optimizer.config is not None
        assert optimizer.weights_ is None
    
    def test_validate_inputs(self, optimizer, sample_returns):
        """测试输入验证"""
        cov_matrix, expected_returns, assets = optimizer._validate_inputs(sample_returns)
        
        assert cov_matrix.shape == (5, 5)
        assert len(expected_returns) == 5
        assert len(assets) == 5
    
    def test_validate_inputs_empty(self, optimizer):
        """测试空数据验证"""
        with pytest.raises(ValueError):
            optimizer._validate_inputs(pd.DataFrame())
    
    def test_portfolio_return(self, optimizer):
        """测试组合收益计算"""
        weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
        expected_returns = np.array([0.1, 0.12, 0.08, 0.15, 0.09])
        
        port_ret = optimizer._portfolio_return(weights, expected_returns)
        assert abs(port_ret - 0.108) < 0.001
    
    def test_portfolio_volatility(self, optimizer):
        """测试组合波动率计算"""
        weights = np.array([0.5, 0.5])
        cov_matrix = np.array([[0.04, 0.01], [0.01, 0.09]])
        
        port_vol = optimizer._portfolio_volatility(weights, cov_matrix)
        assert port_vol > 0
        assert port_vol < 1
    
    def test_risk_contribution(self, optimizer):
        """测试风险贡献计算"""
        weights = np.array([0.5, 0.5])
        cov_matrix = np.array([[0.04, 0.01], [0.01, 0.09]])
        
        risk_contrib = optimizer._risk_contribution(weights, cov_matrix)
        assert len(risk_contrib) == 2
        assert all(risk_contrib >= 0)
    
    def test_optimize_risk_parity(self, optimizer, sample_returns):
        """测试风险平价优化"""
        result = optimizer.optimize_risk_parity(sample_returns)
        
        assert result is not None
        assert "weights" in result
        assert "expected_return" in result
        assert "expected_volatility" in result
        assert "sharpe_ratio" in result
        assert result["method"] == "risk_parity"
        
        weights = list(result["weights"].values())
        assert abs(sum(weights) - 1.0) < 0.01
    
    def test_optimize_mean_variance_max_sharpe(self, optimizer, sample_returns):
        """测试均值-方差优化 (最大夏普)"""
        result = optimizer.optimize_mean_variance(
            sample_returns, target="max_sharpe"
        )
        
        assert result is not None
        assert "weights" in result
        assert result["method"] == "mean_variance_max_sharpe"
        
        weights = list(result["weights"].values())
        assert abs(sum(weights) - 1.0) < 0.01
    
    def test_optimize_mean_variance_min_volatility(self, optimizer, sample_returns):
        """测试均值-方差优化 (最小波动)"""
        result = optimizer.optimize_mean_variance(
            sample_returns, target="min_volatility"
        )
        
        assert result is not None
        assert "weights" in result
        assert result["method"] == "mean_variance_min_volatility"
    
    def test_get_efficient_frontier(self, optimizer, sample_returns):
        """测试有效前沿计算"""
        frontier = optimizer.get_efficient_frontier(sample_returns, n_points=10)
        
        assert isinstance(frontier, pd.DataFrame)
        assert "expected_return" in frontier.columns
        assert "volatility" in frontier.columns
        assert "sharpe_ratio" in frontier.columns
    
    def test_generate_report(self, optimizer, sample_returns):
        """测试报告生成"""
        optimizer.optimize_risk_parity(sample_returns)
        report = optimizer.generate_report()
        
        assert "Portfolio Optimization Report" in report
        assert "Expected Return" in report
        assert "Sharpe Ratio" in report
    
    def test_generate_report_no_optimization(self, optimizer):
        """测试未优化时的报告"""
        report = optimizer.generate_report()
        assert "No optimization" in report


class TestPortfolioOptimizerIntegration:
    """集成测试"""
    
    def test_full_optimization_workflow(self):
        """测试完整优化流程"""
        np.random.seed(42)
        n_days = 252
        
        returns_data = {
            "STOCK_A": np.random.randn(n_days) * 0.02 + 0.001,
            "STOCK_B": np.random.randn(n_days) * 0.025 + 0.0008,
            "STOCK_C": np.random.randn(n_days) * 0.015 + 0.0006,
            "BOND_ETF": np.random.randn(n_days) * 0.005 + 0.0002,
        }
        
        returns = pd.DataFrame(returns_data)
        
        config = OptimizerConfig(
            risk_free_rate=0.03,
            max_weight=0.50,
            min_weight=0.0
        )
        
        optimizer = PortfolioOptimizer(config)
        
        rp_result = optimizer.optimize_risk_parity(returns)
        assert rp_result is not None
        
        mv_result = optimizer.optimize_mean_variance(returns, target="max_sharpe")
        assert mv_result is not None
        
        frontier = optimizer.get_efficient_frontier(returns, n_points=10)
        assert len(frontier) > 0
