"""TDX 季度财务归档拉取器 — 单元测试。

覆盖: 交易所后缀化 / 公告日期 YYMMDD浮点→YYYYMMDD整数 /
归档帧清洗 (列名strip + 重复列去重) / parquet 写读 round-trip。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "factor_mining"))

from fetch_financial_data import (  # noqa: E402
    convert_announcement_int,
    period_from_filename,
    prepare_archive_frame,
    to_symbol,
)


# ── 交易所后缀化 (与桥接 MARKET_SUFFIX_MAP 同规则) ──────────────────────


@pytest.mark.parametrize(
    "code6,expected",
    [
        ("600519", "600519.SH"),
        ("601318", "601318.SH"),
        ("605111", "605111.SH"),
        ("688981", "688981.SH"),
        ("000001", "000001.SZ"),
        ("001286", "001286.SZ"),
        ("002594", "002594.SZ"),
        ("003816", "003816.SZ"),
        ("300750", "300750.SZ"),
        ("301236", "301236.SZ"),
        ("430047", "430047.BJ"),
        ("833171", "833171.BJ"),
        ("871981", "871981.BJ"),
    ],
)
def test_to_symbol_mapped(code6, expected):
    assert to_symbol(code6) == expected


@pytest.mark.parametrize("code6", ["920001", "400001", "", "123456"])
def test_to_symbol_unmapped_returns_none(code6):
    assert to_symbol(code6) is None


# ── 公告日期转换 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        (250419.0, 20250419),      # YYMMDD 浮点 → YYYYMMDD
        (160421.0, 20160421),
        (20250419.0, 20250419),    # 已是 YYYYMMDD → 直通
        (np.nan, np.nan),          # 缺失 → NaN
        (None, np.nan),
        (0.0, np.nan),             # 非法值 → NaN
        (-5.0, np.nan),
    ],
)
def test_convert_announcement_int(raw, expected):
    out = convert_announcement_int(raw)
    if expected is np.nan or (isinstance(expected, float) and np.isnan(expected)):
        assert np.isnan(out)
    else:
        assert out == expected


# ── 归档期解析 ──────────────────────────────────────────────────────────


def test_period_from_filename():
    assert period_from_filename("gpcw20250331.zip") == 20250331
    assert period_from_filename("gpcw20160331.zip") == 20160331
    with pytest.raises(ValueError):
        period_from_filename("not_a_period.zip")


# ── 归档帧清洗: 列strip + 重复列去重 + 公告日转换 ────────────────────────


def _fake_archive() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "基本每股收益": [0.62, -0.53],
            "净利润": [1.0e10, -2.0e9],
            "经营活动产生的现金流量净额 ": [8.0e10, -1.0e9],   # 尾随空格
            "经营活动产生的现金流量净额": [8.0e10, -1.0e9],     # 同名重复列
            "财报公告日期": [250419.0, 250430.0],
            "业绩预告公告日期 ": [np.nan, 250411.0],
        },
        index=pd.Index(["000001", "000002"], name="code"),
    )
    return df


def test_prepare_archive_frame_strips_and_dedups():
    out = prepare_archive_frame(_fake_archive(), report_date=20250331)
    cols = list(out.columns)
    assert "code" in cols and "report_date" in cols
    # 无尾随空格残留
    assert not any(c != c.strip() for c in cols)
    # 重复列只保留一个
    assert cols.count("经营活动产生的现金流量净额") == 1
    assert "财报公告日期" in cols and "业绩预告公告日期" in cols


def test_prepare_archive_frame_converts_announcement_dates():
    out = prepare_archive_frame(_fake_archive())
    row0 = out[out["code"] == "000001"].iloc[0]
    row1 = out[out["code"] == "000002"].iloc[0]
    assert row0["财报公告日期"] == 20250419
    assert row1["财报公告日期"] == 20250430
    assert np.isnan(row0["业绩预告公告日期"])
    assert row1["业绩预告公告日期"] == 20250411


def test_prepare_archive_frame_adds_report_date():
    out = prepare_archive_frame(_fake_archive(), report_date=20250331)
    assert (out["report_date"] == 20250331).all()


# ── parquet round-trip (注入目录版写函数) ───────────────────────────────


def test_write_symbol_parquet_roundtrip(tmp_path):
    from fetch_financial_data import write_symbol_parquets

    df = pd.DataFrame(
        {
            "code": ["000001.SZ", "000001.SZ"],
            "report_date": [20240331, 20250331],
            "基本每股收益": [0.45, 0.62],
            "归属于母公司所有者的净利润": [1.02e10, 1.41e10],
        }
    )
    stats = write_symbol_parquets(df, output_dir=tmp_path)
    assert stats["n_symbols"] == 1
    f = tmp_path / "000001.SZ.parquet"
    assert f.exists()
    back = pd.read_parquet(f)
    assert list(back["report_date"]) == [20240331, 20250331]  # 升序
    assert back["基本每股收益"].iloc[1] == pytest.approx(0.62)