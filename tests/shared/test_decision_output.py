from __future__ import annotations


from uniquant.shared.interfaces import DecisionOutput


def test_create_default():
    d = DecisionOutput()
    assert d.action == "HOLD"
    assert d.reason == ""
    assert d.confidence == 0.0
    assert d.shares == 0
    assert d.price == 0.0
    assert d.regime == "UNKNOWN"
    assert d.score == 0.0
    assert d.engine_status == {}
    assert d.metadata == {}


def test_create_with_values():
    d = DecisionOutput(
        action="BUY",
        reason="strong_buy_signal",
        confidence=0.85,
        shares=200,
        price=15.5,
        regime="NORMAL",
        score=75.0,
    )
    assert d.action == "BUY"
    assert d.reason == "strong_buy_signal"
    assert d.confidence == 0.85
    assert d.shares == 200
    assert d.price == 15.5
    assert d.regime == "NORMAL"
    assert d.score == 75.0


def test_from_dict():
    data = {
        "action": "SELL",
        "reason": "lppl_danger",
        "confidence": 0.9,
        "shares": 500,
        "price": 12.3,
        "regime": "STRESSED",
        "score": 20.0,
        "engine_status": {"lppl": "OK"},
    }
    d = DecisionOutput.from_dict(data)
    assert d.action == "SELL"
    assert d.confidence == 0.9
    assert d.engine_status["lppl"] == "OK"


def test_from_dict_handles_final_score():
    data = {"action": "BUY", "final_score": 80.0}
    d = DecisionOutput.from_dict(data)
    assert d.score == 80.0


def test_from_dict_empty():
    d = DecisionOutput.from_dict({})
    assert d.action == "HOLD"
    assert d.confidence == 0.0
