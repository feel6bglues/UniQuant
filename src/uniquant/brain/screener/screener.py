"""
全市场扫描器
基于 composite_score 生成 Top/Bottom 榜单 + 技术信号验证
"""

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Any

import numpy as np
import pandas as pd

from ...shared.error_handling import handle_errors
from ...shared.logger_factory import get_logger
from ..indicators.indicators import Indicators

logger = get_logger("StockScreener")


@dataclass
class ScreenerConfig:
    """扫描器配置"""
    top_n: int = 50
    bottom_n: int = 50
    sector_top_n: int = 3
    min_data_points: int = 60


class StockScreener:
    """
    全市场扫描器
    
    功能:
    1. Top/Bottom 榜单生成
    2. 技术信号验证 (MA金叉/死叉, RSI 状态)
    3. 分行业 Top3
    4. 全市场风险指标汇总
    """
    
    def __init__(self, config: Optional[ScreenerConfig] = None):
        self.config = config or ScreenerConfig()
        self.indicators = Indicators()
        logger.info("StockScreener initialized with top_n=%s", self.config.top_n)
    
    def generate_top_bottom(
        self,
        df: pd.DataFrame,
        score_col: str = "composite_score",
        code_col: str = "code",
        date_col: str = "date"
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        生成 Top/Bottom 榜单
        
        Args:
            df: 包含 composite_score 的 DataFrame
            score_col: 得分列名
            code_col: 股票代码列名
            date_col: 日期列名
            
        Returns:
            (Top DataFrame, Bottom DataFrame)
        """
        if df.empty:
            logger.warning("Input DataFrame is empty")
            return pd.DataFrame(), pd.DataFrame()
        
        if score_col not in df.columns:
            logger.error("Score column '%s' not found", score_col)
            return pd.DataFrame(), pd.DataFrame()
        
        latest_date = df[date_col].max() if date_col in df.columns else None
        
        if latest_date:
            latest_df = df[df[date_col] == latest_date].copy()
        else:
            latest_df = df.copy()
        
        latest_df = latest_df.dropna(subset=[score_col])
        
        sorted_df = latest_df.sort_values(score_col, ascending=False)
        
        top_df = sorted_df.head(self.config.top_n).copy()
        bottom_df = sorted_df.tail(self.config.bottom_n).copy()
        
        top_df["_rank"] = range(1, len(top_df) + 1)
        bottom_df["_rank"] = range(len(bottom_df), 0, -1)
        
        logger.info("Generated Top%s and Bottom%s stocks", len(top_df), len(bottom_df))
        return top_df, bottom_df
    
    def generate_tech_signals(
        self,
        stocks_df: pd.DataFrame,
        daily_data: Dict[str, pd.DataFrame],
        code_col: str = "code"
    ) -> pd.DataFrame:
        """
        为股票生成技术信号验证
        
        Args:
            stocks_df: 股票列表 DataFrame
            daily_data: 日线数据字典 {code: DataFrame}
            code_col: 股票代码列名
            
        Returns:
            添加技术信号列的 DataFrame
        """
        if stocks_df.empty:
            return stocks_df
        
        stocks_df = stocks_df.copy()

        # 向量化优化：使用 dict + merge 替代 iterrows
        codes = stocks_df[code_col].unique()
        valid_codes = [
            c for c in codes
            if c and c in daily_data and len(daily_data[c]) >= self.config.min_data_points
        ]

        if not valid_codes:
            default_signals = self._get_default_signals()
            for col in default_signals:
                stocks_df[col] = default_signals[col]
            return stocks_df

        # 批量计算信号
        signals_dict = {}
        error_signals = self._get_error_signals()
        for code in valid_codes:
            try:
                signals_dict[code] = self._compute_signals_for_dataframe(daily_data[code])
            except (ValueError, KeyError, TypeError, IndexError) as e:
                logger.warning("Failed to generate tech signals for %s: %s", code, e)
                signals_dict[code] = error_signals

        # 使用 map 合并结果（避免 iterrows）
        for col in signals_dict.get(valid_codes[0], {}).keys():
            stocks_df[col] = stocks_df[code_col].map(lambda x: signals_dict.get(x, {}).get(col, "N/A"))

        logger.info("Generated tech signals for %s stocks", len(stocks_df))
        return stocks_df
        
    def _compute_signals_for_dataframe(self, df: pd.DataFrame) -> Dict[str, Any]:
        df = df.copy()
        
        df["ma_20"] = self.indicators.calc_ma(df, window=20)
        df["ma_60"] = self.indicators.calc_ma(df, window=60)
        df["rsi_14"] = self.indicators.calc_rsi(df, window=14)
        macd_result = self.indicators.calc_macd(df)
        df["macd"] = macd_result["macd"]
        df["macd_signal"] = macd_result["signal"]
        
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        
        signals = {
            "ma_signal": self._evaluate_ma_signals(
                last.get("ma_20"), last.get("ma_60"), last.get("close"),
                prev.get("ma_20", 0), prev.get("ma_60", 0)
            ),
            "rsi_state": self._evaluate_rsi_state(last.get("rsi_14")),
            "macd_signal": self._evaluate_macd_signal(last.get("macd"), last.get("macd_signal")),
            "trend": self._evaluate_trend(last.get("close"), last.get("ma_20"), last.get("ma_60")),
        }

        # 新增：从注册表获取所有技术因子
        try:
            from uniquant.brain.factors.registry import FactorRegistry
            for factor in FactorRegistry.get_enabled():
                if factor.category == "technical":
                    try:
                        value = factor.compute_func(df)
                        signals[factor.name] = float(value.iloc[-1]) if len(value) > 0 else 0.0
                    except (AttributeError, KeyError, TypeError, ValueError, IndexError):
                        logger.exception("计算因子信号失败，跳过")
                        pass
        except ImportError:
            logger.exception("加载 FactorRegistry 失败，跳过")
            pass
            
        return signals

    def _evaluate_ma_signals(self, ma20: Any, ma60: Any, close: Any, prev_ma20: Any, prev_ma60: Any) -> str:
        if ma20 and ma60 and close:
            if ma20 > ma60 and prev_ma20 <= prev_ma60:
                return "GOLDEN_CROSS"
            elif ma20 < ma60 and prev_ma20 >= prev_ma60:
                return "DEATH_CROSS"
            elif ma20 > ma60:
                return "BULLISH_ALIGN"
            return "BEARISH_ALIGN"
        return "N/A"

    def _evaluate_rsi_state(self, rsi: Any) -> str:
        if rsi:
            if rsi > 70:
                return "OVERBOUGHT"
            elif rsi < 30:
                return "OVERSOLD"
            elif rsi > 50:
                return "BULLISH"
            return "BEARISH"
        return "N/A"

    def _evaluate_macd_signal(self, macd: Any, macd_signal_val: Any) -> str:
        if macd is not None and macd_signal_val is not None:
            if macd > macd_signal_val:
                return "BULLISH"
            return "BEARISH"
        return "N/A"

    def _evaluate_trend(self, close: Any, ma20: Any, ma60: Any) -> str:
        if close and ma20 and ma60:
            if close > ma20 > ma60:
                return "STRONG_UP"
            elif close > ma20:
                return "UP"
            elif close < ma20 < ma60:
                return "STRONG_DOWN"
            elif close < ma20:
                return "DOWN"
            return "SIDEWAYS"
        return "N/A"

    def _get_default_signals(self) -> Dict[str, str]:
        return {
            "ma_signal": "N/A",
            "rsi_state": "N/A",
            "macd_signal": "N/A",
            "trend": "N/A",
        }

    def _get_error_signals(self) -> Dict[str, str]:
        return {
            "ma_signal": "ERROR",
            "rsi_state": "ERROR",
            "macd_signal": "ERROR",
            "trend": "ERROR",
        }
    
    def generate_sector_top(
        self,
        df: pd.DataFrame,
        sector_col: str = "sector",
        score_col: str = "composite_score",
        code_col: str = "code",
        date_col: str = "date"
    ) -> pd.DataFrame:
        """
        生成分行业 Top 股票
        
        Args:
            df: 包含 composite_score 和 sector 的 DataFrame
            sector_col: 行业列名
            score_col: 得分列名
            code_col: 股票代码列名
            date_col: 日期列名
            
        Returns:
            分行业 Top DataFrame
        """
        if df.empty:
            return pd.DataFrame()
        
        if sector_col not in df.columns:
            logger.warning("Sector column '%s' not found", sector_col)
            return pd.DataFrame()
        
        if date_col in df.columns:
            latest_date = df[date_col].max()
            df = df[df[date_col] == latest_date].copy()
        
        df = df.dropna(subset=[score_col, sector_col])
        
        result_frames = []
        
        for sector in df[sector_col].unique():
            sector_df = df[df[sector_col] == sector]
            top_sector = sector_df.nlargest(self.config.sector_top_n, score_col)
            top_sector = top_sector.copy()
            top_sector["_sector_rank"] = range(1, len(top_sector) + 1)
            result_frames.append(top_sector)
        
        if not result_frames:
            return pd.DataFrame()
        
        result = pd.concat(result_frames, ignore_index=True)
        result = result.sort_values([sector_col, "_sector_rank"])
        
        logger.info("Generated sector top for %s sectors", result[sector_col].nunique())
        return result
    
    def generate_market_risk_summary(
        self,
        daily_data: Dict[str, pd.DataFrame],
        trading_days_per_year: int = 252
    ) -> Dict[str, Any]:
        """
        生成全市场风险指标汇总
        
        Args:
            daily_data: 日线数据字典 {code: DataFrame}
            trading_days_per_year: 年交易日数
            
        Returns:
            风险指标汇总字典
        """
        if not daily_data:
            return {}

        # 向量化优化：使用 list 收集指标，再统一聚合
        metrics = []

        for code, df in daily_data.items():
            if len(df) < self.config.min_data_points:
                continue

            try:
                df = df.sort_values("date")

                if "close" not in df.columns:
                    continue

                returns = df["close"].pct_change().dropna()

                if len(returns) == 0:
                    continue

                annual_ret = returns.mean() * trading_days_per_year
                annual_vol = returns.std() * np.sqrt(trading_days_per_year)
                sharpe = annual_ret / annual_vol if annual_vol > 0 else 0.0

                cumulative = (1 + returns).cumprod()
                running_max = cumulative.cummax()
                drawdown = (cumulative - running_max) / running_max
                max_dd = drawdown.min()

                if not np.isnan(annual_ret):
                    metrics.append({
                        "code": code,
                        "annual_ret": annual_ret,
                        "annual_vol": annual_vol,
                        "sharpe": sharpe,
                        "max_dd": max_dd
                    })

            except (ValueError, KeyError, TypeError, ZeroDivisionError) as e:
                logger.warning("Failed to calculate risk metrics for %s: %s", code, e)
                continue

        if not metrics:
            return {"total_stocks": len(daily_data), "valid_stocks": 0}

        metrics_df = pd.DataFrame(metrics)

        summary = {
            "total_stocks": len(daily_data),
            "valid_stocks": len(metrics_df),
            "avg_annual_return": float(metrics_df["annual_ret"].mean()) if len(metrics_df) > 0 else 0.0,
            "median_annual_return": float(metrics_df["annual_ret"].median()) if len(metrics_df) > 0 else 0.0,
            "avg_volatility": float(metrics_df["annual_vol"].mean()) if len(metrics_df) > 0 else 0.0,
            "median_volatility": float(metrics_df["annual_vol"].median()) if len(metrics_df) > 0 else 0.0,
            "avg_sharpe": float(metrics_df["sharpe"].mean()) if len(metrics_df) > 0 else 0.0,
            "median_sharpe": float(metrics_df["sharpe"].median()) if len(metrics_df) > 0 else 0.0,
            "avg_max_drawdown": float(metrics_df["max_dd"].mean()) if len(metrics_df) > 0 else 0.0,
            "median_max_drawdown": float(metrics_df["max_dd"].median()) if len(metrics_df) > 0 else 0.0,
            "positive_return_ratio": float((metrics_df["annual_ret"] > 0).mean()) if len(metrics_df) > 0 else 0.0,
        }
        
        logger.info("Generated market risk summary for %s stocks", summary['valid_stocks'])
        return summary
    
    @handle_errors(ValueError, KeyError, TypeError, default_return="", log_level=logging.ERROR)
    def format_top_table(
        self,
        top_df: pd.DataFrame,
        score_col: str = "composite_score",
        code_col: str = "code",
        name_col: str = "name"
    ) -> str:
        """
        格式化 Top 榜单为 Markdown 表格
        
        Args:
            top_df: Top 股票 DataFrame
            score_col: 得分列名
            code_col: 股票代码列名
            name_col: 股票名称列名
            
        Returns:
            Markdown 格式的表格字符串
        """
        if top_df.empty:
            return "No data available"
        
        display_cols = ["_rank", code_col]
        
        if name_col in top_df.columns:
            display_cols.append(name_col)
        
        if score_col in top_df.columns:
            display_cols.append(score_col)
        
        tech_cols = ["ma_signal", "rsi_state", "macd_signal", "trend"]
        for col in tech_cols:
            if col in top_df.columns:
                display_cols.append(col)
        
        display_df = top_df[display_cols].copy()
        
        if "_rank" in display_df.columns:
            display_df = display_df.rename(columns={"_rank": "Rank"})
        if score_col in display_df.columns:
            display_df[score_col] = display_df[score_col].round(4)
        
        return display_df.to_markdown(index=False, floatfmt=".4f")
    
    @handle_errors(ValueError, KeyError, TypeError, default_return="", log_level=logging.ERROR)
    def format_risk_summary_table(
        self,
        summary: Dict[str, Any]
    ) -> str:
        """
        格式化风险汇总为 Markdown 表格
        
        Args:
            summary: 风险汇总字典
            
        Returns:
            Markdown 格式的表格字符串
        """
        if not summary:
            return "No risk summary available"
        
        rows = [
            ("Total Stocks", summary.get("total_stocks", 0)),
            ("Valid Stocks", summary.get("valid_stocks", 0)),
            ("Avg Annual Return", f"{summary.get('avg_annual_return', 0):.2%}"),
            ("Median Annual Return", f"{summary.get('median_annual_return', 0):.2%}"),
            ("Avg Volatility", f"{summary.get('avg_volatility', 0):.2%}"),
            ("Median Volatility", f"{summary.get('median_volatility', 0):.2%}"),
            ("Avg Sharpe Ratio", f"{summary.get('avg_sharpe', 0):.4f}"),
            ("Median Sharpe Ratio", f"{summary.get('median_sharpe', 0):.4f}"),
            ("Avg Max Drawdown", f"{summary.get('avg_max_drawdown', 0):.2%}"),
            ("Median Max Drawdown", f"{summary.get('median_max_drawdown', 0):.2%}"),
            ("Positive Return Ratio", f"{summary.get('positive_return_ratio', 0):.2%}"),
        ]
        
        df = pd.DataFrame(rows, columns=["Metric", "Value"])
        return df.to_markdown(index=False)
