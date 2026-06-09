"""
Tests for analysis engines: CzscAnalysisEngine and FsmAnalysisEngine
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock


@pytest.fixture
def sample_ohlc_df():
    """Create sample OHLC DataFrame for testing"""
    dates = pd.date_range(start="2024-01-01", periods=100, freq="D")
    np.random.seed(42)
    
    base_price = 10.0
    returns = np.random.randn(100) * 0.02
    prices = base_price * (1 + returns).cumprod()
    
    df = pd.DataFrame({
        "date": dates,
        "open": prices * (1 + np.random.randn(100) * 0.01),
        "high": prices * (1 + np.abs(np.random.randn(100)) * 0.02),
        "low": prices * (1 - np.abs(np.random.randn(100)) * 0.02),
        "close": prices,
        "volume": np.random.randint(100000, 1000000, 100),
    })
    
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    
    return df


@pytest.fixture
def mock_orchestrator(sample_ohlc_df):
    """Create mock orchestrator (AnalysisService)"""
    orchestrator = Mock()
    
    orchestrator._generate_cache_key = Mock(return_value="test_cache_key")
    orchestrator._get_cached_result = Mock(return_value=None)
    orchestrator._set_cached_result = Mock(return_value=True)
    orchestrator._optimize_dataframe = Mock(return_value=sample_ohlc_df)
    orchestrator._sample_data = Mock(return_value=sample_ohlc_df)
    orchestrator.ensure_precision_consistency = Mock(side_effect=lambda x: x)
    
    mock_lake = Mock()
    mock_lake.read_data = Mock(return_value=sample_ohlc_df)
    
    mock_data_service = Mock()
    mock_data_service.lake = mock_lake
    orchestrator.data_service = mock_data_service
    
    orchestrator.evt_risk = None
    orchestrator.sizer = None
    orchestrator.brain = None
    
    return orchestrator


class TestCzscAnalysisEngine:
    """Test suite for CzscAnalysisEngine"""

    def test_init(self, mock_orchestrator):
        """Test engine initialization"""
        from uniquant.services.analysis.czsc_analysis_engine import CzscAnalysisEngine
        
        engine = CzscAnalysisEngine(mock_orchestrator)
        assert engine.orchestrator is mock_orchestrator

    def test_run_czsc_analysis_with_df(self, mock_orchestrator, sample_ohlc_df):
        """Test CZSC analysis with provided DataFrame"""
        from uniquant.services.analysis.czsc_analysis_engine import CzscAnalysisEngine
        
        engine = CzscAnalysisEngine(mock_orchestrator)
        result = engine.run_czsc_analysis("000001.SZ", df=sample_ohlc_df)
        
        assert result is not None
        assert "status" in result
        assert result["symbol"] == "000001.SZ"

    def test_run_czsc_analysis_empty_df(self, mock_orchestrator):
        """Test CZSC analysis with empty DataFrame"""
        from uniquant.services.analysis.czsc_analysis_engine import CzscAnalysisEngine
        
        engine = CzscAnalysisEngine(mock_orchestrator)
        
        empty_df = pd.DataFrame()
        result = engine.run_czsc_analysis("000001.SZ", df=empty_df)
        
        assert result["status"] in ["failed", "success"]

    def test_run_czsc_analysis_none_df_reads_from_lake(self, mock_orchestrator, sample_ohlc_df):
        """Test CZSC analysis reads from data lake when df is None"""
        from uniquant.services.analysis.czsc_analysis_engine import CzscAnalysisEngine
        
        engine = CzscAnalysisEngine(mock_orchestrator)
        result = engine.run_czsc_analysis("000001.SZ", df=None)
        
        mock_orchestrator.data_service.lake.read_data.assert_called_once()
        assert result is not None

    def test_fallback_czsc_analysis(self, mock_orchestrator, sample_ohlc_df):
        """Test fallback CZSC analysis"""
        from uniquant.services.analysis.czsc_analysis_engine import CzscAnalysisEngine
        
        engine = CzscAnalysisEngine(mock_orchestrator)
        result = engine._fallback_czsc_analysis("000001.SZ", sample_ohlc_df)
        
        assert result["status"] == "success"
        assert "current_state" in result
        assert "trend" in result
        assert "support_level" in result
        assert "resistance_level" in result

    def test_fallback_czsc_analysis_missing_columns(self, mock_orchestrator):
        """Test fallback CZSC analysis with missing columns"""
        from uniquant.services.analysis.czsc_analysis_engine import CzscAnalysisEngine
        
        engine = CzscAnalysisEngine(mock_orchestrator)
        
        invalid_df = pd.DataFrame({"close": [10, 11, 12]})
        result = engine._fallback_czsc_analysis("000001.SZ", invalid_df)
        
        assert result["status"] == "success"
        assert result["current_state"] == "UNKNOWN"


class TestFsmAnalysisEngine:
    """Test suite for FsmAnalysisEngine"""

    def test_init(self, mock_orchestrator):
        """Test engine initialization"""
        from uniquant.services.analysis.fsm_analysis_engine import FsmAnalysisEngine
        
        engine = FsmAnalysisEngine(mock_orchestrator)
        assert engine.orchestrator is mock_orchestrator

    def test_run_fsm_analysis_with_df(self, mock_orchestrator, sample_ohlc_df):
        """Test FSM analysis with provided DataFrame"""
        from uniquant.services.analysis.fsm_analysis_engine import FsmAnalysisEngine
        
        engine = FsmAnalysisEngine(mock_orchestrator)
        result = engine.run_fsm_analysis("000001.SZ", df=sample_ohlc_df)
        
        assert result is not None
        assert "status" in result
        assert result["symbol"] == "000001.SZ"

    def test_run_fsm_analysis_empty_df(self, mock_orchestrator):
        """Test FSM analysis with empty DataFrame"""
        from uniquant.services.analysis.fsm_analysis_engine import FsmAnalysisEngine
        
        engine = FsmAnalysisEngine(mock_orchestrator)
        
        empty_df = pd.DataFrame()
        result = engine.run_fsm_analysis("000001.SZ", df=empty_df)
        
        assert result["status"] in ["failed", "success"]

    def test_run_fsm_analysis_none_df_reads_from_lake(self, mock_orchestrator, sample_ohlc_df):
        """Test FSM analysis reads from data lake when df is None"""
        from uniquant.services.analysis.fsm_analysis_engine import FsmAnalysisEngine
        
        engine = FsmAnalysisEngine(mock_orchestrator)
        result = engine.run_fsm_analysis("000001.SZ", df=None)
        
        mock_orchestrator.data_service.lake.read_data.assert_called_once()
        assert result is not None

    def test_map_decision_to_recommendation(self, mock_orchestrator):
        """Test decision to recommendation mapping"""
        from uniquant.services.analysis.fsm_analysis_engine import FsmAnalysisEngine
        
        engine = FsmAnalysisEngine(mock_orchestrator)
        
        assert engine._map_decision_to_recommendation("BUY") in ["买入", "未知", "BUY"]
        assert engine._map_decision_to_recommendation("SELL") in ["卖出", "未知", "SELL"]

    def test_fallback_fsm_analysis(self, mock_orchestrator, sample_ohlc_df):
        """Test fallback FSM analysis"""
        from uniquant.services.analysis.fsm_analysis_engine import FsmAnalysisEngine
        
        engine = FsmAnalysisEngine(mock_orchestrator)
        result = engine._fallback_fsm_analysis("000001.SZ", sample_ohlc_df)
        
        assert result["status"] == "success"
        assert "current_state" in result
        assert "signal_strength" in result
        assert "recommendation" in result
        assert "stop_loss" in result
        assert "take_profit" in result

    def test_fallback_fsm_analysis_missing_columns(self, mock_orchestrator):
        """Test fallback FSM analysis with missing columns"""
        from uniquant.services.analysis.fsm_analysis_engine import FsmAnalysisEngine
        
        engine = FsmAnalysisEngine(mock_orchestrator)
        
        invalid_df = pd.DataFrame({"open": [10, 11, 12]})
        result = engine._fallback_fsm_analysis("000001.SZ", invalid_df)
        
        assert result["status"] == "success"
        assert result["current_state"] == "UNKNOWN"
        assert result["signal_strength"] == 0.0


class TestLpplAnalysisEngine:
    """Test suite for LpplAnalysisEngine"""

    def test_init(self, mock_orchestrator):
        """Test engine initialization"""
        from uniquant.services.analysis.lppl_analysis_engine import LpplAnalysisEngine
        
        engine = LpplAnalysisEngine(mock_orchestrator)
        assert engine.orchestrator is mock_orchestrator

    def test_run_lppl_analysis_with_df(self, mock_orchestrator, sample_ohlc_df):
        """Test LPPL analysis with provided DataFrame"""
        from uniquant.services.analysis.lppl_analysis_engine import LpplAnalysisEngine
        
        engine = LpplAnalysisEngine(mock_orchestrator)
        result = engine.run_lppl_analysis("000001.SZ", df=sample_ohlc_df)
        
        assert result is not None
        assert "status" in result
        assert result["symbol"] == "000001.SZ"

    def test_run_lppl_analysis_none_df_reads_from_lake(self, mock_orchestrator, sample_ohlc_df):
        """Test LPPL analysis reads from data lake when df is None"""
        from uniquant.services.analysis.lppl_analysis_engine import LpplAnalysisEngine
        
        engine = LpplAnalysisEngine(mock_orchestrator)
        result = engine.run_lppl_analysis("000001.SZ", df=None)
        
        mock_orchestrator.data_service.lake.read_data.assert_called_once()
        assert result is not None

    def test_fallback_lppl_analysis(self, mock_orchestrator, sample_ohlc_df):
        """Test fallback LPPL analysis"""
        from uniquant.services.analysis.lppl_analysis_engine import LpplAnalysisEngine
        
        engine = LpplAnalysisEngine(mock_orchestrator)
        result = engine._fallback_lppl_analysis("000001.SZ", sample_ohlc_df)
        
        assert result["status"] == "success"
        assert "bubble_detected" in result
        assert "confidence" in result
        assert "amplitude" in result


class TestNtfAnalysisEngine:
    """Test suite for NtfAnalysisEngine"""

    def test_init(self, mock_orchestrator):
        """Test engine initialization"""
        from uniquant.services.analysis.ntf_analysis_engine import NtfAnalysisEngine
        
        engine = NtfAnalysisEngine(mock_orchestrator)
        assert engine.orchestrator is mock_orchestrator

    def test_run_ntf_detection(self, mock_orchestrator):
        """Test NTF detection"""
        from uniquant.services.analysis.ntf_analysis_engine import NtfAnalysisEngine
        
        engine = NtfAnalysisEngine(mock_orchestrator)
        result = engine.run_ntf_detection("000001.SZ")
        
        assert result is not None
        assert "status" in result
        assert result["symbol"] == "000001.SZ"
        assert "ntf_side" in result
        assert "ntf_intensity" in result


class TestRegimeAnalysisEngine:
    """Test suite for RegimeAnalysisEngine"""

    def test_init(self, mock_orchestrator):
        """Test engine initialization"""
        from uniquant.services.analysis.regime_analysis_engine import RegimeAnalysisEngine
        
        engine = RegimeAnalysisEngine(mock_orchestrator)
        assert engine.orchestrator is mock_orchestrator

    def test_run_regime_detection(self, mock_orchestrator):
        """Test regime detection"""
        from uniquant.services.analysis.regime_analysis_engine import RegimeAnalysisEngine
        
        engine = RegimeAnalysisEngine(mock_orchestrator)
        result = engine.run_regime_detection("000300.SH")
        
        assert result is not None
        assert "status" in result
        assert result["symbol"] == "000300.SH"
        assert "regime" in result


class TestMacroAnalysisEngine:
    """Test suite for MacroAnalysisEngine"""

    def test_init(self, mock_orchestrator):
        """Test engine initialization"""
        from uniquant.services.analysis.macro_analysis_engine import MacroAnalysisEngine
        
        engine = MacroAnalysisEngine(mock_orchestrator)
        assert engine.orchestrator is mock_orchestrator

    def test_get_macro_returns_empty_fallback(self, mock_orchestrator):
        """Test get_macro_returns with empty data fallback"""
        from uniquant.services.analysis.macro_analysis_engine import MacroAnalysisEngine
        
        mock_fetcher = Mock()
        mock_fetcher.fetch_index_daily = Mock(return_value=None)
        mock_orchestrator.data_service.fetcher = mock_fetcher
        
        engine = MacroAnalysisEngine(mock_orchestrator)
        result = engine.get_macro_returns(window=10)
        
        assert isinstance(result, pd.Series)
