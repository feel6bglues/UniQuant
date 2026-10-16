"""
Unit tests for FuturesStorageManager and basis surface lake
"""

import pandas as pd
import pytest

from uniquant.data.lake.futures_storage_manager import (
    FuturesContract,
    FuturesStorageManager,
    calculate_third_friday,
)


def test_calculate_third_friday():
    # 2024-03: 3rd Friday is 15th
    assert calculate_third_friday(2024, 3) == pd.Timestamp("2024-03-15")
    # 2024-06: 3rd Friday is 21st
    assert calculate_third_friday(2024, 6) == pd.Timestamp("2024-06-21")
    # 2024-09: 3rd Friday is 20th
    assert calculate_third_friday(2024, 9) == pd.Timestamp("2024-09-20")
    # 2024-12: 3rd Friday is 20th
    assert calculate_third_friday(2024, 12) == pd.Timestamp("2024-12-20")


def test_futures_contract_dataclass():
    c = FuturesContract(
        symbol="IM2406.CFX",
        underlying="000852.SH",
        multiplier=200.0,
        margin_ratio=0.15,
        expiry_date=pd.Timestamp("2024-06-21"),
        tick_size=0.2,
    )
    assert c.clean_symbol == "IM2406"
    assert c.variety == "IM"
    assert c.delivery_month == "2406"


def test_get_contract():
    mgr = FuturesStorageManager()

    # Quarterly contracts
    c_im = mgr.get_contract("IM2406")
    assert c_im is not None
    assert c_im.underlying == "000852.SH"
    assert c_im.multiplier == 200.0
    assert c_im.margin_ratio == 0.15
    assert c_im.expiry_date == pd.Timestamp("2024-06-21")

    c_if = mgr.get_contract("IF2503")
    assert c_if is not None
    assert c_if.underlying == "000300.SH"
    assert c_if.multiplier == 300.0

    # Continuous contracts
    c_cont = mgr.get_contract("IM0")
    assert c_cont is not None
    assert c_cont.underlying == "000852.SH"
    assert c_cont.multiplier == 200.0


@pytest.mark.requires_futures_lake
def test_contract_chain_and_dominant():
    mgr = FuturesStorageManager()
    dt = pd.Timestamp("2024-03-15")

    # Contract chain for CSI 1000
    chain = mgr.get_contract_chain("000852.SH", dt)
    assert len(chain) >= 2
    symbols = [c.clean_symbol for c in chain]
    assert "IM2403" in symbols
    assert "IM2406" in symbols

    # Dominant contract
    dom = mgr.get_dominant_contract("000852.SH", dt)
    assert dom in symbols


@pytest.mark.requires_futures_lake
def test_dynamic_basis_surface():
    mgr = FuturesStorageManager()
    dt = pd.Timestamp("2024-03-15")

    surface = mgr.get_dynamic_basis_surface("000852.SH", dt)
    assert surface["underlying"] == "000852.SH"
    assert surface["spot_close"] > 0
    assert len(surface["contracts"]) >= 2
    assert "dominant_symbol" in surface
    assert "term_slope" in surface

    for c in surface["contracts"]:
        assert c["dte"] >= 0
        assert "basis" in c
        assert "annualized_carry" in c
        assert c["futures_settle"] > 0


@pytest.mark.requires_futures_lake
def test_mlsi_hedge_ratio():
    mgr = FuturesStorageManager()
    dt = pd.Timestamp("2024-03-15")

    beta_star, weights = mgr.compute_mlsi_hedge_ratio("000852.SH", 1.0, dt)
    assert 0.70 <= beta_star <= 1.20
    assert len(weights) > 0
    assert pytest.approx(sum(weights.values())) == 1.0


@pytest.mark.requires_futures_lake
def test_im0_parquet_lake_integrity():
    """验证 IM0 数据湖完备性 (解决 IM 完全空白缺陷 + 结算价非零 + 2017-2026 全覆盖)"""
    mgr = FuturesStorageManager()
    df = mgr.read_futures_daily("IM0")
    assert not df.empty
    assert len(df) >= 2350
    assert df["date"].min() <= pd.Timestamp("2017-01-20")
    assert df["date"].max() >= pd.Timestamp("2026-09-20")
    # 杜绝 0.0 settle 占位符
    assert (df["settle"] > 0).all()
    # 验证拼接点 (2022-07-22) 连续无断档
    splice_sub = df[(df["date"] >= "2022-07-20") & (df["date"] <= "2022-07-25")]
    assert len(splice_sub) >= 4


@pytest.mark.requires_futures_lake
def test_quarterly_contracts_replenished():
    """验证 2025Q2 至 2026Q3 的 6 个季度合约全部就绪且 settle 具备真实数据"""
    mgr = FuturesStorageManager()
    new_quarterly = ["2506", "2509", "2512", "2603", "2606", "2609"]
    for v in ["IF", "IC", "IM"]:
        for q in new_quarterly:
            sym = f"{v}{q}"
            df = mgr.read_futures_daily(sym)
            assert not df.empty, f"Missing contract {sym}"
            assert len(df) >= 150, f"Contract {sym} has only {len(df)} rows"
            assert (df["settle"] > 0).all(), f"Contract {sym} has zero settle"
