"""共享符号判定 — 指数/ETF 识别 (2026-08-18 P0 数据净化)。

旧实现用裸 code 前缀 ("000"/"399") 剔指数, 会误杀 SZ 主板股票
(000001.SZ 平安银行等 414 只)。统一改为符号级判定:
- SH 板 000xxx = 上证指数
- SZ 板 399xxx = 深证指数
- SZ 主板 000xxx.SZ 等普通股票不误杀

与 scripts/wyckoff_full_scan.py 的 `_is_index` 语义一致。
"""
from __future__ import annotations

import pandas as pd


def is_index_symbol(symbol) -> bool:
    """符号级指数判定。

    "000001.SH" -> True (上证指数)
    "399001.SZ" -> True (深证成指)
    "000001.SZ" -> False (平安银行, SZ 主板股票)
    "600000.SH" -> False
    """
    if symbol is None or pd.isna(symbol):
        return False
    symbol = str(symbol)
    code, sep, exch = symbol.partition(".")
    if not sep or not code.isdigit() or len(code) != 6:
        return False
    return (exch == "SH" and code.startswith("000")) or (
        exch == "SZ" and code.startswith("399")
    )


def is_index_series(series) -> "pd.Series[bool]":
    """向量版: 对 symbol Series 返回每行是否指数。"""

    def _f(s):
        return is_index_symbol(str(s)) if s is not None and pd.notna(s) else False

    return series.map(_f)


def drop_index_rows(df) -> "pd.DataFrame":
    """从扫描 CSV DataFrame 剔除指数行 (净化池本已剔除, 此处防御)。"""

    mask = df["symbol"].map(
        lambda s: is_index_symbol(str(s)) if pd.notna(s) else False
    )
    return df[~mask]
