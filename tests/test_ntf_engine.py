"""
Unit tests for NTFEngine (National Team Factor Engine)
"""

import pytest
import pandas as pd
import numpy as np

from uniquant.brain.ntf.ntf_engine import NTFEngine


class TestNTFEngine:
    """Test suite for NTFEngine"""

    @pytest.fixture
    def engine(self):
        """Create NTFEngine instance"""
        return NTFEngine()

    @pytest.fixture
    def sample_etf_data(self):
        """Create sample ETF data for testing"""
        np.random.seed(42)
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        
        base_price = 4.0
        prices = [base_price]
        for i in range(1, n):
            change = np.random.uniform(-0.02, 0.02)
            prices.append(prices[-1] * (1 + change))
        
        base_volume = 100000000
        volumes = [base_volume * np.random.uniform(0.5, 1.5) for _ in range(n)]
        volumes[50] = base_volume * 5.0
        
        df = pd.DataFrame({
            "date": dates,
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": volumes,
        })
        return df

    def test_engine_initialization(self, engine):
        """Test engine initializes correctly"""
        assert engine is not None
        assert hasattr(engine, "detect_intervention")
        assert hasattr(engine, "volume_ratio_threshold")

    def test_detect_intervention_with_valid_data(self, engine, sample_etf_data):
        """Test detect_intervention with valid ETF data"""
        result = engine.detect_intervention(sample_etf_data)
        
        assert result is not None
        assert isinstance(result, dict)
        assert "detected" in result
        assert "side" in result

    def test_detect_intervention_with_insufficient_data(self, engine):
        """Test detect_intervention with insufficient data"""
        small_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=10),
            "close": [4.0] * 10,
            "volume": [100000000] * 10,
        })
        
        result = engine.detect_intervention(small_df)
        assert result["detected"] is False

    def test_detect_intervention_with_custom_window(self, engine, sample_etf_data):
        """Test detect_intervention with custom window"""
        result = engine.detect_intervention(sample_etf_data, window=10)
        
        assert result is not None
        assert isinstance(result, dict)

    def test_side_detection(self, engine, sample_etf_data):
        """Test intervention side detection"""
        result = engine.detect_intervention(sample_etf_data)
        
        valid_sides = ["NONE", "SUPPORT", "RESISTANCE", "LIQUIDITY_PULSE"]
        assert result["side"] in valid_sides

    def test_volume_ratio_calculation(self, engine, sample_etf_data):
        """Test volume ratio calculation"""
        result = engine.detect_intervention(sample_etf_data)
        
        if "volume_ratio" in result:
            assert isinstance(result["volume_ratio"], (int, float))
            assert result["volume_ratio"] >= 0


class TestNTFEngineEdgeCases:
    """Edge case tests for NTFEngine"""

    @pytest.fixture
    def engine(self):
        return NTFEngine()

    def test_zero_volume(self, engine):
        """Test with zero volume"""
        n = 50
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n),
            "close": [4.0] * n,
            "volume": [0] * n,
        })
        
        result = engine.detect_intervention(df)
        assert result is not None

    def test_constant_volume(self, engine):
        """Test with constant volume (no spikes)"""
        n = 100
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n),
            "close": [4.0] * n,
            "volume": [100000000] * n,
        })
        
        result = engine.detect_intervention(df)
        assert not result["detected"]

    def test_custom_threshold(self):
        """Test with custom volume ratio threshold"""
        engine = NTFEngine(volume_ratio_threshold=3.0)
        assert engine.volume_ratio_threshold == 3.0
