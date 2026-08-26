"""
基本面因子实施测试 — P11 价值+质量因子族 (2026-08-26)

覆盖:
1. bridge 新字段映射 (operating_cost / total_shares / free_float_shares)
2. calculate_field_ttm 双口径 TTM (累计 YTD 年边界差分 vs 单季直接滚动)
3. process extra_fields 扩展合并 + 默认行为向后兼容
4. 7 个新因子 compute 函数语义 + 缺列 NaN + 除零守卫
5. 注册中心可见性

数据口径锚点 (预注册冻结, 实测 600519/000001/300750/002594/601318 2024 年报交叉验证):
- 营业收入/营业成本: 单季值 → rolling(4).sum()
- eps/归母净利/OCF/每股OCF: 累计 YTD → 年边界差分 → rolling(4).sum()
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.factors.custom_factors import (
    compute_accruals,
    compute_bp,
    compute_cfp_ttm,
    compute_ep_ttm,
    compute_gross_profitability,
    compute_sp_ttm,
    compute_turnover_20d,
    compute_turnover_momentum_20d,
)
from uniquant.brain.factors.financial_bridge import (
    CUMULATIVE_FLOW_FIELDS,
    FinancialFactorBridge,
    FIELD_MAPPING_DICT,
    SINGLE_QUARTER_FLOW_FIELDS,
)
from uniquant.brain.factors.registry import FactorRegistry


def _fin_df(n_quarters: int = 6, code: str = "000001.SZ") -> pd.DataFrame:
    """构造跨年季度财务数据 (累计口径流量 + 单季口径收入 + 存量)。"""
    dates = pd.date_range("2023-03-31", periods=n_quarters, freq="QE")
    # 累计 YTD 流量: 每季真实单季贡献恒为 1.0
    cum_eps = [1.0 * (i % 4 + 1) for i in range(n_quarters)]
    # 单季收入: 恒为 100
    rev_q = [100.0] * n_quarters
    return pd.DataFrame({
        "code": [code] * n_quarters,
        "report_date": dates,
        "基本每股收益": cum_eps,
        "每股净资产": [10.0] * n_quarters,
        "营业收入": rev_q,
        "其中：营业成本": [60.0] * n_quarters,
        "归属母公司所有者的净利润": [float(v * 2) for v in cum_eps],
        "经营活动产生的现金流量净额": [float(v * 3) for v in cum_eps],
        "每股经营现金流量": [float(v * 0.3) for v in cum_eps],
        "资产总计": [1000.0] * n_quarters,
        "总股本": [50.0] * n_quarters,
        "自由流通股(股)": [30.0] * n_quarters,
        "财报公告日期": [d.timestamp() for d in dates],
    })


def _daily_df(n_days: int = 30, code: str = "000001.SZ") -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n_days),
        "code": [code] * n_days,
        "open": np.full(n_days, 10.0),
        "high": np.full(n_days, 11.0),
        "low": np.full(n_days, 9.0),
        "close": np.full(n_days, 10.0),
        "volume": np.linspace(1e6, 2e6, n_days),
        "amount": np.linspace(1e7, 2e7, n_days),
    })


# ─── 1. 字段映射 ──────────────────────────────────────────────────────────────


class TestBridgeFieldMappings:
    def test_operating_cost_mapped(self):
        assert FIELD_MAPPING_DICT["其中：营业成本"] == "operating_cost"

    def test_total_shares_mapped(self):
        assert FIELD_MAPPING_DICT["总股本"] == "total_shares"

    def test_free_float_shares_mapped(self):
        assert FIELD_MAPPING_DICT["自由流通股(股)"] == "free_float_shares"

    def test_map_fields_renames_new_columns(self):
        bridge = FinancialFactorBridge()
        result = bridge.map_fields(_fin_df())
        for std in ("operating_cost", "total_shares", "free_float_shares"):
            assert std in result.columns


# ─── 2. 双口径 TTM ────────────────────────────────────────────────────────────


class TestCalculateFieldTtm:
    def test_convention_sets_frozen(self):
        assert "revenue" in SINGLE_QUARTER_FLOW_FIELDS
        assert "operating_cost" in SINGLE_QUARTER_FLOW_FIELDS
        assert {"eps", "net_profit_parent", "ocf", "ocf_ps"} <= CUMULATIVE_FLOW_FIELDS
        assert not (SINGLE_QUARTER_FLOW_FIELDS & CUMULATIVE_FLOW_FIELDS)

    def test_single_quarter_field_ttm_is_rolling_sum(self):
        bridge = FinancialFactorBridge()
        mapped = bridge.map_fields(_fin_df())
        out = bridge.calculate_field_ttm(mapped, "revenue")
        assert "revenue_ttm" in out.columns
        # 单季恒 100 → TTM 序列为 [100, 200, 300, 400, 400, 400]
        expect = [100.0, 200.0, 300.0, 400.0, 400.0, 400.0]
        assert np.allclose(out["revenue_ttm"].to_numpy(), expect)

    def test_cumulative_field_ttm_year_boundary_diff(self):
        bridge = FinancialFactorBridge()
        mapped = bridge.map_fields(_fin_df())
        out = bridge.calculate_field_ttm(mapped, "ocf")
        # 累计值 [3,6,9,12,3,6] → 单季 [3,3,3,3,3,3] → TTM [3,6,9,12,12,12]
        # (第 5 行跨年 Q1 重置: 单季 3, 滚动窗 [3,3,3,3]=12)
        expect = [3.0, 6.0, 9.0, 12.0, 12.0, 12.0]
        assert np.allclose(out["ocf_ttm"].to_numpy(), expect)

    def test_ocf_ps_ttm_matches_scale(self):
        bridge = FinancialFactorBridge()
        mapped = bridge.map_fields(_fin_df())
        out = bridge.calculate_field_ttm(mapped, "ocf_ps")
        expect = [0.3, 0.6, 0.9, 1.2, 1.2, 1.2]
        assert np.allclose(out["ocf_ps_ttm"].to_numpy(), expect)

    def test_codes_isolated(self):
        bridge = FinancialFactorBridge()
        df = pd.concat([_fin_df(code="000001.SZ"), _fin_df(code="600519.SH")])
        mapped = bridge.map_fields(df)
        out = bridge.calculate_field_ttm(mapped, "eps")
        # cum_eps=[1,2,3,4,1,2] → 单季 [1,1,1,1,(跨年重置)1,1] → TTM [1,2,3,4,4,4]
        first_block = out[out["code"] == "000001.SZ"]["eps_ttm"]
        assert np.allclose(first_block, [1.0, 2.0, 3.0, 4.0, 4.0, 4.0])

    def test_unknown_field_raises(self):
        bridge = FinancialFactorBridge()
        with pytest.raises(ValueError):
            bridge.calculate_field_ttm(bridge.map_fields(_fin_df()), "not_a_field")

    def test_missing_column_returns_frame_without_target(self):
        bridge = FinancialFactorBridge()
        mapped = bridge.map_fields(_fin_df()).drop(columns=["revenue"])
        out = bridge.calculate_field_ttm(mapped, "revenue")
        assert "revenue_ttm" not in out.columns


# ─── 3. process extra_fields 合并扩展 ────────────────────────────────────────


class TestProcessExtraFields:
    EXTRA = [
        "revenue_ttm", "operating_cost_ttm", "net_profit_parent_ttm",
        "ocf_ttm", "ocf_ps_ttm", "total_assets", "total_shares",
        "free_float_shares",
    ]

    def test_extra_fields_merged_into_daily(self):
        bridge = FinancialFactorBridge()
        out = bridge.process(
            _daily_df(), _fin_df(), price_col="close", extra_fields=self.EXTRA
        )
        for col in self.EXTRA:
            assert col in out.columns, f"missing {col}"
        assert "pe_ttm" in out.columns and "pb" in out.columns
        # 尾日应拿到最新季报的存量值
        assert out["total_assets"].notna().any()
        assert (out["total_assets"].dropna() == 1000.0).all()

    def test_default_process_has_no_extra_columns(self):
        bridge = FinancialFactorBridge()
        out = bridge.process(_daily_df(), _fin_df(), price_col="close")
        for col in self.EXTRA:
            assert col not in out.columns
        assert "pe_ttm" in out.columns

    def test_extra_ttm_value_correctness(self):
        bridge = FinancialFactorBridge()
        out = bridge.process(
            _daily_df(), _fin_df(), price_col="close",
            extra_fields=["revenue_ttm"],
        )
        # 尾日公告为 2023-08 后的第 6 季 → revenue_ttm = 400
        valid = out["revenue_ttm"].dropna()
        assert len(valid) > 0
        assert np.isclose(valid.iloc[-1], 400.0)


# ─── 4. 因子 compute 函数 ─────────────────────────────────────────────────────


def _merged_daily(n_days: int = 30) -> pd.DataFrame:
    """模拟经 bridge.process(extra_fields=...) 后的日线组内帧。"""
    df = _daily_df(n_days)
    df["eps_ttm"] = 2.0
    df["bps"] = 20.0
    df["ocf_ps_ttm"] = 1.0
    df["revenue_ttm"] = 400.0
    df["operating_cost_ttm"] = 160.0
    df["net_profit_parent_ttm"] = 8.0
    df["ocf_ttm"] = 12.0
    df["total_assets"] = 1000.0
    df["total_shares"] = 50.0
    df["free_float_shares"] = 30.0
    return df


class TestValueFactorComputes:
    @pytest.mark.parametrize("func,col,expected", [
        (compute_ep_ttm, ("eps_ttm", "close"), 0.2),
        (compute_bp, ("bps", "close"), 2.0),
        (compute_cfp_ttm, ("ocf_ps_ttm", "close"), 0.1),
    ])
    def test_ratio_semantics(self, func, col, expected):
        out = func(_merged_daily())
        assert isinstance(out, pd.Series)
        assert len(out) == 30
        assert np.allclose(out.dropna(), expected)

    def test_sp_ttm_market_cap_form(self):
        out = compute_sp_ttm(_merged_daily())
        # revenue_ttm / (close * total_shares) = 400/(10*50) = 0.8
        assert np.allclose(out.dropna(), 0.8)

    def test_negative_eps_allowed(self):
        df = _merged_daily()
        df["eps_ttm"] = -2.0
        out = compute_ep_ttm(df)
        assert np.allclose(out.dropna(), -0.2)

    def test_zero_close_guard(self):
        df = _merged_daily()
        df.loc[df.index[-1], "close"] = 0.0
        out = compute_ep_ttm(df)
        assert out.iloc[-1] != out.iloc[-1]  # NaN
        assert out.iloc[:-1].notna().all()

    def test_missing_column_all_nan_same_length(self):
        df = _daily_df()
        out = compute_ep_ttm(df)
        assert len(out) == len(df)
        assert out.isna().all()


class TestQualityFactorComputes:
    def test_gross_profitability(self):
        out = compute_gross_profitability(_merged_daily())
        # (400-160)/1000 = 0.24
        assert np.allclose(out.dropna(), 0.24)

    def test_accruals(self):
        out = compute_accruals(_merged_daily())
        # (8-12)/1000 = -0.004
        assert np.allclose(out.dropna(), -0.004)

    def test_nonpositive_assets_guard(self):
        df = _merged_daily()
        df.loc[df.index[0], "total_assets"] = 0.0
        assert compute_gross_profitability(df).iloc[0] != compute_gross_profitability(df).iloc[0]
        assert compute_accruals(df).iloc[0] != compute_accruals(df).iloc[0]

    def test_missing_columns_nan(self):
        for func in (compute_gross_profitability, compute_accruals):
            out = func(_daily_df())
            assert out.isna().all()


class TestTurnoverFactors:
    def test_turnover_20d_level(self):
        out = compute_turnover_20d(_merged_daily())
        assert out.notna().sum() >= 10
        # volume/free_float ∈ [1e6/30, 2e6/30]
        vals = out.dropna()
        assert (vals > 3e4).all() and (vals < 7e4).all()

    def test_turnover_momentum_fallback_free_float(self):
        df = _merged_daily()
        out = compute_turnover_momentum_20d(df)
        assert out.notna().sum() >= 5  # pct_change(20) 自 index 20 起

    def test_turnover_momentum_still_nan_without_any_source(self):
        df = _merged_daily().drop(columns=["free_float_shares"])
        out = compute_turnover_momentum_20d(df)
        assert out.isna().all()


# ─── 5. 注册中心可见性 ────────────────────────────────────────────────────────


class TestRegistryVisibility:
    NEW_FACTOR_NAMES = [
        "ep_ttm", "bp", "cfp_ttm", "sp_ttm",
        "gross_profitability", "accruals", "turnover_20d",
    ]

    def test_new_factors_registered(self):
        for name in self.NEW_FACTOR_NAMES:
            assert FactorRegistry.has(name), f"{name} 未注册"

    def test_new_factors_compute_via_registry(self):
        info = FactorRegistry.get_factor("ep_ttm")
        assert info is not None
        out = info.compute_func(_merged_daily())
        assert np.allclose(out.dropna(), 0.2)
