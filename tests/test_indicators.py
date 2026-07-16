"""
Task-1.5: Indicators 单元测试
验证技术指标计算正确性
"""

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.indicators import Indicators, IndicatorError


class TestIndicatorsValidation:
    """测试输入验证"""

    @pytest.fixture
    def valid_df(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        return pd.DataFrame({
            "date": dates,
            "open": np.linspace(10.0, 15.0, 100),
            "high": np.linspace(10.5, 15.5, 100),
            "low": np.linspace(9.5, 14.5, 100),
            "close": np.linspace(10.0, 15.0, 100),
            "volume": np.random.randint(1000000, 2000000, 100),
        })

    def test_validate_input_none(self):
        """测试None输入"""
        with pytest.raises(IndicatorError):
            Indicators._validate_input(None)

    def test_validate_input_empty(self):
        """测试空数据"""
        empty_df = pd.DataFrame()
        with pytest.raises(IndicatorError):
            Indicators._validate_input(empty_df)

    def test_validate_input_missing_columns(self):
        """测试缺少必要列"""
        invalid_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=10, freq="D"),
            "close": np.linspace(10.0, 15.0, 10),
        })
        with pytest.raises(IndicatorError):
            Indicators._validate_input(invalid_df)

    def test_validate_input_valid(self, valid_df):
        """测试有效输入"""
        result = Indicators._validate_input(valid_df)
        assert result is None


class TestMA:
    """测试移动平均线"""

    @pytest.fixture
    def price_df(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        return pd.DataFrame({
            "date": dates,
            "close": np.linspace(10.0, 15.0, 100),
        })

    def test_calc_ma_basic(self, price_df):
        """测试基本MA计算"""
        ma = Indicators.calc_ma(price_df, window=20)
        
        assert isinstance(ma, pd.Series)
        assert len(ma) == len(price_df)

    def test_calc_ma_values(self, price_df):
        """测试MA值正确性"""
        ma = Indicators.calc_ma(price_df, window=5)
        
        # 验证前几个值（应该有NaN）
        assert pd.isna(ma.iloc[0])
        
        # 验证有效值
        valid_ma = ma.dropna()
        assert len(valid_ma) > 0

    def test_calc_ma_invalid_window(self, price_df):
        """测试无效窗口"""
        with pytest.raises(IndicatorError):
            Indicators.calc_ma(price_df, window=0)
        with pytest.raises(IndicatorError):
            Indicators.calc_ma(price_df, window=-1)


class TestEMA:
    """测试指数移动平均线"""

    @pytest.fixture
    def price_df(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        return pd.DataFrame({
            "date": dates,
            "close": np.linspace(10.0, 15.0, 100),
        })

    def test_calc_ema_basic(self, price_df):
        """测试基本EMA计算"""
        ema = Indicators.calc_ema(price_df, window=20)
        
        assert isinstance(ema, pd.Series)
        assert len(ema) == len(price_df)

    def test_calc_ema_vs_ma(self, price_df):
        """测试EMA与MA差异"""
        ema = Indicators.calc_ema(price_df, window=20)
        ma = Indicators.calc_ma(price_df, window=20)
        
        # EMA应该比MA更快响应价格变化
        # 在上升趋势中，EMA应该高于MA
        assert ema.iloc[-1] >= ma.iloc[-1] * 0.95


class TestATR:
    """测试平均真实波幅"""

    @pytest.fixture
    def ohlc_df(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        base_price = 100.0
        return pd.DataFrame({
            "date": dates,
            "high": base_price + np.random.uniform(0, 5, 100),
            "low": base_price - np.random.uniform(0, 5, 100),
            "close": base_price + np.random.uniform(-2, 2, 100),
        })

    def test_calc_atr_basic(self, ohlc_df):
        """测试基本ATR计算"""
        atr = Indicators.calc_atr(ohlc_df, window=14)
        
        assert isinstance(atr, pd.Series)
        assert len(atr) == len(ohlc_df)

    def test_calc_atr_positive(self, ohlc_df):
        """测试ATR为正值"""
        atr = Indicators.calc_atr(ohlc_df, window=14)
        valid_atr = atr.dropna()
        
        assert all(valid_atr > 0)


class TestBollinger:
    """测试布林带"""

    @pytest.fixture
    def price_df(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        return pd.DataFrame({
            "date": dates,
            "close": 100 + np.random.randn(100) * 5,
        })

    def test_calc_bollinger_basic(self, price_df):
        """测试基本布林带计算"""
        boll = Indicators.calc_bollinger(price_df, window=20, num_std=2.0)
        
        assert isinstance(boll, pd.DataFrame)
        assert "bollinger_middle" in boll.columns
        assert "bollinger_upper" in boll.columns
        assert "bollinger_lower" in boll.columns

    def test_calc_bollinger_bands(self, price_df):
        """测试布林带上下轨关系"""
        boll = Indicators.calc_bollinger(price_df, window=20, num_std=2.0)
        
        valid_data = boll.dropna()
        assert all(valid_data["bollinger_upper"] >= valid_data["bollinger_middle"])
        assert all(valid_data["bollinger_middle"] >= valid_data["bollinger_lower"])


class TestMACD:
    """测试MACD"""

    @pytest.fixture
    def price_df(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        return pd.DataFrame({
            "date": dates,
            "close": 100 + np.cumsum(np.random.randn(100) * 2),
        })

    def test_calc_macd_basic(self, price_df):
        """测试基本MACD计算"""
        macd = Indicators.calc_macd(price_df)
        
        assert isinstance(macd, pd.DataFrame)
        assert "macd" in macd.columns
        assert "signal" in macd.columns
        assert "hist" in macd.columns

    def test_calc_macd_invalid_params(self, price_df):
        """测试无效参数"""
        with pytest.raises(IndicatorError):
            Indicators.calc_macd(price_df, fast=26, slow=12)


class TestRSI:
    """测试RSI"""

    @pytest.fixture
    def price_df(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        return pd.DataFrame({
            "date": dates,
            "close": 100 + np.cumsum(np.random.randn(100) * 2),
        })

    def test_calc_rsi_basic(self, price_df):
        """测试基本RSI计算"""
        rsi = Indicators.calc_rsi(price_df, window=14)
        
        assert isinstance(rsi, pd.Series)
        assert len(rsi) == len(price_df)

    def test_calc_rsi_range(self, price_df):
        """测试RSI范围"""
        rsi = Indicators.calc_rsi(price_df, window=14)
        valid_rsi = rsi.dropna()
        
        assert all(valid_rsi >= 0)
        assert all(valid_rsi <= 100)


class TestMarketEntropy:
    """测试市场熵"""

    @pytest.fixture
    def price_df(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        return pd.DataFrame({
            "date": dates,
            "close": 100 + np.cumsum(np.random.randn(100) * 2),
        })

    def test_calc_entropy_basic(self, price_df):
        """测试基本熵计算"""
        entropy = Indicators.calc_market_entropy(price_df, window=20)
        
        assert isinstance(entropy, pd.Series)
        assert len(entropy) == len(price_df)

    def test_calc_entropy_positive(self, price_df):
        """测试熵值为正"""
        entropy = Indicators.calc_market_entropy(price_df, window=20)
        valid_entropy = entropy.dropna()
        
        assert all(valid_entropy >= 0)


class TestTurnoverZ:
    """测试换手率Z-Score"""

    @pytest.fixture
    def volume_df(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        return pd.DataFrame({
            "date": dates,
            "close": np.linspace(10.0, 15.0, 100),
            "volume": np.random.randint(1000000, 5000000, 100),
        })

    def test_calc_turnover_z_basic(self, volume_df):
        """测试基本换手率Z-Score计算"""
        z_score = Indicators.calc_turnover_z(volume_df, window=20)
        
        assert isinstance(z_score, pd.Series)
        assert len(z_score) == len(volume_df)

    def test_calc_turnover_z_no_volume(self):
        """测试无成交量数据"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=100, freq="D"),
            "close": np.linspace(10.0, 15.0, 100),
        })
        z_score = Indicators.calc_turnover_z(df, window=20)
        
        # 应该返回全0序列
        assert all(z_score == 0.0)


class TestVolRatio:
    """测试成交量比"""

    @pytest.fixture
    def volume_df(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        return pd.DataFrame({
            "date": dates,
            "close": np.linspace(10.0, 15.0, 100),
            "volume": np.random.randint(1000000, 5000000, 100),
        })

    def test_calc_vol_ratio_basic(self, volume_df):
        """测试基本成交量比计算"""
        ratio = Indicators.calc_vol_ratio(volume_df, window=20)
        
        assert isinstance(ratio, pd.Series)
        assert len(ratio) == len(volume_df)

    def test_calc_vol_ratio_positive(self, volume_df):
        """测试成交量比为正"""
        ratio = Indicators.calc_vol_ratio(volume_df, window=20)
        valid_ratio = ratio.dropna()
        
        assert all(valid_ratio > 0)


class TestCalculateAllIndicators:
    """测试计算所有指标"""

    @pytest.fixture
    def full_df(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        return pd.DataFrame({
            "date": dates,
            "open": 100 + np.random.randn(100) * 2,
            "high": 102 + np.random.randn(100) * 2,
            "low": 98 + np.random.randn(100) * 2,
            "close": 100 + np.cumsum(np.random.randn(100) * 2),
            "volume": np.random.randint(1000000, 5000000, 100),
        })

    def test_calculate_all_indicators_basic(self, full_df):
        """测试计算所有指标"""
        result = Indicators.calculate_all_indicators(full_df)
        
        assert isinstance(result, pd.DataFrame)
        assert "rsi" in result.columns
        assert "macd" in result.columns
        assert "macd_signal" in result.columns
        assert "macd_hist" in result.columns
        assert "atr" in result.columns
        assert "ma20" in result.columns
        assert "ma60" in result.columns
        assert "ema20" in result.columns
        assert "bollinger_upper" in result.columns
        assert "bollinger_middle" in result.columns
        assert "bollinger_lower" in result.columns
        assert "market_entropy" in result.columns
        assert "turnover_z" in result.columns
