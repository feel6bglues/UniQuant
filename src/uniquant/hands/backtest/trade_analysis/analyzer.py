from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ....shared.logger_factory import get_logger

logger = get_logger(__name__)


class TradeAnalyzer:
    """
    交易分析器
    
    提供全面的交易分析:
    - 盈亏分析
    - 时间维度分析
    - 市场状态分析
    """

    def __init__(self):
        pass

    def analyze(self, trades: pd.DataFrame) -> Dict[str, Any]:
        """
        综合交易分析
        
        Args:
            trades: 交易 DataFrame，需包含 action, price, shares, pnl 等列
            
        Returns:
            包含各类分析的字典
        """
        if trades.empty:
            return {"error": "交易记录为空"}

        analysis: Dict[str, Any] = {}

        analysis["win_loss"] = self.win_loss_analysis(trades)
        analysis["time_analysis"] = self.time_analysis(trades)
        analysis["summary"] = {
            "total_trades": len(trades),
            "buy_trades": int((trades["action"] == "BUY").sum()),
            "sell_trades": int((trades["action"] == "SELL").sum()),
        }

        if "pnl" in trades.columns:
            closed = trades[trades["action"] == "SELL"].copy()
            if not closed.empty:
                analysis["pnl_summary"] = {
                    "total_pnl": float(closed["pnl"].sum()),
                    "mean_pnl": float(closed["pnl"].mean()),
                    "median_pnl": float(closed["pnl"].median()),
                    "std_pnl": float(closed["pnl"].std()),
                    "max_profit": float(closed["pnl"].max()),
                    "max_loss": float(closed["pnl"].min()),
                }

        return analysis

    def win_loss_analysis(self, trades: pd.DataFrame) -> Dict[str, Any]:
        """
        盈亏分析
        
        分析盈利/亏损交易的分布特征。
        
        Args:
            trades: 交易 DataFrame
            
        Returns:
            包含盈亏统计的字典
        """
        if "pnl" not in trades.columns:
            return {"error": "缺少 pnl 列"}

        closed = trades[trades["action"] == "SELL"].copy()
        if closed.empty:
            return {"error": "无已平仓交易"}

        pnls = closed["pnl"]
        winners = pnls[pnls > 0]
        losers = pnls[pnls < 0]
        breakeven = pnls[pnls == 0]

        total = len(pnls)
        n_wins = len(winners)
        n_losses = len(losers)

        result: Dict[str, Any] = {
            "total_closed": total,
            "winners": n_wins,
            "losers": n_losses,
            "breakeven": len(breakeven),
            "win_rate": n_wins / total if total > 0 else 0,
            "loss_rate": n_losses / total if total > 0 else 0,
        }

        if n_wins > 0:
            result["win_stats"] = {
                "total": float(winners.sum()),
                "mean": float(winners.mean()),
                "median": float(winners.median()),
                "std": float(winners.std()),
                "min": float(winners.min()),
                "max": float(winners.max()),
            }

        if n_losses > 0:
            result["loss_stats"] = {
                "total": float(losers.sum()),
                "mean": float(losers.mean()),
                "median": float(losers.median()),
                "std": float(losers.std()),
                "min": float(losers.min()),
                "max": float(losers.max()),
            }

        if n_wins > 0 and n_losses > 0:
            result["avg_win"] = float(winners.mean())
            result["avg_loss"] = float(losers.mean())
            result["profit_ratio"] = float(abs(winners.mean() / losers.mean())) if losers.mean() != 0 else 0
            result["expectancy"] = float(n_wins / total * winners.mean() + n_losses / total * losers.mean())

        return result

    def time_analysis(self, trades: pd.DataFrame) -> Dict[str, Any]:
        """
        时间维度分析
        
        分析交易在不同时间维度的分布特征。
        
        Args:
            trades: 交易 DataFrame，需包含 timestamp 列
            
        Returns:
            包含时间分析结果的字典
        """
        if "timestamp" not in trades.columns:
            return {"error": "缺少 timestamp 列"}

        df = trades.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["year"] = df["timestamp"].dt.year
        df["month"] = df["timestamp"].dt.month
        df["weekday"] = df["timestamp"].dt.weekday
        df["hour"] = df["timestamp"].dt.hour

        result: Dict[str, Any] = {
            "by_year": df.groupby("year").size().to_dict(),
            "by_month": df.groupby("month").size().to_dict(),
            "by_weekday": df.groupby("weekday").size().to_dict(),
            "by_hour": df.groupby("hour").size().to_dict() if "hour" in df.columns else {},
        }

        if "pnl" in df.columns:
            result["pnl_by_year"] = df.groupby("year")["pnl"].sum().to_dict()
            result["pnl_by_month"] = df.groupby("month")["pnl"].sum().to_dict()

        return result

    def market_regime_analysis(
        self,
        trades: pd.DataFrame,
        regime: pd.Series,
    ) -> Dict[str, Any]:
        """
        市场状态分析
        
        分析在不同市场状态下交易的表现。
        
        Args:
            trades: 交易 DataFrame，需包含 timestamp 列
            regime: 市场状态 Series，index 为时间戳
            
        Returns:
            各市场状态下的交易统计
        """
        if trades.empty or regime.empty:
            return {"error": "输入数据为空"}

        if "timestamp" not in trades.columns:
            return {"error": "缺少 timestamp 列"}

        df = trades.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        regime_idx = pd.to_datetime(regime.index)

        regimes = []
        for _, row in df.iterrows():
            matches = regime_idx[regime_idx <= row["timestamp"]]
            if len(matches) > 0:
                nearest = matches[-1]
                regimes.append(regime.loc[nearest])
            else:
                regimes.append(None)

        df["regime"] = regimes
        df = df.dropna(subset=["regime"])

        if df.empty:
            return {"error": "无匹配的市场状态数据"}

        regime_stats = {}
        for regime_name, group in df.groupby("regime"):
            stats: Dict[str, Any] = {
                "trade_count": len(group),
                "buy_count": int((group["action"] == "BUY").sum()),
                "sell_count": int((group["action"] == "SELL").sum()),
            }

            if "pnl" in group.columns:
                closed = group[group["action"] == "SELL"]
                if not closed.empty:
                    pnls = closed["pnl"]
                    stats["total_pnl"] = float(pnls.sum())
                    stats["mean_pnl"] = float(pnls.mean())
                    stats["win_rate"] = float((pnls > 0).mean())
                    stats["profit_factor"] = float(
                        pnls[pnls > 0].sum() / abs(pnls[pnls < 0].sum())
                        if pnls[pnls < 0].sum() != 0 else 0
                    )

            regime_stats[str(regime_name)] = stats

        return {
            "regime_stats": regime_stats,
            "n_regimes": len(regime_stats),
        }
