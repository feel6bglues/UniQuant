"""
Unit tests for RegimeDetector (Market Regime Detection)
"""

import pytest
import pandas as pd
import numpy as np

from uniquant.brain.regime.regime_detector import RegimeDetector, Regime


class TestRegimeDetector:
    """Test suite for RegimeDetector"""

    @pytest.fixture
    def detector(self):
        """Create RegimeDetector instance"""
        return RegimeDetector()

    @pytest.fixture
    def sample_market_data(self):
        """Create sample market data for testing"""
        np.random.seed(42)
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        
        base_price = 3000.0
        prices = [base_price]
        for i in range(1, n):
            change = np.random.uniform(-0.02, 0.02)
            prices.append(prices[-1] * (1 + change))
        
        base_volume = 1000000000
        volumes = [base_volume * np.random.uniform(0.5, 1.5) for _ in range(n)]
        
        df = pd.DataFrame({
            "date": dates,
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": volumes,
        })
        return df

    def test_detector_initialization(self, detector):
        """Test detector initializes correctly"""
        assert detector is not None
        assert hasattr(detector, "entropy_threshold")
        assert hasattr(detector, "turnover_z_limit")

    def test_detector_with_custom_params(self):
        """Test detector with custom parameters"""
        detector = RegimeDetector(
            entropy_threshold=0.5,
            turnover_z_limit=2.0,
            min_data_points=50,
        )
        assert detector.entropy_threshold == 0.5
        assert detector.turnover_z_limit == 2.0

    def test_invalid_entropy_threshold(self):
        """Test invalid entropy threshold raises error"""
        with pytest.raises(ValueError):
            RegimeDetector(entropy_threshold=1.5)

    def test_invalid_turnover_z_limit(self):
        """Test invalid turnover z limit raises error"""
        with pytest.raises(ValueError):
            RegimeDetector(turnover_z_limit=-1.0)

    def test_invalid_min_data_points(self):
        """Test invalid min data points raises error"""
        with pytest.raises(ValueError):
            RegimeDetector(min_data_points=5)


class TestRegimeEnum:
    """Test suite for Regime enum"""

    def test_regime_values(self):
        """Test Regime enum values"""
        assert Regime.NORMAL.value == "NORMAL"
        assert Regime.STRESSED.value == "STRESSED"
        assert Regime.FROZEN.value == "FROZEN"
        assert Regime.UNKNOWN.value == "UNKNOWN"

    def test_regime_count(self):
        """Test Regime enum has expected count"""
        assert len(Regime) == 4
