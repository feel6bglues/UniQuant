from __future__ import annotations

from unittest.mock import Mock

import pandas as pd
import pytest

from uniquant.brain.factors.registry import FactorRegistry
from uniquant.services.analysis.macro_analysis_engine import MacroAnalysisEngine


def test_data_aligner_removed_leading_suspension_no_backfill():
    """Step4 S4a: DataAligner 已删除 — 原“前导停牌日不 bfill 价格”契约随之移除,
    数据不齐改由 DataCleaner/DataValidator fail-fast 处理。"""
    import importlib.util

    assert importlib.util.find_spec("uniquant.data.pipeline.data_aligner") is None


def test_factor_registry_config_loader_failure_is_not_silent(monkeypatch):
    from uniquant.brain.factors.registry import FactorAccessLevel
    saved_mode = FactorRegistry.get_mode()
    FactorRegistry.set_mode(FactorAccessLevel.FREE)
    try:
        FactorRegistry._factors.clear()

        def broken_config_loader():
            raise RuntimeError("bad factors config")

        monkeypatch.setattr(
            "uniquant.shared.config_loader.get_config",
            broken_config_loader,
        )

        with pytest.raises(RuntimeError, match="bad factors config"):
            FactorRegistry.register("broken_factor", lambda df: df["close"])

        assert FactorRegistry.get_factor("broken_factor") is None
    finally:
        FactorRegistry.set_mode(saved_mode)


class _MacroEngineOrchestrator:
    def __init__(self) -> None:
        self.evt_risk = Mock()
        self.validation_service = None

    def _generate_cache_key(self, prefix: str, **kwargs) -> str:
        return f"{prefix}:{kwargs}"

    def _get_cached_result(self, cache_key: str, use_disk: bool = False):
        return None

    def _set_cached_result(self, cache_key: str, result, use_disk: bool = False, ttl=None):
        return True

    def validate_risk_metrics(self, metrics):
        return True


def test_macro_engine_empty_real_returns_does_not_generate_random_fallback(monkeypatch):
    engine = MacroAnalysisEngine(_MacroEngineOrchestrator())
    monkeypatch.setattr(engine, "get_macro_returns", lambda window=200: pd.Series(dtype=float))

    def fail_if_random_is_used(*args, **kwargs):
        raise AssertionError("random fallback should not be used")

    monkeypatch.setattr("numpy.random.normal", fail_if_random_is_used)

    result = engine.analyze_macro_health()

    assert result["status"] == "failed"
    assert result["error"] == "DATA_UNAVAILABLE"
    assert result["regime"] == "UNKNOWN"
