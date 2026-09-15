"""Unit tests for P0 patches:
1. ResearchPipeline metadata flattening and adapter signal collection recovery
2. OverfittingDetector scipy.special.erf calculation
"""
import datetime

from uniquant.shared.interfaces import ResearchDataPack
from uniquant.services.research_pipeline import UnifiedResearchPipeline
from uniquant.signal.adapters import TradingSignalCollector
from uniquant.hands.backtest.overfitting_detector import OverfittingDetector


class TestP0SignalChainFlattening:
    """Verify that metadata in ResearchDataPack is properly flattened for TradingSignalCollector."""

    def test_merge_decision_flattens_rdp_metadata(self):
        rdp = ResearchDataPack(
            symbol="000001.SZ",
            metadata={
                "risk": "Danger",
                "bubble_confidence": 0.85,
                "is_3rd_buy": True,
                "bi_count": 5,
                "wyckoff_phase": "Phase C",
                "wyckoff_confidence": 0.75,
                "wyckoff_direction": "markup",
                "ntf_side": "LONG",
                "alpha_score": 88.0,
                "ma_status": "BULL",
                "regime": "FROZEN",
                "price": 12.5,
            },
        )
        decision = {"action": "BUY", "confidence": 0.9, "shares": 500}

        merged = UnifiedResearchPipeline._merge_decision_for_collection(rdp, decision)

        # Check metadata keys are flattened at root level
        assert merged["risk"] == "Danger"
        assert merged["bubble_confidence"] == 0.85
        assert merged["is_3rd_buy"] is True
        assert merged["bi_count"] == 5
        assert merged["wyckoff_phase"] == "Phase C"
        assert merged["ntf_side"] == "LONG"
        assert merged["alpha_score"] == 88.0
        assert merged["ma_status"] == "BULL"
        assert merged["regime"] == "FROZEN"
        # Decision values override / supplement
        assert merged["action"] == "BUY"
        assert merged["confidence"] == 0.9
        assert merged["shares"] == 500

    def test_merge_decision_flattens_dict_metadata_when_no_decision(self):
        data = {
            "symbol": "600519.SH",
            "metadata": {
                "risk": "Safe",
                "bubble_confidence": 0.1,
                "regime": "NORMAL",
            },
        }
        merged = UnifiedResearchPipeline._merge_decision_for_collection(data, {})
        assert merged["risk"] == "Safe"
        assert merged["bubble_confidence"] == 0.1
        assert merged["regime"] == "NORMAL"

    def test_trading_signal_collector_recovers_all_adapters(self):
        """Verify that a flattened collector_pack activates multiple adapters."""
        collector = TradingSignalCollector()
        now = datetime.datetime(2026, 9, 14, 15, 0, 0)

        rdp = ResearchDataPack(
            symbol="000001.SZ",
            metadata={
                "risk": "Danger",
                "bubble_confidence": 0.85,
                "is_3rd_buy": True,
                "bi_count": 3,
                "wyckoff_phase": "Phase C",
                "wyckoff_confidence": 0.80,
                "wyckoff_direction": "做多",
                "ntf_side": "LONG",
                "alpha_score": 85.0,
                "ma_status": "BULL_TREND",
                "regime": "FROZEN",
                "price": 15.0,
            },
        )
        decision = {"action": "BUY", "confidence": 0.85, "shares": 200, "price": 15.0}
        collector_pack = UnifiedResearchPipeline._merge_decision_for_collection(rdp, decision)

        signals = collector.collect(collector_pack, timestamp=now)

        # Signals should be collected from multiple adapters, not just FSM
        assert len(signals) >= 4
        reasons = [s.reason for s in signals]

        # Verify LPPL adapter fired (Danger -> SELL)
        assert any("LPPL" in r for r in reasons)
        # Verify CZSC adapter fired (3rd buy -> BUY)
        assert any("CZSC" in r for r in reasons)
        # Verify Wyckoff adapter fired
        assert any("Wyckoff" in r for r in reasons)
        # Verify Regime adapter fired (FROZEN -> HOLD)
        assert any("市场冻结" in r for r in reasons)


class TestP0OverfittingDetector:
    def test_mdd_p_value_direct_call(self):
        od = OverfittingDetector()
        p = od.mdd_p_value(0.20, 252)
        assert isinstance(p, float)
        assert 0.0 <= p <= 1.0

    def test_mdd_p_value_boundary_values(self):
        od = OverfittingDetector()
        assert od.mdd_p_value(0.0, 100) == 1.0
        assert od.mdd_p_value(-0.05, 100) == 1.0
        assert od.mdd_p_value(0.1, 1) == 1.0
