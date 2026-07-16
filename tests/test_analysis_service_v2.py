from __future__ import annotations

from unittest.mock import Mock, patch

import pandas as pd
import pytest

from uniquant.services.analysis.engine_factory import AnalysisEngineFactory
from uniquant.services.analysis_service_v2 import (
    RECOVERABLE_ERRORS,
    AnalysisService,
    TickerAnalysisResult,
)
from uniquant.shared.config_models import FeatureFlags, RefactoringConfig
from uniquant.shared.interfaces import (
    LPPLOutput,
    ResearchDataPack,
)

pytestmark = pytest.mark.usefixtures("_disable_research_pack")


# ── Patching ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _disable_research_pack():
    """Force dict path in _prepare_data so data_pack is always a dict."""
    with patch(
        "uniquant.services.analysis_service_v2.load_refactoring_config",
        return_value=RefactoringConfig(
            feature_flags=FeatureFlags(use_research_data_pack=False),
        ),
    ):
        yield


def _make_mock_data_service(stock_df=None):
    mock = Mock()
    if stock_df is None:
        stock_df = pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]})
    mock.fetch_for_brain = Mock(return_value={"stock": stock_df, "symbol": "600000.SH"})
    mock.lake.read_data = Mock(return_value=stock_df)
    mock.fetcher = Mock()
    return mock


def _make_engine_factory(**engine_overrides):
    factory = AnalysisEngineFactory(orchestrator=Mock())
    for name, mock_obj in engine_overrides.items():
        factory._engines[name] = mock_obj
    return factory


def _mock_brain(make_decision=None):
    if make_decision is None:
        make_decision = Mock(return_value={"action": "HOLD"})
    return Mock(make_decision=make_decision)


_BASIC_ENGINES = {
    "brain": _mock_brain(),
    "czsc": Mock(run_czsc_analysis=Mock(return_value=Mock(
        is_3rd_buy=False, bi_count=0, price=0.0,
    ))),
    "wyckoff": Mock(run_wyckoff_analysis=Mock(return_value=Mock(
        phase="unknown", confidence=0.0, spring=False, utad=False,
        price=0.0,
    ))),
}


# ══════════════════════════════════════════════════════════════════
# 1. Engine failure fallback
# ══════════════════════════════════════════════════════════════════

def test_engine_failure_lppl_via_run_lppl():
    """_run_lppl catches RuntimeError and writes LPPLOutput(risk_level='ENGINE_FAILED')"""
    data_service = _make_mock_data_service()
    service = AnalysisService(data_service=data_service,
                              engine_factory=AnalysisEngineFactory(orchestrator=Mock()))
    service._factory._engines["lppl"] = Mock(
        run_lppl_analysis=Mock(side_effect=RuntimeError("lppl crash"))
    )
    data_pack = {"stock": Mock(empty=False), "symbol": "600000.SH"}

    service._run_lppl(data_pack)

    assert data_pack["risk"] == "ENGINE_FAILED"
    assert data_pack["bubble_confidence"] == 1.0
    assert data_pack["engine_status"]["lppl"] == "ENGINE_FAILED"


def test_engine_failure_regime_via_run_regime():
    """_run_regime catches RuntimeError and writes RegimeOutput(regime='UNKNOWN')"""
    data_service = _make_mock_data_service()
    data_service.lake.read_data.side_effect = RuntimeError("regime crash")
    service = AnalysisService(data_service=data_service,
                              engine_factory=AnalysisEngineFactory(orchestrator=Mock()))
    data_pack = {}

    service._run_regime("600000.SH", data_pack)

    assert data_pack["regime"] == "UNKNOWN"
    assert data_pack["engine_status"]["regime"] == "ENGINE_FAILED"


def test_engine_failure_all_engines_still_succeeds():
    """Every engine fails but run_ticker_analysis still returns success with fallbacks"""
    data_service = _make_mock_data_service()
    data_service.lake.read_data.side_effect = RuntimeError("regime crash")
    factory = _make_engine_factory(**_BASIC_ENGINES)
    factory._engines["lppl"] = Mock(
        run_lppl_analysis=Mock(side_effect=ValueError("lppl failed"))
    )
    service = AnalysisService(data_service=data_service, engine_factory=factory)

    result = service.run_ticker_analysis("600000.SH")

    assert result.success is True
    assert result.data_pack["regime"] == "UNKNOWN"
    lppl = result.data_pack["lppl_output"]
    assert isinstance(lppl, LPPLOutput)
    assert lppl.risk_level == "ENGINE_FAILED"


# ══════════════════════════════════════════════════════════════════
# 2. RECOVERABLE_ERRORS
# ══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "error_type",
    [
        AttributeError,
        ImportError,
        KeyError,
        ModuleNotFoundError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ],
)
def test_recoverable_errors_caught_by_run_lppl(error_type):
    """Each RECOVERABLE_ERRORS type is caught by _run_lppl's handler"""
    data_service = _make_mock_data_service()
    service = AnalysisService(data_service=data_service,
                              engine_factory=AnalysisEngineFactory(orchestrator=Mock()))
    service._factory._engines["lppl"] = Mock(
        run_lppl_analysis=Mock(side_effect=error_type("engine failed"))
    )
    data_pack = {"stock": Mock(empty=False), "symbol": "600000.SH"}

    service._run_lppl(data_pack)

    assert data_pack["risk"] == "ENGINE_FAILED"
    assert data_pack["engine_status"]["lppl"] == "ENGINE_FAILED"


@pytest.mark.parametrize(
    "error_type",
    [
        AttributeError,
        ImportError,
        KeyError,
        ModuleNotFoundError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ],
)
def test_recoverable_errors_caught_by_run_regime(error_type):
    """Each RECOVERABLE_ERRORS type is caught by _run_regime's handler"""
    data_service = _make_mock_data_service()
    data_service.lake.read_data.side_effect = error_type("regime failed")
    service = AnalysisService(data_service=data_service,
                              engine_factory=AnalysisEngineFactory(orchestrator=Mock()))
    data_pack = {}

    service._run_regime("600000.SH", data_pack)

    assert data_pack["regime"] == "UNKNOWN"
    assert data_pack["engine_status"]["regime"] == "ENGINE_FAILED"


@pytest.mark.parametrize(
    "error_type",
    [
        AttributeError,
        ImportError,
        KeyError,
        ModuleNotFoundError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ],
)
def test_recoverable_errors_caught_by_prepare_data(error_type):
    """RECOVERABLE_ERRORS raised inside _prepare_data returns None"""
    data_service = Mock()
    data_service.fetch_for_brain.side_effect = error_type("data fetch failed")
    service = AnalysisService(data_service=data_service)

    result = service._prepare_data("600000.SH")

    assert result is None


def test_recoverable_errors_caught_by_run_engines_outer_handler():
    """Outer _run_engines handler catches RECOVERABLE_ERRORS escaping per-engine handlers"""
    data_service = _make_mock_data_service()
    factory = _make_engine_factory(**_BASIC_ENGINES)
    service = AnalysisService(data_service=data_service, engine_factory=factory)

    data_pack = {"stock": pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]}),
                 "symbol": "600000.SH"}

    result = service._run_engines("600000.SH", data_pack)

    assert result is True


def test_recoverable_errors_caught_by_run_engines_outer_handler_on_post_engine_code():
    """Outer handler catches RECOVERABLE_ERRORS from post-engine data_pack code"""
    data_service = _make_mock_data_service()
    factory = _make_engine_factory(**_BASIC_ENGINES)
    service = AnalysisService(data_service=data_service, engine_factory=factory)

    broken = {"stock": pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]}),
              "symbol": "600000.SH"}
    broken["__fail__"] = True

    result = service._run_engines("600000.SH", broken)

    assert result is True


# ══════════════════════════════════════════════════════════════════
# 3. Data pack routing
# ══════════════════════════════════════════════════════════════════

def test_data_pack_routing_typed_path_enabled():
    """use_research_data_pack=True -> _prepare_data returns ResearchDataPack"""
    data_service = _make_mock_data_service()
    stock_df = pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]})
    typed_pack = ResearchDataPack(symbol="600000.SH", stock_df=stock_df)
    data_service.fetch_research_pack = Mock(return_value=typed_pack)
    service = AnalysisService(data_service=data_service)

    with patch(
        "uniquant.services.analysis_service_v2.load_refactoring_config",
        return_value=RefactoringConfig(
            feature_flags=FeatureFlags(use_research_data_pack=True),
        ),
    ):
        result = service._prepare_data("600000.SH")

    assert isinstance(result, ResearchDataPack)
    assert result.stock_df is stock_df
    data_service.fetch_research_pack.assert_called_once_with("600000.SH")


def test_data_pack_routing_dict_path_disabled():
    """use_research_data_pack=False -> _prepare_data returns dict"""
    data_service = _make_mock_data_service()
    service = AnalysisService(data_service=data_service)

    result = service._prepare_data("600000.SH")

    assert isinstance(result, dict)
    assert "stock" in result
    data_service.fetch_for_brain.assert_called_once_with("600000.SH")


def test_data_pack_routing_typed_through_run_ticker_analysis():
    """Full run with use_research_data_pack=True produces ResearchDataPack result"""
    data_service = _make_mock_data_service()
    stock_df = pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]})
    typed_pack = ResearchDataPack(symbol="600000.SH", stock_df=stock_df)
    data_service.fetch_research_pack = Mock(return_value=typed_pack)

    factory = _make_engine_factory(**_BASIC_ENGINES)
    service = AnalysisService(data_service=data_service, engine_factory=factory)

    with patch(
        "uniquant.services.analysis_service_v2.load_refactoring_config",
        return_value=RefactoringConfig(
            feature_flags=FeatureFlags(use_research_data_pack=True),
        ),
    ):
        result = service.run_ticker_analysis("600000.SH")

    assert result.success is True
    assert isinstance(result.data_pack, ResearchDataPack)
    assert result.data_pack.symbol == "600000.SH"


def test_data_pack_routing_dict_through_run_ticker_analysis():
    """Full run with use_research_data_pack=False produces dict result"""
    data_service = _make_mock_data_service()
    factory = _make_engine_factory(**_BASIC_ENGINES)
    service = AnalysisService(data_service=data_service, engine_factory=factory)

    result = service.run_ticker_analysis("600000.SH")

    assert result.success is True
    assert isinstance(result.data_pack, dict)