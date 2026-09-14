"""
P14 现金流价值裁决因子测试 — cash_ratio / fcf_yield / real_dy (2026-08-28)

覆盖:
1. financial_bridge capex 映射 + 累计 YTD 口径 TTM (锚点 600519 手工验证)
2. compute_cash_ratio: 净利>0 选择性、缺列 NaN、除零守卫
3. compute_fcf_yield: (ocf_ttm - capex_ttm)/市值
4. compute_real_dy: dividend_dps_ttm/close
5. merge_dividend 365d TTM 语义 (无未来函数)
6. 注册中心可见性 (category=fundamental)

数据口径锚点 (实测 600519 2024-2025 capex 年内单调递增且 Q4=全年 → 累计 YTD):
- capex_ttm@20250930 = 2024Q4 单季 1804345600 + 2025Q1 单季 901104320
  + 2025Q2 单季 694891456 + 2025Q3 单季 686866560 = 4087207936
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.factors.custom_factors import (
    compute_cash_ratio,
    compute_fcf_yield,
    compute_real_dy,
)
from uniquant.brain.factors.financial_bridge import (
    CUMULATIVE_FLOW_FIELDS,
    FIELD_MAPPING_DICT,
    FinancialFactorBridge,
)
from uniquant.brain.factors.registry import FactorRegistry


# ─── 1. bridge capex 映射与口径 ─────────────────────────────────────────

def test_capex_field_mapped():
    assert FIELD_MAPPING_DICT["购建固定资产、无形资产和其他长期资产支付的现金"] == "capex"


def test_capex_in_cumulative_flow_fields():
    # 2026-08-28 实测: 600519/000001/300750/601318/002594 capex 年内单调递增且 Q4=全年
    assert "capex" in CUMULATIVE_FLOW_FIELDS


def test_capex_ttm_annual_is_full_year():
    # 年报 TTM = 全年累计 (无差分)
    bridge = FinancialFactorBridge()
    fin = pd.DataFrame({
        "code": ["600519.SH"] * 8,
        "report_date": pd.to_datetime(
            ["20231231", "20240331", "20240630", "20240930",
             "20241231", "20250331", "20250630", "20250930"],
            format="%Y%m%d"),
        "购建固定资产、无形资产和其他长期资产支付的现金": [
            2.619756e9, 7.960913e8, 1.530992e9, 2.874366e9,
            4.678712e9, 9.011043e8, 1.595996e9, 2.282862e9],
    })
    mapped = bridge.map_fields(fin)
    out = bridge.calculate_field_ttm(mapped, "capex")
    row = out[out["report_date"] == pd.Timestamp("2024-12-31")].iloc[0]
    assert abs(row["capex_ttm"] - 4.678712e9) < 1.0


def test_capex_ttm_quarterly_natural_four():
    # TTM@2025Q3 = 2024Q4单季 + 2025Q1单季 + 2025Q2单季 + 2025Q3单季
    # 单季 = 当年累计差分: 2024Q4=4678711808-2874366208=1804345600,
    #   2025Q1=901104320, 2025Q2=1595995776-901104320=694891456,
    #   2025Q3=2282862336-1595995776=686866560
    # expect = 1804345600+901104320+694891456+686866560 = 4087207936
    bridge = FinancialFactorBridge()
    fin = pd.DataFrame({
        "code": ["600519.SH"] * 8,
        "report_date": pd.to_datetime(
            ["20231231", "20240331", "20240630", "20240930",
             "20241231", "20250331", "20250630", "20250930"],
            format="%Y%m%d"),
        "购建固定资产、无形资产和其他长期资产支付的现金": [
            2619756000.0, 796091328.0, 1530991616.0, 2874366208.0,
            4678711808.0, 901104320.0, 1595995776.0, 2282862336.0],
    })
    mapped = bridge.map_fields(fin)
    out = bridge.calculate_field_ttm(mapped, "capex")
    row = out[out["report_date"] == pd.Timestamp("2025-09-30")].iloc[0]
    expect = 1804345600 + 901104320 + 694891456 + 686866560
    assert abs(row["capex_ttm"] - expect) < 1.0


# ─── 2. cash_ratio ──────────────────────────────────────────────────────

def _panel(ocf=100.0, np_=50.0, capex=20.0, close=10.0, dps=0.5):
    n = 5
    df = pd.DataFrame({
        "code": ["000001.SZ"] * n,
        "date": pd.date_range("2026-01-01", periods=n, freq="D"),
        "ocf_ttm": [ocf] * n,
        "net_profit_parent_ttm": [np_] * n,
        "capex_ttm": [capex] * n,
        "total_shares": [100.0] * n,
        "close": [close] * n,
        "dividend_dps_ttm": [dps] * n,
    })
    return df


def test_cash_ratio_positive_np():
    df = _panel(ocf=100.0, np_=50.0)
    out = compute_cash_ratio(df)
    assert np.allclose(out, 100.0 / 50.0)


def test_cash_ratio_negative_np_is_nan():
    # 净利<0 → 排除 (选择性披露: 亏损股整批剔除)
    df = _panel(ocf=100.0, np_=-50.0)
    out = compute_cash_ratio(df)
    assert out.isna().all()


def test_cash_ratio_zero_np_is_nan():
    df = _panel(ocf=100.0, np_=0.0)
    out = compute_cash_ratio(df)
    assert out.isna().all()


def test_cash_ratio_missing_cols_nan():
    df = pd.DataFrame({"code": ["a"], "ocf_ttm": [1.0]})
    out = compute_cash_ratio(df)
    assert out.isna().all()


# ─── 3. fcf_yield ──────────────────────────────────────────────────────

def test_fcf_yield_positive():
    # (100 - 20) / (10*100) = 0.08
    df = _panel(ocf=100.0, capex=20.0, close=10.0)
    out = compute_fcf_yield(df)
    assert np.allclose(out, 0.08)


def test_fcf_yield_capex_missing_fills_zero():
    # capex 全 NaN → 视为 0 (OCF/mcap)
    df = _panel(ocf=100.0, capex=None, close=10.0)
    out = compute_fcf_yield(df)
    assert np.allclose(out, 100.0 / 1000.0)


def test_fcf_yield_missing_mcap_nan():
    df = _panel(ocf=100.0, close=10.0)
    df["total_shares"] = 0.0
    out = compute_fcf_yield(df)
    assert out.isna().all()


# ─── 4. real_dy ─────────────────────────────────────────────────────────

def test_real_dy_positive():
    df = _panel(dps=0.5, close=10.0)
    out = compute_real_dy(df)
    assert np.allclose(out, 0.5 / 10.0)


def test_real_dy_missing_dividend_col_nan():
    df = pd.DataFrame({"code": ["a"], "close": [10.0]})
    out = compute_real_dy(df)
    assert out.isna().all()


def test_real_dy_zero_close_nan():
    df = _panel(dps=0.5, close=0.0)
    out = compute_real_dy(df)
    assert out.isna().all()


# ─── 5. 注册中心可见性 ─────────────────────────────────────────────────

@pytest.mark.parametrize("name,cat", [
    ("cash_ratio", "fundamental"),
    ("fcf_yield", "fundamental"),
    ("real_dy", "fundamental"),
])
def test_registered(name, cat):
    info = FactorRegistry.get_factor(name)
    assert info is not None
    assert info.category == cat


# ─── 6. merge_dividend 365d TTM 语义 ───────────────────────────────────

def test_merge_dividend_365d_ttm(tmp_path, monkeypatch):
    """过去 365 天真实派现合计; 无未来函数 (仅用除权日已发生的派现)。"""
    import sys
    sys.path.insert(0, "scripts/factor_mining")
    import run_t5_redundancy_precheck as t5

    div_dir = tmp_path / "data" / "lake" / "dividend"
    div_dir.mkdir(parents=True)
    # 茅台真实除权序列 (2024-12-20 每股 23.882; 2025-06-26 每股 27.673)
    pd.DataFrame({
        "code": ["600519.SH", "600519.SH"],
        "ex_date": ["20241220", "20250626"],
        "dps": [23.882, 27.673],
    }).to_parquet(div_dir / "600519.SH.parquet", index=False)

    monkeypatch.setattr(t5, "PROJECT_ROOT", tmp_path)
    df = pd.DataFrame({
        "code": ["600519.SH"] * 3,
        "date": pd.to_datetime(["2024-12-21", "2025-06-27", "2025-12-01"]),
    })
    out = t5.merge_dividend(df)
    # 2024-12-21: 仅 2024-12-20 在 365d 内 → 23.882
    assert abs(out.loc[0, "dividend_dps_ttm"] - 23.882) < 1e-6
    # 2025-06-27: 24-12-20 与 25-06-26 都在 365d 内 → 23.882+27.673
    assert abs(out.loc[1, "dividend_dps_ttm"] - (23.882 + 27.673)) < 1e-6
    # 2025-12-01: 距 24-12-20 约 346 天 <365d → 两笔都在 → 23.882+27.673
    assert abs(out.loc[2, "dividend_dps_ttm"] - (23.882 + 27.673)) < 1e-6


def test_merge_dividend_no_future_leak(tmp_path, monkeypatch):
    """除权日当天及之前不可见 (当天起生效, 前一日为 NaN)。"""
    import sys
    sys.path.insert(0, "scripts/factor_mining")
    import run_t5_redundancy_precheck as t5

    div_dir = tmp_path / "data" / "lake" / "dividend"
    div_dir.mkdir(parents=True)
    pd.DataFrame({
        "code": ["000001.SZ"],
        "ex_date": ["20250626"],
        "dps": [1.0],
    }).to_parquet(div_dir / "000001.SZ.parquet", index=False)

    monkeypatch.setattr(t5, "PROJECT_ROOT", tmp_path)
    df = pd.DataFrame({
        "code": ["000001.SZ"] * 3,
        "date": pd.to_datetime(["2025-06-25", "2025-06-26", "2025-06-27"]),
    })
    out = t5.merge_dividend(df)
    # 除权前一日 (06-25): 无派现已发生 → 0 (无分红, real_dy=0 合理)
    assert abs(out.loc[0, "dividend_dps_ttm"] - 0.0) < 1e-9
    # 除权当天 (06-26): 派现已发生 → 1.0 (searchsorted side=right 含当天)
    assert abs(out.loc[1, "dividend_dps_ttm"] - 1.0) < 1e-6
