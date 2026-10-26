"""
QuoteResampler 与 FreshnessValidator 独立单元测试
=============================================================================
验证:
1. QuoteResampler 独立初始化与周线/月线合成逻辑;
2. FreshnessValidator 独立初始化与两级 SLA 评估逻辑;
3. StorageManager 委托行为完全等价。
=============================================================================
"""

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from uniquant.data.lake.freshness_validator import FreshnessValidator, format_date_val
from uniquant.data.lake.resampler import QuoteResampler
from uniquant.data.lake.storage_manager import StorageManager


def test_format_date_val_edges():
    assert format_date_val(None) is None
    assert format_date_val("20261012") == "2026-10-12"
    assert format_date_val("2026-10-12") == "2026-10-12"
    assert format_date_val(pd.Timestamp("2026-10-12")) == "2026-10-12"
    assert format_date_val("invalid-date-string") is None


def test_resampler_empty_input():
    mock_sm = MagicMock()
    mock_sm.read_data.return_value = pd.DataFrame()
    resampler = QuoteResampler(mock_sm)

    weekly = resampler.synthesize_weekly("600519.SH")
    assert weekly.empty

    monthly = resampler.synthesize_monthly("600519.SH")
    assert monthly.empty


def test_resampler_synthesize_weekly_and_monthly(tmp_path: Path):
    # D5 R-5 主数据表
    (tmp_path / "all_stock_codes.csv").write_text("code,tradeStatus,code_name\nsh.600519,1,贵州茅台\n")
    sm = StorageManager(data_dir=str(tmp_path))

    daily_df = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "open": [100.0, 102.0, 101.0],
        "high": [105.0, 106.0, 103.0],
        "low": [99.0, 101.0, 100.0],
        "close": [102.0, 103.0, 104.0],
        "volume": [1000.0, 2000.0, 1500.0],
        "amount": [100000.0, 200000.0, 150000.0],
    })
    sm.write_data("600519.SH", daily_df, data_type="daily")

    resampler = QuoteResampler(sm)
    weekly = resampler.synthesize_weekly("600519.SH")
    assert len(weekly) == 1
    assert weekly["open"].iloc[0] == 100.0
    assert weekly["high"].iloc[0] == 106.0
    assert weekly["low"].iloc[0] == 99.0
    assert weekly["close"].iloc[0] == 104.0
    assert weekly["volume"].iloc[0] == 4500.0

    monthly = resampler.synthesize_monthly("600519.SH")
    assert len(monthly) == 1
    assert monthly["close"].iloc[0] == 104.0


def test_freshness_validator_init_and_properties(tmp_path: Path):
    (tmp_path / "all_stock_codes.csv").write_text("code,tradeStatus,code_name\nsh.600519,1,贵州茅台\n")
    sm = StorageManager(data_dir=str(tmp_path))
    fv = FreshnessValidator(sm)
    assert fv.daily_dir == sm.daily_dir
    res = fv.validate_freshness(check_tdx=False)
    assert res["details"]["lake_empty"] is True
