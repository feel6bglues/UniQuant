"""
测试 FactorAnalyzer 未来函数（Lookahead Bias）防护

核心目标：
1. 验证 _compute_forward_returns 在 "live" 模式下严格禁止负 shift（未来数据泄漏）
2. 验证 "backtest" 模式仍保留正常的 shift(-N) 行为
3. 验证时间戳边界校验：当前最新数据时间不得晚于"此刻"
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.factors.analyzer import FactorAnalyzer


class TestLookaheadBiasPrevention:
    """未来函数防护测试"""

    @pytest.fixture
    def analyzer(self):
        return FactorAnalyzer()

    @pytest.fixture
    def sample_panel_df(self):
        """
        构建横截面面板数据（多股票 × 多日期），
        模拟 compute_ic_ir 的真实输入格式。
        """
        np.random.seed(42)
        n_stocks = 20
        n_dates = 60

        data = []
        for date in pd.date_range("2024-01-01", periods=n_dates, freq="B"):
            for i in range(n_stocks):
                data.append({
                    "date": date,
                    "code": f"{i:06d}.SZ",
                    "close": 10 + np.random.randn() * 2,
                    "momentum": np.random.randn(),
                })

        return pd.DataFrame(data).sort_values(["code", "date"]).reset_index(drop=True)

    # ------------------------------------------------------------------ #
    #  测试 1：live 模式下 _compute_forward_returns 必须抛出异常
    # ------------------------------------------------------------------ #
    def test_live_mode_forbids_negative_shift(self, analyzer):
        """
        在 live 模式下调用 _compute_forward_returns 应抛出 ValueError，
        因为负 shift 会引入未来数据。
        """
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="B"),
            "close": np.linspace(10, 20, 30),
        })

        with pytest.raises(ValueError, match="[Ll]ookahead|[Ll]ive|[Ff]uture|[Nn]egative.*shift"):
            analyzer._compute_forward_returns(
                df, holding_period=5, price_col="close", mode="live"
            )

    # ------------------------------------------------------------------ #
    #  测试 2：backtest 模式下 _compute_forward_returns 正常工作
    # ------------------------------------------------------------------ #
    def test_backtest_mode_allows_negative_shift(self, analyzer):
        """
        backtest 模式应保留 shift(-N) 行为，返回正确长度的未来收益率。
        """
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="B"),
            "close": np.linspace(10, 20, 30),
        })

        fwd_ret = analyzer._compute_forward_returns(
            df, holding_period=5, price_col="close", mode="backtest"
        )

        assert len(fwd_ret) == len(df)
        # 最后 5 行应为 NaN（没有未来数据）
        assert fwd_ret.tail(5).isna().all()
        # 前面的行应有有效值
        assert not fwd_ret.head(20).isna().all()

    # ------------------------------------------------------------------ #
    #  测试 3：默认模式向后兼容（仍为 backtest）
    # ------------------------------------------------------------------ #
    def test_default_mode_is_backtest(self, analyzer):
        """不传 mode 参数时应默认为 backtest，保持向后兼容。"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="B"),
            "close": np.linspace(10, 20, 30),
        })

        # 不应抛出异常
        fwd_ret = analyzer._compute_forward_returns(df, holding_period=5, price_col="close")
        assert len(fwd_ret) == len(df)

    # ------------------------------------------------------------------ #
    #  测试 4：时间戳边界校验 — 数据时间晚于当前时间应告警/拒绝
    # ------------------------------------------------------------------ #
    def test_future_timestamp_rejected_in_live_mode(self, analyzer):
        """
        如果 DataFrame 中包含未来时间戳（晚于当前时间），
        live 模式应拒绝处理。
        """
        future_dates = pd.date_range("2099-01-01", periods=30, freq="B")
        df = pd.DataFrame({
            "date": future_dates,
            "close": np.linspace(10, 20, 30),
        })

        with pytest.raises(ValueError, match="[Ff]uture|[Tt]imestamp|[Ll]ookahead"):
            analyzer._compute_forward_returns(
                df, holding_period=5, price_col="close", mode="live"
            )

    # ------------------------------------------------------------------ #
    #  测试 5：compute_ic_ir 在传入 mode="live" 时传播约束
    # ------------------------------------------------------------------ #
    def test_compute_ic_ir_propagates_live_mode_restriction(self, analyzer, sample_panel_df):
        """
        compute_ic_ir 内部调用 _compute_forward_returns。
        当 mode="live" 时，应抛出 ValueError 而非静默使用未来数据。
        """
        with pytest.raises(ValueError):
            analyzer.compute_ic_ir(
                sample_panel_df,
                factor_cols=["momentum"],
                holding_periods=[1, 5],
                mode="live",
            )

    # ------------------------------------------------------------------ #
    #  测试 6：compute_ic_ir 在 backtest 模式下正常工作（回归测试）
    # ------------------------------------------------------------------ #
    def test_compute_ic_ir_backtest_mode_works(self, analyzer, sample_panel_df):
        """确保 backtest 模式下的 compute_ic_ir 行为不变。"""
        results = analyzer.compute_ic_ir(
            sample_panel_df,
            factor_cols=["momentum"],
            holding_periods=[1, 5],
            mode="backtest",
        )

        assert "momentum" in results
        for period, result in results["momentum"].items():
            assert result.factor_name == "momentum"
            assert isinstance(result.ic_mean, float)

    # ------------------------------------------------------------------ #
    #  测试 7：极端行情 — 全 NaN 价格列
    # ------------------------------------------------------------------ #
    def test_forward_returns_all_nan_prices(self, analyzer):
        """价格列全为 NaN 时，未来收益率应全为 NaN，不抛异常。"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="B"),
            "close": [np.nan] * 30,
        })

        fwd_ret = analyzer._compute_forward_returns(
            df, holding_period=5, price_col="close", mode="backtest"
        )

        assert fwd_ret.isna().all()

    # ------------------------------------------------------------------ #
    #  测试 8：极端行情 — 一字板（价格完全相同）
    # ------------------------------------------------------------------ #
    def test_forward_returns_constant_prices(self, analyzer):
        """价格完全相同时（一字板），未来收益率应全为 0。"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="B"),
            "close": [10.0] * 30,
        })

        fwd_ret = analyzer._compute_forward_returns(
            df, holding_period=5, price_col="close", mode="backtest"
        )

        # 前 25 行应为 0（10/10 - 1 = 0）
        assert (fwd_ret.head(25) == 0.0).all()
        # 最后 5 行应为 NaN
        assert fwd_ret.tail(5).isna().all()
