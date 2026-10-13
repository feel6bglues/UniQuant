"""Tests for env_config, loader, market_constants, perf."""

import os


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