from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class SensitivityAnalyzer:
    """
    参数敏感性分析器
    
    提供:
    - One-at-a-Time (OAT) 敏感性分析
    - 龙卷风图数据准备
    - 参数与绩效的相关性分析
    """

    def __init__(self):
        pass

    def one_at_a_time(
        self,
        base_params: Dict[str, Any],
        param_ranges: Dict[str, List[Any]],
        strategy_fn: Callable[[Dict[str, Any]], float],
        metric_name: str = "sharpe_ratio",
    ) -> pd.DataFrame:
        """
        One-at-a-Time (OAT) 敏感性分析
        
        每次改变一个参数，保持其他参数不变，
        观察绩效指标的变化。
        
        Args:
            base_params: 基准参数
            param_ranges: 各参数取值范围的字典
            strategy_fn: 策略函数，接收参数字典返回绩效指标
            metric_name: 绩效指标名称
            
        Returns:
            包含每个参数组合绩效的 DataFrame
        """
        results: List[Dict[str, Any]] = []

        base_result = strategy_fn(base_params)
        base_metric = base_result if isinstance(base_result, (int, float)) else base_result.get(metric_name, 0)

        for param_name, param_values in param_ranges.items():
            if len(param_values) < 2:
                continue

            for val in param_values:
                params = dict(base_params)
                params[param_name] = val
                result = strategy_fn(params)
                metric = result if isinstance(result, (int, float)) else result.get(metric_name, 0)

                results.append({
                    "parameter": param_name,
                    "value": val,
                    metric_name: metric,
                    "base_metric": base_metric,
                    "delta": metric - base_metric,
                    "delta_pct": (metric - base_metric) / max(abs(base_metric), 1e-10),
                })

        return pd.DataFrame(results)

    def tornado_plot_data(self, sensitivities: pd.DataFrame, metric_col: str = "sharpe_ratio") -> pd.DataFrame:
        """
        准备龙卷风图数据
        
        计算每个参数在取值范围内对绩效指标的影响范围。
        
        Args:
            sensitivities: OAT 分析结果 DataFrame
            metric_col: 绩效指标列名
            
        Returns:
            包含每个参数最小/最大影响的 DataFrame，用于龙卷风图
        """
        if sensitivities.empty:
            return pd.DataFrame()

        tornado_data = []
        for param_name, group in sensitivities.groupby("parameter"):
            if len(group) < 2:
                continue
            min_metric = group[metric_col].min()
            max_metric = group[metric_col].max()
            base_metric = group["base_metric"].iloc[0]
            range_val = max_metric - min_metric

            tornado_data.append({
                "parameter": param_name,
                "base_metric": base_metric,
                "min_metric": min_metric,
                "max_metric": max_metric,
                "range": range_val,
                "range_pct": range_val / max(abs(base_metric), 1e-10),
                "min_value": group.loc[group[metric_col].idxmin(), "value"],
                "max_value": group.loc[group[metric_col].idxmax(), "value"],
                "direction": "positive" if max_metric > base_metric else "negative",
            })

        tornado_df = pd.DataFrame(tornado_data)
        if not tornado_df.empty:
            tornado_df = tornado_df.sort_values("range", ascending=True)

        return tornado_df

    def correlation_analysis(
        self,
        param_values: pd.DataFrame,
        metric_values: pd.Series,
    ) -> pd.DataFrame:
        """
        分析参数值与绩效指标的相关性
        
        Args:
            param_values: 参数值 DataFrame，每列为一个参数
            metric_values: 对应的绩效指标值 Series
            
        Returns:
            包含 Pearson / Spearman 相关系数的 DataFrame
        """
        if param_values.empty or metric_values.empty:
            return pd.DataFrame()

        if len(param_values) != len(metric_values):
            logger.warning("参数值与绩效指标长度不匹配")
            return pd.DataFrame()

        results = []
        for col in param_values.columns:
            numeric = pd.to_numeric(param_values[col], errors="coerce")
            valid = numeric.notna() & metric_values.notna()
            if valid.sum() < 5:
                continue

            pearson = numeric[valid].corr(metric_values[valid], method="pearson")
            spearman = numeric[valid].corr(metric_values[valid], method="spearman")

            results.append({
                "parameter": col,
                "pearson": pearson if not np.isnan(pearson) else 0,
                "spearman": spearman if not np.isnan(spearman) else 0,
                "abs_pearson": abs(pearson) if not np.isnan(pearson) else 0,
                "abs_spearman": abs(spearman) if not np.isnan(spearman) else 0,
                "n_valid": int(valid.sum()),
            })

        corr_df = pd.DataFrame(results)
        if not corr_df.empty:
            corr_df = corr_df.sort_values("abs_pearson", ascending=False)

        return corr_df
