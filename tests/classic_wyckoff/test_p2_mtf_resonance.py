"""Tests for P2: MTF 统一 — MultiTimeframeResonance replaces rule9 in merge_multitimeframe_reports."""

from unittest.mock import patch

import pytest

from uniquant.brain.wyckoff.analysis import (
    _resonance_to_rule9_alignment,
    merge_multitimeframe_reports,
)
from uniquant.brain.wyckoff.models import (
    ConfidenceLevel,
    RiskRewardProjection,
    TradingPlan,
    WyckoffPhase,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
)
from uniquant.brain.wyckoff.phase_analysis import MultiTimeframeResonance
from uniquant.brain.wyckoff.rules import V3Rules


def _make_report(phase: WyckoffPhase, direction: str = "做多",
                 signal_type: str = "spring") -> WyckoffReport:
    return WyckoffReport(
        symbol="000001.SH",
        period="daily",
        structure=WyckoffStructure(phase=phase, current_price=10.0, current_date="2026-01-01"),
        signal=WyckoffSignal(
            signal_type=signal_type,
            confidence=ConfidenceLevel.B,
            description="test signal",
        ),
        risk_reward=RiskRewardProjection(),
        trading_plan=TradingPlan(
            direction=direction,
            confidence=ConfidenceLevel.B,
            current_qualification="test",
        ),
    )


class TestResonanceToRule9Mapping:
    """Test the _resonance_to_rule9_alignment mapping function directly."""

    def test_markdown_override_monthly(self):
        r = MultiTimeframeResonance.resonance('markdown', 'markup', 'markup')
        t, d = _resonance_to_rule9_alignment(
            r, WyckoffPhase.MARKDOWN, WyckoffPhase.MARKUP, WyckoffPhase.MARKUP)
        assert t == "markdown_override"
        assert "月线Markdown" in d

    def test_markdown_override_weekly(self):
        r = MultiTimeframeResonance.resonance('markup', 'markdown', 'markup')
        t, d = _resonance_to_rule9_alignment(
            r, WyckoffPhase.MARKUP, WyckoffPhase.MARKDOWN, WyckoffPhase.MARKUP)
        assert t == "markdown_override"
        assert "周线Markdown" in d

    def test_distribution_override_monthly(self):
        r = MultiTimeframeResonance.resonance('distribution', 'markup', 'markup')
        t, d = _resonance_to_rule9_alignment(
            r, WyckoffPhase.DISTRIBUTION, WyckoffPhase.MARKUP, WyckoffPhase.MARKUP)
        assert t == "distribution_override"
        assert "月线Distribution" in d

    def test_fully_aligned_via_resonance_three_bullish(self):
        r = MultiTimeframeResonance.resonance('accumulation', 'markup', 'accumulation')
        t, d = _resonance_to_rule9_alignment(
            r, WyckoffPhase.ACCUMULATION, WyckoffPhase.MARKUP, WyckoffPhase.ACCUMULATION)
        assert t == "fully_aligned"
        assert "共振" in d

    def test_fully_aligned_three_same_exact(self):
        r = MultiTimeframeResonance.resonance('markup', 'markup', 'markup')
        t, d = _resonance_to_rule9_alignment(
            r, WyckoffPhase.MARKUP, WyckoffPhase.MARKUP, WyckoffPhase.MARKUP)
        assert t == "fully_aligned"
        assert "共振" in d

    def test_fully_aligned_three_bearish_monthly_distribution(self):
        """monthly distribution triggers distribution_override before resonance check."""
        r = MultiTimeframeResonance.resonance('distribution', 'distribution', 'markdown')
        t, d = _resonance_to_rule9_alignment(
            r, WyckoffPhase.DISTRIBUTION, WyckoffPhase.DISTRIBUTION, WyckoffPhase.MARKDOWN)
        assert t == "distribution_override"
        assert "Distribution" in d

    def test_fully_aligned_three_bearish_markdown_override_priority(self):
        """markdown override takes priority over fully_aligned resonance."""
        r = MultiTimeframeResonance.resonance('distribution', 'markdown', 'distribution')
        t, d = _resonance_to_rule9_alignment(
            r, WyckoffPhase.DISTRIBUTION, WyckoffPhase.MARKDOWN, WyckoffPhase.DISTRIBUTION)
        assert t == "markdown_override", "bearish override takes priority over resonance full alignment"

    def test_fully_aligned_three_bearish_distribution_override_priority(self):
        r = MultiTimeframeResonance.resonance('distribution', 'distribution', 'distribution')
        t, d = _resonance_to_rule9_alignment(
            r, WyckoffPhase.DISTRIBUTION, WyckoffPhase.DISTRIBUTION, WyckoffPhase.DISTRIBUTION)
        assert t == "distribution_override"
        assert "Distribution" in d

    def test_aligned_weekly_monthly_markup(self):
        r = MultiTimeframeResonance.resonance('markup', 'markup', 'unknown')
        t, d = _resonance_to_rule9_alignment(
            r, WyckoffPhase.MARKUP, WyckoffPhase.MARKUP, WyckoffPhase.UNKNOWN)
        assert t == "aligned"
        assert "Markup" in d

    def test_degraded_weekly_unknown_daily_markup(self):
        r = MultiTimeframeResonance.resonance('unknown', 'unknown', 'markup')
        t, d = _resonance_to_rule9_alignment(
            r, WyckoffPhase.UNKNOWN, WyckoffPhase.UNKNOWN, WyckoffPhase.MARKUP)
        assert t == "degraded"
        assert "Unknown" in d

    def test_mixed_no_override(self):
        r = MultiTimeframeResonance.resonance('accumulation', 'unknown', 'markdown')
        t, d = _resonance_to_rule9_alignment(
            r, WyckoffPhase.ACCUMULATION, WyckoffPhase.UNKNOWN, WyckoffPhase.MARKDOWN)
        assert t == "mixed"
        assert "混合" in d


class TestMergeMultiframeWithResonance:
    """Integration tests: merge_multitimeframe_reports with mtf_resonance=true."""

    def test_t1_resonance_alignment_applied(self):
        """accumulation+markup+accumulation = 3 bullish resonance => fully_aligned
        alignment_type, which affects signal processing (no override)."""
        with patch("uniquant.brain.wyckoff.analysis.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = True
            report = merge_multitimeframe_reports(
                symbol="000001.SH",
                daily_report=_make_report(WyckoffPhase.ACCUMULATION),
                weekly_report=_make_report(WyckoffPhase.MARKUP),
                monthly_report=_make_report(WyckoffPhase.ACCUMULATION),
                rules=V3Rules(),
            )
        assert report.multi_timeframe is not None
        assert report.signal.signal_type == "spring"
        assert report.trading_plan.direction == "做多"

    def test_t2_fallback_rule9_when_flag_false(self):
        with patch("uniquant.brain.wyckoff.analysis.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = False
            report = merge_multitimeframe_reports(
                symbol="000001.SH",
                daily_report=_make_report(WyckoffPhase.ACCUMULATION),
                weekly_report=_make_report(WyckoffPhase.MARKUP),
                monthly_report=_make_report(WyckoffPhase.ACCUMULATION),
                rules=V3Rules(),
            )
        assert report.multi_timeframe is not None

    def test_t3_fully_aligned_all_same(self):
        with patch("uniquant.brain.wyckoff.analysis.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = True
            report = merge_multitimeframe_reports(
                symbol="000001.SH",
                daily_report=_make_report(WyckoffPhase.MARKUP),
                weekly_report=_make_report(WyckoffPhase.MARKUP),
                monthly_report=_make_report(WyckoffPhase.MARKUP),
                rules=V3Rules(),
            )
        assert report.multi_timeframe is not None
        assert report.multi_timeframe.alignment == "fully_aligned"

    def test_t4_weekly_daily_same_monthly_diff(self):
        with patch("uniquant.brain.wyckoff.analysis.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = True
            report = merge_multitimeframe_reports(
                symbol="000001.SH",
                daily_report=_make_report(WyckoffPhase.MARKUP),
                weekly_report=_make_report(WyckoffPhase.MARKUP),
                monthly_report=_make_report(WyckoffPhase.ACCUMULATION),
                rules=V3Rules(),
            )
        assert report.multi_timeframe is not None
        assert report.multi_timeframe.alignment == "weekly_daily_aligned"

    def test_t5_all_three_conflicting(self):
        with patch("uniquant.brain.wyckoff.analysis.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = True
            report = merge_multitimeframe_reports(
                symbol="000001.SH",
                daily_report=_make_report(WyckoffPhase.MARKUP),
                weekly_report=_make_report(WyckoffPhase.MARKDOWN),
                monthly_report=_make_report(WyckoffPhase.ACCUMULATION),
                rules=V3Rules(),
            )
        assert report.multi_timeframe is not None
        assert report.multi_timeframe.alignment == "mixed"

    def test_t6_default_true_when_config_missing_key(self):
        with patch("uniquant.brain.wyckoff.analysis.get_config") as mock_cfg:
            mock_cfg.return_value.get.side_effect = lambda key, default=True: default
            report = merge_multitimeframe_reports(
                symbol="000001.SH",
                daily_report=_make_report(WyckoffPhase.MARKUP),
                weekly_report=_make_report(WyckoffPhase.MARKUP),
                monthly_report=_make_report(WyckoffPhase.MARKUP),
                rules=V3Rules(),
            )
        assert report.multi_timeframe is not None
        assert report.multi_timeframe.alignment == "fully_aligned"


class TestResonanceMarkdownOverride:
    """markdown_override should still work (same as rule9)."""

    def test_monthly_markdown_force_empty(self):
        with patch("uniquant.brain.wyckoff.analysis.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = True
            report = merge_multitimeframe_reports(
                symbol="000001.SH",
                daily_report=_make_report(WyckoffPhase.MARKUP, direction="做多", signal_type="no_signal"),
                weekly_report=_make_report(WyckoffPhase.MARKUP),
                monthly_report=_make_report(WyckoffPhase.MARKDOWN),
                rules=V3Rules(),
            )
        assert report.signal.signal_type == "no_signal"
        assert report.trading_plan.direction == "空仓观望"

    def test_monthly_markdown_but_strong_signal_exempt(self):
        with patch("uniquant.brain.wyckoff.analysis.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = True
            report = merge_multitimeframe_reports(
                symbol="000001.SH",
                daily_report=_make_report(WyckoffPhase.MARKUP, direction="做多", signal_type="sos_candidate"),
                weekly_report=_make_report(WyckoffPhase.MARKUP),
                monthly_report=_make_report(WyckoffPhase.MARKDOWN),
                rules=V3Rules(),
            )
        assert report.trading_plan.direction == "做多"
        assert report.signal.signal_type == "sos_candidate"

    def test_weekly_markdown_force_empty(self):
        with patch("uniquant.brain.wyckoff.analysis.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = True
            report = merge_multitimeframe_reports(
                symbol="000001.SH",
                daily_report=_make_report(WyckoffPhase.MARKUP, direction="做多", signal_type="no_signal"),
                weekly_report=_make_report(WyckoffPhase.MARKDOWN),
                monthly_report=_make_report(WyckoffPhase.MARKUP),
                rules=V3Rules(),
            )
        assert report.signal.signal_type == "no_signal"
        assert report.trading_plan.direction == "空仓观望"

    def test_distribution_override_monthly(self):
        with patch("uniquant.brain.wyckoff.analysis.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = True
            report = merge_multitimeframe_reports(
                symbol="000001.SH",
                daily_report=_make_report(WyckoffPhase.MARKUP, direction="做多", signal_type="no_signal"),
                weekly_report=_make_report(WyckoffPhase.MARKUP),
                monthly_report=_make_report(WyckoffPhase.DISTRIBUTION),
                rules=V3Rules(),
            )
        assert report.signal.signal_type == "no_signal"
        assert report.trading_plan.direction == "空仓观望"