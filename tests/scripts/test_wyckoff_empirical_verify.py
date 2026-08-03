"""测试 wyckoff_empirical_verify.py 的实证表计算."""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.wyckoff_empirical_verify import (
    _compute_structural_rank_ic,
    _compute_lps_conduction,
    _compute_pnf_divergence,
    _compute_vdb_empirical,
    _compute_markup_rs_empirical,
    compute_verification_report,
    _load_scan_csv,
)


# ── 辅助 ────────────────────────────────────────────────────────────────────────

def _make_df(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(records)


# ── structural_rank_ic ──────────────────────────────────────────────────────────

def test_rank_ic_positive() -> None:
    df = _make_df([
        {"symbol": "A", "structural_score": 80, "fwd_20d": 10.0, "ok": True},
        {"symbol": "B", "structural_score": 60, "fwd_20d": 5.0, "ok": True},
        {"symbol": "C", "structural_score": 40, "fwd_20d": 0.0, "ok": True},
        {"symbol": "D", "structural_score": 20, "fwd_20d": -5.0, "ok": True},
        {"symbol": "E", "structural_score": 10, "fwd_20d": -10.0, "ok": True},
    ])
    result = _compute_structural_rank_ic(df)
    assert result["n"] >= 5
    assert result["spearman_rho"] is not None
    assert result["p_value"] is not None


def test_rank_ic_too_few() -> None:
    df = _make_df([
        {"symbol": "A", "structural_score": 80, "fwd_20d": 10.0, "ok": True},
    ])
    result = _compute_structural_rank_ic(df)
    assert result["spearman_rho"] is None
    assert result["n"] == 1


def test_rank_ic_na_handling() -> None:
    df = _make_df([
        {"symbol": "A", "structural_score": 80, "fwd_20d": None, "ok": True},
        {"symbol": "B", "structural_score": 60, "fwd_20d": 5.0, "ok": True},
        {"symbol": "C", "structural_score": 40, "fwd_20d": None, "ok": True},
        {"symbol": "D", "structural_score": 20, "fwd_20d": -5.0, "ok": True},
        {"symbol": "E", "structural_score": 10, "fwd_20d": -10.0, "ok": True},
    ])
    result = _compute_structural_rank_ic(df)
    assert result["n"] == 3
    assert result["spearman_rho"] is None  # <5 samples → cannot compute


# ── lps_conduction ─────────────────────────────────────────────────────────────

def test_lps_conduction_typical() -> None:
    df = _make_df([
        {"symbol": "A", "spring": True, "lps_stage": "lps_confirmed", "ok": True},
        {"symbol": "B", "spring": True, "lps_stage": "test_held", "ok": True},
        {"symbol": "C", "spring": True, "lps_stage": "lps_confirmed", "ok": True},
        {"symbol": "D", "spring": True, "lps_stage": "not_test", "ok": True},
        {"symbol": "E", "spring": True, "lps_stage": "invalidated", "ok": True},
        {"symbol": "F", "spring": False, "lps_stage": "not_test", "ok": True},
    ])
    result = _compute_lps_conduction(df)
    assert result["count"] == 5
    assert result["lps_confirmed"] == 2
    assert result["lps_confirmed_rate"] == 0.4


def test_lps_conduction_no_springs() -> None:
    df = _make_df([
        {"symbol": "A", "spring": False, "lps_stage": "not_test", "ok": True},
        {"symbol": "B", "spring": False, "lps_stage": "not_test", "ok": True},
    ])
    result = _compute_lps_conduction(df)
    assert result["count"] == 0
    assert result["lps_confirmed_rate"] is None


def test_lps_conduction_few_samples() -> None:
    df = _make_df([
        {"symbol": "A", "spring": True, "lps_stage": "lps_confirmed", "ok": True},
    ])
    result = _compute_lps_conduction(df)
    assert result["count"] == 1
    assert result["lps_confirmed_rate"] is None
    assert result["note"] == "too_few_samples"


# ── pnf_divergence ─────────────────────────────────────────────────────────────

def test_pnf_divergence() -> None:
    df = _make_df([
        {"symbol": "A", "pnf_phase_divergence": "分歧", "fwd_20d": 5.0, "fwd_60d": 10.0, "ok": True},
        {"symbol": "B", "pnf_phase_divergence": None, "fwd_20d": 3.0, "fwd_60d": 8.0, "ok": True},
        {"symbol": "C", "pnf_phase_divergence": "分歧", "fwd_20d": None, "fwd_60d": None, "ok": True},
        {"symbol": "D", "pnf_phase_divergence": None, "fwd_20d": -2.0, "fwd_60d": -5.0, "ok": True},
    ])
    result = _compute_pnf_divergence(df)
    assert "分歧" in result
    assert "一致" in result
    assert result["分歧"]["count"] == 2
    assert result["一致"]["count"] == 2


def test_pnf_divergence_no_divergence() -> None:
    df = _make_df([
        {"symbol": "A", "pnf_phase_divergence": None, "fwd_20d": 3.0, "fwd_60d": 8.0, "ok": True},
    ])
    result = _compute_pnf_divergence(df)
    assert result["分歧"]["count"] == 0
    assert result["一致"]["count"] == 1


# ── vdb_empirical ──────────────────────────────────────────────────────────────

def test_vdb_empirical() -> None:
    df = _make_df([
        {"symbol": "A", "vdb_divergence": "none", "fwd_20d": 2.0, "ok": True},
        {"symbol": "B", "vdb_divergence": "bullish_divergence", "fwd_20d": 5.0, "ok": True},
        {"symbol": "C", "vdb_divergence": "bearish_divergence", "fwd_20d": -3.0, "ok": True},
        {"symbol": "D", "vdb_divergence": "none", "fwd_20d": 1.0, "ok": True},
        {"symbol": "E", "vdb_divergence": "bullish_divergence", "fwd_20d": 8.0, "ok": True},
    ])
    result = _compute_vdb_empirical(df)
    assert "none" in result
    assert "bullish_divergence" in result
    assert "bearish_divergence" in result
    assert result["none"]["count"] == 2
    assert result["bullish_divergence"]["count"] == 2
    assert result["bearish_divergence"]["count"] == 1
    assert abs(result["bullish_divergence"]["mean_fwd_20d"] - 6.5) < 0.01


# ── markup_rs_empirical ────────────────────────────────────────────────────────

def test_markup_rs_empirical() -> None:
    df = _make_df([
        {"symbol": "A", "phase": "markup", "relative_strength": "leader", "fwd_20d": 15.0, "ok": True},
        {"symbol": "B", "phase": "markup", "relative_strength": "follower", "fwd_20d": 5.0, "ok": True},
        {"symbol": "C", "phase": "markup", "relative_strength": "leader", "fwd_20d": 12.0, "ok": True},
        {"symbol": "D", "phase": "markup", "relative_strength": "systemic_decline", "fwd_20d": -2.0, "ok": True},
        {"symbol": "E", "phase": "distribution", "relative_strength": "leader", "fwd_20d": 3.0, "ok": True},
    ])
    result = _compute_markup_rs_empirical(df)
    assert "leader" in result
    assert "follower" in result
    assert "systemic_decline" in result
    assert result["leader"]["count"] == 2
    assert result["follower"]["count"] == 1
    assert result["systemic_decline"]["count"] == 1
    assert abs(result["leader"]["mean_fwd_20d"] - 13.5) < 0.01


def test_markup_rs_empirical_no_markup() -> None:
    df = _make_df([
        {"symbol": "A", "phase": "accumulation", "relative_strength": "leader", "fwd_20d": 5.0, "ok": True},
    ])
    result = _compute_markup_rs_empirical(df)
    assert result == {}


# ── compute_verification_report ────────────────────────────────────────────────

def test_compute_verification_report_basic() -> None:
    df = _make_df([
        {"symbol": "A", "ok": True, "phase": "accumulation", "spring": False, "confidence_level": "B",
         "structural_score": 80, "fwd_20d": 10.0, "fwd_60d": 15.0,
         "pnf_phase_divergence": None, "vdb_divergence": "none", "lps_stage": "not_test",
         "relative_strength": "leader"},
        {"symbol": "B", "ok": True, "phase": "distribution", "spring": True, "confidence_level": "C",
         "structural_score": 50, "fwd_20d": -3.0, "fwd_60d": -8.0,
         "pnf_phase_divergence": "分歧", "vdb_divergence": "bearish_divergence", "lps_stage": "lps_confirmed",
         "relative_strength": "follower"},
        {"symbol": "C", "ok": True, "phase": "markup", "spring": False, "confidence_level": "A",
         "structural_score": 90, "fwd_20d": 8.0, "fwd_60d": 20.0,
         "pnf_phase_divergence": None, "vdb_divergence": "none", "lps_stage": "not_test",
         "relative_strength": "leader"},
        {"symbol": "D", "ok": False, "error": "too_short", "phase": "unknown", "spring": False,
         "confidence_level": "D", "structural_score": 0, "fwd_20d": None, "fwd_60d": None,
         "pnf_phase_divergence": None, "vdb_divergence": "none", "lps_stage": "not_test",
         "relative_strength": None},
    ])
    report = compute_verification_report(df)
    assert "total_symbols" in report
    assert report["total_symbols"] == 4
    assert report["ok_symbols"] == 3
    assert "phase_empirical" in report
    assert "structural_rank_ic" in report
    assert "lps_conduction" in report
    assert "pnf_divergence" in report
    assert "vdb_empirical" in report
    assert "markup_rs_empirical" in report


# ── _load_scan_csv ─────────────────────────────────────────────────────────────

def test_load_scan_csv(tmp_path) -> None:
    p = tmp_path / "test.csv"
    p.write_text("symbol,phase,ok\n600519.SH,accumulation,True\n000001.SZ,distribution,False\n")
    df = _load_scan_csv(str(p))
    assert len(df) == 2
    assert list(df.columns) == ["symbol", "phase", "ok"]


def test_load_scan_csv_missing_symbol(tmp_path) -> None:
    p = tmp_path / "test.csv"
    p.write_text("phase,ok\naccumulation,True\n")
    with pytest.raises(ValueError, match="缺少 symbol"):
        _load_scan_csv(str(p))