import warnings

import numpy as np
import pandas as pd

from uniquant.brain.ntf.ntf_engine import NTFEngine
from uniquant.brain.regime.regime_detector import Regime, RegimeDetector


class _Fetcher:
    def __init__(self, df):
        self.df = df

    def fetch_history(self, *args, **kwargs):
        return self.df


class TestNTFEngineAdditional:
    def test_detect_intervention_side_variants_and_action_desc(self):
        engine = NTFEngine(volume_ratio_threshold=2.0)
        base = pd.DataFrame(
            {
                "close": [10.0] * 29 + [8.0],
                "volume": [100.0] * 29 + [300.0],
            }
        )
        support = engine.detect_intervention(base, window=5)
        assert bool(support["detected"]) is True
        assert support["side"] == "SUPPORT"
        assert support["action"]

        resistance_df = pd.DataFrame(
            {
                "close": [10.0] * 29 + [12.0],
                "volume": [100.0] * 29 + [300.0],
            }
        )
        resistance = engine.detect_intervention(resistance_df, window=5)
        assert resistance["side"] == "RESISTANCE"

        middle_df = pd.DataFrame(
            {
                "close": list(range(1, 30)) + [15],
                "volume": [100.0] * 29 + [300.0],
            }
        )
        pulse = engine.detect_intervention(middle_df, window=5)
        assert pulse["side"] == "LIQUIDITY_PULSE"
        assert engine._get_action_desc("UNKNOWN") == ""

    def test_scan_for_giants_and_detect_from_data(self):
        engine = NTFEngine(volume_ratio_threshold=2.0)
        engine.critical_etfs = {"510300.SH": "CSI300"}
        df = pd.DataFrame(
            {
                "Date": pd.date_range("2026-04-01", periods=30),
                "Close": [10.0] * 29 + [8.0],
                "Volume": [100.0] * 29 + [300.0],
            }
        )

        results = engine.scan_for_giants({"510300.SH": df, "159001.SZ": df})
        assert list(results.keys()) == ["510300.SH"]

        fetched = engine.detect_intervention_from_data(_Fetcher(df), "510300.SH", "2026-01-01", "2026-04-01", window=5)
        assert bool(fetched["detected"]) is True

        missing = engine.detect_intervention_from_data(_Fetcher(pd.DataFrame()), "510300.SH", "2026-01-01", "2026-04-01")
        assert missing["action"] == "无法获取数据"

        wrong_cols = engine.detect_intervention_from_data(_Fetcher(pd.DataFrame({"close": [1, 2, 3]})), "510300.SH", "2026-01-01", "2026-04-01")
        assert wrong_cols["action"] == "数据缺少必要列"


class TestRegimeDetectorAdditional:
    def test_validate_input_data_and_detect_special_cases(self, monkeypatch):
        detector = RegimeDetector(min_data_points=10)
        valid = pd.DataFrame({"close": range(12), "volume": range(12)})
        assert detector._validate_input_data(None) is False
        assert detector._validate_input_data([]) is False
        assert detector._validate_input_data(pd.DataFrame()) is False
        assert detector._validate_input_data(pd.DataFrame({"close": [1] * 5, "volume": [1] * 5})) is False
        assert detector._validate_input_data(pd.DataFrame({"close": [1] * 12})) is False
        assert detector._validate_input_data(pd.DataFrame({"close": [np.nan] * 12, "volume": [1] * 12})) is False
        assert detector._validate_input_data(valid) is True

        short = pd.DataFrame({"close": [1.0] * 5, "volume": [1.0] * 5})
        assert detector.detect(short) is Regime.NORMAL

        monkeypatch.setattr("uniquant.brain.regime.regime_detector.Indicators.calc_market_entropy", lambda df: pd.Series(dtype=float))
        monkeypatch.setattr("uniquant.brain.regime.regime_detector.Indicators.calc_turnover_z", lambda df: pd.Series(dtype=float))
        assert detector.detect(valid) is Regime.NORMAL

    def test_detect_regime_paths_and_summary(self, monkeypatch):
        detector = RegimeDetector(min_data_points=10)
        df = pd.DataFrame({"close": range(60), "volume": range(60)})

        monkeypatch.setattr("uniquant.brain.regime.regime_detector.Indicators.calc_market_entropy", lambda _: pd.Series([0.1] * 60))
        monkeypatch.setattr("uniquant.brain.regime.regime_detector.Indicators.calc_turnover_z", lambda _: pd.Series([0.0] * 60))
        assert detector.detect(df) is Regime.FROZEN

        monkeypatch.setattr("uniquant.brain.regime.regime_detector.Indicators.calc_market_entropy", lambda _: pd.Series(np.linspace(0.1, 0.9, 60)))
        monkeypatch.setattr("uniquant.brain.regime.regime_detector.Indicators.calc_turnover_z", lambda _: pd.Series([0.0] * 59 + [99.0]))
        assert detector.detect(df) is Regime.STRESSED

        monkeypatch.setattr("uniquant.brain.regime.regime_detector.Indicators.calc_turnover_z", lambda _: pd.Series([0.0] * 60))
        assert detector.detect(df) is Regime.NORMAL

        monkeypatch.setattr("uniquant.brain.regime.regime_detector.Indicators.calc_market_entropy", lambda _: pd.Series([np.nan]))
        monkeypatch.setattr("uniquant.brain.regime.regime_detector.Indicators.calc_turnover_z", lambda _: pd.Series([np.nan]))
        summary = detector.get_summary(df)
        assert summary == {
            "regime": "NORMAL",
            "entropy": 0.0,
            "turnover_z": 0.0,
            "is_safe": True,
        }

    def test_detect_from_data_handles_deprecated_path_and_empty_fetch(self, monkeypatch):
        detector = RegimeDetector(min_data_points=10)
        renamed_df = pd.DataFrame(
            {
                "Date": pd.date_range("2026-04-01", periods=12),
                "Close": [1.0] * 12,
                "High": [1.1] * 12,
                "Low": [0.9] * 12,
                "Volume": [100.0] * 12,
            }
        )

        monkeypatch.setattr(detector, "get_summary", lambda df: {"regime": "NORMAL", "columns": list(df.columns)})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = detector.detect_from_data(_Fetcher(renamed_df), "000001.SZ", "2026-01-01", "2026-04-01")

        assert result["regime"] == "NORMAL"
        assert "close" in result["columns"]
        assert any(item.category is DeprecationWarning for item in caught)

        missing = detector.detect_from_data(_Fetcher(pd.DataFrame()), "000001.SZ", "2026-01-01", "2026-04-01")
        assert missing["error"] == "无法获取数据"
