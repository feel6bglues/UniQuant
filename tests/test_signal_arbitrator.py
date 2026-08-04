"""Tests for SignalArbitrator — arbitration logic and sizer wiring.

Anti-drift assertions:
  - arbitrate_candidates() wires PositionSizerProtocol for non-FSM BUY
    (refutes the P3.2 claim that sizer is not called in production)
"""

from __future__ import annotations

from unittest.mock import MagicMock


from uniquant.shared.interfaces import (
    PositionSizerProtocol,
    TradingSignal,
)
from uniquant.signal.arbitrator import (
    CandidateSignal,
    SignalArbitrator,
)


class TestArbitrateBasic:
    """Basic arbitration behavior."""

    def test_empty_signals(self):
        arb = SignalArbitrator()
        result = arb.arbitrate([])
        assert result == []

    def test_single_buy_signal(self):
        arb = SignalArbitrator()
        sig = TradingSignal(action="BUY", confidence=0.8, symbol="000001.SZ")
        result = arb.arbitrate([sig])
        assert len(result) == 1
        assert result[0].action == "BUY"

    def test_sell_priority(self):
        arb = SignalArbitrator(sell_priority=True)
        buy = TradingSignal(action="BUY", confidence=0.9, symbol="000001.SZ")
        sell = TradingSignal(action="SELL", confidence=0.6, symbol="000001.SZ")
        result = arb.arbitrate([buy, sell])
        assert len(result) == 1
        assert result[0].action == "SELL"

    def test_higher_confidence_wins_same_action(self):
        arb = SignalArbitrator()
        low = TradingSignal(action="BUY", confidence=0.5, symbol="000001.SZ")
        high = TradingSignal(action="BUY", confidence=0.9, symbol="000001.SZ")
        result = arb.arbitrate([low, high])
        assert len(result) == 1
        assert result[0].confidence == 0.9

    def test_quality_threshold_filters_low_oos_r2_sell(self):
        arb = SignalArbitrator(quality_threshold=0.5)
        sig1 = TradingSignal(action="SELL", confidence=0.8, symbol="000001.SZ")
        sig1.metadata["out_of_sample_r_squared"] = 0.2
        sig2 = TradingSignal(action="SELL", confidence=0.6, symbol="000001.SZ")
        sig2.metadata["out_of_sample_r_squared"] = 0.2
        result = arb.arbitrate([sig1, sig2])
        assert result == []

    def test_quality_threshold_passes_high_oos_r2_sell(self):
        arb = SignalArbitrator(quality_threshold=0.5)
        sig1 = TradingSignal(action="SELL", confidence=0.8, symbol="000001.SZ")
        sig1.metadata["out_of_sample_r_squared"] = 0.9
        sig2 = TradingSignal(action="SELL", confidence=0.6, symbol="000001.SZ")
        sig2.metadata["out_of_sample_r_squared"] = 0.9
        result = arb.arbitrate([sig1, sig2])
        assert len(result) == 1


class TestArbitrateCandidates:
    """Candidate arbitration with DecisionOutput and sizer."""

    def test_no_candidates(self):
        arb = SignalArbitrator()
        signals, report = arb.arbitrate_candidates([], symbol="000001.SZ")
        assert signals == []
        assert report.final_action == "HOLD"

    def test_hold_by_default(self):
        arb = SignalArbitrator()
        signals, report = arb.arbitrate_candidates(
            [CandidateSignal(action="HOLD", confidence=0.5, direction=0, strength=0.5, source="test")],
            symbol="000001.SZ",
        )
        assert signals == []
        assert report.final_action == "HOLD"

    def test_sell_priority_in_candidates(self):
        arb = SignalArbitrator(sell_priority=True)
        candidates = [
            CandidateSignal(action="BUY", confidence=0.9, direction=1, strength=0.9, source="lppl"),
            CandidateSignal(action="SELL", confidence=0.6, direction=-1, strength=0.6, source="czsc"),
        ]
        signals, report = arb.arbitrate_candidates(candidates, symbol="000001.SZ")
        assert len(signals) == 1
        assert signals[0].action == "SELL"


class TestArbitrateCandidatesSizer:
    """arbitrate_candidates() must wire PositionSizerProtocol for non-FSM BUY.

    This set of tests prevents regression of the P3.2 concern.
    """

    def test_non_fsm_buy_needs_sizer(self):
        arb = SignalArbitrator()
        candidates = [
            CandidateSignal(action="BUY", confidence=0.8, direction=1, strength=0.8, source="lppl"),
        ]
        signals, report = arb.arbitrate_candidates(candidates, symbol="000001.SZ", sizer=None)
        assert signals == []
        assert "non_fsm_needs_sizer" in report.veto_chain

    def test_non_fsm_buy_with_sizer(self):
        arb = SignalArbitrator()
        mock_sizer = MagicMock(spec=PositionSizerProtocol)
        mock_sizer.calculate_shares.return_value = {"suggested_shares": 500}
        candidates = [
            CandidateSignal(action="BUY", confidence=0.8, direction=1, strength=0.8, source="lppl"),
        ]
        signals, report = arb.arbitrate_candidates(
            candidates, sizer=mock_sizer, symbol="000001.SZ",
        )
        assert len(signals) == 1
        assert signals[0].action == "BUY"
        assert signals[0].shares == 500

    def test_non_fsm_buy_sizer_failure_defaults_to_100(self):
        arb = SignalArbitrator()
        mock_sizer = MagicMock(spec=PositionSizerProtocol)
        mock_sizer.calculate_shares.side_effect = ValueError("simulated failure")
        candidates = [
            CandidateSignal(action="BUY", confidence=0.8, direction=1, strength=0.8, source="lppl"),
        ]
        signals, report = arb.arbitrate_candidates(
            candidates, sizer=mock_sizer, symbol="000001.SZ",
        )
        assert len(signals) == 1
        assert signals[0].shares == 100

    def test_fsm_buy_bypasses_sizer(self):
        arb = SignalArbitrator()
        candidates = [
            CandidateSignal(action="BUY", confidence=0.8, direction=1, strength=0.8, source="fsm"),
        ]
        signals, report = arb.arbitrate_candidates(candidates, symbol="000001.SZ", sizer=None)
        assert len(signals) == 1
        assert signals[0].action == "BUY"


class TestCandidateWithDecisionOutput:
    """DecisionOutput hard constraints override candidate signals."""

    def test_force_wait_returns_hold(self):
        arb = SignalArbitrator()
        from uniquant.shared.interfaces import DecisionOutput
        candidates = [
            CandidateSignal(action="BUY", confidence=0.9, direction=1, strength=0.9, source="lppl"),
        ]
        decision = DecisionOutput(action="FORCE_WAIT", confidence=1.0)
        signals, report = arb.arbitrate_candidates(
            candidates, decision_output=decision, symbol="000001.SZ",
        )
        assert signals == []

    def test_force_wait_empty_candidates_is_hold(self):
        arb = SignalArbitrator()
        signals, report = arb.arbitrate_candidates([], symbol="000001.SZ")
        assert signals == []
        assert report.final_action == "HOLD"

    def test_force_wait_with_decision_output(self):
        arb = SignalArbitrator()
        from uniquant.shared.interfaces import DecisionOutput
        candidates = [
            CandidateSignal(action="BUY", confidence=0.9, direction=1, strength=0.9, source="lppl"),
        ]
        decision = DecisionOutput(action="FORCE_WAIT", confidence=1.0)
        signals, report = arb.arbitrate_candidates(
            candidates, decision_output=decision, symbol="000001.SZ",
        )
        assert signals == []
        assert "decision_output=FORCE_WAIT" in report.veto_chain

    def test_force_exit_returns_sell(self):
        arb = SignalArbitrator()
        from uniquant.shared.interfaces import DecisionOutput
        decision = DecisionOutput(action="FORCE_EXIT", confidence=1.0)
        signals, report = arb.arbitrate_candidates(
            [CandidateSignal(action="BUY", confidence=0.9, direction=1, strength=0.9, source="test")],
            decision_output=decision, symbol="000001.SZ",
        )
        assert len(signals) == 1
        assert signals[0].action == "SELL"

    def test_decision_brain_buy_with_shares(self):
        arb = SignalArbitrator()
        from uniquant.shared.interfaces import DecisionOutput
        decision = DecisionOutput(action="BUY", confidence=0.8, shares=300)
        signals, report = arb.arbitrate_candidates(
            [CandidateSignal(action="BUY", confidence=0.5, direction=1, strength=0.5, source="test")],
            decision_output=decision, symbol="000001.SZ",
        )
        assert len(signals) == 1
        assert signals[0].action == "BUY"
        assert signals[0].shares == 300


class TestArbitrationLog:
    """Arbitration log tracking."""

    def test_logs_are_recorded(self):
        arb = SignalArbitrator()
        sig = TradingSignal(action="BUY", confidence=0.8, symbol="000001.SZ")
        arb.arbitrate([sig])
        assert len(arb.logs) > 0

    def test_clear_logs(self):
        arb = SignalArbitrator()
        sig = TradingSignal(action="BUY", confidence=0.8, symbol="000001.SZ")
        arb.arbitrate([sig])
        arb.clear_logs()
        assert arb.logs == []
