"""
因子分析器
计算因子有效性指标 IC/IR/IC>0 比例
"""

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from ...shared.error_handling import handle_errors
from ...shared.logger_factory import get_logger
from ...shared.time_provider import get_time_provider

logger = get_logger("FactorAnalyzer")


class LookaheadBiasError(ValueError):
    """Raised when a factor calculation depends on future data."""


def check_lookahead_leakage(
    df: pd.DataFrame,
    factor_func: Callable,
    factor_cols: List[str],
) -> bool:
    """
    Detect look-ahead bias using future perturbation invariance.

    Runs factor_func on the original df, then on copies with future close prices
    perturbed at multiple cutoffs. If any factor value before a cutoff changes,
    it depends on future data → raises LookaheadBiasError.

    Args:
        df: Input DataFrame with at least 'close' column.
        factor_func: Callable that accepts a DataFrame and returns a DataFrame
                     with factor columns added.
        factor_cols: List of factor column names to check.

    Returns:
        True if no look-ahead bias detected.

    Raises:
        LookaheadBiasError: If a factor shows dependence on future data.
    """
    baseline = factor_func(df.copy()).copy()
    n = len(df)
    cutoffs = [int(n * p) for p in [0.33, 0.50, 0.66]]

    rng = np.random.RandomState(42)

    for cutoff in cutoffs:
        if cutoff >= n or cutoff <= 0:
            continue

        perturbed = df.copy()
        future_close = perturbed.loc[cutoff:, "close"].values
        perturbed.loc[cutoff:, "close"] = future_close * rng.uniform(1.5, 3.0, size=len(future_close))

        result = factor_func(perturbed.copy()).copy()

        for col in factor_cols:
            if col not in baseline.columns or col not in result.columns:
                continue

            b_before = baseline.loc[:cutoff - 1, col]
            r_before = result.loc[:cutoff - 1, col]

            if b_before.isna().all() or r_before.isna().all():
                continue

            if not np.allclose(
                b_before.fillna(0).values,
                r_before.fillna(0).values,
                rtol=1e-5,
            ):
                raise LookaheadBiasError(
                    f"Look-ahead bias detected in factor '{col}'"
                )

    return True


class AnalysisMode(Enum):
    BACKTEST = auto()
    LIVE = auto()

    @classmethod
    def from_config(cls, mode_str: str) -> "AnalysisMode":
        mapping = {"live": cls.LIVE, "backtest": cls.BACKTEST}
        result = mapping.get(mode_str.lower())
        if result is None:
            raise ValueError(f"Unknown mode: {mode_str!r}")
        return result


def _exponential_weights(n: int, half_life: int) -> np.ndarray:
    w = np.exp(-np.arange(n) * np.log(2) / half_life)
    return w[::-1] / w.sum()


@dataclass
class FactorICResult:
    """因子 IC 分析结果"""
    factor_name: str
    ic_mean: float
    ic_std: float
    icir: float
    ic_positive_ratio: float
    ic_t_stat: float
    n_periods: int


class FactorAnalyzer:
    """
    因子分析器
    
    功能:
    1. Rank IC 计算 (Spearman 秩相关)
    2. IC/IR 统计
    3. IC>0 比例
    4. 因子相关性矩阵
    """
    
    DEFAULT_HOLDING_PERIODS = [1, 5, 20]
    
    def __init__(self):
        self.results: Dict[str, FactorICResult] = {}
        logger.info("FactorAnalyzer initialized")
    
    def _compute_forward_returns(
        self,
        df: pd.DataFrame,
        holding_period: int,
        price_col: str = "close",
        mode: str = "backtest",
    ) -> pd.Series:
        """
        计算未来收益率

        ⚠️ 警告: 此方法使用负 shift 引入未来数据，仅限离线回测使用。

        Args:
            df: 价格数据 DataFrame
            holding_period: 持有期 (天)
            price_col: 价格列名
            mode: 运行模式
                - "backtest": 允许负 shift（默认，向后兼容）
                - "live": 禁止未来数据泄漏，抛出 ValueError

        Returns:
            未来收益率 Series

        Raises:
            ValueError: 当 mode="live" 时，防止未来函数（Lookahead Bias）
        """
        if price_col not in df.columns:
            raise ValueError(f"Price column '{price_col}' not found")

        if mode == "live":
            raise ValueError(
                "Lookahead bias detected: _compute_forward_returns uses negative shift "
                "which introduces future data. This method is NOT safe for live trading. "
                "Use mode='backtest' for offline factor analysis only."
            )

        if "date" in df.columns:
            max_date = pd.to_datetime(df["date"]).max()
            if max_date > pd.Timestamp(get_time_provider().now()):
                raise ValueError(
                    f"Future timestamp detected in data: {max_date}. "
                    "Data contains future dates beyond current time. "
                    "This indicates a potential lookahead bias."
                )

        future_ret = df[price_col].shift(-holding_period) / df[price_col] - 1
        return future_ret
    
    def compute_rank_ic(
        self,
        factor_values: pd.Series,
        forward_returns: pd.Series
    ) -> float:
        """
        计算 Rank IC (Spearman 秩相关系数)
        
        Args:
            factor_values: 因子值 Series
            forward_returns: 未来收益率 Series
            
        Returns:
            Rank IC 值
        """
        factor_clean = factor_values.dropna()
        returns_clean = forward_returns.dropna()
        
        common_idx = factor_clean.index.intersection(returns_clean.index)
        
        if len(common_idx) < 5:
            return np.nan
        
        factor_aligned = factor_values.loc[common_idx]
        returns_aligned = forward_returns.loc[common_idx]
        
        mask = ~(factor_aligned.isna() | returns_aligned.isna())
        factor_aligned = factor_aligned[mask]
        returns_aligned = returns_aligned[mask]
        
        if len(factor_aligned) < 5:
            return np.nan

        if factor_aligned.nunique(dropna=True) < 2 or returns_aligned.nunique(dropna=True) < 2:
            return np.nan
        
        try:
            ic, _ = stats.spearmanr(factor_aligned, returns_aligned)
            return ic if not np.isnan(ic) else 0.0
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to compute Spearman correlation: {e}")
            return np.nan

    def _pick_best_period_result(
        self,
        period_results: Dict[int, FactorICResult]
    ) -> Tuple[Optional[int], Optional[FactorICResult]]:
        """在多个持有期中选择绝对 ICIR 最优的结果。"""
        best_period: Optional[int] = None
        best_result: Optional[FactorICResult] = None
        best_score = -np.inf

        for period, result in period_results.items():
            score = abs(result.icir)
            if score > best_score:
                best_score = score
                best_period = period
                best_result = result

        return best_period, best_result
    
    def compute_ic_ir(
        self,
        df: pd.DataFrame,
        factor_cols: List[str],
        holding_periods: Optional[List[int]] = None,
        date_col: str = "date",
        code_col: str = "code",
        price_col: str = "close",
        mode: AnalysisMode | str = AnalysisMode.BACKTEST,
        half_life: Optional[int] = None,
    ) -> Dict[str, Dict[int, FactorICResult]]:
        """
        计算因子 IC/IR

        Args:
            df: 包含因子值和价格的数据 DataFrame
            factor_cols: 因子列名列表
            holding_periods: 持有期列表 (天)
            date_col: 日期列名
            code_col: 股票代码列名
            price_col: 价格列名
            mode: 运行模式
                - AnalysisMode.BACKTEST: 允许负 shift（默认，向后兼容）
                - AnalysisMode.LIVE: 禁止未来数据泄漏，抛出 ValueError
            half_life: IC 序列的半衰期权重计算周期 (默认 None 表示等权)

        Returns:
            Dict[factor_name, Dict[holding_period, FactorICResult]]

        Raises:
            ValueError: 当 mode=AnalysisMode.LIVE 时，防止未来函数（Lookahead Bias）
        """
        if isinstance(mode, str):
            mode = AnalysisMode.from_config(mode)
        elif not isinstance(mode, AnalysisMode):
            raise TypeError(f"mode must be an AnalysisMode enum or str, got {type(mode).__name__}")

        if holding_periods is None:
            holding_periods = self.DEFAULT_HOLDING_PERIODS

        if mode == AnalysisMode.LIVE:
            raise ValueError(
                "Lookahead bias detected: compute_ic_ir uses negative shift "
                "which introduces future data. This method is NOT safe for live trading. "
                "Use mode=AnalysisMode.BACKTEST for offline factor analysis only."
            )

        df = df.copy()

        if date_col in df.columns:
            df = df.sort_values([code_col, date_col])

        results: Dict[str, Dict[int, FactorICResult]] = {}

        # 向量化优化：批量计算所有远期收益，避免重复计算
        df_with_fwd = {}
        for period in holding_periods:
            fwd_col = f"_forward_ret_{period}"
            df[fwd_col] = df.groupby(code_col)[price_col].shift(-period) / df[price_col] - 1
            df_with_fwd[period] = fwd_col

        for factor_col in factor_cols:
            if factor_col not in df.columns:
                logger.warning(f"Factor column '{factor_col}' not found, skipping")
                continue

            results[factor_col] = {}

            for period in holding_periods:
                logger.debug(f"Computing IC for {factor_col} @ {period}d...")

                fwd_col = df_with_fwd[period]

                # 向量化优化：使用 groupby 替代内层日期循环
                if date_col in df.columns:
                    def calc_daily_ic(group):
                        factor_vals = group[factor_col]
                        ret_vals = group[fwd_col]
                        valid = ~(factor_vals.isna() | ret_vals.isna())
                        if valid.sum() < 5:
                            return np.nan
                        return self.compute_rank_ic(factor_vals[valid], ret_vals[valid])

                    ic_series = df.groupby(date_col, group_keys=False)[
                        [factor_col, fwd_col]
                    ].apply(calc_daily_ic)
                    ic_series = ic_series.dropna().tolist()
                else:
                    ic = self.compute_rank_ic(df[factor_col], df[fwd_col])
                    ic_series = [ic] if not np.isnan(ic) else []
                
                if len(ic_series) > 0:
                    ic_array = np.array(ic_series)
                    if half_life is not None and len(ic_array) > 1:
                        w = _exponential_weights(len(ic_array), half_life)
                        ic_mean = float(np.average(ic_array, weights=w))
                        variance = np.average((ic_array - ic_mean) ** 2, weights=w)
                        ic_std = float(np.sqrt(variance))
                    else:
                        ic_mean = float(np.mean(ic_array))
                        ic_std = float(np.std(ic_array))
                    icir = ic_mean / ic_std if ic_std > 0 else 0.0
                    ic_positive_ratio = float(np.sum(ic_array > 0) / len(ic_array))
                    
                    t_stat = ic_mean / (ic_std / np.sqrt(len(ic_array))) if ic_std > 0 else 0.0
                    
                    result = FactorICResult(
                        factor_name=factor_col,
                        ic_mean=ic_mean,
                        ic_std=ic_std,
                        icir=icir,
                        ic_positive_ratio=ic_positive_ratio,
                        ic_t_stat=t_stat,
                        n_periods=len(ic_series)
                    )
                    
                    results[factor_col][period] = result
                    
                    logger.debug(
                        f"Factor {factor_col} @ {period}d: IC={ic_mean:.4f}, "
                        f"IR={icir:.4f}, IC>0={ic_positive_ratio:.2%}"
                    )
        
        # 向量化优化：批量清理临时列
        for period in holding_periods:
            df.drop(columns=[f"_forward_ret_{period}"], errors="ignore", inplace=True)
        
        self.results = {}
        for factor_name, period_results in results.items():
            _, best_result = self._pick_best_period_result(period_results)
            self.results[factor_name] = best_result
        
        if not self.results or all(v is None for v in self.results.values()):
            logger.warning("IC/IR computation returned empty results, using default weights")
            self.results = {col: None for col in factor_cols}
        
        logger.info(f"Computed IC/IR for {len([v for v in self.results.values() if v])} factors")
        return results
    
    def compute_factor_correlation(
        self,
        df: pd.DataFrame,
        factor_cols: List[str],
        method: str = "spearman"
    ) -> pd.DataFrame:
        """
        计算因子相关性矩阵
        
        Args:
            df: 包含因子值的数据 DataFrame
            factor_cols: 因子列名列表
            method: 相关性计算方法 ('pearson' or 'spearman')
            
        Returns:
            因子相关性矩阵 DataFrame
        """
        available_cols = [c for c in factor_cols if c in df.columns]
        
        if len(available_cols) < 2:
            logger.warning("Need at least 2 factors for correlation matrix")
            return pd.DataFrame()
        
        factor_df = df[available_cols].dropna()
        
        if len(factor_df) < 10:
            logger.warning("Insufficient data for correlation calculation")
            return pd.DataFrame()
        
        if method == "spearman":
            corr_matrix = factor_df.rank().corr(method="pearson")
        else:
            corr_matrix = factor_df.corr(method=method)
        
        logger.info(f"Computed {method} correlation matrix for {len(available_cols)} factors")
        return corr_matrix
    
    def get_top_factors(
        self,
        metric: str = "icir",
        top_n: int = 10,
        min_periods: int = 10
    ) -> List[Tuple[str, float]]:
        """
        获取表现最好的因子
        
        Args:
            metric: 排序指标 ('icir', 'ic_mean', 'ic_positive_ratio')
            top_n: 返回数量
            min_periods: 最小期数要求
            
        Returns:
            List of (factor_name, metric_value)
        """
        valid_results = [
            (name, result)
            for name, result in self.results.items()
            if result is not None and result.n_periods >= min_periods
        ]
        
        if not valid_results:
            return []
        
        if metric == "icir":
            sorted_results = sorted(valid_results, key=lambda x: abs(x[1].icir), reverse=True)
            return [(r[0], r[1].icir) for r in sorted_results[:top_n]]
        elif metric == "ic_mean":
            sorted_results = sorted(valid_results, key=lambda x: abs(x[1].ic_mean), reverse=True)
            return [(r[0], r[1].ic_mean) for r in sorted_results[:top_n]]
        elif metric == "ic_positive_ratio":
            sorted_results = sorted(valid_results, key=lambda x: x[1].ic_positive_ratio, reverse=True)
            return [(r[0], r[1].ic_positive_ratio) for r in sorted_results[:top_n]]
        else:
            logger.warning(f"Unknown metric: {metric}")
            return []
    
    @handle_errors(ValueError, KeyError, TypeError, default_return={}, log_level=logging.ERROR)
    def generate_report(
        self,
        results: Optional[Dict[str, Dict[int, FactorICResult]]] = None
    ) -> Dict[str, Any]:
        """
        生成因子分析报告
        
        Args:
            results: IC/IR 计算结果 (默认使用 self.results)
            
        Returns:
            报告字典
        """
        if results is None:
            results = {k: {1: v} for k, v in self.results.items()}
        
        report: Dict[str, Any] = {
            "summary": {},
            "by_factor": {},
            "by_period": {},
        }
        
        all_ic_means: List[float] = []
        all_icirs: List[float] = []
        
        for factor_name, period_results in results.items():
            factor_summary: Dict[str, Any] = {
                "periods": {},
                "best_period": None,
                "avg_ic": None,
                "avg_icir": None,
            }

            best_period, _ = self._pick_best_period_result(period_results)
            
            for period, result in period_results.items():
                factor_summary["periods"][period] = {
                    "ic_mean": result.ic_mean,
                    "ic_std": result.ic_std,
                    "icir": result.icir,
                    "ic_positive_ratio": result.ic_positive_ratio,
                    "n_periods": result.n_periods,
                }
                
                all_ic_means.append(result.ic_mean)
                all_icirs.append(result.icir)
            
            factor_summary["best_period"] = best_period
            
            if factor_summary["periods"]:
                factor_summary["avg_ic"] = np.mean([
                    p["ic_mean"] for p in factor_summary["periods"].values()
                ])
                factor_summary["avg_icir"] = np.mean([
                    p["icir"] for p in factor_summary["periods"].values()
                ])
            
            report["by_factor"][factor_name] = factor_summary
        
        if all_ic_means:
            report["summary"] = {
                "total_factors": len(results),
                "avg_ic": float(np.mean(all_ic_means)),
                "avg_icir": float(np.mean(all_icirs)),
                "factors_with_positive_ic": int(np.sum(np.array(all_ic_means) > 0)),
            }
        
        logger.info(f"Generated factor analysis report for {len(results)} factors")
        return report
