from __future__ import annotations

import pytest

from uniquant.shared.kill_switch import KillSwitchError, SharedKillSwitch, get_kill_switch
from uniquant.signal.arbitrator import SignalArbitrator
from uniquant.shared.interfaces import TradingSignal, CandidateSignal


class TestKillSwitch:
    def test_default_not_killed(self):
        ks = SharedKillSwitch()
        ks.reset()
        assert not ks.is_killed
        assert ks.reason == ""

    def test_kill_and_reset(self):
        ks = SharedKillSwitch()
        ks.reset()
        ks.kill("emergency")
        assert ks.is_killed
        assert ks.reason == "emergency"
        ks.reset()
        assert not ks.is_killed

    def test_kill_raises_on_check(self):
        ks = SharedKillSwitch()
        ks.reset()
        ks.kill("test")
        with pytest.raises(KillSwitchError, match="test"):
            ks.check()
        ks.reset()

    def test_hook_execution(self):
        ks = SharedKillSwitch()
        ks.reset()
        calls = []
        ks.register_hook(lambda: calls.append(1))
        ks.kill("hook_test")
        assert len(calls) == 1
        ks.reset()

    def test_singleton(self):
        ks1 = get_kill_switch()
        ks2 = get_kill_switch()
        assert ks1 is ks2

    def test_multiple_kills_same_reason(self):
        ks = SharedKillSwitch()
        ks.reset()
        ks.kill("reason_a")
        ks.kill("reason_b")
        assert ks.reason == "reason_b"
        ks.reset()


class TestKillSwitchArbitratorIntegration:
    def test_kill_switch_blocks_signals(self):
        ks = get_kill_switch()
        ks.reset()

        arb = SignalArbitrator()
        candidates = [
            CandidateSignal(
                source="lppl", action="SELL", confidence=0.8,
                direction=-1, strength=0.5,
            ),
        ]
        signals, report = arb.arbitrate_candidates(candidates, symbol="000001.SZ")
        assert len(signals) > 0
        assert report.final_action == "SELL"

        ks.kill("test_block")
        signals2, report2 = arb.arbitrate_candidates(candidates, symbol="000001.SZ")
        assert len(signals2) == 0
        assert report2.final_action == "HOLD"
        assert "kill_switch" in report2.final_reason
        ks.reset()

    def test_arbitrate_respects_kill_switch(self):
        ks = get_kill_switch()
        ks.reset()

        arb = SignalArbitrator()
        raw_signals = [
            TradingSignal(action="BUY", reason="test", confidence=0.7, symbol="000001.SZ"),
        ]
        result = arb.arbitrate(raw_signals, symbol="000001.SZ")
        assert len(result) > 0

        ks.kill("block_all")
        result2 = arb.arbitrate(raw_signals, symbol="000001.SZ")
        assert len(result2) == 0
        ks.reset()
