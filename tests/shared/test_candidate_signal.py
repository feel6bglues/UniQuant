from __future__ import annotations

import pytest

from uniquant.shared.interfaces import CandidateSignal


def test_create_minimal():
    cs = CandidateSignal(
        source="lppl",
        action="SELL",
        confidence=0.85,
        direction=-1,
        strength=0.75,
    )
    assert cs.source == "lppl"
    assert cs.action == "SELL"
    assert cs.confidence == 0.85
    assert cs.direction == -1
    assert cs.strength == 0.75
    assert cs.price_target is None
    assert cs.stop_loss is None
    assert cs.time_horizon is None
    assert cs.metadata == {}


def test_create_full():
    cs = CandidateSignal(
        source="wyckoff",
        action="BUY",
        confidence=0.7,
        direction=1,
        strength=0.6,
        price_target=15.0,
        stop_loss=13.5,
        time_horizon="short",
        metadata={"phase": "accumulation"},
    )
    assert cs.price_target == 15.0
    assert cs.stop_loss == 13.5
    assert cs.time_horizon == "short"
    assert cs.metadata["phase"] == "accumulation"


def test_immutable():
    cs = CandidateSignal(source="regime", action="HOLD", confidence=0.0, direction=0, strength=0.0)
    with pytest.raises(AttributeError):
        cs.action = "BUY"


def test_different_sources():
    sources = ["regime", "lppl", "ntf", "czsc", "wyckoff", "alpha", "indicator"]
    for src in sources:
        cs = CandidateSignal(source=src, action="BUY", confidence=0.5, direction=1, strength=0.5)
        assert cs.source == src


def test_confidence_range():
    cs = CandidateSignal(source="alpha", action="BUY", confidence=0.99, direction=1, strength=0.9)
    assert 0.0 <= cs.confidence <= 1.0
