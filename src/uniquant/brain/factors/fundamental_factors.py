# src/uniquant/brain/factors/fundamental_factors.py
"""
UniQuant Brain Fundamental Factors Module
==========================================
基本面价值与质量因子族 (P11 & P14)

包含:
- _fundamental_ratio: 基本面比值通用助手
- compute_ep_ttm: EP 盈利收益率 (EPS_TTM / 收盘价)
- compute_bp: BP 账面市值比 (BPS / 收盘价)
- compute_cfp_ttm: CFP 现金流收益率 (OCF_PS_TTM / 收盘价)
- compute_sp_ttm: SP 销售收益率 (Revenue_TTM / 市值)
- compute_gross_profitability: 毛利盈利能力 ((Rev_TTM - Cost_TTM) / 总资产)
- compute_accruals: 应计因子 ((净利润_TTM - OCF_TTM) / 总资产)
- compute_cash_ratio: 现金含量因子 (OCF_TTM / 净利润_TTM, 净利>0)
- compute_fcf_yield: FCF 自由现金流收益率 ((OCF_TTM - CAPEX_TTM) / 市值)
- compute_real_dy: 真实股息率因子 (年度每股现金分红 / 收盘价)
"""

import numpy as np
import pandas as pd

from .registry import FactorRegistry


def _fundamental_ratio(
    df: pd.DataFrame,
    numer_cols: list[str],
    denom_col: str,
    require_positive_denom: bool = True,
) -> pd.Series:
    """基本面比值通用助手: 分子线性组合 ÷ 分母, 缺列/除零返回 NaN。"""
    missing = [c for c in (*numer_cols, denom_col) if c not in df.columns]
    if missing:
        return pd.Series(index=df.index, dtype=float)
    numer = df[numer_cols[0]].astype(float)
    for col in numer_cols[1:]:
        numer = numer - df[col].astype(float)  # 仅支持两列相减 (rev-cost 形态)
    denom = df[denom_col].astype(float).replace(0, np.nan)
    if require_positive_denom:
        denom = denom.where(denom > 0)
    return numer / denom


def compute_ep_ttm(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    EP 因子: 盈利收益率 = EPS_TTM / 收盘价

    金融学假设:
    - Fama-French (1992/1993): 高 E/P 股票未来收益更高 (价值溢价)
    - 行为解释: 投资者对成长股过度外推, 对低估值股票系统性低估
    - 相比 PE 倒数形式的优势: 亏损股 (EPS<0) 自然得到负 EP 排序靠后,
      无需剔除或截断
    - IC 预期: 正值 (高 EP → 高未来收益)
    """
    return _fundamental_ratio(df, ["eps_ttm"], "close", require_positive_denom=False)


def compute_bp(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    BP 因子: 账面市值比 = BPS / 收盘价

    金融学假设:
    - Fama-French HML 的直接代理; 高 B/P = 市场对其净资产定价低
    - 风险解释: 高 B/P 公司多处于财务困境, 要求风险补偿
    - IC 预期: 正值 (高 BP → 高未来收益)
    """
    return _fundamental_ratio(df, ["bps"], "close", require_positive_denom=False)


def compute_cfp_ttm(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    CFP 因子: 现金流收益率 = OCF_PS_TTM / 收盘价

    金融学假设:
    - Lakonishok, Shleifer & Vishny (1994): 现金流 yield 优于盈利 yield —
      现金流更难被盈余管理操纵
    - 与 EP 组合可分离"应计虚增"与"真实现金创造"
    - IC 预期: 正值 (高 CFP → 高未来收益)
    """
    return _fundamental_ratio(df, ["ocf_ps_ttm"], "close", require_positive_denom=False)


def compute_sp_ttm(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    SP 因子: 销售收益率 = Revenue_TTM / (收盘价 × 总股本)

    金融学假设:
    - Barbee, Mukherji & Raines (1996): S/P 在美国市场预测力优于 B/P
    - 营收比利润更难操纵, 且对周期底部亏损股仍有定义
    - IC 预期: 正值 (高 SP → 高未来收益)
    """
    if not {"revenue_ttm", "total_shares", "close"} <= set(df.columns):
        return pd.Series(index=df.index, dtype=float)
    market_cap = (
        df["close"].astype(float) * df["total_shares"].astype(float).where(
            lambda x: x > 0
        )
    ).replace(0, np.nan)
    return df["revenue_ttm"].astype(float) / market_cap


def compute_gross_profitability(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    毛利盈利能力因子 = (Revenue_TTM − Operating_Cost_TTM) / 总资产

    金融学假设:
    - Novy-Marx (2013): 毛利/资产是盈利质量最纯净的度量 — 毛利在利润表
      上游, 远离应计操纵; G/P 高的公司每单位资产创造更多经济租金
    - ⚠️ 对立假设 (预注册登记): 本项目 P5 实测 roe@fwd63 IC=-0.0780、
      P6 实测 roe 在 trend_on|vol_low +0.029 vs vol_high −0.129 翻转 →
      A 股该窗口"质量溢价"整体存疑, GP 可能整体无效甚至负向
    - IC 预期: 正值; 若整体 ≤0 则按对立假设记录, 不改判
    """
    return _fundamental_ratio(df, ["revenue_ttm", "operating_cost_ttm"], "total_assets")


def compute_accruals(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    应计因子 = (归母净利_TTM − OCF_TTM) / 总资产

    金融学假设:
    - Sloan (1996): 应计异象 — 利润中现金含量低 (高应计) 的公司,
      未来收益系统性更低 (应计不可持续 + 盈余管理信号)
    - A 股盈余管理普遍, 该效应可能更强
    - IC 预期: 负值 (高应计 → 低未来收益)
    """
    if not {"net_profit_parent_ttm", "ocf_ttm", "total_assets"} <= set(df.columns):
        return pd.Series(index=df.index, dtype=float)
    assets = df["total_assets"].astype(float).replace(0, np.nan).where(lambda x: x > 0)
    return (
        df["net_profit_parent_ttm"].astype(float) - df["ocf_ttm"].astype(float)
    ) / assets


# ─── P14 现金流价值裁决因子族 (2026-08-28) ──────────────────────────────
# 外部研究 (docs/workbuddy/互联网金工量化_全链路汇总报告_2026-08-28.md) 主张:
#   现金含量 OCF/NP 为全A 最强基本面因子 (IR 1.650)、FCF_Yield 0.648、
#   真实 DY 0.315; 但其结论未过动量残差门 → 本案用五门框架裁决。
# 数据: ocf_ttm/capex_ttm 由 bridge 双口径 TTM 提供; dividend 由
#   scripts/factor_mining/fetch_dividend_data.py 拉取 (data/lake/dividend)。
# 缺列全 NaN (先例安全, 沿用 P11 惯例)。


def compute_cash_ratio(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    现金含量因子 = OCF_TTM / 归母净利_TTM

    外部主张 (待裁决):
    - 外部研究: 全A IR +1.650, 三口径 (龙头/HS300/全A) 全场景为正, "最被低估信号"
    - 金融学: 盈利质量 — 利润中现金流含量高者, 盈余管理少、盈利可持续
    - 对立假设 (本项目 P11 规律): 该比值可能只是动量/反转 beta,
      控 mom20 后残差 IC 或翻负 → 双向裁决, 不预设通过
    - IC 预期: 正值 (高现金含量 → 高未来收益)
    - ⚠️ 选择性披露: require_positive_denom=True (净利>0 才定义) →
      亏损股整批排除, 截面覆盖需披露 (红队 R3)
    """
    return _fundamental_ratio(
        df, ["ocf_ttm"], "net_profit_parent_ttm", require_positive_denom=True
    )


def compute_fcf_yield(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    FCF 收益率因子 = (OCF_TTM − CAPEX_TTM) / 市值

    外部主张 (待裁决):
    - 外部研究: FCF_Yield 全A IR +0.648; 但正交化 (控 EP/DY) 后残差 IR −0.285
      → 外部自认"价值因子换皮"; 本案进一步控动量裁决
    - 金融学: 自由现金流 yield 是质量/价值的复合度量 (Damodaran)
    - 对立假设: 与 P11 cfp_ttm (OCF_PS/close) 仅差 CAPEX 项 → 冗余预检先行
      (T5: 截面 spearman>0.9 则宣告非独立增量)
    - IC 预期: 正值 (高 FCF yield → 高未来收益)
    """
    if not {"ocf_ttm", "capex_ttm", "total_shares", "close"} <= set(df.columns):
        return pd.Series(index=df.index, dtype=float)
    mcap = (
        df["close"].astype(float) * df["total_shares"].astype(float).where(
            lambda x: x > 0
        )
    ).replace(0, np.nan)
    fcf = df["ocf_ttm"].astype(float) - df["capex_ttm"].astype(float).fillna(0)
    return fcf / mcap


def compute_real_dy(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    真实股息率因子 = 年度每股现金分红 / 收盘价

    外部主张 (待裁决):
    - 外部研究: 真实 DY 全A 年频夏普 0.312 (vs 近似 DY 0.398 = EP 代理幻觉);
      "全A 必须用真实 DY"
    - 金融学: 股息率价值信号 (Gordon); 真实分红不可伪造
    - 数据: data/lake/dividend/{code}.parquet 拉取的年度 dps 合计,
      由脚本侧合并为 dividend_yoy 列并入日线主表 (见 run_cash_fcf_dy_test.py)
    - 对立假设: 高 DY 股=低成长/成熟大盘, 可能只是市值/动量 beta
    - IC 预期: 正值 (高真实 DY → 高未来收益)
    """
    if "dividend_dps_ttm" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    close = df["close"].astype(float).replace(0, np.nan)
    return df["dividend_dps_ttm"].astype(float) / close


def register_fundamental_factors() -> None:
    """注册基本面价值与质量因子族到 FactorRegistry"""
    FactorRegistry.register(
        name="ep_ttm",
        compute_func=compute_ep_ttm,
        category="fundamental",
        default_weight=1.0,
        description="EP盈利收益率 | eps_ttm/close, 做多深度价值 (Fama-French)",
    )
    FactorRegistry.register(
        name="bp",
        compute_func=compute_bp,
        category="fundamental",
        default_weight=1.0,
        description="BP账面市值比 | bps/close, HML代理 (Fama-French 1993)",
    )
    FactorRegistry.register(
        name="cfp_ttm",
        compute_func=compute_cfp_ttm,
        category="fundamental",
        default_weight=1.0,
        description="CFP现金流收益率 | ocf_ps_ttm/close, 抗盈余管理 (LSV 1994)",
    )
    FactorRegistry.register(
        name="sp_ttm",
        compute_func=compute_sp_ttm,
        category="fundamental",
        default_weight=1.0,
        description="SP销售收益率 | revenue_ttm/市值, 营收yield (Barbee 1996)",
    )
    FactorRegistry.register(
        name="gross_profitability",
        compute_func=compute_gross_profitability,
        category="fundamental",
        default_weight=1.0,
        description="毛利盈利能力 | (rev_ttm-cost_ttm)/总资产 (Novy-Marx 2013; 对立假设已登记)",
    )
    FactorRegistry.register(
        name="accruals",
        compute_func=compute_accruals,
        category="fundamental",
        default_weight=1.0,
        description="应计异象 | (归母净利_ttm-ocf_ttm)/总资产, 做多低应计 (Sloan 1996)",
    )
    FactorRegistry.register(
        name="cash_ratio",
        compute_func=compute_cash_ratio,
        category="fundamental",
        default_weight=1.0,
        description="现金含量 | ocf_ttm/归母净利_ttm(净利>0), 外部IR1.65候选待裁决",
    )
    FactorRegistry.register(
        name="fcf_yield",
        compute_func=compute_fcf_yield,
        category="fundamental",
        default_weight=1.0,
        description="FCF收益率 | (ocf_ttm-capex_ttm)/市值, 外部候选待裁决 (冗余预检T5)",
    )
    FactorRegistry.register(
        name="real_dy",
        compute_func=compute_real_dy,
        category="fundamental",
        default_weight=1.0,
        description="真实股息率 | 年度每股分红/close (data/lake/dividend), 外部候选待裁决",
    )


__all__ = [
    "_fundamental_ratio",
    "compute_ep_ttm",
    "compute_bp",
    "compute_cfp_ttm",
    "compute_sp_ttm",
    "compute_gross_profitability",
    "compute_accruals",
    "compute_cash_ratio",
    "compute_fcf_yield",
    "compute_real_dy",
    "register_fundamental_factors",
]
