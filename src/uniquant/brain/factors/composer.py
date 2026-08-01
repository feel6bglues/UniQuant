"""
因子合成器 - 现在从 FactorRegistry 读取所有因子
"""

from copy import deepcopy
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np
from scipy import linalg

from ...shared.logger_factory import get_logger
from .registry import FactorRegistry
from .analyzer import FactorAnalyzer, FactorICResult
from .neutralizer import FactorNeutralizer

logger = get_logger("FactorComposer")


class FactorComposer:
    """
    多因子合成器（支持无限扩展）
    
    支持:
    - Z-score 标准化
    - 对称正交化 (Symmetric Orthogonalization)
    - IC 加权合成
    """
    def __init__(self, orthogonalize: bool = True):
        self.registry = FactorRegistry()
        self.analyzer = FactorAnalyzer()
        self.orthogonalize = orthogonalize
        self.last_diagnostics = self._new_diagnostics()

    def _new_diagnostics(self) -> Dict[str, Any]:
        return {
            "requested_factors": [],
            "computed_factors": [],
            "used_factors": [],
            "missing_requested_factors": [],
            "failed_factors": {},
            "orthogonalization_attempted": False,
            "orthogonalization_failed": False,
            "orthogonalization_error": None,
            "composite_status": "NOT_STARTED",
            "composite_usable": False,
        }

    def get_last_diagnostics(self) -> Dict[str, Any]:
        """Return a copy of the last factor composition diagnostics."""
        return deepcopy(self.last_diagnostics)

    def _mark_composite_status(self) -> None:
        diagnostics = self.last_diagnostics
        if not diagnostics["used_factors"]:
            diagnostics["composite_status"] = "UNAVAILABLE"
            diagnostics["composite_usable"] = False
            return

        degraded = (
            bool(diagnostics["failed_factors"])
            or bool(diagnostics["missing_requested_factors"])
            or bool(diagnostics["orthogonalization_failed"])
        )
        diagnostics["composite_status"] = "DEGRADED" if degraded else "OK"
        diagnostics["composite_usable"] = True

    def _iter_groups(self, df: pd.DataFrame):
        """按股票代码分组；如果没有 code 列则返回单组。"""
        if "code" in df.columns and not df["code"].empty:
            for _, group in df.groupby("code", sort=False):
                yield group
        else:
            yield df

    def _sort_group(self, df: pd.DataFrame) -> pd.DataFrame:
        """确保滚动因子按时间顺序计算。"""
        if "date" in df.columns:
            return df.sort_values("date")
        return df

    def compute_all_factors(
        self,
        df: pd.DataFrame,
        mode: str = "backtest",
        return_diagnostics: bool = False,
    ):
        """
        一次性计算所有已注册的因子
        """
        self.last_diagnostics = self._new_diagnostics()
        enabled_factors = list(self.registry.get_enabled())
        self.last_diagnostics["requested_factors"] = [
            factor.name for factor in enabled_factors
        ]

        if df.empty:
            result = pd.DataFrame()
            return (result, self.get_last_diagnostics()) if return_diagnostics else result

        factor_values = pd.DataFrame(index=df.index)

        for factor in enabled_factors:
            try:
                factor_series = pd.Series(index=df.index, dtype=float)
                factor_error = None
                for group in self._iter_groups(df):
                    group_df = self._sort_group(group.copy())
                    try:
                        series = factor.compute_func(group_df.copy(), mode=mode)
                    except TypeError:
                        series = factor.compute_func(group_df.copy())
                    if len(series) != len(group_df):
                        factor_error = (
                            f"length mismatch: expected {len(group_df)}, got {len(series)}"
                        )
                        logger.warning(f"因子 {factor.name} 返回长度不匹配")
                        continue

                    series = pd.Series(np.asarray(series, dtype=float), index=group_df.index)
                    factor_series.loc[group_df.index] = series.to_numpy()

                if factor_error and not factor_series.notna().any():
                    self.last_diagnostics["failed_factors"][factor.name] = factor_error
                    continue

                factor_values[factor.name] = factor_series
                self.last_diagnostics["computed_factors"].append(factor.name)
            except Exception as e:
                logger.error(f"因子 {factor.name} 计算失败: {e}")
                self.last_diagnostics["failed_factors"][factor.name] = str(e)

        return (
            factor_values,
            self.get_last_diagnostics(),
        ) if return_diagnostics else factor_values

    def _resolve_ic_result(self, value: Any) -> Optional[FactorICResult]:
        """从各种兼容输入中提取单个 IC 结果。"""
        if isinstance(value, FactorICResult):
            return value

        if isinstance(value, dict) and value:
            candidates = [v for v in value.values() if isinstance(v, FactorICResult)]
            if not candidates:
                return None
            return max(candidates, key=lambda result: abs(result.icir))

        if isinstance(value, list):
            logger.warning(
                "_resolve_ic_result received list (expected dict or FactorICResult) for value with %d items",
                len(value),
            )
            return None

        return None

    def _apply_cross_window_decay(
        self,
        history: List[float],
        current_icir: float,
        half_life: int = 10,
    ) -> float:
        """
        跨窗口 ICIR 指数衰减加权。
        将当前 ICIR 与历史 ICIR 序列进行 decay-weighted 平均,
        使近期 ICIR 权重 > 远期 ICIR 权重。

        与 analyzer.py compute_ic_ir 的 half_life (日度 IC 序列加权)
        独立且正交 — 前者跨训练窗口, 后者窗口内日频。

        双重归一化说明:
        1. 本方法: 单因子跨窗口 ICIR 指数加权平均 (权重归一化到和为 1)
        2. _resolve_weights: 所有因子间归一化 (权重归一化到和为 1)

        Args:
            history: 历史 ICIR 值列表 (旧→新)
            current_icir: 当前窗口的 ICIR 值
            half_life: 半衰期(训练窗口数)。10 = 10 个窗口前权重降为一半
                      默认 10 适用于典型 20-50 窗口的 walk_forward 场景。
        """
        all_values = list(history) + [current_icir]
        n = len(all_values)
        if n <= 1:
            return current_icir
        if half_life is None or half_life <= 0:
            return float(np.mean(all_values))

        positions = np.arange(n - 1, -1, -1, dtype=np.float64)
        weights = np.exp(-np.log(2) * positions / half_life)
        weights = weights / weights.sum()
        return float(np.sum(np.array(all_values) * weights))

    def _resolve_weights(
        self,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Any]] = None,
        ic_history: Optional[Dict[str, Dict[str, List[float]]]] = None,
        half_life: Optional[int] = None,
    ) -> Dict[str, float]:
        """
        根据 IC 结果或注册表默认权重生成合成权重。
        支持跨窗口 ICIR 指数衰减和规范化归一化。

        ic_history 结构: {factor_name: {period_label: [icir_values_old_to_new]}}
        例如: {"momentum_20d": {"1d": [0.1, 0.2], "5d": [0.15, 0.25]}}
        """
        weights: Dict[str, float] = {}

        for col in factor_cols:
            weight = None
            period_key: Optional[str] = None
            if ic_results and col in ic_results:
                result = self._resolve_ic_result(ic_results[col])
                if result is not None and np.isfinite(result.icir):
                    weight = float(result.icir)
                    period_key = f"{result.n_periods}d"

            if weight is None:
                factor = self.registry.get_factor(col)
                weight = float(factor.default_weight) if factor is not None else 1.0

            if (
                weight is not None
                and ic_history
                and col in ic_history
                and half_life is not None
                and half_life > 0
            ):
                col_history_data = ic_history[col]
                if period_key is not None and period_key in col_history_data:
                    weight = self._apply_cross_window_decay(
                        col_history_data[period_key], weight, half_life
                    )

            weights[col] = weight

        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        else:
            weights = {col: 1.0 / max(len(factor_cols), 1) for col in factor_cols}
        return weights

    def _zscore_frame(self, factor_df: pd.DataFrame) -> pd.DataFrame:
        """对因子列做安全标准化，避免 0 方差产生异常值。"""
        if factor_df.empty:
            return factor_df.copy()

        std = factor_df.std(ddof=0).replace(0, np.nan)
        z_df = (factor_df - factor_df.mean()) / std
        return z_df.replace([np.inf, -np.inf], np.nan)

    def _normalize_factors(
        self,
        df: pd.DataFrame,
        factor_df: pd.DataFrame,
        date_col: str = "date",
    ) -> pd.DataFrame:
        """按日期做横截面标准化；无日期时退化为全局标准化。"""
        if factor_df.empty:
            return factor_df.copy()

        if date_col not in df.columns:
            return self._zscore_frame(factor_df)

        normalized_parts = []
        for _, indexer in df.groupby(date_col, sort=False).groups.items():
            group_factors = factor_df.loc[indexer]
            normalized_parts.append(self._zscore_frame(group_factors))

        normalized = pd.concat(normalized_parts).loc[factor_df.index]
        return normalized

    def _build_composite_frame(
        self,
        df: pd.DataFrame,
        factor_df: pd.DataFrame,
        weights: Dict[str, float],
        date_col: str = "date",
        normalize: bool = True,
        orthogonalize: bool = False,
    ) -> pd.DataFrame:
        """把标准化因子和 composite_score 组装成结果表。"""
        if factor_df.empty:
            return pd.DataFrame(index=df.index)

        normalized = self._normalize_factors(df, factor_df, date_col=date_col) if normalize else factor_df.copy()

        if orthogonalize and normalized.shape[1] >= 2:
            normalized = self._symmetric_orthogonalization(normalized)

        composite = pd.Series(0.0, index=normalized.index, dtype=float)

        for col in normalized.columns:
            if col in weights:
                composite = composite.add(normalized[col] * weights[col], fill_value=0.0)

        result = normalized.copy()
        result["composite_score"] = composite
        return result

    def _symmetric_orthogonalization(self, factor_df: pd.DataFrame) -> pd.DataFrame:
        """
        对称正交化 (Symmetric Orthogonalization)
        
        使用特征值分解实现对称正交化，消除因子间的共线性，
        同时保持因子的对称性和信息含量。
        
        方法: F_orth = F @ (F.T @ F)^{-1/2}
        
        Args:
            factor_df: 标准化后的因子 DataFrame
            
        Returns:
            正交化后的因子 DataFrame
        """
        if factor_df.empty or factor_df.shape[1] < 2:
            return factor_df

        self.last_diagnostics["orthogonalization_attempted"] = True
        
        F = factor_df.values
        n, k = F.shape
        
        F_centered = F - F.mean(axis=0)
        
        cov_matrix = np.cov(F_centered.T)
        
        try:
            eigenvalues, eigenvectors = linalg.eigh(cov_matrix)
            
            eigenvalues = np.maximum(eigenvalues, 1e-10)
            
            D_inv_sqrt = np.diag(1.0 / np.sqrt(eigenvalues))
            
            cov_inv_sqrt = eigenvectors @ D_inv_sqrt @ eigenvectors.T
            
            F_orth = F_centered @ cov_inv_sqrt

            orth_df = pd.DataFrame(F_orth, index=factor_df.index, columns=factor_df.columns)
            orth_std = orth_df.std(ddof=0).replace(0, np.nan)
            orth_df = (orth_df - orth_df.mean()) / orth_std
            
            return orth_df.replace([np.inf, -np.inf], np.nan)

        except linalg.LinAlgError as e:
            logger.warning(f"对称正交化失败，使用原始因子: {e}")
            self.last_diagnostics["orthogonalization_failed"] = True
            self.last_diagnostics["orthogonalization_error"] = str(e)
            return factor_df

    def compose_scores(
        self,
        df: pd.DataFrame,
        ic_weights: Optional[Dict[str, float]] = None,
        factor_cols: Optional[List[str]] = None,
        date_col: str = "date",
        industry_dummies: Optional[pd.DataFrame] = None,
        log_market_cap: Optional[pd.Series] = None,
        neutralize: bool = False,
        mode: str = "backtest",
        return_diagnostics: bool = False,
    ):
        """
        合成 composite_score
        
        Args:
            df: 原始数据 DataFrame
            ic_weights: 因子权重字典，如果为 None 则使用默认权重
            industry_dummies: 行业哑变量矩阵 (用于因子中性化)
            log_market_cap: 对数市值 (用于因子中性化)
            neutralize: 是否对 composite_score 做因子中性化
            
        Returns:
            包含 composite_score 和标准化因子的 DataFrame
        """
        factor_df = self.compute_all_factors(df, mode=mode)
        if factor_df.empty:
            result = pd.DataFrame()
            self._mark_composite_status()
            return (result, self.get_last_diagnostics()) if return_diagnostics else result

        if factor_cols is not None:
            available_cols = [col for col in factor_cols if col in factor_df.columns]
            self.last_diagnostics["missing_requested_factors"] = [
                col for col in factor_cols if col not in factor_df.columns
            ]
            factor_df = factor_df[available_cols]

        if factor_df.empty:
            result = pd.DataFrame(index=df.index)
            self._mark_composite_status()
            return (result, self.get_last_diagnostics()) if return_diagnostics else result

        if ic_weights is None:
            ic_weights = self._resolve_weights(list(factor_df.columns))
        else:
            ic_weights = {col: float(ic_weights[col]) for col in factor_df.columns if col in ic_weights}

        self.last_diagnostics["used_factors"] = list(factor_df.columns)

        result = self._build_composite_frame(
            df,
            factor_df,
            ic_weights,
            date_col=date_col,
            normalize=True,
            orthogonalize=self.orthogonalize,
        )

        if neutralize and "composite_score" in result.columns and industry_dummies is not None and log_market_cap is not None:
            neutralizer = FactorNeutralizer()
            result["composite_score"] = neutralizer.neutralize(
                result["composite_score"], industry_dummies, log_market_cap
            )

        self._mark_composite_status()
        return (result, self.get_last_diagnostics()) if return_diagnostics else result

    def process(
        self,
        df: pd.DataFrame,
        factor_cols: Optional[List[str]] = None,
        ic_results: Optional[Dict[str, Any]] = None,
        date_col: str = "date",
        mode: str = "backtest",
        return_diagnostics: bool = False,
        ic_history: Optional[Dict[str, Dict[str, List[float]]]] = None,
        half_life: Optional[int] = None,
    ):
        """
        兼容性入口：计算因子、生成权重并输出 composite_score。
        """
        factor_df = self.compute_all_factors(df, mode=mode)
        if factor_cols is not None:
            requested_factor_cols = list(factor_cols)
            factor_cols = [col for col in factor_cols if col in factor_df.columns]
            self.last_diagnostics["missing_requested_factors"] = [
                col for col in requested_factor_cols if col not in factor_df.columns
            ]
            factor_df = factor_df[factor_cols]
        else:
            factor_cols = list(factor_df.columns)

        if factor_df.empty:
            result_df = df.copy()
            self._mark_composite_status()
            if return_diagnostics:
                return result_df, {}, self.get_last_diagnostics()
            return result_df, {}

        weights = self._resolve_weights(
            factor_cols,
            ic_results=ic_results,
            ic_history=ic_history,
            half_life=half_life,
        )
        self.last_diagnostics["used_factors"] = list(factor_df.columns)
        scored_factors = self._build_composite_frame(
            df,
            factor_df,
            weights,
            date_col=date_col,
            normalize=True,
            orthogonalize=self.orthogonalize,
        )

        result_df = df.copy()
        for col in factor_df.columns:
            result_df[col] = factor_df[col]
        result_df["composite_score"] = scored_factors["composite_score"]

        self._mark_composite_status()
        if return_diagnostics:
            return result_df, weights, self.get_last_diagnostics()
        return result_df, weights
