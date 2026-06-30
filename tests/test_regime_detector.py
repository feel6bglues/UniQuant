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

    def test_detect_normal_market(self, detector, sample_market_data):
        """正常市场数据应返回非UNKNOWN的合法结果"""
        result = detector.detect(sample_market_data)
        assert result in (Regime.NORMAL, Regime.STRESSED, Regime.FROZEN)

    def test_detect_none_input(self, detector):
        """None输入应返回UNKNOWN"""
        result = detector.detect(None)
        assert result == Regime.UNKNOWN

    def test_detect_empty_dataframe(self, detector):
        """空DataFrame应返回UNKNOWN（防止fail-open）"""
        empty_df = pd.DataFrame()
        result = detector.detect(empty_df)
        assert result == Regime.UNKNOWN

    def test_detect_missing_close_column(self, detector):
        """缺少close列应返回UNKNOWN"""
        df = pd.DataFrame({"open": [1.0, 2.0], "volume": [100, 200]})
        result = detector.detect(df)
        assert result == Regime.UNKNOWN

    def test_detect_all_nan_close(self, detector):
        """close列全为NaN应返回UNKNOWN（防止fail-open）"""
        df = pd.DataFrame({
            "close": [np.nan, np.nan, np.nan],
            "volume": [100, 200, 300],
        })
        result = detector.detect(df)
        assert result == Regime.UNKNOWN

    def test_detect_short_data_causes_nan_entropy(self, detector):
        """数据点不足60天导致entropy为NaN时应返回UNKNOWN（防止fail-open）"""
        np.random.seed(42)
        n = 45
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        prices = [3000.0]
        for i in range(1, n):
            prices.append(prices[-1] * (1 + np.random.uniform(-0.02, 0.02)))
        df = pd.DataFrame({
            "close": prices,
            "volume": [1e9] * n,
        }, index=dates)
        result = detector.detect(df)
        assert result == Regime.UNKNOWN


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
