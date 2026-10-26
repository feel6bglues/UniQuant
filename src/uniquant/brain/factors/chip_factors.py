# src/uniquant/brain/factors/chip_factors.py
"""
UniQuant Brain Chip Structure Factors Module
==============================================
P12 筹码结构因子族 (2026-08-26)

包含:
- _chip_passthrough: 筹码衍生列数值转换与缺失守卫
- compute_holder_num_chg_1q: 股东户数变化因子 (ln(股东人数) 季度环比变化率)
- compute_inst_shares_chg_1q: 机构持股变化因子 (机构持股总量季度环比变化率)
- compute_top10_float_chg_1q: 大股东持股变化因子 (十大流通股东合计持股季度环比变化率)
"""

import pandas as pd

from .registry import FactorRegistry


def _chip_passthrough(df: pd.DataFrame, col: str) -> pd.Series:
    """筹码衍生列数值转换与缺失守卫"""
    if col not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def compute_holder_num_chg_1q(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    股东户数变化因子: ln(股东人数) 季度环比变化率 (季报快照 PIT)

    金融学假设:
    - 户数增加 = 筹码分散 = 散户接盘 → 未来收益低 (Dhar & Zhu 2006 散户偏好;
      A 股筹码集中度实证主流方向)
    - IC 预期: 负值 (户数增 → 看跌)
    """
    return _chip_passthrough(df, "holder_num_chg_1q")


def compute_inst_shares_chg_1q(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    机构持股变化因子: 机构持股总量季度环比变化率

    金融学假设:
    - 机构净增持 = 知情交易者流入 → 未来收益高 (Nofsinger & Sias 1999;
      A 股机构增减持信号效应)
    - ⚠️ 口径: 总量含被动指数成分, 且生效走保守披露偏移路径
    - IC 预期: 正值 (机构增持 → 看涨)
    """
    return _chip_passthrough(df, "inst_shares_chg_1q")


def compute_top10_float_chg_1q(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    大股东持股变化因子: 十大流通股东合计持股季度环比变化率

    金融学假设:
    - 大股东/重要股东增持 = 内部人信号 → 未来收益高
    - IC 预期: 正值 (十大流通增持 → 看涨)
    """
    return _chip_passthrough(df, "top10_float_chg_1q")


def register_chip_factors() -> None:
    """注册筹码结构因子族到 FactorRegistry"""
    FactorRegistry.register(
        name="holder_num_chg_1q",
        compute_func=compute_holder_num_chg_1q,
        category="fundamental",
        default_weight=1.0,
        description="股东户数变化 | q-o-q变化率, 户数增=散户化看跌",
    )
    FactorRegistry.register(
        name="inst_shares_chg_1q",
        compute_func=compute_inst_shares_chg_1q,
        category="fundamental",
        default_weight=1.0,
        description="机构持股变化 | 机构持股总量q-o-q变化率, 净增持看涨",
    )
    FactorRegistry.register(
        name="top10_float_chg_1q",
        compute_func=compute_top10_float_chg_1q,
        category="fundamental",
        default_weight=1.0,
        description="十大流通股东变化 | 合计持股q-o-q变化率, 大股东信号",
    )


__all__ = [
    "_chip_passthrough",
    "compute_holder_num_chg_1q",
    "compute_inst_shares_chg_1q",
    "compute_top10_float_chg_1q",
    "register_chip_factors",
]
