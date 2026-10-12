#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
UniQuant Brain Forensics: Ohlson (1995) Clean Surplus Valuation Factor
================================================================================
模块路径: uniquant.brain.factors.forensics.ohlson_valuation
学术文献:
  Ohlson, J. A. (1995). Earnings, book values, and dividends in equity valuation.
  Contemporary Accounting Research, 11(2), 661-687.

【数理经济学核心原理】：
1. 干净剩余关系 (Clean Surplus Relation, CSR):
     B_t = B_{t-1} + NI_t - D_t
   定义异常盈余 (Abnormal Earnings / Residual Income):
     x^a_t = NI_t - r * B_{t-1}，其中 r 为股权资金必要回报率 (季度 r_q = 0.02)
2. 线性信息动态 (Linear Information Dynamics, AR(1)):
     x^a_{t+1} = \omega * x^a_t + \epsilon_{t+1}
3. 经验贝叶斯 (Empirical Bayes) 双重收缩估计器:
     \omega_i^* = (1 - \lambda_i) \hat{\omega}_i + \lambda_i \bar{\omega}_{prior}
     \lambda_i = s_i^2 / (s_i^2 + \tau^2)
     严格截断紧致界限: \omega^{EB} \in [0.15, 0.85]
4. 横截收敛裕度定理 (Transversality & Discount Convergence Theorem):
     1 + r_q - \omega^{EB} >= 1 + 0.02 - 0.85 = 0.1700 > 0
   保证贴现无穷级数绝对一致收敛，乘数 \alpha_1 = \frac{\omega}{1 + r - \omega} 紧致有界 (<= 5.0)。
================================================================================
"""

import logging
from typing import Dict, List
import numpy as np
import pandas as pd
from scipy import stats

from ..base import BaseFactor
from ..registry import FactorRegistry

logger = logging.getLogger("uniquant.brain.factors.forensics.ohlson_valuation")



class OhlsonValuationFactor(BaseFactor):
    """
    Ohlson (1995) 清洁剩余异常盈余持续性与内生估值因子
    """

    name: str = "ohlson_valuation"
    category: str = "forensics"
    default_weight: float = 1.0
    description: str = "Ohlson(1995) 清洁剩余异常盈余经验贝叶斯持续性与贴现估值因子"

    # 核心数理超参数
    DEFAULT_R_QUARTERLY: float = 0.02  # 季度贴现率 2% (年化约 8.24%)
    OMEGA_LOWER_BOUND: float = 0.15   # 持续性后验下界
    OMEGA_UPPER_BOUND: float = 0.85   # 持续性后验上界 (保证裕度 >= 0.17)
    MIN_CONVERGENCE_MARGIN: float = 0.1700

    def __init__(
        self,
        cost_of_equity_quarterly: float = DEFAULT_R_QUARTERLY,
        omega_lower: float = OMEGA_LOWER_BOUND,
        omega_upper: float = OMEGA_UPPER_BOUND,
        default_weight: float = 1.0,
    ):
        super().__init__(
            name=self.name,
            category=self.category,
            default_weight=default_weight,
            description=self.description,
        )
        self.r_q = cost_of_equity_quarterly
        self.omega_lower = omega_lower
        self.omega_upper = omega_upper
        # 验证数理紧致性: 1 + r - omega_upper >= 0.17
        margin = (1.0 + self.r_q) - self.omega_upper
        if margin < self.MIN_CONVERGENCE_MARGIN - 1e-6:
            raise ValueError(
                f"横截收敛裕度不足! 1 + r - omega_upper = {margin:.4f} < {self.MIN_CONVERGENCE_MARGIN}"
            )

    @staticmethod
    def _extract_series(df: pd.DataFrame, candidates: List[str], default_val: float = 0.0) -> pd.Series:
        for c in candidates:
            if c in df.columns:
                return pd.to_numeric(df[c], errors="coerce").fillna(default_val)
        return pd.Series(default_val, index=df.index, dtype=float)

    def solve_empirical_bayes_omega(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        全截面/面板求解各标的 AR(1) 盈余持续性参数并施加经验贝叶斯收缩
        """
        ni = self._extract_series(df, ["net_income", "归属于母公司所有者的净利润", "净利润", "net_profit"])
        eq = self._extract_series(df, ["equity", "所有者权益（或股东权益）合计", "股东权益", "total_equity"])
        
        # 识别代码列
        code_s = None
        for c in ["code", "股票代码", "symbol"]:
            if c in df.columns:
                code_s = df[c].astype(str)
                break
        if code_s is None:
            code_s = pd.Series(df.index.astype(str), index=df.index)

        df_calc = pd.DataFrame({"code": code_s, "ni": ni, "eq": eq}, index=df.index)
        
        # 计算异常盈余: x^a_t = NI_t - r * Equity_{t-1}
        raw_ar1 = {}
        grouped = df_calc.groupby("code")
        
        for code, grp in grouped:
            if len(grp) < 4:
                raw_ar1[code] = {"omega": 0.45, "std_err": 0.20}
                continue
            
            eq_lag = grp["eq"].shift(1).fillna(grp["eq"].iloc[0])
            xa = grp["ni"] - self.r_q * eq_lag
            xa_lead = xa.shift(-1)
            valid = pd.DataFrame({"xa": xa, "xa_lead": xa_lead}).dropna()
            
            if len(valid) >= 4 and valid["xa"].std() > 1e-4:
                slope, _, _, _, std_err = stats.linregress(valid["xa"], valid["xa_lead"])
                raw_ar1[code] = {
                    "omega": float(slope) if np.isfinite(slope) else 0.45,
                    "std_err": float(std_err) if (pd.notna(std_err) and std_err > 0) else 0.15,
                }
            else:
                raw_ar1[code] = {"omega": 0.45, "std_err": 0.20}

        # 经验贝叶斯先验超参数估计
        all_omegas = [v["omega"] for v in raw_ar1.values() if np.isfinite(v["omega"])]
        all_ses = [v["std_err"] for v in raw_ar1.values() if np.isfinite(v["std_err"])]

        prior_mean = float(np.median(all_omegas)) if all_omegas else 0.45
        sample_var = float(np.var(all_omegas)) if len(all_omegas) > 2 else 0.04
        mean_sampling_var = float(np.mean(np.square(all_ses))) if all_ses else 0.02
        prior_tau2 = max(1e-4, sample_var - mean_sampling_var)

        eb_results = {}
        for code, m in raw_ar1.items():
            s_i = m["omega"]
            se_i = m["std_err"]
            lambda_i = float((se_i ** 2) / (se_i ** 2 + prior_tau2))
            omega_shrunk = (1.0 - lambda_i) * s_i + lambda_i * prior_mean
            # 严格强制截断至 [OMEGA_LOWER_BOUND, OMEGA_UPPER_BOUND]
            omega_eb = float(np.clip(omega_shrunk, self.omega_lower, self.omega_upper))
            eb_results[code] = omega_eb

        return eb_results

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """
        计算 Ohlson 清洁剩余因子得分
        返回: pd.Series (与 df.index 严格对齐)
        """
        if df.empty:
            return pd.Series(dtype=float)

        eb_map = self.solve_empirical_bayes_omega(df)
        
        # 提取股票代码
        code_s = None
        for c in ["code", "股票代码", "symbol"]:
            if c in df.columns:
                code_s = df[c].astype(str)
                break
        if code_s is None:
            code_s = pd.Series(df.index.astype(str), index=df.index)

        # 映射后验持久性参数 omega_eb
        omega_series = code_s.map(eb_map).fillna(0.45)

        # 计算异常盈余 x^a
        ni = self._extract_series(df, ["net_income", "归属于母公司所有者的净利润", "净利润", "net_profit"])
        eq = self._extract_series(df, ["equity", "所有者权益（或股东权益）合计", "股东权益", "total_equity"])
        ta = self._extract_series(df, ["assets", "total_assets", "资产总计"])
        safe_ta = ta.replace(0.0, np.nan)

        # 动态折现有限性与估值乘数: alpha_1 = omega / (1 + r_q - omega)
        discount_gap = (1.0 + self.r_q) - omega_series
        alpha_multiplier = omega_series / discount_gap.clip(lower=self.MIN_CONVERGENCE_MARGIN)

        # 标准化异常盈余密度: x^a / TotalAssets
        xa_density = (ni - self.r_q * eq) / safe_ta
        xa_density = xa_density.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-0.5, 0.5)

        # Ohlson 价值超额溢价得分: alpha_1 * (x^a / Assets) + omega_eb 持续性奖励
        factor_score = alpha_multiplier * xa_density + 0.5 * omega_series
        return factor_score.replace([np.inf, -np.inf], np.nan).fillna(0.0)


# 注册入 FactorRegistry
FactorRegistry.register(
    name=OhlsonValuationFactor.name,
    compute_func=OhlsonValuationFactor().compute,
    category=OhlsonValuationFactor.category,
    default_weight=OhlsonValuationFactor.default_weight,
    description=OhlsonValuationFactor.description,
)
