"""
Task-1.1: AlphaDecoupler 数据对齐陷阱修复测试
验证停牌复牌场景下收益率计算的正确性
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.alpha_decoupler import AlphaDecoupler


class TestAlphaDecouplerDataAlignment:
    """测试数据对齐修复"""

    @pytest.fixture
    def normal_stock_data(self):
        """正常交易数据"""
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        return pd.DataFrame({
            "date": dates,
            "close": np.linspace(10.0, 12.0, 30),
        })

    @pytest.fixture
    def normal_bench_data(self):
        """正常基准数据"""
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        return pd.DataFrame({
            "date": dates,
            "close": np.linspace(3000.0, 3100.0, 30),
        })

    @pytest.fixture
    def suspended_stock_data(self):
        """停牌复牌数据 - 模拟停牌后复牌产生跨日收益"""
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        close_prices = np.linspace(10.0, 12.0, 30)
        # 模拟停牌5天后复牌，价格跳跃
        close_prices[15] = close_prices[14] * 1.15  # 停牌期间累计涨幅15%
        close_prices[16] = close_prices[15] * 1.01
        close_prices[17] = close_prices[15] * 1.02
        close_prices[18] = close_prices[15] * 1.03
        close_prices[19] = close_prices[15] * 1.04
        return pd.DataFrame({
            "date": dates,
            "close": close_prices,
        })

    @pytest.fixture
    def mismatched_dates_stock(self):
        """日期不匹配的股票数据 - 股票有额外停牌日"""
        dates = pd.date_range("2024-01-01", periods=25, freq="D")
        return pd.DataFrame({
            "date": dates,
            "close": np.linspace(10.0, 12.0, 25),
        })

    def test_calc_rs_slope_normal(self, normal_stock_data, normal_bench_data):
        """测试正常情况下的RS斜率计算"""
        result = AlphaDecoupler.calc_rs_slope(
            normal_stock_data, normal_bench_data, window=10
        )
        assert isinstance(result, float)
        assert not np.isnan(result)

    def test_calc_rs_slope_suspended_stock(self, suspended_stock_data, normal_bench_data):
        """测试停牌复牌场景 - 验证不会产生异常脉冲"""
        result = AlphaDecoupler.calc_rs_slope(
            suspended_stock_data, normal_bench_data, window=10
        )
        assert isinstance(result, float)
        assert not np.isnan(result)
        # 结果应该在合理范围内，不应因停牌跳跃而产生极端值
        assert abs(result) < 100

    def test_calc_benchmark_corr_normal(self, normal_stock_data, normal_bench_data):
        """测试正常情况下的相关性计算"""
        result = AlphaDecoupler.calc_benchmark_corr(
            normal_stock_data, normal_bench_data, window=10
        )
        assert isinstance(result, float)
        assert -1.0 <= result <= 1.0

    def test_calc_benchmark_corr_suspended(self, suspended_stock_data, normal_bench_data):
        """测试停牌复牌场景下的相关性计算"""
        result = AlphaDecoupler.calc_benchmark_corr(
            suspended_stock_data, normal_bench_data, window=10
        )
        assert isinstance(result, float)
        assert -1.0 <= result <= 1.0

    def test_calc_rs_slope_mismatched_dates(self, mismatched_dates_stock, normal_bench_data):
        """测试日期不匹配场景"""
        result = AlphaDecoupler.calc_rs_slope(
            mismatched_dates_stock, normal_bench_data, window=10
        )
        assert isinstance(result, float)
        assert not np.isnan(result)

    def test_get_alpha_score_normal(self, normal_stock_data, normal_bench_data):
        """测试Alpha得分计算"""
        result = AlphaDecoupler.get_alpha_score(
            normal_stock_data, normal_bench_data, None
        )
        assert isinstance(result, float)
        assert not np.isnan(result)

    def test_get_alpha_score_with_sector(self, normal_stock_data, normal_bench_data):
        """测试带行业数据的Alpha得分计算"""
        sector_data = normal_stock_data.copy()
        sector_data["close"] = sector_data["close"] * 100
        result = AlphaDecoupler.get_alpha_score(
            normal_stock_data, normal_bench_data, sector_data
        )
        assert isinstance(result, float)
        assert not np.isnan(result)

    def test_get_alpha_features(self, normal_stock_data, normal_bench_data):
        """测试获取所有Alpha特征"""
        result = AlphaDecoupler.get_alpha_features(
            normal_stock_data, normal_bench_data, window=10
        )
        assert isinstance(result, dict)
        assert "rs_slope" in result
        assert "benchmark_corr" in result
        assert isinstance(result["rs_slope"], float)
        assert isinstance(result["benchmark_corr"], float)

    def test_empty_data_returns_zero(self):
        """测试空数据返回0"""
        empty_df = pd.DataFrame(columns=["date", "close"])
        normal_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=10, freq="D"),
            "close": np.linspace(10.0, 12.0, 10),
        })
        result = AlphaDecoupler.calc_rs_slope(empty_df, normal_df, window=5)
        assert result == 0.0

    def test_insufficient_data_returns_zero(self):
        """测试数据不足返回0"""
        short_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "close": np.linspace(10.0, 12.0, 5),
        })
        normal_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "close": np.linspace(3000.0, 3100.0, 5),
        })
        result = AlphaDecoupler.calc_rs_slope(short_df, normal_df, window=20)
        assert result == 0.0


class TestAlphaDecouplerEdgeCases:
    """边界条件测试"""

    def test_none_input_returns_default(self):
        """测试None输入返回默认值（handle_errors装饰器行为）"""
        normal_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=10, freq="D"),
            "close": np.linspace(10.0, 12.0, 10),
        })
        # handle_errors装饰器捕获异常后返回默认值0.0
        result = AlphaDecoupler.calc_rs_slope(None, normal_df, window=5)
        assert result == 0.0

    def test_missing_columns_returns_default(self):
        """测试缺少必要列返回默认值（handle_errors装饰器行为）"""
        invalid_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=10, freq="D"),
            "price": np.linspace(10.0, 12.0, 10),
        })
        normal_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=10, freq="D"),
            "close": np.linspace(3000.0, 3100.0, 10),
        })
        # handle_errors装饰器捕获异常后返回默认值0.0
        result = AlphaDecoupler.calc_rs_slope(invalid_df, normal_df, window=5)
        assert result == 0.0

    def test_negative_window_returns_default(self):
        """测试负窗口参数返回默认值（handle_errors装饰器行为）"""
        stock_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=10, freq="D"),
            "close": np.linspace(10.0, 12.0, 10),
        })
        bench_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=10, freq="D"),
            "close": np.linspace(3000.0, 3100.0, 10),
        })
        # handle_errors装饰器捕获异常后返回默认值0.0
        result = AlphaDecoupler.calc_rs_slope(stock_df, bench_df, window=-1)
        assert result == 0.0
