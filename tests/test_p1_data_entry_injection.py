from __future__ import annotations

import threading

import pandas as pd

from uniquant.data.data_fetcher import DataFetcher
from uniquant.data.lake.storage_manager import StorageManager
from uniquant.services.analysis.macro_service import MacroAnalysisService
from uniquant.services import analysis_service_legacy
from uniquant.services.analysis_service_v2 import AnalysisService
from uniquant.services.data_service import DataService
from uniquant.services.service_container import ServiceContainer


class _DummyFetcher:
    pass


class _DummyLake:
    def __init__(self):
        self.reads = []

    def read_data(self, symbol, data_type="stock", market="cn"):
        self.reads.append((symbol, data_type, market))
        return pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3), "close": [1.0, 2.0, 3.0]})


class _DummyDataService:
    def __init__(self):
        self.fetcher = _DummyFetcher()
        self.lake = _DummyLake()
        self.storage_manager = self.lake


def test_data_fetcher_pipeline_reuses_injected_storage_manager(tmp_path):
    storage = StorageManager(str(tmp_path / "data"))

    fetcher = DataFetcher(data_dir=str(tmp_path / "ignored"), storage_manager=storage)

    assert fetcher.storage_manager is storage
    assert fetcher.data_adjuster.storage_manager is storage
    assert fetcher.adjust_factor_manager.storage_manager is storage
    assert fetcher.pipeline.adjuster.storage_manager is storage


def test_data_service_default_fetcher_reuses_service_storage_manager(tmp_path):
    storage = StorageManager(str(tmp_path / "data"))

    service = DataService(storage_manager=storage)

    assert service.storage_manager is storage
    assert service.fetcher.storage_manager is storage
    assert service.fetcher.pipeline.adjuster.storage_manager is storage


def test_service_container_uses_one_storage_graph():
    ServiceContainer._instance = None
    container = ServiceContainer.instance()

    container.initialize()

    storage = container.get("storage")
    data_service = container.get("data_service")
    analysis_service = container.get("analysis_service")

    assert data_service.storage_manager is storage
    assert data_service.fetcher.storage_manager is storage
    assert data_service.fetcher.pipeline.adjuster.storage_manager is storage
    assert analysis_service.data_service is data_service

    ServiceContainer._instance = None


def test_analysis_service_ntf_uses_injected_data_fetcher(monkeypatch):
    data_service = _DummyDataService()
    service = AnalysisService(data_service=data_service, engine_factory=None)
    data_pack = {}

    def detect_intervention_from_data(self, fetcher, symbol, start_date, end_date):
        assert fetcher is data_service.fetcher
        return {"side": "BUY", "intensity": 0.7, "action": "WATCH"}

    monkeypatch.setattr(
        "uniquant.brain.ntf.ntf_engine.NTFEngine.detect_intervention_from_data",
        detect_intervention_from_data,
    )

    service._run_ntf("000001.SZ", data_pack)

    assert data_pack["ntf_side"] == "BUY"
    assert data_pack["ntf_intensity"] == 0.7
    assert data_pack["ntf_action"] == "WATCH"


def test_analysis_service_alpha_uses_injected_lake(monkeypatch):
    data_service = _DummyDataService()
    service = AnalysisService(data_service=data_service, engine_factory=None)
    data_pack = {
        "stock": pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=3), "close": [1.0, 1.1, 1.2]}
        )
    }

    monkeypatch.setattr(
        "uniquant.brain.alpha_decoupler.alpha_decoupler.AlphaDecoupler.get_alpha_score",
        lambda stock_df, bench, sector: 0.42,
    )

    service._run_alpha(data_pack)

    assert data_pack["alpha_score"] == 0.42
    assert ("000300.SH", "index", "cn") in data_service.lake.reads
    assert ("000905.SH", "index", "cn") in data_service.lake.reads


def test_macro_service_ntf_signals_use_injected_data_fetcher(monkeypatch):
    data_service = _DummyDataService()
    service = MacroAnalysisService(data_service=data_service)
    data_pack = {}

    def detect_intervention_from_data(self, fetcher, symbol, start_date, end_date):
        assert fetcher is data_service.fetcher
        return {"side": "SELL", "intensity": 0.3, "action": "REDUCE"}

    monkeypatch.setattr(
        "uniquant.brain.ntf.ntf_engine.NTFEngine.detect_intervention_from_data",
        detect_intervention_from_data,
    )

    service.detect_ntf_signals(data_pack)

    assert data_pack["ntf_side"] == "SELL"
    assert data_pack["ntf_intensity"] == 0.3
    assert data_pack["ntf_action"] == "REDUCE"


def test_legacy_analysis_service_ntf_uses_injected_data_fetcher(monkeypatch):
    data_service = _DummyDataService()
    service = object.__new__(analysis_service_legacy.AnalysisService)
    service.data_service = data_service
    service._cache_lock = threading.Lock()
    service._market_cache_date = None
    service._ntf_signals = None
    data_pack = {}

    def detect_intervention_from_data(self, fetcher, symbol, start_date, end_date):
        assert fetcher is data_service.fetcher
        return {"side": "BUY", "intensity": 0.9, "action": "FOLLOW"}

    monkeypatch.setattr(
        "uniquant.brain.ntf.ntf_engine.NTFEngine.detect_intervention_from_data",
        detect_intervention_from_data,
    )

    service._run_ntf_detection("000001.SZ", data_pack)

    assert data_pack["ntf_side"] == "BUY"
    assert data_pack["ntf_intensity"] == 0.9
    assert data_pack["ntf_action"] == "FOLLOW"


def test_legacy_analysis_service_alpha_uses_injected_lake(monkeypatch):
    data_service = _DummyDataService()
    service = object.__new__(analysis_service_legacy.AnalysisService)
    service.data_service = data_service
    data_pack = {
        "stock": pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=3), "close": [1.0, 1.1, 1.2]}
        )
    }

    monkeypatch.setattr(
        "uniquant.brain.alpha_decoupler.alpha_decoupler.AlphaDecoupler.get_alpha_score",
        lambda stock_df, bench, sector: 0.55,
    )

    service._run_alpha_analysis(data_pack)

    assert data_pack["alpha_score"] == 0.55
    assert ("000300.SH", "index", "cn") in data_service.lake.reads
    assert ("000905.SH", "index", "cn") in data_service.lake.reads
