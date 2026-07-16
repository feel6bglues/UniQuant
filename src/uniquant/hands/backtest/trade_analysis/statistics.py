from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from ....shared.logger_factory import get_logger

logger = get_logger(__name__)


class TradeStatistics:
    """
    交易统计计算器
    
    提供各类交易统计指标的计算:
    - 盈亏比 (Profit Factor)
    - 平均交易收益
    - 最大连续亏损
    - 夏普比率
    """

    def __init__(self):
        pass

    def calculate(self, trades: pd.DataFrame) -> Dict[str, Any]:
        """
        计算所有交易统计指标
        
        Args:
            trades: 交易 DataFrame，需包含 pnl 和 action 列
            
        Returns:
            包含所有统计指标的字典
        """
        if trades.empty:
            return {"error": "交易记录为空"}

        closed = trades[trades["action"] == "SELL"].copy() if "action" in trades.columns else trades.copy()

        if closed.empty:
            return {"error": "无已平仓交易"}

        statistics: Dict[str, Any] = {
            "total_trades": len(closed),
            "profit_factor": self.profit_factor(closed),
            "average_trade": self.average_trade(closed),
            "max_consecutive_losses": self.max_consecutive_losses(closed),
            "sharpe_ratio": self.sharpe_ratio(closed),
        }

        if "pnl_pct" in closed.columns:
            statistics["average_return_pct"] = float(closed["pnl_pct"].mean())

        if "pnl" in closed.columns:
            pnls = closed["pnl"]
            statistics["total_pnl"] = float(pnls.sum())
            statistics["median_trade"] = float(pnls.median())
            statistics["std_trade"] = float(pnls.std())
            statistics["min_trade"] = float(pnls.min())
            statistics["max_trade"] = float(pnls.max())
            statistics["skewness"] = float(pnls.skew())
            statistics["kurtosis"] = float(pnls.kurtosis())

        return statistics

    def profit_factor(self, trades: pd.DataFrame) -> float:
        """
        计算盈亏比 (Profit Factor)
        
        PF = 总盈利 / 总亏损
        
        Args:
            trades: 交易 DataFrame
            
        Returns:
            盈亏比
        """
        if "pnl" not in trades.columns:
            return 0.0

        pnls = trades[trades["action"] == "SELL"]["pnl"] if "action" in trades.columns else trades["pnl"]

        gross_profit = pnls[pnls > 0].sum()
        gross_loss = abs(pnls[pnls < 0].sum())

        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0

        return float(gross_profit / gross_loss)

    def average_trade(self, trades: pd.DataFrame) -> float:
        """
        计算平均交易收益
        
        Args:
            trades: 交易 DataFrame
            
        Returns:
            平均每笔交易的 PnL
        """
        if "pnl" not in trades.columns:
            return 0.0

        pnls = trades[trades["action"] == "SELL"]["pnl"] if "action" in trades.columns else trades["pnl"]

        if len(pnls) == 0:
            return 0.0

        return float(pnls.mean())

    def max_consecutive_losses(self, trades: pd.DataFrame) -> int:
        """
        计算最大连续亏损次数
        
        Args:
            trades: 交易 DataFrame
            
        Returns:
            最大连续亏损次数
        """
        if "pnl" not in trades.columns:
            return 0

        pnls = trades[trades["action"] == "SELL"]["pnl"] if "action" in trades.columns else trades["pnl"]

        if len(pnls) == 0:
            return 0

        max_streak = 0
        current_streak = 0

        for pnl in pnls:
            if pnl < 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0

        return max_streak

    def sharpe_ratio(self, trades: pd.DataFrame, risk_free_rate: float = 0.03) -> float:
        """
        计算交易的夏普比率

        优先使用 pnl_pct (百分比收益率), 回退到美元 PnL。

        Args:
            trades: 交易 DataFrame
            risk_free_rate: 无风险利率 (年化)

        Returns:
            夏普比率
        """
        if "pnl" not in trades.columns and "pnl_pct" not in trades.columns:
            return 0.0

        closed = trades[trades["action"] == "SELL"] if "action" in trades.columns else trades

        if "pnl_pct" in closed.columns:
            returns = closed["pnl_pct"]
        elif "pnl" in closed.columns and "price" in closed.columns and "shares" in closed.columns:
            cost_basis = closed["price"] * closed["shares"] + closed.get("commission", 0.0)
            cost_basis = cost_basis.replace(0, float("nan"))
            returns = closed["pnl"] / cost_basis
        else:
            returns = closed["pnl"]

        returns = returns.dropna()

        if len(returns) < 2:
            return 0.0

        mean_ret = np.mean(returns)
        std_ret = np.std(returns, ddof=1)

        if std_ret == 0:
            return 0.0

        rfr_per_trade = risk_free_rate / 252
        excess = mean_ret - rfr_per_trade

        sharpe = excess / std_ret * np.sqrt(252)
        return float(sharpe)
