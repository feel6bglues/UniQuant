import pytest
from unittest.mock import MagicMock, patch

from uniquant.services.service_container import ServiceContainer


class TestServiceContainer:
    def setup_method(self):
        ServiceContainer._instance = None
        self.container = ServiceContainer.instance()

    def teardown_method(self):
        ServiceContainer._instance = None

    def test_singleton(self):
        c2 = ServiceContainer.instance()
        assert self.container is c2

    def test_register_and_get(self):
        mock = MagicMock()
        self.container.register("test_svc", mock)
        assert self.container.get("test_svc") is mock

    def test_get_nonexistent(self):
        assert self.container.get("nonexistent") is None

    def test_reset_clears(self):
        self.container.register("x", MagicMock())
        self.container.reset()
        assert self.container.get("x") is None

    def test_clear_removes_all(self):
        self.container.register("a", MagicMock())
        self.container.register("b", MagicMock())
        self.container.clear()
        assert self.container.get("a") is None
        assert self.container.get("b") is None

    def test_register_overwrite(self):
        a, b = MagicMock(), MagicMock()
        self.container.register("x", a)
        self.container.register("x", b)
        assert self.container.get("x") is b

    @patch("uniquant.services.service_container.StorageManager")
    @patch("uniquant.services.service_container.TradeCalendarManager")
    @patch("uniquant.services.data_service.DataService")
    @patch("uniquant.services.cache_coordinator.CacheCoordinator")
    @patch("uniquant.services.stock_query_service.StockQueryService")
    @patch("uniquant.services.analysis.engine_factory.AnalysisEngineFactory")
    def test_initialization_topology(
        self,
        mock_engine_factory,
        mock_stock_query_cls,
        mock_cache_coord_cls,
        mock_data_svc_cls,
        mock_calendar,
        mock_storage,
    ):
        self.container.initialize()

        assert self.container.get("storage") is not None
        assert self.container.get("calendar") is not None
        assert self.container.get("cache") is not None
        assert self.container.get("data_service") is not None
        assert self.container.get("engine_factory") is not None
