from __future__ import annotations

from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.factors.registry import FactorRegistry
from uniquant.data.pipeline.data_aligner import DataAligner
from uniquant.hands.backtest.monte_carlo import MonteCarloSimulator
from uniquant.services.analysis.macro_analysis_engine import MacroAnalysisEngine
from uniquant.services.analysis.macro_service import MacroAnalysisService


class _DummyCalendar:
    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            {"trade_date": pd.to_datetime(["2024-01-02", "2024-01-03"])}
        )


class _DummyMetadata:
    def get_stock_info(self, symbol: str):
        return None


def test_data_aligner_does_not_backfill_leading_suspension_prices():
    aligner = object.__new__(DataAligner)
    aligner.calendar_manager = _DummyCalendar()
    aligner.metadata_manager = _DummyMetadata()

    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-03"]),
            "code": ["600000"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "volume": [1000.0],
            "amount": [10200.0],
        }
    )

    result = aligner.align_stock_data("600000.SH", raw)

    first = result.loc[result["date"] == pd.Timestamp("2024-01-02")].iloc[0]
    assert pd.isna(first["open"])
    assert pd.isna(first["high"])
    assert pd.isna(first["low"])
    assert pd.isna(first["close"])
    assert first["volume"] == 0.0
    assert first["amount"] == 0.0


def test_factor_registry_config_loader_failure_is_not_silent(monkeypatch):
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
