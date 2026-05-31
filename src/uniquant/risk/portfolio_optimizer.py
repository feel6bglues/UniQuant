"""
组合优化模块
实现 Risk Parity (风险平价) 和 Mean-Variance (均值-方差) 优化
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from ..shared.error_handling import handle_errors
from ..shared.logger_factory import get_logger

logger = get_logger("PortfolioOptimizer")


def _risk_parity_objective(weights: np.ndarray, cov: np.ndarray) -> float:
    vol = np.sqrt(max(weights @ cov @ weights, 1e-16))
    rc = weights * (cov @ weights) / vol
    target = np.ones(len(weights)) / len(weights)
    return np.sum((rc - target) ** 2)


@dataclass
class OptimizerConfig:
    """优化器配置"""
    risk_free_rate: float = 0.03  # 无风险利率 (年化)
    max_weight: float = 0.40  # 单资产最大权重
    min_weight: float = 0.0  # 单资产最小权重
    target_return: Optional[float] = None  # 目标收益率 (None 表示不限制)
    max_iterations: int = 1000  # 最大迭代次数
    tolerance: float = 1e-8  # 收敛容差


class PortfolioOptimizer:
    """
    组合优化器
    
    支持两种优化方法:
    1. Risk Parity (风险平价): 各资产风险贡献相等
    2. Mean-Variance (均值-方差): 在给定风险下最大化收益，或在给定收益下最小化风险
    """
    
    def __init__(self, config: Optional[OptimizerConfig] = None):
        self.config = config or OptimizerConfig()
        self.weights_: Optional[np.ndarray] = None
        self.expected_return_: Optional[float] = None
        self.expected_volatility_: Optional[float] = None
        self.sharpe_ratio_: Optional[float] = None
        self._last_assets: List[str] = []
        
        logger.info(f"PortfolioOptimizer initialized with config: {self.config}")
    
    def _validate_inputs(
        self,
        returns: pd.DataFrame,
        expected_returns: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """验证输入数据"""
        if returns.empty:
            raise ValueError("Returns DataFrame is empty")
        
        assets = returns.columns.tolist()
        n_assets = len(assets)
        
        cov_matrix = returns.cov().values
        
        if np.any(np.isnan(cov_matrix)):
            raise ValueError("Covariance matrix contains NaN values")
        
        if expected_returns is None:
            expected_returns = returns.mean().values * 252  # 年化
        
        if len(expected_returns) != n_assets:
            raise ValueError(
                f"Expected returns length ({len(expected_returns)}) "
                f"does not match number of assets ({n_assets})"
            )
        
        self._last_assets = assets
        return cov_matrix, expected_returns, assets
    
    def _portfolio_return(
        self,
        weights: np.ndarray,
        expected_returns: np.ndarray
    ) -> float:
        """计算组合预期收益"""
        return np.dot(weights, expected_returns)
    
    def _portfolio_volatility(
        self,
        weights: np.ndarray,
        cov_matrix: np.ndarray
    ) -> float:
        """计算组合波动率"""
        return np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
    
    def _risk_contribution(
        self,
        weights: np.ndarray,
        cov_matrix: np.ndarray
    ) -> np.ndarray:
        """计算各资产的风险贡献"""
        portfolio_vol = self._portfolio_volatility(weights, cov_matrix)
        marginal_contrib = np.dot(cov_matrix, weights)
        risk_contrib = weights * marginal_contrib / portfolio_vol
        return risk_contrib
    
    @handle_errors(ValueError, np.linalg.LinAlgError, default_return=None)
    def optimize_risk_parity(
        self,
        returns: pd.DataFrame,
        target_weights: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        """
        风险平价优化 - 使用 scipy.optimize.minimize (SLSQP)
        
        目标: 各资产的风险贡献相等
        
        Args:
            returns: 资产收益率 DataFrame (每列一个资产)
            target_weights: 目标风险权重 (默认等权)
            
        Returns:
            优化结果字典
        """
        cov_matrix, expected_returns, assets = self._validate_inputs(returns)
        n_assets = len(assets)

        if n_assets < 2:
            return None

        if target_weights is None:
            target_weights = np.ones(n_assets) / n_assets

        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0},
        ]

        bounds = [(self.config.min_weight, self.config.max_weight) for _ in range(n_assets)]
        x0 = np.ones(n_assets) / n_assets

        opt_result = minimize(
            _risk_parity_objective,
            x0,
            args=(cov_matrix,),
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={
                'maxiter': self.config.max_iterations,
                'ftol': self.config.tolerance,
                'disp': False
            }
        )

        if not opt_result.success:
            logger.warning(f"Risk parity optimization did not converge: {opt_result.message}")
            weights = x0
        else:
            weights = opt_result.x

        self.weights_ = weights
        self.expected_return_ = self._portfolio_return(weights, expected_returns)
        self.expected_volatility_ = self._portfolio_volatility(weights, cov_matrix)

        if self.expected_volatility_ > 0:
            self.sharpe_ratio_ = (
                self.expected_return_ - self.config.risk_free_rate
            ) / self.expected_volatility_
        else:
            self.sharpe_ratio_ = 0.0

        result = {
            "method": "risk_parity",
            "weights": dict(zip(assets, weights.round(4).tolist())),
            "expected_return": self.expected_return_,
            "expected_volatility": self.expected_volatility_,
            "sharpe_ratio": self.sharpe_ratio_,
            "risk_contributions": dict(zip(
                assets,
                self._risk_contribution(weights, cov_matrix).round(6).tolist()
            )),
            "success": opt_result.success,
            "message": opt_result.message,
        }

        logger.info(f"Risk Parity optimization completed: Sharpe={self.sharpe_ratio_:.4f}")
        return result
    
    def _negative_sharpe(self, weights: np.ndarray, cov_matrix: np.ndarray, expected_returns: np.ndarray) -> float:
        """负夏普比率（用于最小化）"""
        port_vol = self._portfolio_volatility(weights, cov_matrix)
        if port_vol <= 0:
            return 1e6
        port_ret = self._portfolio_return(weights, expected_returns)
        sharpe = (port_ret - self.config.risk_free_rate) / port_vol
        return -sharpe
    
    def _portfolio_volatility_obj(self, weights: np.ndarray, cov_matrix: np.ndarray) -> float:
        """组合波动率（用于最小化）"""
        return self._portfolio_volatility(weights, cov_matrix)
    
    def _target_return_penalty(self, weights: np.ndarray, cov_matrix: np.ndarray, expected_returns: np.ndarray) -> float:
        """目标收益惩罚函数"""
        port_vol = self._portfolio_volatility(weights, cov_matrix)
        port_ret = self._portfolio_return(weights, expected_returns)
        return_diff = abs(port_ret - self.config.target_return)
        return port_vol + 1000 * return_diff
    
    @handle_errors(ValueError, np.linalg.LinAlgError, default_return=None)
    def optimize_mean_variance(
        self,
        returns: pd.DataFrame,
        expected_returns: Optional[np.ndarray] = None,
        target: str = "max_sharpe"
    ) -> Dict[str, Any]:
        """
        均值-方差优化 - 使用 scipy.optimize.minimize (SLSQP)
        
        Args:
            returns: 资产收益率 DataFrame
            expected_returns: 预期收益率数组 (年化)
            target: 优化目标
                - "max_sharpe": 最大化夏普比率
                - "min_volatility": 最小化波动率
                - "target_return": 在目标收益下最小化风险
                
        Returns:
            优化结果字典
        """
        cov_matrix, expected_returns, assets = self._validate_inputs(
            returns, expected_returns
        )
        n_assets = len(assets)
        
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0},
        ]
        
        bounds = [(self.config.min_weight, self.config.max_weight) for _ in range(n_assets)]
        
        x0 = np.ones(n_assets) / n_assets
        
        if target == "max_sharpe":
            def objective(w):
                return self._negative_sharpe(w, cov_matrix, expected_returns)
        elif target == "min_volatility":
            def objective(w):
                return self._portfolio_volatility_obj(w, cov_matrix)
        elif target == "target_return":
            if self.config.target_return is None:
                raise ValueError("target_return must be set for target_return optimization")
            def objective(w):
                return self._target_return_penalty(w, cov_matrix, expected_returns)
        else:
            raise ValueError(f"Unknown target: {target}")
        
        result = minimize(
            objective,
            x0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={
                'maxiter': self.config.max_iterations,
                'ftol': self.config.tolerance,
                'disp': False
            }
        )
        
        if not result.success:
            logger.warning(f"Optimization did not converge: {result.message}")
            best_weights = x0
        else:
            best_weights = result.x
        
        best_ret = self._portfolio_return(best_weights, expected_returns)
        best_vol = self._portfolio_volatility(best_weights, cov_matrix)
        best_sharpe = (best_ret - self.config.risk_free_rate) / best_vol if best_vol > 0 else 0.0
        
        self.weights_ = best_weights
        self.expected_return_ = best_ret
        self.expected_volatility_ = best_vol
        self.sharpe_ratio_ = best_sharpe
        
        return {
            "method": f"mean_variance_{target}",
            "weights": dict(zip(assets, best_weights.round(4).tolist())),
            "expected_return": best_ret,
            "expected_volatility": best_vol,
            "sharpe_ratio": best_sharpe,
            "risk_contributions": dict(zip(
                assets,
                self._risk_contribution(best_weights, cov_matrix).round(6).tolist()
            )),
            "success": result.success,
            "message": result.message,
        }
    
    def get_efficient_frontier(
        self,
        returns: pd.DataFrame,
        expected_returns: Optional[np.ndarray] = None,
        n_points: int = 20
    ) -> pd.DataFrame:
        """
        计算有效前沿
        
        Args:
            returns: 资产收益率 DataFrame
            expected_returns: 预期收益率数组
            n_points: 前沿点数
            
        Returns:
            有效前沿 DataFrame
        """
        cov_matrix, expected_returns, assets = self._validate_inputs(
            returns, expected_returns
        )
        
        min_ret = expected_returns.min()
        max_ret = expected_returns.max()
        target_returns = np.linspace(min_ret, max_ret, n_points)
        
        frontier = []
        
        for target_ret in target_returns:
            original_target = self.config.target_return
            self.config.target_return = target_ret
            try:
                result = self.optimize_mean_variance(
                    returns, expected_returns, target="target_return"
                )
                if result:
                    frontier.append({
                        "target_return": target_ret,
                        "expected_return": result["expected_return"],
                        "volatility": result["expected_volatility"],
                        "sharpe_ratio": result["sharpe_ratio"],
                    })
            finally:
                self.config.target_return = original_target
        
        return pd.DataFrame(frontier)
    
    def generate_report(self) -> str:
        """生成优化报告"""
        if self.weights_ is None:
            return "No optimization has been performed yet."
        
        lines = [
            "=" * 60,
            "Portfolio Optimization Report",
            "=" * 60,
            f"Expected Return: {self.expected_return_:.4%}",
            f"Expected Volatility: {self.expected_volatility_:.4%}",
            f"Sharpe Ratio: {self.sharpe_ratio_:.4f}",
            "-" * 60,
            "Weights:",
        ]
        
        for asset, weight in zip(self._last_assets, self.weights_):
            lines.append(f"  {asset}: {weight:.4%}")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)
