"""Tests for WyckoffAnalysisEngine._extract_from_report and related methods."""

import pytest

from unittest.mock import MagicMock, patch

from uniquant.shared.interfaces import WyckoffOutput


# ── Minimal test doubles for WyckoffReport sub-dataclasses ──

class DummyPhase:
    value = "accumulation"

class DummyConfidence:
    value = "A"

class DummyStructure:
    phase = DummyPhase()

class DummySignal:
    signal_type = "spring"
    confidence = DummyConfidence()

class DummyRiskReward:
    reward_risk_ratio = 2.5

class DummyTradingPlan:
    confidence = DummyConfidence()

class DummyMTF:
    resonance_count = 3
    resonance_dir = "bullish"
    resonance_strength = 1.0

class DummyReport:
    """Minimal replacement for WyckoffReport dataclass."""
    def __init__(self, structure=None, signal=None, risk_reward=None, trading_plan=None,
                 multi_timeframe=None):
        self.structure = structure
        self.signal = signal
        self.risk_reward = risk_reward
        self.trading_plan = trading_plan
        self.multi_timeframe = multi_timeframe


@pytest.fixture
def full_report():
    """A fully populated report (via dummy objects)."""
    return DummyReport(
        structure=DummyStructure(),
        signal=DummySignal(),
        risk_reward=DummyRiskReward(),
        trading_plan=DummyTradingPlan(),
    )


@pytest.fixture
def empty_report():
    """A report with no fields (all None)."""
    return DummyReport(structure=None, signal=None, risk_reward=None, trading_plan=None)


@pytest.fixture
def partial_report():
    """A report with only structure (no signal/risk_reward/trading_plan)."""
    return DummyReport(structure=DummyStructure(), signal=None, risk_reward=None, trading_plan=None)


# ── Tests ──

class TestExtractFromReport:

    def test_full_extraction(self, full_report):
        """Complete WyckoffReport → WyckoffOutput conversion."""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        engine = WyckoffAnalysisEngine(MagicMock())
        output = engine._extract_from_report(full_report, price=100.0)

        assert isinstance(output, WyckoffOutput)
        assert output.phase == "accumulation"
        assert output.spring is True
        assert output.utad is False
        assert output.rr_ratio == 2.5
        assert output.price == 100.0
        assert output.confidence > 0.5  # "A" → 0.9

    def test_mtf_resonance_annotation_preserved(self):
        """P2-1: resonance_count/dir/strength 标注透传至 WyckoffOutput."""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        report = DummyReport(
            structure=DummyStructure(),
            signal=DummySignal(),
            risk_reward=DummyRiskReward(),
            trading_plan=DummyTradingPlan(),
            multi_timeframe=DummyMTF(),
        )
        engine = WyckoffAnalysisEngine(MagicMock())
        output = engine._extract_from_report(report, price=100.0)

        assert output.resonance_count == 3
        assert output.resonance_dir == "bullish"
        assert output.resonance_strength == 1.0

    def test_mtf_resonance_default_when_absent(self, full_report):
        """报告无 multi_timeframe 时共振标注保持默认 (0/""/0.0)。"""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        engine = WyckoffAnalysisEngine(MagicMock())
        output = engine._extract_from_report(full_report, price=100.0)

        assert output.resonance_count == 0
        assert output.resonance_dir == ""
        assert output.resonance_strength == 0.0

    def test_empty_report_fallback(self, empty_report):
        """Report with all-None fields should produce default WyckoffOutput."""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        engine = WyckoffAnalysisEngine(MagicMock())
        output = engine._extract_from_report(empty_report, price=50.0)

        assert output.phase == "unknown"
        assert output.spring is False
        assert output.rr_ratio == 0.0
        assert output.price == 50.0
        assert output.confidence == 0.0

    def test_partial_report(self, partial_report):
        """Only structure present → phase populated, others default."""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        engine = WyckoffAnalysisEngine(MagicMock())
        output = engine._extract_from_report(partial_report, price=75.0)

        assert output.phase == "accumulation"
        assert output.rr_ratio == 0.0  # default
        assert output.spring is False  # default
        assert output.confidence == 0.0  # default (no signal)

    def test_signal_utad(self):
        """UTAD signal type → utad=True."""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        class UDummySignal:
            signal_type = "utad After Distribution"
            confidence = DummyConfidence()

        report = DummyReport(
            structure=DummyStructure(),
            signal=UDummySignal(),
            risk_reward=DummyRiskReward(),
            trading_plan=None,
        )
        engine = WyckoffAnalysisEngine(MagicMock())
        output = engine._extract_from_report(report, price=100.0)

        assert output.spring is False
        assert output.utad is True

    def test_rr_ratio_from_risk_reward(self):
        """rr_ratio should come from risk_reward.reward_risk_ratio."""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        class CustomRR:
            reward_risk_ratio = 3.14

        report = DummyReport(
            structure=DummyStructure(),
            signal=DummySignal(),
            risk_reward=CustomRR(),
            trading_plan=None,
        )
        engine = WyckoffAnalysisEngine(MagicMock())
        output = engine._extract_from_report(report, price=100.0)

        assert output.rr_ratio == 3.14

    def test_confidence_mapping_all_levels(self):
        """All 4 ConfidenceLevel values should map correctly."""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        engine = WyckoffAnalysisEngine(MagicMock())
        expected = {"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3}

        for level, expected_conf in expected.items():
            class LevelConf:
                value = level

            class LevelSignal:
                signal_type = "spring"
                confidence = LevelConf()

            report = DummyReport(
                structure=DummyStructure(),
                signal=LevelSignal(),
                risk_reward=None,
                trading_plan=None,
            )
            output = engine._extract_from_report(report, price=100.0)
            assert abs(output.confidence - expected_conf) < 0.01, \
                f"ConfidenceLevel {level} expected {expected_conf}, got {output.confidence}"

    def test_non_dataclass_dict_input(self):
        """If result is a dict (not a dataclass), should still not crash."""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        engine = WyckoffAnalysisEngine(MagicMock())
        # This simulates the original bug path (dict with no "get" for structure, etc.)
        result_dict = {"phase": "accumulation", "price": 50.0}

        # Should not raise AttributeError
        output = engine._extract_from_report(result_dict, price=50.0)
        assert output.phase == "unknown"  # degrades gracefully

    def test_bypassed_default(self, full_report):
        """bypassed should always be False in current implementation."""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        engine = WyckoffAnalysisEngine(MagicMock())
        output = engine._extract_from_report(full_report, price=100.0)
        assert output.bypassed is False

    def test_none_structure(self):
        """result.structure = None should not crash."""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        report = DummyReport(structure=None, signal=DummySignal(), risk_reward=None, trading_plan=None)
        engine = WyckoffAnalysisEngine(MagicMock())
        output = engine._extract_from_report(report, price=100.0)
        assert output.phase == "unknown"

    def test_rr_ratio_zero_default(self, partial_report):
        """When no risk_reward, rr_ratio should be 0.0."""
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        engine = WyckoffAnalysisEngine(MagicMock())
        output = engine._extract_from_report(partial_report, price=100.0)
        assert output.rr_ratio == 0.0


class TestRunWyckoffAnalysisIndexDf:
    """W1: run_wyckoff_analysis passes index_df through to the engine."""

    def test_index_df_passed_to_engine(self, tmp_path):
        """index_df is forwarded to WyckoffEngine.analyze."""
        import pandas as pd
        from unittest.mock import MagicMock
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        stock = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=60, freq="D"),
            "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 10000,
        })
        index = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=60, freq="D"),
            "close": 100.0, "volume": 100000,
        })
        orch = MagicMock()
        orch._generate_cache_key.return_value = "ck"
        orch._optimize_dataframe.side_effect = lambda df: df
        orch._sample_data.side_effect = lambda df, max_rows: df

        captured = {}
        class FakeEngine:
            def analyze(self, df, multi_timeframe=False, index_df=None):
                captured["index"] = index_df
                return MagicMock(structure=None, signal=None, risk_reward=None, trading_plan=None)

        engine = WyckoffAnalysisEngine(orch)
        with patch("uniquant.brain.wyckoff.engine.WyckoffEngine", lambda: FakeEngine()):
            engine.run_wyckoff_analysis(symbol="600000.SH", df=stock, index_df=index)
        assert captured["index"] is index

    def test_index_df_none_auto_loads_csi300(self, tmp_path, monkeypatch):
        """When index_df is None, _load_index_df tries configured paths."""
        import pandas as pd
        from unittest.mock import MagicMock
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        index = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=10, freq="D"), "close": [1.0] * 10})
        p = tmp_path / "000300.SH.parquet"
        index.to_parquet(p)

        engine = WyckoffAnalysisEngine(MagicMock())
        monkeypatch.setattr(engine, "_INDEX_PATHS", (str(p),))
        loaded = engine._load_index_df()
        assert loaded is not None
        assert "close" in loaded.columns

    def test_load_index_df_missing_returns_none(self, tmp_path, monkeypatch):
        """No index file available -> returns None (graceful degrade)."""
        from unittest.mock import MagicMock
        from uniquant.services.analysis.wyckoff_analysis_engine import WyckoffAnalysisEngine

        engine = WyckoffAnalysisEngine(MagicMock())
        monkeypatch.setattr(engine, "_INDEX_PATHS", (str(tmp_path / "nope.parquet"),))
        assert engine._load_index_df() is None
