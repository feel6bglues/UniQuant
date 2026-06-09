from __future__ import annotations

from unittest.mock import Mock

import pytest

from uniquant.brain.fsm.fsm import DecisionBrain
from uniquant.services.analysis.engine_factory import AnalysisEngineFactory
from uniquant.services.analysis_service_v2 import AnalysisService


def _buy_candidate_packet(**overrides):
    packet = {
        "symbol": "600000.SH",
        "regime": "NORMAL",
        "risk": "Safe",
        "ntf_side": "SUPPORT",
        "alpha_score": 0.75,
        "is_3rd_buy": True,
        "ma_status": "MA20 > MA60",
        "bubble_confidence": 0.0,
        "ntf_intensity": 0.5,
        "bi_count": 3,
        "price": 10.0,
        "pre_close": 10.0,
        "atr_stop": 9.4,
    }
    packet.update(overrides)
    return packet


def test_decision_brain_blocks_buy_when_risk_engine_failed():
    brain = DecisionBrain(persist_state=False)

    result = brain.make_decision(
        _buy_candidate_packet(
            risk="ENGINE_FAILED",
            engine_status={"lppl": "ENGINE_FAILED"},
            engine_errors={"lppl": "boom"},
        )
    )

    assert result["action"] in {"HOLD", "FORCE_WAIT"}
    assert "RISK_ENGINE_FAILED" in result.get("buy_blockers", [])
    assert result["engine_status"]["lppl"] == "ENGINE_FAILED"


def test_decision_brain_blocks_buy_when_market_regime_unknown():
    brain = DecisionBrain(persist_state=False)

    result = brain.make_decision(
        _buy_candidate_packet(
            regime="UNKNOWN",
            engine_status={"regime": "DATA_UNAVAILABLE"},
        )
    )

    assert result["action"] in {"HOLD", "FORCE_WAIT"}
    assert "REGIME_UNKNOWN" in result.get("buy_blockers", [])


@pytest.mark.parametrize(
    ("atr_stop", "expected_blocker"),
    [
        (0.0, "STOP_LOSS_MISSING"),
        (8.0, "STOP_LOSS_TOO_WIDE"),
    ],
)
def test_decision_brain_blocks_buy_without_survivable_stop_loss(
    atr_stop,
    expected_blocker,
):
    brain = DecisionBrain(persist_state=False)

    result = brain.make_decision(_buy_candidate_packet(atr_stop=atr_stop))

    assert result["action"] == "HOLD"
    assert expected_blocker in result.get("buy_blockers", [])


def test_analysis_service_marks_regime_failure_as_unknown():
    data_service = Mock()
    data_service.lake.read_data.side_effect = RuntimeError("regime failed")
    service = AnalysisService(
        data_service=data_service,
        engine_factory=AnalysisEngineFactory(orchestrator=Mock()),
    )
    data_pack = {}

    service._run_regime("600000.SH", data_pack)

    assert data_pack["regime"] == "UNKNOWN"
    assert data_pack["engine_status"]["regime"] == "ENGINE_FAILED"
    assert "regime failed" in data_pack["engine_errors"]["regime"]


def test_analysis_service_marks_lppl_failure_as_engine_failed():
    data_service = Mock()
    service = AnalysisService(
        data_service=data_service,
        engine_factory=AnalysisEngineFactory(orchestrator=Mock()),
    )
    service._factory._engines["lppl"] = Mock(
        run_lppl_analysis=Mock(side_effect=RuntimeError("lppl failed"))
    )
    data_pack = {"stock": Mock(empty=False), "symbol": "600000.SH"}

    service._run_lppl(data_pack)

    assert data_pack["risk"] == "ENGINE_FAILED"
    assert data_pack["bubble_confidence"] == 1.0
    assert data_pack["engine_status"]["lppl"] == "ENGINE_FAILED"
    assert "lppl failed" in data_pack["engine_errors"]["lppl"]
