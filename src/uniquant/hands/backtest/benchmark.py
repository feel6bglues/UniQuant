from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class BenchmarkComparator:
    """
    基准比较器
    
    提供策略与基准的对比分析:
    - CAPM Alpha / Beta
    - 跟踪误差 (Tracking Error)
    - 信息比率 (Information Ratio)
    """

    def __init__(self, benchmark_symbol: str = "^GSPC"):
        """
        Args:
            benchmark_symbol: 基准标的代码 (默认 ^GSPC 标普500)
        """
        self.benchmark_symbol = benchmark_symbol

    def compare(
        self,
        strategy_returns: pd.Series,
        benchmark_returns: pd.Series,
        risk_free_rate: float = 0.03,
    ) -> Dict[str, Any]:
        """
        综合比较策略与基准
        
        Args:
            strategy_returns: 策略日收益率
            benchmark_returns: 基准日收益率
            risk_free_rate: 无风险利率 (年化)
            
        Returns:
            包含 Alpha, Beta, 跟踪误差, 信息比率等的字典
        """
        if strategy_returns.empty or benchmark_returns.empty:
            return {"error": "收益率为空"}

        aligned = pd.concat(
            [strategy_returns.rename("strategy"), benchmark_returns.rename("benchmark")],
            axis=1,
        ).dropna()

        if len(aligned) < 10:
            return {"error": "对齐后有效数据不足"}

        s_ret = aligned["strategy"]
        b_ret = aligned["benchmark"]

        alpha_beta = self.calculate_alpha_beta(s_ret, b_ret, risk_free_rate)
        info_ratio = self.information_ratio(s_ret, b_ret)
        tracking_error = self._tracking_error(s_ret, b_ret)

        strategy_cum = (1 + s_ret).prod() - 1
        benchmark_cum = (1 + b_ret).prod() - 1
        excess_return = strategy_cum - benchmark_cum

        return {
            "alpha": alpha_beta["alpha"],
            "beta": alpha_beta["beta"],
            "information_ratio": info_ratio,
            "tracking_error": tracking_error,
            "excess_return": float(excess_return),
            "strategy_return": float(strategy_cum),
            "benchmark_return": float(benchmark_cum),
            "correlation": float(s_ret.corr(b_ret)),
            "n_observations": len(aligned),
        }

    def calculate_alpha_beta(
        self,
        strategy_returns: pd.Series,
        benchmark_returns: pd.Series,
        risk_free_rate: float = 0.03,
    ) -> Dict[str, float]:
        """
        计算 CAPM Alpha 和 Beta
        
        Beta 衡量策略相对于基准的系统性风险敞口，
        Alpha 衡量经风险调整后的超额收益。
        
        Args:
            strategy_returns: 策略日收益率
            benchmark_returns: 基准日收益率
            risk_free_rate: 无风险利率 (年化)
            
        Returns:
            {"alpha": float, "beta": float}
        """
        rfr_daily = risk_free_rate / 252

        s_excess = strategy_returns - rfr_daily
        b_excess = benchmark_returns - rfr_daily

        cov = np.cov(s_excess, b_excess)
        beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 0 else 0

        mean_s = np.mean(s_excess)
        mean_b = np.mean(b_excess)
        alpha_daily = mean_s - beta * mean_b

        alpha_annual = alpha_daily * 252

        return {
            "alpha": float(alpha_annual),
            "beta": float(beta),
        }

    def information_ratio(
        self,
        strategy_returns: pd.Series,
        benchmark_returns: pd.Series,
    ) -> float:
        """
        计算信息比率 (Information Ratio)
        
        IR = E(Rp - Rb) / TE(Rp - Rb)
        衡量单位主动风险带来的超额收益。
        
        Args:
            strategy_returns: 策略日收益率
            benchmark_returns: 基准日收益率
            
        Returns:
            年化信息比率
        """
        excess = strategy_returns - benchmark_returns
        mean_excess = np.mean(excess)
        std_excess = np.std(excess)

        if std_excess == 0:
            return 0.0

        ir = mean_excess / std_excess * np.sqrt(252)
        return float(ir)

    def _tracking_error(
        self,
        strategy_returns: pd.Series,
        benchmark_returns: pd.Series,
    ) -> float:
        """计算年化跟踪误差"""
        excess = strategy_returns - benchmark_returns
        te = np.std(excess) * np.sqrt(252)
        return float(te)
