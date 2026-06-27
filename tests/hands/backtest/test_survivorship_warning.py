"""Backtest survivorship warning tests"""
import pandas as pd
from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine


def _make_df():
    """Create a simple stock dataframe for testing"""
    dates = pd.bdate_range("2024-01-01", "2024-01-10")
    n = len(dates)
    return pd.DataFrame({
        "date": dates,
        "open": [10.0] * n,
        "high": [11.0] * n,
        "low": [9.0] * n,
        "close": [10.5] * n,
        "volume": [1_000_000] * n,
        "pre_close": [10.0] * n,
        "avg_daily_volume": [1_000_000] * n,
    })


class TestSurvivorshipWarning:
    def test_no_warning_without_delist_data(self):
        """没有退市数据时，metadata 不包含 survivorship_warning"""
        engine = UnifiedBacktestEngine()
        df = _make_df()
        signals = []
        result = engine.run(df, signals, symbol="000001.SZ")
        assert "survivorship_warning" not in result.metadata

    def test_metadata_baseline(self):
        """基本 metadata + 补充字段始终存在"""
        engine = UnifiedBacktestEngine()
        df = _make_df()
        signals = []
        result = engine.run(df, signals, symbol="000001.SZ")
        assert result.metadata["symbol"] == "000001.SZ"
        assert result.metadata["engine"] == "unified"
        assert result.metadata["signal_count"] == 0
        assert "start_date" in result.metadata
        assert "end_date" in result.metadata

    def test_metadata_config_params_present(self):
        """回测配置参数在 metadata 中可追溯"""
        engine = UnifiedBacktestEngine(
            commission_rate=0.0003,
            stamp_duty_rate=0.001,
            slippage_rate=0.002,
            min_commission=5.0,
        )
        df = _make_df()
        result = engine.run(df, [], symbol="000001.SZ")
        assert result.metadata["commission_rate"] == 0.0003
        assert result.metadata["stamp_duty_rate"] == 0.001
        assert result.metadata["slippage_rate"] == 0.002
        assert result.metadata["min_commission"] == 5.0

    def test_metadata_trading_days_count(self):
        """trading_days_count 反映实际交易日数"""
        engine = UnifiedBacktestEngine()
        df = _make_df()
        result = engine.run(df, [], symbol="000001.SZ")
        assert result.metadata["trading_days_count"] == len(df)

    def test_metadata_final_equity(self):
        """final_equity 与 equity_curve 最后一笔一致"""
        engine = UnifiedBacktestEngine()
        df = _make_df()
        result = engine.run(df, [], symbol="000001.SZ")
        assert result.metadata["final_equity"] == result.equity_curve[-1]

    def test_metadata_max_position(self):
        """回测包含买入时 max_position 记录峰值"""
        engine = UnifiedBacktestEngine(initial_capital=100_000)
        df = _make_df()
        from uniquant.shared.interfaces import TradingSignal
        import datetime
        signal = TradingSignal(action="BUY", reason="test", confidence=0.8, shares=100, symbol="000001.SZ", timestamp=datetime.datetime(2024, 1, 2))
        result = engine.run(df, [signal], symbol="000001.SZ")
        assert result.metadata["max_position"] >= 100

    def test_warning_when_delist_within_backtest_period(self):
        """有退市日期且回测覆盖退市日时，metadata 包含 survivorship_warning"""
        import sys
        from unittest.mock import MagicMock, patch

        mock_mgr = MagicMock()
        mock_mgr.get_delist_date.return_value = pd.Timestamp("2024-01-07")

        mock_module = MagicMock()
        mock_module.StockMetadataManager = MagicMock(return_value=mock_mgr)

        with patch.dict(sys.modules, {"uniquant.data.managers.stock_metadata_manager": mock_module}):
            engine = UnifiedBacktestEngine()
            df = _make_df()
            signals = []
            result = engine.run(df, signals, symbol="000001.SZ")

        assert "survivorship_warning" in result.metadata
        assert "delisted" in result.metadata["survivorship_warning"]
        assert "2024-01-07" in result.metadata["survivorship_warning"]
