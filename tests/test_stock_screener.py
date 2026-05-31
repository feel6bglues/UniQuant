"""
测试 StockScreener
"""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.screener import (
    StockScreener,
    ScreenerConfig,
)


class TestStockScreener:
    """StockScreener 测试类"""
    
    @pytest.fixture
    def screener(self):
        return StockScreener()
    
    @pytest.fixture
    def sample_df(self):
        """创建示例数据"""
        np.random.seed(42)
        n_stocks = 100
        
        return pd.DataFrame({
            "date": [pd.Timestamp("2023-12-31")] * n_stocks,
            "code": [f"{i:06d}.SZ" for i in range(n_stocks)],
            "composite_score": np.random.randn(n_stocks),
            "sector": np.random.choice(["金融", "科技", "医药", "消费"], n_stocks),
        })
    
    @pytest.fixture
    def sample_daily_data(self):
        """创建示例日线数据 (完整OHLC)"""
        np.random.seed(42)
        data = {}
        
        for i in range(10):
            code = f"{i:06d}.SZ"
            n_days = 200
            dates = pd.date_range("2023-01-01", periods=n_days)
            
            close_prices = 10 + np.cumsum(np.random.randn(n_days) * 0.1)
            high_prices = close_prices * 1.02
            low_prices = close_prices * 0.98
            open_prices = close_prices * 0.99
            
            data[code] = pd.DataFrame({
                "date": dates,
                "open": open_prices,
                "high": high_prices,
                "low": low_prices,
                "close": close_prices,
            })
        
        return data
    
    def test_generate_top_bottom(self, screener, sample_df):
        """测试 Top/Bottom 榜单生成"""
        top_df, bottom_df = screener.generate_top_bottom(sample_df)
        
        assert len(top_df) == screener.config.top_n
        assert len(bottom_df) == screener.config.bottom_n
        assert "_rank" in top_df.columns
        assert "_rank" in bottom_df.columns
    
    def test_generate_top_bottom_custom_n(self, sample_df):
        """测试自定义数量的 Top/Bottom"""
        config = ScreenerConfig(top_n=20, bottom_n=20)
        screener = StockScreener(config)
        
        top_df, bottom_df = screener.generate_top_bottom(sample_df)
        
        assert len(top_df) == 20
        assert len(bottom_df) == 20
    
    def test_generate_top_bottom_empty(self, screener):
        """测试空数据"""
        top_df, bottom_df = screener.generate_top_bottom(pd.DataFrame())
        
        assert top_df.empty
        assert bottom_df.empty
    
    def test_generate_top_bottom_missing_column(self, screener, sample_df):
        """测试缺少得分列"""
        df = sample_df.drop(columns=["composite_score"])
        
        top_df, bottom_df = screener.generate_top_bottom(df)
        
        assert top_df.empty
        assert bottom_df.empty
    
    def test_generate_tech_signals(self, screener, sample_daily_data):
        """测试技术信号生成"""
        stocks_df = pd.DataFrame({
            "code": list(sample_daily_data.keys())[:5],
            "composite_score": np.random.randn(5),
        })
        
        result = screener.generate_tech_signals(stocks_df, sample_daily_data)
        
        assert "ma_signal" in result.columns
        assert "rsi_state" in result.columns
        assert "macd_signal" in result.columns
        assert "trend" in result.columns
    
    def test_generate_tech_signals_missing_data(self, screener):
        """测试缺少日线数据"""
        stocks_df = pd.DataFrame({
            "code": ["000001.SZ"],
            "composite_score": [0.5],
        })
        
        result = screener.generate_tech_signals(stocks_df, {})
        
        assert "ma_signal" in result.columns
        assert result.iloc[0]["ma_signal"] == "N/A"
    
    def test_generate_tech_signals_type_handling(self, screener):
        """测试技术信号生成的类型处理
        
        验证 Indicators.calc_ma/calc_rsi 返回 Series，
        而 calc_macd 返回 DataFrame，代码能正确处理
        """
        np.random.seed(42)
        n_days = 100
        dates = pd.date_range("2023-01-01", periods=n_days)
        
        close_prices = 10 + np.cumsum(np.random.randn(n_days) * 0.1)
        df = pd.DataFrame({
            "date": dates,
            "open": close_prices * 0.99,
            "high": close_prices * 1.02,
            "low": close_prices * 0.98,
            "close": close_prices,
        })
        
        daily_data = {"000001.SZ": df}
        stocks_df = pd.DataFrame({
            "code": ["000001.SZ"],
            "composite_score": [0.5],
        })
        
        result = screener.generate_tech_signals(stocks_df, daily_data)
        
        assert "ma_signal" in result.columns
        assert "rsi_state" in result.columns
        assert "macd_signal" in result.columns
        assert "trend" in result.columns
        
        assert result.iloc[0]["ma_signal"] != "ERROR"
        assert result.iloc[0]["rsi_state"] != "ERROR"
        assert result.iloc[0]["macd_signal"] != "ERROR"
        assert result.iloc[0]["trend"] != "ERROR"

    def test_generate_tech_signals_ignores_failing_technical_factor(self, screener):
        """测试单个技术因子失败时不会中断整体信号生成"""
        dates = pd.date_range("2023-01-01", periods=100)
        close_prices = np.linspace(10.0, 20.0, 100)
        df = pd.DataFrame({
            "date": dates,
            "open": close_prices * 0.99,
            "high": close_prices * 1.01,
            "low": close_prices * 0.98,
            "close": close_prices,
        })
        daily_data = {"000001.SZ": df}
        stocks_df = pd.DataFrame({
            "code": ["000001.SZ"],
            "composite_score": [0.5],
        })

        from uniquant.brain.factors.registry import FactorRegistry

        failing_factor = SimpleNamespace(
            name="broken_factor",
            category="technical",
            compute_func=lambda _df: (_ for _ in ()).throw(ValueError("boom")),
        )

        original_get_enabled = FactorRegistry.get_enabled
        FactorRegistry.get_enabled = classmethod(lambda cls: [failing_factor])
        try:
            result = screener.generate_tech_signals(stocks_df, daily_data)
        finally:
            FactorRegistry.get_enabled = original_get_enabled

        assert "ma_signal" in result.columns
        assert "broken_factor" not in result.columns
    
    def test_generate_sector_top(self, screener, sample_df):
        """测试分行业 Top"""
        result = screener.generate_sector_top(sample_df)
        
        assert not result.empty
        assert "_sector_rank" in result.columns
        assert result["_sector_rank"].max() <= screener.config.sector_top_n
    
    def test_generate_sector_top_missing_column(self, screener, sample_df):
        """测试缺少行业列"""
        df = sample_df.drop(columns=["sector"])
        
        result = screener.generate_sector_top(df)
        
        assert result.empty
    
    def test_generate_market_risk_summary(self, screener, sample_daily_data):
        """测试市场风险汇总"""
        summary = screener.generate_market_risk_summary(sample_daily_data)
        
        assert "total_stocks" in summary
        assert "valid_stocks" in summary
        assert "avg_annual_return" in summary
        assert "avg_volatility" in summary
        assert "avg_sharpe" in summary
        assert "avg_max_drawdown" in summary
    
    def test_generate_market_risk_summary_empty(self, screener):
        """测试空数据的风险汇总"""
        summary = screener.generate_market_risk_summary({})
        
        assert summary == {}
    
    def test_format_top_table(self, screener, sample_df):
        """测试格式化 Top 表格"""
        top_df, _ = screener.generate_top_bottom(sample_df)
        
        table = screener.format_top_table(top_df)
        
        assert isinstance(table, str)
        assert "Rank" in table or "|" in table
    
    def test_format_top_table_empty(self, screener):
        """测试空数据格式化"""
        table = screener.format_top_table(pd.DataFrame())
        
        assert "No data" in table
    
    def test_format_risk_summary_table(self, screener, sample_daily_data):
        """测试格式化风险汇总表格"""
        summary = screener.generate_market_risk_summary(sample_daily_data)
        
        table = screener.format_risk_summary_table(summary)
        
        assert isinstance(table, str)
        assert "Metric" in table or "|" in table
    
    def test_format_risk_summary_table_empty(self, screener):
        """测试空风险汇总格式化"""
        table = screener.format_risk_summary_table({})
        
        assert "No risk summary" in table


class TestScreenerConfig:
    """ScreenerConfig 测试类"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = ScreenerConfig()
        
        assert config.top_n == 50
        assert config.bottom_n == 50
        assert config.sector_top_n == 3
        assert config.min_data_points == 60
    
    def test_custom_config(self):
        """测试自定义配置"""
        config = ScreenerConfig(
            top_n=30,
            bottom_n=30,
            sector_top_n=5,
            min_data_points=100
        )
        
        assert config.top_n == 30
        assert config.bottom_n == 30
        assert config.sector_top_n == 5
        assert config.min_data_points == 100
