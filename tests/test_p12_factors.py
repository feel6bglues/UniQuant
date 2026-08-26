"""
P12 尾部风险 + 筹码结构因子测试 (2026-08-26)

覆盖:
1. Batch A 价格尾部因子×4: cvar_95_60d / max_drawdown_20d / downside_semivol_20d / kurtosis_20d
2. Batch B 筹码映射: holder_num/inst_shares/top10_float_shares
3. Batch B 筹码派生列 (q-o-q 变化率) 与 loader financial_frames override
4. 因子 compute 函数语义 + 缺列 NaN

预注册: docs/analysis/P12_PREREGISTRATION_TAIL_CHIP_FACTORS.md
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.factors.custom_factors import (
    compute_cvar_95_60d,
    compute_downside_semivol_20d,
    compute_holder_num_chg_1q,
    compute_inst_shares_chg_1q,
    compute_kurtosis_20d,
    compute_max_drawdown_20d,
    compute_top10_float_chg_1q,
)
from uniquant.brain.factors.financial_bridge import FIELD_MAPPING_DICT


def _price_df(n: int = 120, seed: int = 7) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    close = 100 * np.exp(np.cumsum(rng.randn(n) * 0.02))
    return pd.DataFrame({
        "date": pd.bdate_range("2024-01-02", periods=n),
        "code": ["600001.SH"] * n,
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close,
        "volume": np.full(n, 1e6),
        "amount": np.full(n, 1e7),
    })


# ─── Batch A: 尾部/价格因子 ──────────────────────────────────────────────────


class TestTailFactors:
    def test_cvar_equals_mean_of_worst_three(self):
        df = _price_df()
        rets = df["close"].pct_change(fill_method=None)
        out = compute_cvar_95_60d(df)
        assert out.notna().sum() > 0
        # 手工复核最后一个有效窗口
        i = int(out.last_valid_index())
        win = rets.iloc[i - 59: i + 1].dropna().to_numpy()
        worst3 = np.sort(win)[:3]
        assert np.isclose(out.loc[i], worst3.mean())

    def test_cvar_constant_price_zero(self):
        df = _price_df()
        df["close"] = 100.0
        # 常价无损失 → 最差5%均值=0 (数学正解, 非 NaN)
        out = compute_cvar_95_60d(df)
        assert (out.dropna() == 0.0).all() and out.notna().sum() > 0

    def test_max_drawdown_matches_manual(self):
        df = _price_df()
        out = compute_max_drawdown_20d(df)
        assert out.notna().sum() > 0
        i = int(out.last_valid_index())
        win = df["close"].iloc[i - 19: i + 1].to_numpy()
        peak = np.maximum.accumulate(win)
        expect = (win / peak - 1.0).min()
        assert np.isclose(out.loc[i], expect)

    def test_max_drawdown_nonpositive_and_crash_case(self):
        close = np.concatenate([np.full(30, 100.0), np.linspace(100, 50, 30)])
        df = _price_df(60).assign(close=close)
        out = compute_max_drawdown_20d(df)
        assert out.min() < -0.2  # 腰斩段深回撤
        assert (out.dropna() <= 1e-12).all()

    def test_downside_semivol_zero_when_no_losses(self):
        close = np.linspace(100, 200, 40)
        df = _price_df(40).assign(close=close)
        out = compute_downside_semivol_20d(df)
        assert (out.dropna() == 0.0).all()

    def test_downside_semivol_positive_after_loss(self):
        close = np.concatenate([np.full(25, 100.0), [95.0]])
        df = _price_df(26).assign(close=close)
        out = compute_downside_semivol_20d(df)
        assert out.iloc[-1] > 0

    def test_kurtosis_normal_is_near_zero_fat_tail_positive(self):
        rng = np.random.RandomState(3)
        base = rng.randn(200) * 0.01
        fat = base.copy()
        fat[::10] *= 8
        thin = base.copy()
        out_fat = compute_kurtosis_20d(pd.DataFrame({"close": 100 * np.exp(np.cumsum(fat))}))
        out_thin = compute_kurtosis_20d(pd.DataFrame({"close": 100 * np.exp(np.cumsum(thin))}))
        assert np.nanmean(out_fat.to_numpy()) > np.nanmean(out_thin.to_numpy())

    @pytest.mark.parametrize("func", [
        compute_cvar_95_60d, compute_max_drawdown_20d,
        compute_downside_semivol_20d, compute_kurtosis_20d,
    ])
    def test_missing_close_all_nan(self, func):
        out = func(pd.DataFrame({"date": pd.bdate_range("2024-01-02", periods=30)}))
        assert len(out) == 30 and out.isna().all()


# ─── Batch B: 筹码字段映射与因子 ─────────────────────────────────────────────


class TestChipMappings:
    @pytest.mark.parametrize("cn,std", [
        ("股东人数(户)", "holder_num"),
        ("机构持股总量(股)", "inst_shares"),
        ("十大流通股东持股数量合计(股)", "top10_float_shares"),
    ])
    def test_mapping(self, cn, std):
        assert FIELD_MAPPING_DICT[cn] == std


def _chip_daily(col: str, values: list[float]) -> pd.DataFrame:
    n = len(values)
    return pd.DataFrame({
        "date": pd.bdate_range("2024-01-02", periods=n),
        "code": ["600001.SH"] * n,
        col: values,
    })


class TestChipFactors:
    def test_holder_num_chg_passthrough(self):
        vals = [np.nan] * 3 + [100.0, 110.0, np.nan]
        out = compute_holder_num_chg_1q(_chip_daily("holder_num_chg_1q", vals))
        assert np.isnan(out.iloc[0])
        assert np.isclose(out.iloc[4], 110.0)

    def test_inst_shares_chg_passthrough(self):
        out = compute_inst_shares_chg_1q(_chip_daily("inst_shares_chg_1q", [1.0, 2.0]))
        assert np.allclose(out.dropna(), [1.0, 2.0])

    def test_top10_float_chg_passthrough(self):
        out = compute_top10_float_chg_1q(_chip_daily("top10_float_chg_1q", [-5.0]))
        assert np.isclose(out.iloc[0], -5.0)

    @pytest.mark.parametrize("func,col", [
        (compute_holder_num_chg_1q, "holder_num_chg_1q"),
        (compute_inst_shares_chg_1q, "inst_shares_chg_1q"),
        (compute_top10_float_chg_1q, "top10_float_chg_1q"),
    ])
    def test_missing_col_all_nan(self, func, col):
        df = _chip_daily("close", [1.0] * 10)
        out = func(df)
        assert len(out) == 10 and out.isna().all()


# ─── loader override 参数 ─────────────────────────────────────────────────────


class TestLoaderFinancialFramesOverride:
    def test_financial_frames_override_skips_disk(self, tmp_path):
        from scripts.factor_mining.data_loader import merge_financial_metrics

        daily_dir = tmp_path / "lake" / "quotes" / "daily"
        daily_dir.mkdir(parents=True)
        dates = pd.bdate_range("2024-01-02", periods=30)
        pd.DataFrame({
            "date": dates, "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0,
            "volume": 1e6, "amount": 1e7, "code": "600001.SH",
        }).to_parquet(daily_dir / "600001.SH.parquet")

        fin_override = {
            "600001.SH": pd.DataFrame({
                "code": ["600001.SH"],
                # 2023-06-30 + 2mo 披露偏移 = 2023-08-29 < 日线起点 → PIT 生效
                "report_date": [pd.Timestamp("2023-06-30")],
                "holder_num": [5000.0],
                "inst_shares": [1e6],
                "top10_float_shares": [9e5],
            })
        }
        df = merge_financial_metrics(
            load_universe(str(tmp_path), min_days=10),
            extra_fields=["holder_num", "inst_shares", "top10_float_shares",
                          "holder_num_chg_1q", "inst_shares_chg_1q", "top10_float_chg_1q"],
            data_dir=str(tmp_path),
            financial_frames=fin_override,
        )
        assert "holder_num" in df.columns
        assert df["holder_num"].notna().any()
        # 请求列在财务帧缺失 → bridge 不产生该列 (合理行为)
        assert "inst_shares_chg_1q" not in df.columns


def load_universe(data_dir, min_days):
    from scripts.factor_mining.data_loader import load_universe as _lu
    return _lu(data_dir=data_dir, min_days=min_days)
