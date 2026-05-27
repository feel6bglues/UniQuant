import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ..shared.config_loader import config
from ..shared.error_handling import handle_errors
from ..shared.exceptions import AnalysisError, EngineError
from ..shared.interfaces import DataFetcherProtocol
from ..shared.logger_factory import get_logger

logger = get_logger(__name__)


class AlphaDecoupler:
    """
    Alpha Decoupler for catching relative strength.
    Calculates RS Slope and filters low-correlation assets.
    """

    @staticmethod
    @handle_errors(
        ValueError,
        TypeError,
        AnalysisError,
        default_return="000300.SH",
        log_level=logging.ERROR,
    )
    def get_benchmark(market_cap: float) -> str:
        """
        Route to appropriate benchmark based on market cap.
        
        Gemini 建议: 根据 2024-2026 A股结构更新阈值
        - > 800亿: 沪深300 (大盘蓝筹)
        - 200-800亿: 中证500 (中盘)
        - 50-200亿: 中证1000 (小盘)
        - < 50亿: 中证2000 (微盘股)
        """
        thresholds = config.get("brain.alpha_decoupler.benchmark_thresholds", {})
        large_cap = thresholds.get("large_cap", 800e8)
        mid_cap = thresholds.get("mid_cap", 200e8)
        small_cap = thresholds.get("small_cap", 50e8)

        if market_cap > large_cap:
            return "000300.SH"
        if market_cap > mid_cap:
            return "000905.SH"
        if market_cap > small_cap:
            return "000852.SH"
        return "932000.CSI"

    @staticmethod
    @handle_errors(
        ValueError,
        TypeError,
        AnalysisError,
        default_return=lambda benchmark_symbol: benchmark_symbol,
        log_level=logging.ERROR,
    )
    def get_benchmark_name(benchmark_symbol: str) -> str:
        """Get benchmark name from symbol."""
        # This could also be moved to config, but mapping is static enough for now or loaded from markets.yaml
        # Let's check markets.yaml... it has names.
        markets_bench = config.get("markets.benchmarks.names", {})
        return markets_bench.get(benchmark_symbol, benchmark_symbol)

    @staticmethod
    @handle_errors(
        ValueError,
        TypeError,
        AnalysisError,
        default_return=0.0,
        log_level=logging.ERROR,
    )
    def calc_rs_slope(
        stock_df: Optional[pd.DataFrame],
        bench_df: Optional[pd.DataFrame],
        window: int = 20,
    ) -> float:
        if stock_df is None or bench_df is None:
            raise EngineError("Input DataFrames cannot be None")
        if stock_df.empty or bench_df.empty:
            return 0.0
        if "date" not in stock_df.columns or "close" not in stock_df.columns:
            raise EngineError("stock_df must have 'date' and 'close' columns")
        if "date" not in bench_df.columns or "close" not in bench_df.columns:
            raise EngineError("bench_df must have 'date' and 'close' columns")

        # Override window if in config? No, parameter usually overrides config default.
        if window <= 0:
            raise EngineError(f"Window must be positive, got {window}")

        # 确保日期列类型一致
        stock_df = stock_df.copy()
        bench_df = bench_df.copy()

        # 转换日期列为datetime类型
        if not pd.api.types.is_datetime64_any_dtype(stock_df["date"]):
            stock_df["date"] = pd.to_datetime(stock_df["date"])
        if not pd.api.types.is_datetime64_any_dtype(bench_df["date"]):
            bench_df["date"] = pd.to_datetime(bench_df["date"])

        # 修复: 先计算各自的收益率，再merge，避免停牌复牌产生脉冲噪音
        stock_df["stock_ret"] = stock_df["close"].pct_change().fillna(0)
        bench_df["bench_ret"] = bench_df["close"].pct_change().fillna(0)

        combined = pd.merge(
            stock_df[["date", "stock_ret"]],
            bench_df[["date", "bench_ret"]],
            on="date",
        )

        if combined.empty:
            return 0.0

        # 计算收益率差并累积
        combined["diff_ret"] = combined["stock_ret"] - combined["bench_ret"]
        combined["rs_curve"] = combined["diff_ret"].cumsum()

        # 获取最近window长度的数据
        rs_data = combined["rs_curve"].tail(window).values

        # 检查数据长度
        if len(rs_data) < window:
            return 0.0

        # 线性拟合求斜率
        x = np.arange(len(rs_data))
        slope = np.polyfit(x, rs_data, 1)[0]

        # 将斜率乘以100，使其量级更符合阅读习惯
        return float(slope * 100)

    @staticmethod
    def calc_benchmark_corr(
        stock_df: Optional[pd.DataFrame],
        bench_df: Optional[pd.DataFrame],
        window: int = 20,
    ) -> float:
        if stock_df is None or bench_df is None:
            raise EngineError("Input DataFrames cannot be None")
        if "date" not in stock_df.columns or "close" not in stock_df.columns:
            raise EngineError("stock_df must have 'date' and 'close' columns")
        if "date" not in bench_df.columns or "close" not in bench_df.columns:
            raise EngineError("bench_df must have 'date' and 'close' columns")
        if window <= 0:
            raise EngineError(f"Window must be positive, got {window}")

        # 确保日期列类型一致
        stock_df = stock_df.copy()
        bench_df = bench_df.copy()

        # 转换日期列为datetime类型
        if not pd.api.types.is_datetime64_any_dtype(stock_df["date"]):
            stock_df["date"] = pd.to_datetime(stock_df["date"])
        if not pd.api.types.is_datetime64_any_dtype(bench_df["date"]):
            bench_df["date"] = pd.to_datetime(bench_df["date"])

        # 修复: 先计算各自的收益率，再merge，避免停牌复牌产生脉冲噪音
        stock_df["stock_ret"] = stock_df["close"].pct_change().fillna(0)
        bench_df["bench_ret"] = bench_df["close"].pct_change().fillna(0)

        combined = pd.merge(
            stock_df[["date", "stock_ret"]],
            bench_df[["date", "bench_ret"]],
            on="date",
        )

        if combined.empty or len(combined) < window:
            return 0.0

        correlation = (
            combined[["stock_ret", "bench_ret"]].tail(window).corr().iloc[0, 1]
        )

        return float(correlation)

    @staticmethod
    def get_alpha_features(
        stock_df: pd.DataFrame, bench_df: pd.DataFrame, window: int = 20
    ) -> Dict[str, Any]:
        """
        Get all alpha features in one call.
        """
        rs_slope = AlphaDecoupler.calc_rs_slope(stock_df, bench_df, window)
        benchmark_corr = AlphaDecoupler.calc_benchmark_corr(stock_df, bench_df, window)

        return {
            "rs_slope": round(rs_slope, 4),
            "benchmark_corr": round(benchmark_corr, 4),
        }

    @staticmethod
    def get_alpha_score(
        stock_df: pd.DataFrame,
        bench_df: pd.DataFrame,
        sector_df: Optional[pd.DataFrame] = None,
    ) -> float:
        """
        计算行业中性的RS斜率，排除大盘普涨带来的Beta收益，寻找真正具有超额Alpha的脱钩标的

        参数:
        stock_df: 个股数据
        bench_df: 大盘基准数据
        sector_df: 行业基准数据（可选）

        返回:
        float: alpha得分
        """

        def _calc_aligned_slope(
            df1: pd.DataFrame, df2: pd.DataFrame, window: int = 10
        ) -> float:
            # 修复: 先计算各自的收益率，再merge，避免停牌复牌产生脉冲噪音
            df1 = df1.copy()
            df2 = df2.copy()
            df1["ret1"] = df1["close"].pct_change().fillna(0)
            df2["ret2"] = df2["close"].pct_change().fillna(0)
            merged = pd.merge(
                df1[["date", "ret1"]],
                df2[["date", "ret2"]],
                on="date",
            )
            if merged.empty:
                return 0.0
            diff_ret = merged["ret1"] - merged["ret2"]
            rs_curve = diff_ret.cumsum()
            rs_data = rs_curve.tail(window).values
            if len(rs_data) < window:
                return 0.0
            slope = np.polyfit(np.arange(len(rs_data)), rs_data, 1)[0]
            return float(slope * 100)

        # 确保数据框是副本，避免修改原始数据
        stock_df = stock_df.copy()
        bench_df = bench_df.copy()

        # 确保日期列类型一致（如果存在date列）
        if "date" in stock_df.columns and not pd.api.types.is_datetime64_any_dtype(
            stock_df["date"]
        ):
            stock_df["date"] = pd.to_datetime(stock_df["date"])
        if "date" in bench_df.columns and not pd.api.types.is_datetime64_any_dtype(
            bench_df["date"]
        ):
            bench_df["date"] = pd.to_datetime(bench_df["date"])

        slope_vs_bench = _calc_aligned_slope(stock_df, bench_df)

        slope_vs_sector = 0.0
        if sector_df is not None and not sector_df.empty:
            sector_df = sector_df.copy()
            if (
                "date" in sector_df.columns
                and not pd.api.types.is_datetime64_any_dtype(sector_df["date"])
            ):
                sector_df["date"] = pd.to_datetime(sector_df["date"])
            slope_vs_sector = _calc_aligned_slope(stock_df, sector_df)
        else:
            # 如果没有行业数据，将大盘权重加倍，或者只返回大盘Alpha
            slope_vs_sector = slope_vs_bench

        # 双重走强：个股不仅强于大盘，还要强于其所属板块
        return float(slope_vs_bench + slope_vs_sector)

    @staticmethod
    def get_alpha_score_from_data(
        data_fetcher: DataFetcherProtocol,
        stock_symbol: str,
        bench_symbol: str,
        sector_symbol: str,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        """
        从数据模块获取数据并计算Alpha得分
        
        .. deprecated::
            此方法破坏 Data Lake 原则，大脑模块不应直接调用 DataFetcher。
            请使用 `calc_rs_slope(stock_df, bench_df)` 替代，传入已标准化的 DataFrame。

        参数:
        data_fetcher: DataFetcherProtocol实例，用于获取数据
        stock_symbol: 个股代码
        bench_symbol: 大盘基准代码
        sector_symbol: 行业基准代码
        start_date: 开始日期，格式为"YYYY-MM-DD"
        end_date: 结束日期，格式为"YYYY-MM-DD"

        返回:
        Dict[str, Any]: Alpha得分计算结果
        """
        import warnings
        warnings.warn(
            "get_alpha_score_from_data is deprecated. "
            "Use calc_rs_slope(stock_df, bench_df) with pre-loaded DataFrame instead.",
            DeprecationWarning,
            stacklevel=2
        )
        try:
            stock_df = data_fetcher.fetch_history(stock_symbol, start_date, end_date)
            bench_df = data_fetcher.fetch_history(bench_symbol, start_date, end_date)
            sector_df = data_fetcher.fetch_history(sector_symbol, start_date, end_date)

            # 验证数据
            if stock_df is None or stock_df.empty:
                logger.error(f"无法获取个股 {stock_symbol} 的数据")
                return {
                    "alpha_score": 0.0,
                    "error": f"无法获取个股 {stock_symbol} 的数据",
                }
            if bench_df is None or bench_df.empty:
                logger.error(f"无法获取基准 {bench_symbol} 的数据")
                return {
                    "alpha_score": 0.0,
                    "error": f"无法获取基准 {bench_symbol} 的数据",
                }
            if sector_df is None or sector_df.empty:
                logger.error(f"无法获取行业 {sector_symbol} 的数据")
                return {
                    "alpha_score": 0.0,
                    "error": f"无法获取行业 {sector_symbol} 的数据",
                }

            # 标准化列名
            for df in [stock_df, bench_df, sector_df]:
                if "Date" in df.columns:
                    df = df.rename(columns={"Date": "date"})
                if "Close" in df.columns:
                    df = df.rename(columns={"Close": "close"})

            # 计算Alpha得分
            alpha_score = AlphaDecoupler.get_alpha_score(stock_df, bench_df, sector_df)

            return {
                "alpha_score": round(alpha_score, 4),
                "stock_symbol": stock_symbol,
                "bench_symbol": bench_symbol,
                "sector_symbol": sector_symbol,
            }
        except Exception as e:
            logger.error(f"计算Alpha得分时出错: {e}")
            return {"alpha_score": 0.0, "error": str(e)}
