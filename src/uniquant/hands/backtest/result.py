import warnings
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ...shared.cost_model import calculate_sharpe_ratio


@dataclass
class TradeRecord:
    """交易记录

    .. deprecated::
        请使用 ``uniquant.hands.backtest.unified_engine.TradeRecord`` (UnifiedTradeRecord) 代替。
    """
    timestamp: datetime
    action: str
    price: float
    shares: int
    commission: float
    slippage: float
    pnl: float = 0.0
    pnl_pct: float = 0.0
    reason: str = ""

    def __post_init__(self):
        warnings.warn(
            "result.TradeRecord is deprecated. Use UnifiedTradeRecord from "
            "uniquant.hands.backtest.unified_engine instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "price": self.price,
            "shares": self.shares,
            "commission": self.commission,
            "slippage": self.slippage,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "reason": self.reason,
        }


@dataclass
class BacktestResult:
    """回测结果统计"""
    initial_capital: float = 100000.0
    final_capital: float = 0.0
    total_return: float = 0.0
    annualized_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_holding_days: float = 0.0
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    drawdown_metrics: Optional[Dict] = None
    tail_risk_metrics: Optional[Dict] = None
    stress_test_results: Optional[Dict] = None
    overfitting_metrics: Optional[Dict] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def calculate_metrics(self) -> None:
        """计算回测指标"""
        if not self.trades:
            return

        closed_trades = [t for t in self.trades if t.action == "SELL"]
        self.total_trades = len(closed_trades)

        if self.total_trades == 0:
            return

        profits = [t.pnl for t in closed_trades if t.pnl > 0]
        losses = [t.pnl for t in closed_trades if t.pnl < 0]

        self.winning_trades = len(profits)
        self.losing_trades = len(losses)
        self.win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0

        self.avg_win = np.mean(profits) if profits else 0
        self.avg_loss = np.mean(losses) if losses else 0

        total_profit = sum(profits) if profits else 0
        total_loss = abs(sum(losses)) if losses else 0
        self.profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

        if self.equity_curve:
            ec = np.array(self.equity_curve, dtype=np.float64)
            self.final_capital = float(ec[-1])
            self.total_return = (self.final_capital - self.initial_capital) / self.initial_capital

            rolling_max = np.maximum.accumulate(ec)
            dd = (rolling_max - ec) / np.maximum(rolling_max, 1e-10)
            self.max_drawdown = float(np.max(dd))

            if self.daily_returns:
                returns = np.array(self.daily_returns)
                if len(returns) > 1 and np.std(returns) > 0:
                    self.sharpe_ratio = calculate_sharpe_ratio(returns, period_days=1)

                trading_days = len(returns)
                if trading_days > 0:
                    self.annualized_return = (1 + self.total_return) ** (252 / trading_days) - 1

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "initial_capital": self.initial_capital,
            "final_capital": self.final_capital,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "avg_holding_days": self.avg_holding_days,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "trades": [t.to_dict() for t in self.trades],
        }

    def to_dataframe(self) -> pd.DataFrame:
        """转换为DataFrame"""
        if not self.trades:
            return pd.DataFrame()

        return pd.DataFrame([t.to_dict() for t in self.trades])

    def generate_report(self) -> str:
        """生成回测报告"""
        report = []
        report.append("=" * 60)
        report.append("回测报告")
        report.append("=" * 60)
        report.append(f"回测区间: {self.start_date} ~ {self.end_date}")
        report.append(f"初始资金: {self.initial_capital:,.2f}")
        report.append(f"最终资金: {self.final_capital:,.2f}")
        report.append("-" * 60)
        report.append("收益指标:")
        report.append(f"  总收益率: {self.total_return:.2%}")
        report.append(f"  年化收益率: {self.annualized_return:.2%}")
        report.append(f"  最大回撤: {self.max_drawdown:.2%}")
        report.append(f"  夏普比率: {self.sharpe_ratio:.2f}")
        report.append("-" * 60)
        report.append("交易统计:")
        report.append(f"  总交易次数: {self.total_trades}")
        report.append(f"  盈利次数: {self.winning_trades}")
        report.append(f"  亏损次数: {self.losing_trades}")
        report.append(f"  胜率: {self.win_rate:.2%}")
        report.append(f"  盈亏比: {self.profit_factor:.2f}")
        report.append(f"  平均盈利: {self.avg_win:,.2f}")
        report.append(f"  平均亏损: {self.avg_loss:,.2f}")
        report.append("=" * 60)

        return "\n".join(report)
