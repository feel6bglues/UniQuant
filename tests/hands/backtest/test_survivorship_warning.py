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
        """基本 metadata 字段始终存在"""
        engine = UnifiedBacktestEngine()
        df = _make_df()
        signals = []
        result = engine.run(df, signals, symbol="000001.SZ")
        assert result.metadata["symbol"] == "000001.SZ"
        assert result.metadata["engine"] == "unified"
        assert result.metadata["signal_count"] == 0
        assert "start_date" in result.metadata
        assert "end_date" in result.metadata

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
