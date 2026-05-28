"""
因子合成器 - 现在从 FactorRegistry 读取所有因子
"""

import pandas as pd
import numpy as np
from scipy import linalg
from typing import Any, Dict, List, Optional, Tuple

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

    def compute_all_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        一次性计算所有已注册的因子
        """
        if df.empty:
            return pd.DataFrame()

        factor_values = pd.DataFrame(index=df.index)

        for factor in self.registry.get_enabled():
            try:
                factor_series = pd.Series(index=df.index, dtype=float)
                for group in self._iter_groups(df):
                    group_df = self._sort_group(group.copy())
                    series = factor.compute_func(group_df.copy())
                    if len(series) != len(group_df):
                        logger.warning(f"因子 {factor.name} 返回长度不匹配")
                        continue

                    series = pd.Series(np.asarray(series, dtype=float), index=group_df.index)
                    factor_series.loc[group_df.index] = series.to_numpy()

                factor_values[factor.name] = factor_series
            except Exception as e:
                logger.error(f"因子 {factor.name} 计算失败: {e}")

        return factor_values

    def _resolve_ic_result(self, value: Any) -> Optional[FactorICResult]:
        """从各种兼容输入中提取单个 IC 结果。"""
        if isinstance(value, FactorICResult):
            return value

        if isinstance(value, dict) and value:
            candidates = [v for v in value.values() if isinstance(v, FactorICResult)]
            if not candidates:
                return None
            return max(candidates, key=lambda result: abs(result.icir))

        return None

    def _resolve_weights(
        self,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """
        根据 IC 结果或注册表默认权重生成合成权重。
        """
        weights: Dict[str, float] = {}

        for col in factor_cols:
            weight = None
            if ic_results and col in ic_results:
                result = self._resolve_ic_result(ic_results[col])
                if result is not None and np.isfinite(result.icir):
                    weight = float(result.icir)

            if weight is None:
                factor = self.registry.get_factor(col)
                weight = float(factor.default_weight) if factor is not None else 1.0

            weights[col] = weight

        return weights

    def _zscore_frame(self, factor_df: pd.DataFrame) -> pd.DataFrame:
        """对因子列做安全标准化，避免 0 方差产生异常值。"""
        if factor_df.empty:
            return factor_df.copy()

        std = factor_df.std(ddof=0).replace(0, np.nan)
        z_df = (factor_df - factor_df.mean()) / std
        return z_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)

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
        return normalized.fillna(0.0)

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
            
            return orth_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
            
        except linalg.LinAlgError as e:
            logger.warning(f"对称正交化失败，使用原始因子: {e}")
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
    ) -> pd.DataFrame:
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
        factor_df = self.compute_all_factors(df)
        if factor_df.empty:
            return pd.DataFrame()

        if factor_cols is not None:
            available_cols = [col for col in factor_cols if col in factor_df.columns]
            factor_df = factor_df[available_cols]

        if factor_df.empty:
            return pd.DataFrame(index=df.index)

        if ic_weights is None:
            ic_weights = self._resolve_weights(list(factor_df.columns))
        else:
            ic_weights = {col: float(ic_weights[col]) for col in factor_df.columns if col in ic_weights}

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

        return result

    def process(
        self,
        df: pd.DataFrame,
        factor_cols: Optional[List[str]] = None,
        ic_results: Optional[Dict[str, Any]] = None,
        date_col: str = "date",
    ) -> Tuple[pd.DataFrame, Dict[str, float]]:
        """
        兼容性入口：计算因子、生成权重并输出 composite_score。
        """
        factor_df = self.compute_all_factors(df)
        if factor_cols is not None:
            factor_cols = [col for col in factor_cols if col in factor_df.columns]
            factor_df = factor_df[factor_cols]
        else:
            factor_cols = list(factor_df.columns)

        if factor_df.empty:
            return df.copy(), {}

        weights = self._resolve_weights(factor_cols, ic_results=ic_results)
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

        return result_df, weights
