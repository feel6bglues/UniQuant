import importlib as _importlib
import pytest
from unittest.mock import MagicMock, patch

_mock_module = MagicMock()
for _cls_name in [
    "FsmAnalysisEngine",
    "CzscAnalysisEngine",
    "LpplAnalysisEngine",
    "RegimeAnalysisEngine",
    "NtfAnalysisEngine",
    "MacroAnalysisEngine",
    "ReportGeneratorEngine",
]:
    _engine_cls = MagicMock()
    _engine_instance = MagicMock()
    _engine_cls.return_value = _engine_instance
    setattr(_mock_module, _cls_name, _engine_cls)


@pytest.fixture(autouse=True)
def mock_imports():
    _original_import_module = _importlib.import_module

    def _side_effect(name, package=None):
        if package == "uniquant.services.analysis":
            return _mock_module
        return _original_import_module(name, package)

    with patch("importlib.import_module", side_effect=_side_effect):
        yield


@pytest.fixture
def factory():
    from uniquant.services.analysis.engine_factory import AnalysisEngineFactory

    orch = MagicMock()
    return AnalysisEngineFactory(orchestrator=orch)


class TestEngineFactory:
    def test_initialization(self, factory):
        assert factory._engines == {}

    def test_properties_exist(self, factory):
        assert hasattr(factory, "fsm")
        assert hasattr(factory, "czsc")
        assert hasattr(factory, "lppl")
        assert hasattr(factory, "regime")
        assert hasattr(factory, "ntf")
        assert hasattr(factory, "macro")
        assert hasattr(factory, "report")

    def test_delayed_init(self, factory):
        assert "czsc" not in factory._engines
        _ = factory.czsc
        assert "czsc" in factory._engines

    def test_cached_after_access(self, factory):
        e1 = factory.fsm
        e2 = factory.fsm
        assert e1 is e2

    def test_import_error_isolated(self, factory):
        with patch.object(factory, "_lazy_init") as mock_lazy:
            mock_lazy.side_effect = lambda name, *a, **kw: None if name == "fsm" else MagicMock()
            assert factory.fsm is None
            assert factory.czsc is not None

    def test_data_service_passed_to_engine(self, factory):
        mock_cls = _mock_module.FsmAnalysisEngine
        mock_cls.reset_mock()
        factory._engines.clear()
        _ = factory.fsm
        mock_cls.assert_called_once_with(orchestrator=factory._orchestrator)
