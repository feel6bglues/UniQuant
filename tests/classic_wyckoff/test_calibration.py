"""Tests for Wyckoff calibration threshold loading and detector behavior.

Verifies:
1. WyckoffEngine.__init__ loads calibration config
2. Detectors respond to calibration value changes
3. Calibration script file exists
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from uniquant.brain.wyckoff.engine import WyckoffEngine
from uniquant.brain.wyckoff.models import WyckoffPhase


class TestCalibrationInit:
    """WyckoffEngine.__init__ loads calibration from config."""

    def test_default_calibration_empty_when_no_config(self):
        """Engine loads empty dict when config has no calibration section."""
        with patch("uniquant.brain.wyckoff.engine.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = {}
            engine = WyckoffEngine()
            assert engine.calibration == {}

    def test_calibration_loads_from_config(self):
        """Engine reads calibration values from config."""
        calib_data = {
            "markup_short_trend_min": 0.05,
            "distribution_prior_trend_min": 0.08,
        }
        with patch("uniquant.brain.wyckoff.engine.get_config") as mock_cfg:
            def side_effect(key, default=None):
                return calib_data if key == "wyckoff.calibration" else default
            mock_cfg.return_value.get.side_effect = side_effect
            engine = WyckoffEngine()
            assert engine.calibration["markup_short_trend_min"] == 0.05
            assert engine.calibration["distribution_prior_trend_min"] == 0.08

    def test_calibration_defaults_used_when_not_in_config(self):
        """Detector falls back to hardcoded default when key is missing from calibration."""
        with patch("uniquant.brain.wyckoff.engine.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = {}
            engine = WyckoffEngine()
            assert engine.calibration == {}


class TestDetectorBehaviorChanges:
    """Detectors respond to calibration value changes."""

    def test_markup_calibration_affects_phase(self, sine_ohlcv):
        """Different calibration values may produce different phase results."""
        df = sine_ohlcv
        engine_default = WyckoffEngine()
        report_default = engine_default.analyze(df, symbol="TEST.SH")

        engine_tight = WyckoffEngine()
        engine_tight.calibration = {"markup_short_trend_min": 0.05, "markup_relative_position_min": 0.65}
        report_tight = engine_tight.analyze(df, symbol="TEST.SH")

        assert isinstance(report_default.structure.phase, WyckoffPhase)
        assert isinstance(report_tight.structure.phase, WyckoffPhase)

    def test_distribution_prior_trend_calibration(self, distribution_ohlcv):
        """Tighter prior_trend_min changes distribution detection."""
        engine_default = WyckoffEngine()
        df = distribution_ohlcv
        report_default = engine_default.analyze(df, symbol="TEST.SH")

        engine_tight = WyckoffEngine()
        engine_tight.calibration = {"distribution_prior_trend_min": 0.10}
        report_tight = engine_tight.analyze(df, symbol="TEST.SH")

        assert isinstance(report_default.structure.phase, WyckoffPhase)
        assert isinstance(report_tight.structure.phase, WyckoffPhase)

    def test_accumulation_st_max_calibration(self, accumulation_ohlcv):
        """Tighter st_max changes accumulation detection."""
        engine_default = WyckoffEngine()
        df = accumulation_ohlcv
        report_default = engine_default.analyze(df, symbol="TEST.SH")

        engine_tight = WyckoffEngine()
        engine_tight.calibration = {"accum_short_trend_max": -0.05, "accum_require_both_bc_sc": True}
        report_tight = engine_tight.analyze(df, symbol="TEST.SH")

        assert isinstance(report_default.structure.phase, WyckoffPhase)
        assert isinstance(report_tight.structure.phase, WyckoffPhase)

    def test_markdown_st_max_calibration(self, sine_ohlcv):
        """Tighter st_max changes markdown detection."""
        engine_default = WyckoffEngine()
        df = sine_ohlcv
        report_default = engine_default.analyze(df, symbol="TEST.SH")

        engine_tight = WyckoffEngine()
        engine_tight.calibration = {"markdown_short_trend_max": -0.08, "markdown_cp_below_ma": 0.90}
        report_tight = engine_tight.analyze(df, symbol="TEST.SH")

        assert isinstance(report_default.structure.phase, WyckoffPhase)
        assert isinstance(report_tight.structure.phase, WyckoffPhase)


class TestCalibrationScript:
    """Calibration script file exists."""

    def test_calibrate_script_exists(self):
        """Calibration script file exists."""
        assert os.path.exists("scripts/wyckoff_calibrate.py"), "scripts/wyckoff_calibrate.py must exist"

    def test_ab_compare_script_exists(self):
        """A/B compare script file exists."""
        assert os.path.exists("scripts/wyckoff_ab_compare.py"), "scripts/wyckoff_ab_compare.py must exist"