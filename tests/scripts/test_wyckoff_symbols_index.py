"""P0 数据净化 (2026-08-18): 共享符号级指数判定 _symbols.is_index_symbol.

防止下游统计脚本 (direction_map_check/confidence_survival/buyset_*) 用裸
code 前缀 ("000"/"399") 剔指数而误杀 SZ 主板股票 (000001.SZ 等 414 只).
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.wyckoff_experiments._symbols import (
    drop_index_rows,
    is_index_series,
    is_index_symbol,
)


@pytest.mark.parametrize("symbol,expected", [
    ("000001.SH", True),
    ("000300.SH", True),
    ("000905.SH", True),
    ("999999.SH", False),
    ("399001.SZ", True),
    ("399006.SZ", True),
    ("399101.SZ", True),
    ("600519.SH", False),
    ("000001.SZ", False),
    ("000858.SZ", False),
    ("002415.SZ", False),
    ("300750.SZ", False),
    ("688981.SH", False),
    ("510050.SH", False),
    ("159915.SZ", False),
    ("000001", False),
    ("", False),
    (None, False),
])
def test_is_index_symbol(symbol, expected: bool) -> None:
    assert is_index_symbol(symbol) == expected


def test_is_index_series_does_not_kill_sz_main_board() -> None:
    s = pd.Series(["000001.SH", "000001.SZ", "399001.SZ", "600000.SH", "000002.SZ"])
    out = is_index_series(s)
    assert list(out) == [True, False, True, False, False]


def test_drop_index_rows_keeps_sz_main_board() -> None:
    df = pd.DataFrame({
        "symbol": ["000001.SH", "000001.SZ", "399001.SZ", "000002.SZ"],
        "p": [1, 2, 3, 4],
    })
    out = drop_index_rows(df)
    assert set(out["symbol"]) == {"000001.SZ", "000002.SZ"}