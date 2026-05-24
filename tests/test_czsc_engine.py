"""
Unit tests for CZSCEngine (Chan Theory Engine)
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch

from uniquant.brain.czsc.czsc_engine import CZSCEngine


class TestCZSCEngine:
    """Test suite for CZSCEngine"""

    @pytest.fixture
    def engine(self):
        """Create CZSCEngine instance"""
        return CZSCEngine()

    @pytest.fixture
    def sample_row(self):
        """Create sample OHLC row for testing"""
        return pd.Series({
            "date": pd.Timestamp("2024-01-01"),
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.2,
            "volume": 1000000,
        })

    def test_engine_initialization(self, engine):
        """Test engine initializes correctly"""
        assert engine is not None
        assert hasattr(engine, "update_and_get_signals")

    def test_update_and_get_signals_with_valid_data(self, engine, sample_row):
        """Test update_and_get_signals with valid row data"""
        result = engine.update_and_get_signals(sample_row)
        
        assert result is not None
        assert isinstance(result, dict)
        assert "is_3rd_buy" in result
        assert "bi_count" in result

    def test_update_and_get_signals_with_invalid_data(self, engine):
        """Test update_and_get_signals with invalid data"""
        invalid_row = pd.Series({
            "date": pd.Timestamp("2024-01-01"),
            "open": -10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.2,
            "volume": 1000000,
        })
        
        result = engine.update_and_get_signals(invalid_row)
        assert "error" in result

    def test_update_and_get_signals_with_missing_columns(self, engine):
        """Test update_and_get_signals with missing required columns"""
        df_missing = pd.Series({
            "date": pd.Timestamp("2024-01-01"),
            "close": 10.0,
        })
        
        result = engine.update_and_get_signals(df_missing)
        assert "error" in result

    def test_update_and_get_signals_with_nan_values(self, engine):
        """Test update_and_get_signals handles NaN values"""
        df_nan = pd.Series({
            "date": pd.Timestamp("2024-01-01"),
            "open": 10.0,
            "high": None,
            "low": 9.5,
            "close": 10.0,
            "volume": 1000000,
        })
        
        result = engine.update_and_get_signals(df_nan)
        assert "error" in result

    def test_validate_input_row_with_valid_data(self, engine, sample_row):
        """Test _validate_input_row with valid data"""
        assert engine._validate_input_row(sample_row) is True

    def test_validate_input_row_with_invalid_prices(self, engine):
        """Test _validate_input_row with invalid price logic"""
        invalid_row = pd.Series({
            "date": pd.Timestamp("2024-01-01"),
            "open": 10.0,
            "high": 9.0,
            "low": 9.5,
            "close": 10.2,
            "volume": 1000000,
        })
        
        assert engine._validate_input_row(invalid_row) is False


class TestCZSCEngineEdgeCases:
    """Edge case tests for CZSCEngine"""

    @pytest.fixture
    def engine(self):
        return CZSCEngine()

    def test_none_input(self, engine):
        """Test with None input"""
        result = engine.update_and_get_signals(None)
        assert "error" in result

    def test_wrong_type_input(self, engine):
        """Test with wrong type input"""
        result = engine.update_and_get_signals("not a series")
        assert "error" in result

    def test_zero_prices(self, engine):
        """Test with zero prices"""
        zero_row = pd.Series({
            "date": pd.Timestamp("2024-01-01"),
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "close": 0.0,
            "volume": 1000000,
        })
        
        result = engine.update_and_get_signals(zero_row)
        assert "error" in result

    def test_negative_volume(self, engine):
        """Test with negative volume"""
        neg_vol_row = pd.Series({
            "date": pd.Timestamp("2024-01-01"),
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.2,
            "volume": -1000000,
        })
        
        result = engine.update_and_get_signals(neg_vol_row)
        assert result is not None

    def test_get_czsc_signals_returns_error_payload_on_runtime_error(self, engine):
        """Recoverable runtime errors should be converted to safe fallback payloads."""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="B"),
            "open": np.linspace(10, 20, 30),
            "high": np.linspace(10.5, 20.5, 30),
            "low": np.linspace(9.5, 19.5, 30),
            "close": np.linspace(10.2, 20.2, 30),
            "volume": np.full(30, 1000.0),
        })

        with patch.object(engine, "_initialize_czsc_analyzer", side_effect=RuntimeError("boom")):
            result = engine.get_czsc_signals(df)

        assert result["is_3rd_buy"] is False
        assert result["bi_count"] == 0
        assert result["geometry_desc"] == "分析失败"

    def test_prepare_bar_list_skips_recoverable_rawbar_errors(self, engine):
        """RawBar construction recoverable errors should only skip the bad row."""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=2, freq="B"),
            "open": [10.0, 11.0],
            "high": [10.5, 11.5],
            "low": [9.5, 10.5],
            "close": [10.2, 11.2],
            "volume": [1000.0, 1000.0],
        })

        original_rawbar = __import__("uniquant.brain.czsc.czsc_engine", fromlist=["RawBar"]).RawBar

        def flaky_rawbar(*args, **kwargs):
            if kwargs["dt"] == df.loc[0, "date"]:
                raise ValueError("bad rawbar")
            return original_rawbar(*args, **kwargs)

        with patch("uniquant.brain.czsc.czsc_engine.RawBar", side_effect=flaky_rawbar):
            bars, skipped = engine._prepare_bar_list(df)

        assert len(bars) == 1
        assert skipped == 1
