from __future__ import annotations

from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.factors.registry import FactorRegistry
from uniquant.hands.backtest.monte_carlo import MonteCarloSimulator
from uniquant.services.analysis.macro_analysis_engine import MacroAnalysisEngine
from uniquant.services.analysis.macro_service import MacroAnalysisService


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


def test_macro_service_empty_real_returns_does_not_generate_random_fallback(monkeypatch):
    service = MacroAnalysisService()
    monkeypatch.setattr(service, "get_macro_returns", lambda window=200: pd.Series(dtype=float))

    def fail_if_random_is_used(*args, **kwargs):
        raise AssertionError("random fallback should not be used")

    monkeypatch.setattr("numpy.random.normal", fail_if_random_is_used)

    result = service.analyze_macro_health()

    assert result["status"] == "failed"
    assert result["error"] == "DATA_UNAVAILABLE"
    assert result["regime"] == "UNKNOWN"


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


def test_monte_carlo_default_seed_is_reproducible_independent_of_global_rng():
    returns = pd.Series(np.linspace(-0.02, 0.03, 80))
    equity = (1 + returns).cumprod() * 100_000

    np.random.seed(1)
    mc_a = MonteCarloSimulator(n_simulations=40)
    shuffle_a = mc_a.run_shuffle(returns)
    bootstrap_a = mc_a.run_bootstrap(equity)

    np.random.seed(999)
    mc_b = MonteCarloSimulator(n_simulations=40)
    shuffle_b = mc_b.run_shuffle(returns)
    bootstrap_b = mc_b.run_bootstrap(equity)

    assert shuffle_a["mean_simulated_sharpe"] == shuffle_b["mean_simulated_sharpe"]
    assert shuffle_a["confidence_interval"] == shuffle_b["confidence_interval"]
    assert bootstrap_a["mean_simulated_final"] == bootstrap_b["mean_simulated_final"]
    assert bootstrap_a["final_equity_ci"] == bootstrap_b["final_equity_ci"]
