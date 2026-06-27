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


def _sig_no_ts(action: str, reason: str = "", confidence: float = 0.5) -> TradingSignal:
    return TradingSignal(
        action=action,
        reason=reason,
        confidence=confidence,
        symbol="000001.SZ",
        timestamp=None,
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

    # ── G-4a: None/negative confidence ────────────────────────
    def test_none_confidence_does_not_crash(self):
        arb = SignalArbitrator()
        s = TradingSignal(action="BUY", reason="test", confidence=None, symbol="000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        result = arb.arbitrate([s], symbol="000001.SZ")
        assert len(result) == 1
        assert result[0].action == "BUY"

    def test_negative_confidence_does_not_crash(self):
        arb = SignalArbitrator()
        buy = _sig("BUY", "czsc", -0.5)
        sell = _sig("SELL", "lppl", -0.3)
        result = arb.arbitrate([buy, sell], symbol="000001.SZ")
        assert len(result) == 1
        # SELL should still win (sell_priority), negative confidence doesn't crash
        assert result[0].action == "SELL"

    def test_highest_confidence_skips_none(self):
        arb = SignalArbitrator()
        none_conf = TradingSignal(action="BUY", reason="alpha", confidence=None, symbol="000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        high_conf = _sig("BUY", "czsc", 0.9)
        result = arb.arbitrate([none_conf, high_conf], symbol="000001.SZ")
        assert len(result) == 1
        assert result[0].confidence == 0.9

    # ── G-4g: HOLD-only signals ──────────────────────────────
    def test_hold_only_signals_return_empty(self):
        arb = SignalArbitrator()
        s1 = _sig("HOLD", "no_trade", 0.5)
        s2 = _sig("HOLD", "wait", 0.3)
        result = arb.arbitrate([s1, s2], symbol="000001.SZ")
        assert result == []

    def test_mixed_hold_and_actionable_filters_hold(self):
        arb = SignalArbitrator()
        hold = _sig("HOLD", "wait", 0.5)
        buy = _sig("BUY", "czsc", 0.8)
        result = arb.arbitrate([hold, buy], symbol="000001.SZ")
        assert len(result) == 1
        assert result[0].action == "BUY"

    # ── G-4d: No-timestamp signals ───────────────────────────
    def test_no_timestamp_signals_grouped_under_unknown(self):
        arb = SignalArbitrator()
        s1 = _sig_no_ts("BUY", "czsc", 0.8)
        s2 = _sig_no_ts("SELL", "lppl", 0.9)
        result = arb.arbitrate([s1, s2], symbol="000001.SZ")
        assert len(result) == 1
        # SELL should win (sell_priority)
        assert result[0].action == "SELL"
        logs = arb.logs
        assert logs[0].date == "unknown"

    # ── G-4b: Unknown action ─────────────────────────────────
    def test_unknown_action_filtered_out(self):
        arb = SignalArbitrator()
        unknown = TradingSignal(action="EXECUTE_BUY", reason="legacy", confidence=0.8, symbol="000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        buy = _sig("BUY", "czsc", 0.7)
        result = arb.arbitrate([unknown, buy], symbol="000001.SZ")
        assert len(result) == 1
        assert result[0].action == "BUY"

    def test_all_unknown_actions_return_empty(self):
        arb = SignalArbitrator()
        s1 = TradingSignal(action="ADD", reason="legacy_1", confidence=0.8, symbol="000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        s2 = TradingSignal(action="FORCE_WAIT", reason="legacy_2", confidence=0.7, symbol="000001.SZ", timestamp=datetime.datetime(2024, 6, 1))
        result = arb.arbitrate([s1, s2], symbol="000001.SZ")
        assert result == []

    # ── G-4h: Sizer exception path ───────────────────────────
    def test_sizer_exception_falls_back_to_default_shares(self):
        arb = SignalArbitrator()
        candidates = [CandidateSignal(source="wyckoff", action="BUY", confidence=0.8, direction=1, strength=0.7)]
        mock_sizer = MagicMock()
        mock_sizer.calculate_shares.side_effect = RuntimeError("sizer failed")
        signals, report = arb.arbitrate_candidates(candidates, sizer=mock_sizer, symbol="000001.SZ")
        assert len(signals) == 1
        assert signals[0].shares == 100

    # ── G-4i: CIRCUIT_BREAK ──────────────────────────────────
    def test_circuit_break_veto(self):
        arb = SignalArbitrator()
        candidates = [CandidateSignal(source="czsc", action="BUY", confidence=0.8, direction=1, strength=0.7)]
        decision = DecisionOutput(action="CIRCUIT_BREAK", reason="circuit", confidence=1.0)
        signals, report = arb.arbitrate_candidates(candidates, decision_output=decision, symbol="000001.SZ")
        assert signals == []
        assert "CIRCUIT_BREAK" in report.veto_chain[0]

    # ── G-4j: HOLD default path ──────────────────────────────
    def test_no_actionable_candidates_returns_hold(self):
        arb = SignalArbitrator()
        signals, report = arb.arbitrate_candidates([], symbol="000001.SZ")
        assert signals == []
        assert report.final_action == "HOLD"
        assert "no candidates" in report.final_reason

    # ── G-4e/4f: Engine priority ties ────────────────────────
    def test_engine_priority_tie_picks_first(self):
        arb = SignalArbitrator()
        s1 = _sig("BUY", "unknown_engine_a", 0.5)
        s2 = _sig("BUY", "unknown_engine_b", 0.6)
        result = arb.arbitrate([s1, s2], symbol="000001.SZ")
        assert len(result) == 1
        # Both have priority 99, so higher confidence wins (rule 2 before rule 3)
        assert result[0].confidence == 0.6


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
