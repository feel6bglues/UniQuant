"""信号仲裁器测试"""
import datetime
from unittest.mock import MagicMock

from uniquant.shared.interfaces import TradingSignal
from uniquant.signal.arbitrator import SignalArbitrator


from uniquant.shared.interfaces import CandidateSignal, DecisionOutput


def _sig(action: str, reason: str = "", confidence: float = 0.5) -> TradingSignal:
    return TradingSignal(
        action=action,
        reason=reason,
        confidence=confidence,
        symbol="000001.SZ",
        timestamp=datetime.datetime(2024, 6, 1),
    )


class TestSignalArbitrator:
    def test_empty_signals(self):
        arb = SignalArbitrator()
        assert arb.arbitrate([], symbol="000001.SZ") == []

    def test_single_signal_passes_through(self):
        arb = SignalArbitrator()
        s = _sig("BUY", "czsc_signal", 0.8)
        result = arb.arbitrate([s], symbol="000001.SZ")
        assert len(result) == 1
        assert result[0].action == "BUY"
        assert result[0].reason == "czsc_signal"

    def test_sell_priority_over_buy(self):
        arb = SignalArbitrator(sell_priority=True)
        buy = _sig("BUY", "czsc_3rd_buy", 0.9)
        sell = _sig("SELL", "lppl_exit", 0.7)
        result = arb.arbitrate([buy, sell], symbol="000001.SZ")
        assert len(result) == 1
        assert result[0].action == "SELL"
        assert "lppl_exit" in result[0].reason

    def test_highest_confidence_wins_same_action(self):
        arb = SignalArbitrator()
        low_conf = _sig("BUY", "alpha_score", 0.3)
        high_conf = _sig("BUY", "czsc_3rd_buy", 0.9)
        result = arb.arbitrate([low_conf, high_conf], symbol="000001.SZ")
        assert len(result) == 1
        assert result[0].confidence == 0.9

    def test_multiple_days_handled_correctly(self):
        arb = SignalArbitrator()
        d1 = datetime.datetime(2024, 6, 1)
        d2 = datetime.datetime(2024, 6, 2)
        s1 = TradingSignal(action="BUY", reason="day1", symbol="000001.SZ", timestamp=d1)
        s2 = TradingSignal(action="SELL", reason="day2", symbol="000001.SZ", timestamp=d2)
        result = arb.arbitrate([s1, s2], symbol="000001.SZ")
        assert len(result) == 2
        assert result[0].reason == "day1"
        assert result[1].reason == "day2"

    def test_arbitration_logs_generated(self):
        arb = SignalArbitrator()
        buy = _sig("BUY", "czsc", 0.5)
        sell = _sig("SELL", "lppl", 0.6)
        arb.arbitrate([buy, sell], symbol="000001.SZ")
        logs = arb.logs
        assert len(logs) == 1
        assert logs[0].conflicts_resolved == 1
        assert logs[0].selected_action == "SELL"

    def test_sell_priority_false_allows_buy(self):
        arb = SignalArbitrator(sell_priority=False)
        buy = _sig("BUY", "czsc", 0.8)
        sell = _sig("SELL", "lppl", 0.7)
        result = arb.arbitrate([buy, sell], symbol="000001.SZ")
        assert len(result) == 1
        # Without sell_priority, highest confidence wins
        assert result[0].confidence == 0.8


class TestSignalArbitratorCandidateSignals:
    def test_empty_candidates(self):
        arb = SignalArbitrator()
        signals, report = arb.arbitrate_candidates([], symbol="000001.SZ")
        assert signals == []
        assert report.candidates_count == 0

    def test_force_wait_veto(self):
        arb = SignalArbitrator()
        candidates = [CandidateSignal(source="czsc", action="BUY", confidence=0.8, direction=1, strength=0.7)]
        decision = DecisionOutput(action="FORCE_WAIT", reason="market frozen", confidence=1.0)
        signals, report = arb.arbitrate_candidates(candidates, decision_output=decision, symbol="000001.SZ")
        assert signals == []
        assert "risk_veto" in report.final_reason or "FORCE_WAIT" in report.veto_chain[0]

    def test_force_exit(self):
        arb = SignalArbitrator()
        candidates = [CandidateSignal(source="czsc", action="BUY", confidence=0.8, direction=1, strength=0.7)]
        decision = DecisionOutput(action="FORCE_EXIT", reason="danger", confidence=1.0)
        signals, report = arb.arbitrate_candidates(candidates, decision_output=decision, symbol="000001.SZ")
        assert len(signals) == 1
        assert signals[0].action == "SELL"

    def test_decision_buy_authoritative(self):
        arb = SignalArbitrator()
        candidates = [CandidateSignal(source="czsc", action="BUY", confidence=0.8, direction=1, strength=0.7)]
        decision = DecisionOutput(action="BUY", shares=200, confidence=0.9)
        signals, report = arb.arbitrate_candidates(candidates, decision_output=decision, symbol="000001.SZ")
        assert len(signals) == 1
        assert signals[0].action == "BUY"

    def test_non_fsm_needs_sizer(self):
        arb = SignalArbitrator()
        candidates = [CandidateSignal(source="wyckoff", action="BUY", confidence=0.8, direction=1, strength=0.7)]
        signals, report = arb.arbitrate_candidates(candidates, symbol="000001.SZ")
        assert signals == []
        assert "sizer" in report.final_reason

    def test_non_fsm_sizer_approves(self):
        arb = SignalArbitrator()
        candidates = [CandidateSignal(source="wyckoff", action="BUY", confidence=0.8, direction=1, strength=0.7)]
        mock_sizer = MagicMock()
        mock_sizer.calculate_shares.return_value = {"suggested_shares": 300}
        signals, report = arb.arbitrate_candidates(candidates, sizer=mock_sizer, symbol="000001.SZ")
        assert len(signals) == 1
        assert signals[0].action == "BUY"
        assert signals[0].shares == 300, f"Expected 300, got {signals[0].shares}"
        mock_sizer.calculate_shares.assert_called_once()

    def test_sell_priority(self):
        arb = SignalArbitrator()
        candidates = [
            CandidateSignal(source="lppl", action="SELL", confidence=0.9, direction=-1, strength=0.9),
            CandidateSignal(source="czsc", action="BUY", confidence=0.8, direction=1, strength=0.7),
        ]
        signals, report = arb.arbitrate_candidates(candidates, symbol="000001.SZ")
        assert len(signals) == 1
        assert signals[0].action == "SELL"

    def test_report_metadata(self):
        arb = SignalArbitrator()
        candidates = [
            CandidateSignal(source="lppl", action="SELL", confidence=0.9, direction=-1, strength=0.9),
            CandidateSignal(source="czsc", action="BUY", confidence=0.8, direction=1, strength=0.7),
        ]
        signals, report = arb.arbitrate_candidates(candidates, symbol="000001.SZ")
        assert report.symbol == "000001.SZ"
        assert report.candidates_count == 2
        assert len(report.rejected) > 0
