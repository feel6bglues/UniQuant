"""
Unit tests for scripts/maintenance/sync_local_tdx_day.py
"""

import struct
from pathlib import Path
import pandas as pd

from scripts.maintenance.sync_local_tdx_day import (
    get_price_divisor,
    symbol_from_day_filename,
    parse_incremental_day_file,
    sync_single_file,
    DAY_STRUCT_FMT,
)


def test_get_price_divisor():
    assert get_price_divisor("600519") == 100.0
    assert get_price_divisor("000001") == 100.0
    assert get_price_divisor("300750") == 100.0
    assert get_price_divisor("688981") == 100.0
    assert get_price_divisor("113050") == 10000.0
    assert get_price_divisor("128012") == 10000.0
    assert get_price_divisor("510300") == 1000.0
    assert get_price_divisor("159919") == 1000.0
    assert get_price_divisor("900901") == 1000.0


def test_symbol_from_day_filename():
    code, market, symbol = symbol_from_day_filename(Path("/path/to/sh600519.day"))
    assert code == "600519"
    assert market == "SH"
    assert symbol == "600519.SH"

    code, market, symbol = symbol_from_day_filename(Path("/path/to/sz000001.day"))
    assert code == "000001"
    assert market == "SZ"
    assert symbol == "000001.SZ"

    code, market, symbol = symbol_from_day_filename(Path("sh000300.day"))
    assert code == "000300"
    assert market == "SH"
    assert symbol == "000300.SH"


def test_parse_incremental_day_file_synthetic(tmp_path):
    # Pack synthetic binary .day file
    # <IIIIIfII: date, open, high, low, close, amount, volume, reserved
    day_file = tmp_path / "sh600000.day"
    records = [
        (20260723, 1000, 1050, 990, 1020, 1000000.0, 10000, 0),
        (20260724, 1020, 1080, 1010, 1070, 1500000.0, 15000, 0),
        (20260725, 1070, 1100, 1060, 1090, 1200000.0, 12000, 0),
    ]
    with open(day_file, "wb") as f:
        for r in records:
            f.write(struct.pack(DAY_STRUCT_FMT, *r))

    # All records
    parsed_all = parse_incremental_day_file(day_file, last_date_int=0)
    assert len(parsed_all) == 3
    assert parsed_all[0]["close"] == 10.20
    assert parsed_all[1]["close"] == 10.70
    assert parsed_all[2]["close"] == 10.90

    # Incremental records > 20260723
    parsed_inc = parse_incremental_day_file(day_file, last_date_int=20260723)
    assert len(parsed_inc) == 2
    assert parsed_inc[0]["date"] == pd.Timestamp("2026-07-24")
    assert parsed_inc[1]["date"] == pd.Timestamp("2026-07-25")


def test_sync_single_file_e2e(tmp_path):
    data_dir = tmp_path / "data"
    vipdoc = tmp_path / "vipdoc"
    sh_lday = vipdoc / "sh" / "lday"
    sh_lday.mkdir(parents=True)

    day_file = sh_lday / "sh600000.day"
    records = [
        (20260723, 1000, 1050, 990, 1020, 1000000.0, 10000, 0),
        (20260724, 1020, 1080, 1010, 1070, 1500000.0, 15000, 0),
    ]
    with open(day_file, "wb") as f:
        for r in records:
            f.write(struct.pack(DAY_STRUCT_FMT, *r))

    res1 = sync_single_file((day_file, data_dir, False))
    assert res1["status"] == "created_new"
    assert res1["new_bars"] == 2

    # Check parquet created
    target_parquet = data_dir / "lake" / "quotes" / "daily" / "600000.SH.parquet"
    assert target_parquet.exists()
    df1 = pd.read_parquet(target_parquet)
    assert len(df1) == 2

    # Run again without changes -> up_to_date
    res2 = sync_single_file((day_file, data_dir, False))
    assert res2["status"] == "up_to_date"
    assert res2["new_bars"] == 0

    # Append new record to day_file
    with open(day_file, "ab") as f:
        f.write(struct.pack(DAY_STRUCT_FMT, 20260725, 1070, 1100, 1060, 1090, 1200000.0, 12000, 0))

    res3 = sync_single_file((day_file, data_dir, False))
    assert res3["status"] == "updated"
    assert res3["new_bars"] == 1
    assert res3["total_bars"] == 3

    df3 = pd.read_parquet(target_parquet)
    assert len(df3) == 3
    assert df3["date"].max() == pd.Timestamp("2026-07-25")
