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

# ─── P11: merge_financial_metrics (2026-08-26) ────────────────────────────────


@pytest.fixture
def data_dir_with_financial(tmp_path):
    """日线 + 财务 parquet 齐备的临时数据湖 (其中一只股票无财务文件)。"""
    root = tmp_path
    daily = root / "lake" / "quotes" / "daily"
    fin = root / "lake" / "financial"
    daily.mkdir(parents=True, exist_ok=True)
    fin.mkdir(parents=True, exist_ok=True)

    dates = pd.bdate_range("2024-01-02", periods=60)
    for sym in ("600001.SH", "000001.SZ"):
        closes = np.full(60, 10.0)
        pd.DataFrame({
            "date": dates, "open": closes, "high": closes + 0.1,
            "low": closes - 0.1, "close": closes,
            "volume": np.full(60, 1e6), "amount": np.full(60, 1e7),
            "code": sym,
        }).to_parquet(daily / f"{sym}.parquet")

    qdates = pd.date_range("2023-03-31", periods=6, freq="QE")
    cum = [1.0, 2.0, 3.0, 4.0, 1.0, 2.0]
    pd.DataFrame({
        "code": ["600001.SH"] * 6,
        "report_date": qdates,
        "基本每股收益": cum,
        "每股净资产": [10.0] * 6,
        "营业收入": [100.0] * 6,
        "其中：营业成本": [60.0] * 6,
        "资产总计": [1000.0] * 6,
        "总股本": [50.0] * 6,
    }).to_parquet(fin / "600001.SH.parquet")
    return str(root)


def test_merge_financial_metrics_merges_and_ttm(data_dir_with_financial):
    from scripts.factor_mining.data_loader import (
        EXTRA_FINANCIAL_FIELDS,
        merge_financial_metrics,
    )

    df = load_universe(data_dir=data_dir_with_financial, min_days=10, max_workers=2)
    out = merge_financial_metrics(
        df, extra_fields=EXTRA_FINANCIAL_FIELDS,
        data_dir=data_dir_with_financial, max_workers=2,
    )
    assert len(out) == len(df)
    has_fin = out[out["code"] == "600001.SH"]
    no_fin = out[out["code"] == "000001.SZ"]
    assert has_fin["eps_ttm"].notna().all()
    # PIT 验证: fixture 公告日无效 → 回退报告期+偏移; 2023Q4 年报
    # effective=2024-04-30 晚于日线尾日(~2024-03-27) 未生效,
    # 故仅前 3 季 cum=[1,2,3] 可见 → 单季全 1 → TTM 尾值=3 (无未来信息泄露)
    assert np.isclose(has_fin["eps_ttm"].iloc[-1], 3.0)
    assert has_fin["revenue_ttm"].notna().all()
    assert np.isclose(has_fin["total_assets"].iloc[-1], 1000.0)
    # 无财务文件的股票保持原列结构, 财务列为 NaN
    assert no_fin["eps_ttm"].isna().all()
    assert set(df.columns) <= set(out.columns)


def test_merge_financial_metrics_no_financial_dir(tmp_path):
    from scripts.factor_mining.data_loader import merge_financial_metrics

    root = tmp_path
    daily = root / "lake" / "quotes" / "daily"
    daily.mkdir(parents=True)
    dates = pd.bdate_range("2024-01-02", periods=30)
    pd.DataFrame({
        "date": dates, "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0,
        "volume": 1e6, "amount": 1e7, "code": "600001.SH",
    }).to_parquet(daily / "600001.SH.parquet")

    df = load_universe(data_dir=str(root), min_days=10)
    out = merge_financial_metrics(df, data_dir=str(root))
    assert len(out) == len(df)
