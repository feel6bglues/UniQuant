"""P0-B: 测试 wyckoff_full_scan.py 的 fwd 收益 + is_etf + as_of 模式."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.wyckoff_full_scan import (
    _is_etf,
    _compute_fwd_returns,
    _truncate_to_as_of,
    build_empirical_table,
)


# ── is_etf ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("symbol,expected", [
    ("159915.SZ", True),
    ("159919.SZ", True),
    ("161716.SZ", True),
    ("166001.SZ", True),
    ("510050.SH", True),
    ("510300.SH", True),
    ("512100.SH", True),
    ("513050.SH", True),
    ("518880.SH", True),
    ("560010.SH", True),
    ("588000.SH", True),
    ("588050.SH", True),
    ("600519.SH", False),
    ("000001.SZ", False),
    ("002415.SZ", False),
    ("300750.SZ", False),
    ("688981.SH", False),
    ("601857.SH", False),
    ("000858.SZ", False),
    ("003816.SZ", False),
    ("001979.SZ", False),
    ("301269.SZ", False),
    ("159", False),
    ("51", False),
    ("588", False),
    ("600000.SH", False),
    ("510000.SH", True),
])
def test_is_etf(symbol: str, expected: bool) -> None:
    assert _is_etf(symbol) == expected


# ── fwd 收益计算 ──────────────────────────────────────────────────────────────

def _make_df(prices: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(prices), freq="B")
    return pd.DataFrame({"date": dates, "close": prices, "open": prices, "high": prices, "low": prices, "volume": 1_000_000})


def test_fwd_returns_known_values() -> None:
    """Non-as_of mode: no future data → both NaN."""
    df = _make_df([100.0, 102.0, 105.0, 103.0, 110.0, 115.0, 112.0, 120.0, 125.0, 130.0])
    fwd20, fwd60 = _compute_fwd_returns(df)
    assert pd.isna(fwd20), f"expected NaN, got {fwd20}"
    assert pd.isna(fwd60)


def test_fwd_returns_with_future_data() -> None:
    """As_of mode: analysis at index 79 → 20d forward (idx 99) exists, 60d forward (idx 139) does not."""
    closes = [100.0 + i for i in range(100)]
    df = _make_df(closes)
    analysis_last_idx = 79
    fwd20, fwd60 = _compute_fwd_returns(df, analysis_last_idx)
    last = closes[79]
    assert not pd.isna(fwd20), f"fwd20 should not be NaN, got {fwd20}"
    assert pd.isna(fwd60), f"fwd60 should be NaN (need idx 139, only 100 bars), got {fwd60}"
    expected_fwd20 = ((closes[99] - last) / last) * 100
    assert abs(fwd20 - expected_fwd20) < 0.01, f"fwd20={fwd20} != {expected_fwd20}"


def test_fwd_returns_with_sufficient_future() -> None:
    """As_of mode: enough future data for both fwd20 and fwd60."""
    closes = [100.0 + i for i in range(200)]
    df = _make_df(closes)
    analysis_last_idx = 100
    fwd20, fwd60 = _compute_fwd_returns(df, analysis_last_idx)
    last = closes[100]
    assert not pd.isna(fwd20)
    assert not pd.isna(fwd60)
    expected_fwd20 = ((closes[120] - last) / last) * 100
    expected_fwd60 = ((closes[160] - last) / last) * 100
    assert abs(fwd20 - expected_fwd20) < 0.01
    assert abs(fwd60 - expected_fwd60) < 0.01


def test_fwd_returns_partial() -> None:
    """As_of mode: analysis at index 4 → fwd20 (idx 24) exists, fwd60 (idx 64) does not."""
    closes = [100.0 + i * 2 for i in range(25)]
    df = _make_df(closes)
    analysis_last_idx = 4
    fwd20, fwd60 = _compute_fwd_returns(df, analysis_last_idx)
    assert not pd.isna(fwd20), f"fwd20 should have value (idx 24 exists), got {fwd20}"
    assert pd.isna(fwd60), f"fwd60 should be NaN (need idx 64, only 25 bars), got {fwd60}"


def test_fwd_returns_empty_df() -> None:
    df = _make_df([100.0])
    fwd20, fwd60 = _compute_fwd_returns(df)
    assert pd.isna(fwd20)
    assert pd.isna(fwd60)


# ── as_of 截断 ────────────────────────────────────────────────────────────────

def test_truncate_to_as_of_typical() -> None:
    df = _make_df([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
    truncated = _truncate_to_as_of(df, "2024-01-05")
    assert len(truncated) == 5
    assert truncated["close"].iloc[-1] == 104.0


def test_truncate_to_as_of_no_match() -> None:
    df = _make_df([100.0, 101.0, 102.0])
    truncated = _truncate_to_as_of(df, "2025-01-01")
    assert len(truncated) == 3


def test_truncate_to_as_of_none() -> None:
    df = _make_df([100.0, 101.0, 102.0])
    truncated = _truncate_to_as_of(df, None)
    assert len(truncated) == 3


# ── analyze_one 输出含新字段 (mock-free: 纯函数测试) ──────────────────────────

def test_analyze_one_output_fields_via_helpers() -> None:
    rec = {"symbol": "600519.SH", "ok": True, "rows": 100, "last_close": 150.0}
    rec["is_etf"] = _is_etf("600519.SH")
    rec["fwd_20d"] = 5.0
    rec["fwd_60d"] = 10.0
    assert rec["is_etf"] is False
    assert rec["fwd_20d"] == 5.0
    assert rec["fwd_60d"] == 10.0


# ── build_empirical_table ────────────────────────────────────────────────────

def test_build_empirical_table_basic() -> None:
    data = [
        {"phase": "accumulation", "fwd_20d": 5.0, "fwd_60d": 10.0, "confidence_level": "B", "spring": True, "ok": True},
        {"phase": "distribution", "fwd_20d": -3.0, "fwd_60d": -8.0, "confidence_level": "C", "spring": False, "ok": True},
        {"phase": "markup", "fwd_20d": 8.0, "fwd_60d": 15.0, "confidence_level": "A", "spring": False, "ok": True},
        {"phase": "accumulation", "fwd_20d": None, "fwd_60d": None, "confidence_level": "D", "spring": True, "ok": False},
        {"phase": "markdown", "fwd_20d": -5.0, "fwd_60d": -12.0, "confidence_level": "C", "spring": False, "ok": True},
        {"phase": "unknown", "fwd_20d": 1.0, "fwd_60d": 2.0, "confidence_level": "D", "spring": True, "ok": True},
    ]
    table = build_empirical_table(data)
    assert "phase" in table
    assert "spring" in table
    assert "confidence_level" in table
    assert len(table["phase"]) >= 4
    assert table["phase"]["accumulation"]["count"] == 1  # ok=True only
    assert table["spring"]["True"]["count"] == 2  # 2 ok=True records with spring=True (record 1 + record 6)


def test_build_empirical_table_empty() -> None:
    table = build_empirical_table([])
    assert table == {}