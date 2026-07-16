"""Tests for optimal_params, env_config, loader, market_constants, network_constants, perf,
and small service files (market_regime_service, report_service, signal_generation_service)."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from uniquant.shared.optimal_params import (
    ALLOWED_KEYS,
    _as_bool,
    _as_float,
    _as_non_negative_float,
    _as_positive_int,
    _as_unit_float,
    load_optimal_config,
    resolve_symbol_params,
)

FALLBACK = {
    "step": 1,
    "window_range": [5, 60],
    "r2_threshold": 0.75,
    "danger_r2_offset": 0.0,
    "consensus_threshold": 0.25,
    "danger_days": 5,
    "warning_days": 10,
    "watch_days": 15,
    "warning_trade_enabled": True,
    "full_exit_days": 3,
    "optimizer": "bayesian",
    "lookahead_days": 3,
    "drop_threshold": 0.1,
    "ma_window": 20,
    "max_peaks": 5,
    "signal_model": "multi_factor_v1",
    "initial_position": 0.0,
}

DEFAULT_YAML = {
    "defaults": {"step": 2, "r2_threshold": 0.8},
    "window_sets": {"fast": [5, 30]},
    "symbols": {
        "000001.SZ": {"step": 3, "window_set": "fast", "optimizer": "genetic"},
    },
}


class TestHelpers:
    def test_as_positive_int_valid(self):
        assert _as_positive_int("10", "k", [], 1) == 10
        assert _as_positive_int(5, "k", [], 1) == 5

    def test_as_positive_int_non_positive(self):
        w = []
        assert _as_positive_int(0, "k", w, 99) == 99
        assert len(w) == 1

    def test_as_positive_int_invalid(self):
        w = []
        assert _as_positive_int("abc", "k", w, 99) == 99
        assert len(w) == 1

    def test_as_unit_float_valid(self):
        assert _as_unit_float("0.5", "k", [], 0.0) == 0.5
        assert _as_unit_float(1.0, "k", [], 0.0) == 1.0
        assert _as_unit_float(0.0, "k", [], 0.5) == 0.0

    def test_as_unit_float_out_of_range(self):
        w = []
        assert _as_unit_float(1.5, "k", w, 0.5) == 0.5
        assert len(w) == 1

    def test_as_unit_float_invalid(self):
        w = []
        assert _as_unit_float("bad", "k", w, 0.5) == 0.5
        assert len(w) == 1

    def test_as_float_valid(self):
        assert _as_float("3.14", "k", [], 0.0) == 3.14
        assert _as_float(-1.0, "k", [], 0.0) == -1.0

    def test_as_float_invalid(self):
        w = []
        assert _as_float(None, "k", w, 42.0) == 42.0
        assert len(w) == 1

    def test_as_non_negative_float_valid(self):
        assert _as_non_negative_float("0.0", "k", [], 1.0) == 0.0
        assert _as_non_negative_float(5.0, "k", [], 1.0) == 5.0

    def test_as_non_negative_float_negative(self):
        w = []
        assert _as_non_negative_float(-1.0, "k", w, 2.0) == 2.0
        assert len(w) == 1

    def test_as_non_negative_float_invalid(self):
        w = []
        assert _as_non_negative_float("x", "k", w, 2.0) == 2.0
        assert len(w) == 1

    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, False),
            (True, True),
            (False, False),
            ("1", True),
            ("true", True),
            ("yes", True),
            ("y", True),
            ("on", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("off", False),
            (1, True),
            (0, False),
        ],
    )
    def test_as_bool(self, value, expected):
        assert _as_bool(value, False) == expected


class TestLoadOptimalConfig:
    def test_load_valid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(DEFAULT_YAML, f)
            p = f.name
        try:
            cfg = load_optimal_config(p)
            assert cfg["defaults"] == {"step": 2, "r2_threshold": 0.8}
            assert "window_sets" in cfg
            assert "symbols" in cfg
        finally:
            os.unlink(p)

    def test_load_empty_config(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({}, f)
            p = f.name
        try:
            cfg = load_optimal_config(p)
            assert cfg["defaults"] == {}
            assert cfg["window_sets"] == {}
            assert cfg["symbols"] == {}
        finally:
            os.unlink(p)

    def test_load_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            p = f.name
        try:
            cfg = load_optimal_config(p)
            assert cfg["defaults"] == {}
        finally:
            os.unlink(p)

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_optimal_config("/nonexistent/path.yaml")

    def test_load_non_dict_root(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(["a", "b"], f)
            p = f.name
        try:
            with pytest.raises(ValueError, match="根节点必须是字典"):
                load_optimal_config(p)
        finally:
            os.unlink(p)


class TestResolveSymbolParams:
    def test_symbol_not_found(self):
        config_data = {"defaults": {}, "symbols": {}, "window_sets": {}}
        result, warnings = resolve_symbol_params(config_data, "999999.SZ", FALLBACK)
        assert result["param_source"] == "default_fallback"
        assert len(warnings) == 1

    def test_symbol_with_config(self):
        result, _ = resolve_symbol_params(DEFAULT_YAML, "000001.SZ", FALLBACK)
        assert result["step"] == 3
        assert result["optimizer"] == "genetic"
        assert result["window_range"] == [5, 30]
        assert result["param_source"] == "optimal_yaml"

    def test_defaults_applied(self):
        result, _ = resolve_symbol_params(DEFAULT_YAML, "000001.SZ", FALLBACK)
        assert result["r2_threshold"] == 0.8

    def test_fallback_for_missing_keys(self):
        result, _ = resolve_symbol_params(DEFAULT_YAML, "000001.SZ", FALLBACK)
        assert result["ma_window"] == 20
        assert result["max_peaks"] == 5

    def test_window_set_undefined(self):
        config_data = {
            "defaults": {},
            "window_sets": {},
            "symbols": {"000001.SZ": {"window_set": "nonexistent"}},
        }
        result, warnings = resolve_symbol_params(config_data, "000001.SZ", FALLBACK)
        assert result["window_set"] == "default_fallback"
        assert result["window_range"] == list(FALLBACK["window_range"])

    def test_warning_days_ordering(self):
        config_data = {
            "defaults": {},
            "window_sets": {},
            "symbols": {"000001.SZ": {"danger_days": 10, "warning_days": 5}},
        }
        result, _ = resolve_symbol_params(config_data, "000001.SZ", FALLBACK)
        assert result["warning_days"] >= result["danger_days"] + 1

    def test_watch_days_ordering(self):
        config_data = {
            "defaults": {},
            "window_sets": {},
            "symbols": {"000001.SZ": {"danger_days": 3, "warning_days": 5, "watch_days": 4}},
        }
        result, _ = resolve_symbol_params(config_data, "000001.SZ", FALLBACK)
        assert result["watch_days"] >= result["warning_days"] + 1

    def test_invalid_values_fallback(self):
        config_data = {
            "defaults": {},
            "window_sets": {},
            "symbols": {"000001.SZ": {"step": -1, "r2_threshold": "bad", "ma_window": 0}},
        }
        result, warnings = resolve_symbol_params(config_data, "000001.SZ", FALLBACK)
        assert result["step"] == FALLBACK["step"]
        assert result["r2_threshold"] == FALLBACK["r2_threshold"]
        assert result["ma_window"] == FALLBACK["ma_window"]
        assert len(warnings) >= 3

    def test_watch_days_defaults_to_warning_days(self):
        config_data = {
            "defaults": {},
            "window_sets": {},
            "symbols": {"000001.SZ": {"danger_days": 3, "warning_days": 7}},
        }
        result, _ = resolve_symbol_params(config_data, "000001.SZ", FALLBACK)
        assert result["watch_days"] >= 8


class TestEnvConfig:
    def test_import(self):
        import uniquant.shared.env_config as mod
        assert callable(mod.configure_environment)

    def test_configure_environment(self):
        from uniquant.shared.env_config import configure_environment
        key = "OMP_NUM_THREADS"
        original = os.environ.pop(key, None)
        try:
            configure_environment()
            assert os.environ[key] == "1"
        finally:
            if original is not None:
                os.environ[key] = original
            else:
                os.environ.pop(key, None)


class TestLoader:
    def test_import(self):
        from uniquant.shared.loader import load_strategy_weights
        assert callable(load_strategy_weights)

    def test_load_strategy_weights_nonexistent(self):
        from uniquant.shared.loader import load_strategy_weights
        assert load_strategy_weights("/nonexistent/path.yaml") is None


class TestMarketConstants:
    def test_import(self):
        import uniquant.shared.market_constants as mod
        assert "sz" in mod.A_SHARE_BOARDS
        assert "sh" in mod.A_SHARE_BOARDS
        assert "bj" in mod.A_SHARE_BOARDS
        assert mod.A_SHARD_BOARDS is mod.A_SHARE_BOARDS


class TestNetworkConstants:
    def test_import(self):
        import uniquant.shared.network_constants as mod
        assert mod.MAX_RETRIES == 3
        assert mod.RETRY_DELAY_BASE == 1.0


class TestPerf:
    def test_import(self):
        import uniquant.shared.perf as mod
        assert callable(mod.perf_section)
        assert callable(mod.perf_report)
        assert callable(mod.perf_reset)

    def test_perf_report_and_reset(self, monkeypatch):
        monkeypatch.setenv("UNIQUANT_PERF", "1")
        import importlib
        import uniquant.shared.perf as mod
        importlib.reload(mod)

        mod.perf_reset()
        with mod.perf_section("test_op"):
            pass
        report = mod.perf_report()
        assert "test_op" in report
        assert report["test_op"]["calls"] == 1
        assert report["test_op"]["total_ms"] >= 0

        mod.perf_reset()
        assert mod.perf_report() == {}

    def test_perf_disabled(self, monkeypatch):
        monkeypatch.setenv("UNIQUANT_PERF", "0")
        import importlib
        import uniquant.shared.perf as mod
        importlib.reload(mod)

        mod.perf_reset()
        with mod.perf_section("disabled_op"):
            pass
        assert mod.perf_report() == {}

    def test_perf_section_yields_without_env(self, monkeypatch):
        monkeypatch.delenv("UNIQUANT_PERF", raising=False)
        import importlib
        import uniquant.shared.perf as mod
        importlib.reload(mod)

        mod.perf_reset()
        with mod.perf_section("no_env_op"):
            pass
        assert mod.perf_report() == {}


class TestMarketRegimeService:
    def test_import(self):
        from uniquant.services.market_regime_service import MarketRegimeService, RegimeResult
        assert MarketRegimeService is not None
        assert RegimeResult is not None

    def test_init(self):
        from uniquant.services.market_regime_service import MarketRegimeService
        svc = MarketRegimeService()
        assert svc._analysis_service is None

    def test_init_with_analysis_service(self):
        from uniquant.services.market_regime_service import MarketRegimeService
        svc = MarketRegimeService(analysis_service="mock")
        assert svc._analysis_service == "mock"

    def test_detect_regime_returns_unknown(self, sample_ohlcv_data):
        from uniquant.services.market_regime_service import MarketRegimeService
        svc = MarketRegimeService()
        result = svc.detect_regime(sample_ohlcv_data, "000001.SZ")
        assert result.regime == "unknown"
        assert result.confidence == 0.0
        assert result.details == {}

    def test_detect_intervention(self, sample_ohlcv_data):
        from uniquant.services.market_regime_service import MarketRegimeService
        svc = MarketRegimeService()
        result = svc.detect_intervention(sample_ohlcv_data)
        assert result == {"detected": False}

    def test_detect_bubble(self, sample_ohlcv_data):
        from uniquant.services.market_regime_service import MarketRegimeService
        svc = MarketRegimeService()
        result = svc.detect_bubble(sample_ohlcv_data, "000001.SZ")
        assert result == {"bubble": False}


class TestReportService:
    def test_import(self):
        from uniquant.services.report_service import ReportService
        assert ReportService is not None

    def test_init(self):
        from uniquant.services.report_service import ReportService
        svc = ReportService()
        assert isinstance(svc, ReportService)

    def test_generate_report(self):
        from uniquant.services.report_service import ReportService
        svc = ReportService()
        result = svc.generate_report({"key": "val"}, "000001.SZ")
        assert result == "Report for 000001.SZ: OK"


class TestSignalGenerationService:
    def test_import(self):
        from uniquant.services.signal_generation_service import SignalGenerationService
        assert SignalGenerationService is not None

    def test_init(self):
        from uniquant.services.signal_generation_service import SignalGenerationService
        svc = SignalGenerationService()
        assert isinstance(svc, SignalGenerationService)

    def test_generate_signals(self, sample_ohlcv_data):
        from uniquant.services.signal_generation_service import SignalGenerationService
        svc = SignalGenerationService()
        result = svc.generate_signals(sample_ohlcv_data, "000001.SZ")
        assert result["symbol"] == "000001.SZ"
        assert result["signals"] == {}