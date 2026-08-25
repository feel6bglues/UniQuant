"""测试因子挖掘数据加载器 (净化池 + as_of + min_days)。"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.factor_mining.data_loader import (  # noqa: E402
    MIN_DAYS_FOR_WALK_FORWARD,
    _load_one,
    describe_universe,
    load_universe,
)


@pytest.fixture
def data_dir(tmp_path):
    """构造带指数/股票/短历史/ETF 的临时数据湖。"""
    root = tmp_path
    daily = root / "lake" / "quotes" / "daily"
    daily.mkdir(parents=True, exist_ok=True)

    rng = np.random.RandomState(7)

    def _write(symbol, n, start="2020-01-02"):
        dates = pd.bdate_range(start, periods=n)
        closes = 10 + rng.randn(n).cumsum() * 0.3
        df = pd.DataFrame({
            "date": dates,
            "open": closes,
            "high": closes + 0.2,
            "low": closes - 0.2,
            "close": closes,
            "volume": rng.randint(100000, 10000000, n),
            "amount": rng.randint(1000000, 100000000, n),
            "code": symbol,
        })
        df.to_parquet(daily / f"{symbol}.parquet")

    _write("600001.SH", 900)          # 股票, 长历史
    _write("000001.SZ", 900)          # SZ 主板股票 (非指数, 不应误杀)
    _write("000001.SH", 900)          # 上证指数 (应被净化剔除)
    _write("399001.SZ", 900)          # 深证成指 (应被净化剔除)
    _write("300001.SZ", 300)          # 短历史 (应被 min_days 过滤)
    return str(root)


def test_load_universe_excludes_indices(data_dir):
    df = load_universe(data_dir=data_dir, min_days=500, max_workers=4)
    codes = set(df["code"].unique())
    assert "600001.SH" in codes
    assert "000001.SZ" in codes
    assert "000001.SH" not in codes
    assert "399001.SZ" not in codes


def test_load_universe_min_days_filters(data_dir):
    df = load_universe(data_dir=data_dir, min_days=500, max_workers=4)
    assert "300001.SZ" not in set(df["code"].unique())
    assert "600001.SH" in set(df["code"].unique())


def test_load_universe_as_of_truncates(data_dir):
    df = load_universe(
        data_dir=data_dir, min_days=500, max_workers=4, as_of="2023-06-30"
    )
    assert df["date"].max() <= pd.Timestamp("2023-06-30")
    assert df["date"].min() >= pd.Timestamp("2020-01-02")


def test_load_universe_format(data_dir):
    df = load_universe(data_dir=data_dir, min_days=500, max_workers=4)
    assert {"date", "code", "open", "high", "low", "close", "volume", "amount"}.issubset(
        df.columns
    )
    assert df["code"].nunique() == 2
    assert df.groupby("code").size().min() == 900


def test_load_one_reads_single(data_dir):
    storage = None
    from uniquant.data.lake.storage_manager import StorageManager

    storage = StorageManager(data_dir)
    df = _load_one(storage, "600001.SH", None)
    assert df is not None and len(df) == 900


def test_load_one_as_of(data_dir):
    from uniquant.data.lake.storage_manager import StorageManager

    storage = StorageManager(data_dir)
    df = _load_one(storage, "600001.SH", "2023-06-30")
    assert df["date"].max() <= pd.to_datetime("2023-06-30")


def test_describe_universe(data_dir):
    df = load_universe(data_dir=data_dir, min_days=500, max_workers=4)
    info = describe_universe(df)
    assert info["n_symbols"] == 2
    assert info["n_rows"] == 1800


def test_min_days_default_constant():
    assert MIN_DAYS_FOR_WALK_FORWARD >= 577  # 504 train + 63 test + 余量