"""Step 0 基线捕获脚本测试 (DATA_SOURCE_MIGRATION_PLAN §5 Step 0.1).

用 tmp_path 合成最小湖 (daily/index/financial/fq + 1 个 index symlink),
验证: 目录计数、symlink 被排除、baseline json 结构完整、量纲指标精确。
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pandas as pd
import pytest

from scripts.maintenance.capture_lake_baseline import (
    collect_stock_pool,
    compute_dimension_stats,
    list_stock_symbols,
    main,
    sample_dimension_stats,
    scan_parquet_dir,
)

DAILY_A_DATES = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"]
DAILY_B_DATES = ["2026-08-01", "2026-08-02", "2026-08-03"]
INDEX_DATES = [f"2026-07-0{d}" for d in range(1, 8)]


def _frame(dates: list[str], code: str) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "open": [10.0] * n,
            "high": [11.0] * n,
            "low": [9.0] * n,
            "close": [10.5] * n,
            "amount": [1000.0 + i for i in range(n)],
            "volume": [100.0 + i for i in range(n)],
            "code": [code] * n,
        }
    )


@pytest.fixture()
def lake(tmp_path: Path) -> Path:
    """最小合成湖: daily 2 普通文件 + 1 symlink, index 1, financial 2, gbbq 1。"""
    daily = tmp_path / "quotes" / "daily"
    index = tmp_path / "quotes" / "index"
    financial = tmp_path / "financial"
    fq = tmp_path / "fq"
    for d in (daily, index, financial, fq):
        d.mkdir(parents=True, exist_ok=True)

    _frame(DAILY_A_DATES, "600519.SH").to_parquet(daily / "600519.SH.parquet")
    _frame(DAILY_B_DATES, "000001.SZ").to_parquet(daily / "000001.SZ.parquet")
    _frame(INDEX_DATES, "000300.SH").to_parquet(index / "000300.SH.parquet")
    # daily 内指数 symlink (与实测 000300.SH/000001.SZ 同型)
    (daily / "000300.SH.parquet").symlink_to(index / "000300.SH.parquet")

    _frame(DAILY_A_DATES, "600519.SH").to_parquet(financial / "600519.SH.parquet")
    _frame(DAILY_B_DATES, "000001.SZ").to_parquet(financial / "000001.SZ.parquet")

    pd.DataFrame(
        {"date": pd.to_datetime(DAILY_A_DATES[:4]), "close": [1.0] * 4}
    ).to_parquet(fq / "gbbq.parquet")
    return tmp_path


def test_scan_parquet_dir_counts_and_dates(lake: Path) -> None:
    daily = scan_parquet_dir(lake / "quotes" / "daily")
    assert daily["file_count"] == 2
    assert daily["total_rows"] == len(DAILY_A_DATES) + len(DAILY_B_DATES)
    assert daily["last_date_min"] == "2026-08-03"
    assert daily["last_date_max"] == "2026-09-05"
    assert len(daily["schema_variants"]) == 1
    assert daily["schema_variants"][0]["file_count"] == 2
    assert "amount" in daily["schema_variants"][0]["columns"]
    assert "volume" in daily["schema_variants"][0]["columns"]

    index = scan_parquet_dir(lake / "quotes" / "index")
    assert index["file_count"] == 1
    assert index["total_rows"] == len(INDEX_DATES)
    assert index["last_date_max"] == "2026-07-07"


def test_symlink_excluded_from_counts_and_stock_pool(lake: Path) -> None:
    daily = scan_parquet_dir(lake / "quotes" / "daily")
    assert daily["symlink_count"] == 1
    assert daily["symlink_files"] == ["000300.SH.parquet"]
    # 5201+index 口径: 普通文件计数不含 symlink
    assert daily["file_count"] + daily["symlink_count"] == 3

    symbols = list_stock_symbols(lake / "quotes" / "daily")
    assert symbols == ["000001.SZ", "600519.SH"]
    assert "000300.SH" not in symbols

    pool = collect_stock_pool(lake / "quotes" / "daily")
    assert pool["count"] == 2
    expected_sha = __import__("hashlib").sha256(
        "\n".join(symbols).encode("utf-8")
    ).hexdigest()
    assert pool["sha256"] == expected_sha
    assert "lightweight" in pool["method"]
    assert "get_symbols" in pool["method"]


def test_main_writes_complete_baseline_json(lake: Path) -> None:
    out = lake / "out" / "lake_baseline.json"
    rc = main(
        [
            "--lake-root",
            str(lake),
            "--output",
            str(out),
            "--gbbq",
            str(lake / "fq" / "gbbq.parquet"),
            "--all-stock-codes",
            str(lake / "all_stock_codes.csv"),
            "--sample-n",
            "3",
            "--seed",
            "42",
        ]
    )

    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    for key in (
        "generated_at",
        "git_head",
        "quotes_daily",
        "quotes_index",
        "financial",
        "fq_gbbq",
        "stock_pool",
        "dimension_stats",
    ):
        assert key in data, key

    assert data["quotes_daily"]["file_count"] == 2
    assert data["quotes_daily"]["symlink_count"] == 1
    assert data["quotes_index"]["file_count"] == 1
    assert data["financial"]["file_count"] == 2
    assert data["fq_gbbq"]["rows"] == 4
    assert data["stock_pool"]["count"] == 2
    assert data["git_head"] is None or len(data["git_head"]) >= 7

    dim = data["dimension_stats"]
    assert dim["seed"] == 42
    assert dim["n_sampled"] == 2
    assert len(dim["sampled_symbols"]) == 2
    for metric in ("amount", "close", "volume"):
        assert set(dim["metrics"][metric]) == {"p25", "median", "p75"}


def test_compute_dimension_stats_exact() -> None:
    df1 = pd.DataFrame(
        {
            "amount": [100.0, 200.0, 300.0, 400.0],
            "close": [10.0, 20.0, 30.0, 40.0],
            "volume": [1000.0, 2000.0, 3000.0, 4000.0],
        }
    )
    df2 = pd.DataFrame({"amount": [float("nan")], "close": [5.0], "volume": [500.0]})

    stats = compute_dimension_stats([df1, df2])

    # amount: NaN 行剔除后 4 样本 → p25=175/median=250/p75=325
    assert stats["amount"] == {"p25": 175.0, "median": 250.0, "p75": 325.0}
    # close/volume: df2 值有效, 5 样本 → [5,10,20,30,40] 线性插值
    assert stats["close"] == {"p25": 10.0, "median": 20.0, "p75": 30.0}
    assert stats["volume"] == {"p25": 1000.0, "median": 2000.0, "p75": 3000.0}


def test_sample_dimension_stats_deterministic(lake: Path) -> None:
    daily = lake / "quotes" / "daily"

    stats1 = sample_dimension_stats(daily, sample_n=1, seed=42)
    stats2 = sample_dimension_stats(daily, sample_n=1, seed=42)

    assert stats1["sampled_symbols"] == stats2["sampled_symbols"]
    expected = random.Random(42).sample(["000001.SZ", "600519.SH"], 1)
    assert stats1["sampled_symbols"] == expected
    assert stats1["n_sampled"] == 1
    assert stats1["metrics"]["close"] == {"p25": 10.5, "median": 10.5, "p75": 10.5}
