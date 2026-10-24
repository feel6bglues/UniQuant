"""测试动态复权引擎 (CorporateActionAdjuster) 与数据加载器复权集成。"""

import numpy as np
import pandas as pd
import pytest

from uniquant.data.corporate_action import get_corporate_action_adjuster
from scripts.factor_mining.data_loader import load_universe


@pytest.mark.requires_gbbq
def test_corporate_action_adjuster_initialization():
    adjuster = get_corporate_action_adjuster()
    assert adjuster._is_loaded is True
    assert len(adjuster._events_by_code) > 5000


@pytest.mark.requires_lake
def test_adjust_dataframe_qfq_yunnan_baiyao():
    """验证云南白药 (000538.SZ) 2022-05-05 10送4派16元真实经济收益。"""
    adjuster = get_corporate_action_adjuster()
    df = pd.read_parquet("data/lake/quotes/daily/000538.SZ.parquet")
    df_qfq = adjuster.adjust(df, "000538.SZ", adjust_type="qfq")

    # 提取除权日前一日 (2022-04-29) 与除权日 (2022-05-05)
    d1 = pd.Timestamp("2022-04-29")
    d2 = pd.Timestamp("2022-05-05")
    sub = df_qfq[df_qfq["date"].isin([d1, d2])].sort_values("date")

    assert len(sub) == 2
    p1 = sub["close"].iloc[0]
    p2 = sub["close"].iloc[1]
    ret = (p2 / p1) - 1.0

    # 原始不复权收益约为 -28.16%，真实前复权收益应为 +2.74%
    assert ret > 0.02
    assert ret < 0.03
    assert np.isclose(ret, 0.027372, atol=1e-4)


@pytest.mark.requires_lake
def test_adjust_dataframe_qfq_pingan_bank():
    """验证平安银行 (000001.SZ) 1991 年原始上市价 49 元经全历史除权链复权。"""
    adjuster = get_corporate_action_adjuster()
    df = pd.read_parquet("data/lake/quotes/daily/000001.SZ.parquet")
    df_qfq = adjuster.adjust(df, "000001.SZ", adjust_type="qfq")

    earliest_row = df_qfq.sort_values("date").iloc[0]
    latest_row = df_qfq.sort_values("date").iloc[-1]

    # 原始未复权早期价格为 49 元
    assert np.isclose(df.sort_values("date").iloc[0]["close"], 49.00)
    # 前复权价格应约为 0.147 元 (qfq 以最新收盘为锚, 该值随湖内新纳入分红事件单调下移:
    # 2026-10-24 复核 = 0.1471, 含 gbbq 2026-10-14 resync 的 2025/2026 年度分红)。
    # ⚠️ 维护指令: 每次 sync_gbbq 纳入新年度分红事件后, 必须用本测试实测值重新钉带,
    #             旧带 0.20~0.22 (0.2073, 钉于 2026-10-16 之前) 已随锚点漂移作废。
    assert earliest_row["close"] < 1.0
    assert 0.14 < earliest_row["close"] < 0.16
    assert np.isclose(earliest_row["close"], 0.1471, atol=5e-3)
    # 最新一日前复权价格应等于原始价格
    assert np.isclose(latest_row["close"], df.sort_values("date").iloc[-1]["close"])


@pytest.mark.requires_lake
def test_adjust_dataframe_hfq():
    """验证后复权 (HFQ) 首日因子为 1.0，最新日价格放大。"""
    adjuster = get_corporate_action_adjuster()
    df = pd.read_parquet("data/lake/quotes/daily/000538.SZ.parquet")
    df_hfq = adjuster.adjust(df, "000538.SZ", adjust_type="hfq")

    first_factor = df_hfq.sort_values("date").iloc[0]["adj_factor"]
    last_factor = df_hfq.sort_values("date").iloc[-1]["adj_factor"]

    assert np.isclose(first_factor, 1.0)
    assert last_factor > 15.0  # 云南白药后复权累积倍数超过 15 倍


@pytest.mark.requires_lake
def test_adjust_dataframe_none():
    adjuster = get_corporate_action_adjuster()
    df = pd.read_parquet("data/lake/quotes/daily/000538.SZ.parquet")
    df_none = adjuster.adjust(df, "000538.SZ", adjust_type="none")

    pd.testing.assert_frame_equal(df, df_none)


@pytest.mark.requires_gbbq
def test_stock_with_no_events():
    adjuster = get_corporate_action_adjuster()
    dates = pd.bdate_range("2024-01-02", periods=10)
    dummy_df = pd.DataFrame({
        "date": dates,
        "open": np.full(10, 10.0),
        "high": np.full(10, 10.5),
        "low": np.full(10, 9.5),
        "close": np.full(10, 10.0),
    })
    adjusted = adjuster.adjust(dummy_df, "999999.SZ", adjust_type="qfq")
    assert np.allclose(adjusted["close"], 10.0)
    assert np.allclose(adjusted["adj_factor"], 1.0)


@pytest.mark.requires_lake
def test_load_universe_with_qfq():
    df_raw = load_universe(symbols=["000538.SZ"], min_days=100)
    df_qfq = load_universe(symbols=["000538.SZ"], min_days=100, adjust="qfq")

    assert len(df_raw) == len(df_qfq)
    # 最新交易日价格应当一致
    assert np.isclose(df_raw["close"].iloc[-1], df_qfq["close"].iloc[-1])
    # 历史早期价格 QFQ 应当显著低于原始价格
    assert df_qfq["close"].iloc[0] < df_raw["close"].iloc[0]
