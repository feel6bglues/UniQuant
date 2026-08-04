"""测试 wyckoff_multi_period_analysis.py 的核心函数."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.wyckoff_multi_period_analysis import (
    AS_OF_DATES,
    compute_phase_forward_stats,
    compute_lps_conduction_rate,
    build_phase_transition_matrix,
    evaluate_wyckoff_theory,
    PHASE_CYCLE,
)


def test_as_of_dates_count() -> None:
    assert len(AS_OF_DATES) == 6


def test_phase_cycle_order() -> None:
    assert PHASE_CYCLE == ["accumulation", "markup", "distribution", "markdown"]


def test_compute_phase_forward_stats_basic() -> None:
    data = [
        {"phase": "accumulation", "fwd_20d": 5.0, "fwd_60d": 10.0, "ok": True},
        {"phase": "accumulation", "fwd_20d": 3.0, "fwd_60d": 8.0, "ok": True},
        {"phase": "distribution", "fwd_20d": -2.0, "fwd_60d": -5.0, "ok": True},
        {"phase": "markup", "fwd_20d": 8.0, "fwd_60d": 15.0, "ok": True},
        {"phase": "markdown", "fwd_20d": -4.0, "fwd_60d": -10.0, "ok": True},
        {"phase": "unknown", "fwd_20d": 1.0, "fwd_60d": None, "ok": True},
    ]
    stats = compute_phase_forward_stats(data)
    assert "accumulation" in stats
    assert "distribution" in stats
    assert stats["accumulation"]["count"] == 2
    assert stats["accumulation"]["mean_fwd_20d"] == 4.0
    assert stats["distribution"]["mean_fwd_20d"] == -2.0
    assert stats["markup"]["mean_fwd_20d"] == 8.0
    assert stats["markdown"]["mean_fwd_20d"] == -4.0


def test_compute_phase_forward_stats_win_rate() -> None:
    data = [
        {"phase": "accumulation", "fwd_20d": 5.0, "fwd_60d": None, "ok": True},
        {"phase": "accumulation", "fwd_20d": -1.0, "fwd_60d": None, "ok": True},
        {"phase": "accumulation", "fwd_20d": 3.0, "fwd_60d": None, "ok": True},
        {"phase": "accumulation", "fwd_20d": -2.0, "fwd_60d": None, "ok": True},
    ]
    stats = compute_phase_forward_stats(data)
    assert stats["accumulation"]["win_rate_20d"] == 50.0


def test_compute_phase_forward_stats_empty() -> None:
    assert compute_phase_forward_stats([]) == {}


def test_compute_lps_conduction_rate() -> None:
    data = [
        {"spring": True, "lps_stage": "lps_confirmed", "ok": True},
        {"spring": True, "lps_stage": "test_held", "ok": True},
        {"spring": True, "lps_stage": "not_test", "ok": True},
        {"spring": False, "lps_stage": "not_test", "ok": True},
        {"spring": True, "lps_stage": "invalidated", "ok": True},
    ]
    result = compute_lps_conduction_rate(data)
    assert result["spring_count"] == 4
    assert result["lps_confirmed"] == 1
    assert result["lps_test_held"] == 1
    assert result["lps_conduction_rate"] == 0.25
    assert result["lps_any_rate"] == 0.5


def test_compute_lps_conduction_rate_no_spring() -> None:
    data = [{"spring": False, "lps_stage": "not_test", "ok": True}]
    result = compute_lps_conduction_rate(data)
    assert result["spring_count"] == 0
    assert result["lps_conduction_rate"] == 0.0


def test_build_phase_transition_matrix_basic() -> None:
    period_results = {
        "2024-01-31": [
            {"symbol": "A", "phase": "accumulation", "ok": True},
            {"symbol": "B", "phase": "markup", "ok": True},
        ],
        "2024-06-28": [
            {"symbol": "A", "phase": "markup", "ok": True},
            {"symbol": "B", "phase": "distribution", "ok": True},
        ],
    }
    result = build_phase_transition_matrix(period_results)
    assert result["symbol_count"] == 2
    assert result["total_transitions"] == 2
    assert result["correct_transitions"] == 2
    assert result["correct_transition_rate"] == 1.0
    assert "accumulation->markup" in result["transition_matrix"]
    assert "markup->distribution" in result["transition_matrix"]


def test_build_phase_transition_matrix_invalid() -> None:
    period_results = {
        "2024-01-31": [
            {"symbol": "A", "phase": "accumulation", "ok": True},
        ],
        "2024-06-28": [
            {"symbol": "A", "phase": "distribution", "ok": True},
        ],
    }
    result = build_phase_transition_matrix(period_results)
    assert result["total_transitions"] == 1
    assert result["correct_transitions"] == 0
    assert result["correct_transition_rate"] == 0.0


def test_evaluate_wyckoff_theory_all_pass() -> None:
    period_stats = {
        "2024-01-31": {
            "accumulation": {"mean_fwd_20d": 5.0, "median_fwd_20d": 4.0, "win_rate_20d": 60.0},
            "markup": {"mean_fwd_20d": 8.0, "median_fwd_20d": 7.0, "win_rate_20d": 70.0},
            "distribution": {"mean_fwd_20d": -3.0, "median_fwd_20d": -2.0, "win_rate_20d": 30.0},
            "markdown": {"mean_fwd_20d": -5.0, "median_fwd_20d": -4.0, "win_rate_20d": 20.0},
        },
    }
    result = evaluate_wyckoff_theory(period_stats)
    assert result["overall_score"] == 100.0
    assert result["overall_passed"] == 4
    assert result["overall_total"] == 4


def test_evaluate_wyckoff_theory_all_fail() -> None:
    period_stats = {
        "2024-01-31": {
            "accumulation": {"mean_fwd_20d": -5.0, "median_fwd_20d": -4.0, "win_rate_20d": 30.0},
            "markup": {"mean_fwd_20d": -3.0, "median_fwd_20d": -2.0, "win_rate_20d": 40.0},
            "distribution": {"mean_fwd_20d": 5.0, "median_fwd_20d": 4.0, "win_rate_20d": 60.0},
            "markdown": {"mean_fwd_20d": 2.0, "median_fwd_20d": 1.0, "win_rate_20d": 55.0},
        },
    }
    result = evaluate_wyckoff_theory(period_stats)
    assert result["overall_score"] == 0.0
    assert result["overall_passed"] == 0


def test_evaluate_wyckoff_theory_missing_phase() -> None:
    period_stats = {
        "2024-01-31": {
            "accumulation": {"mean_fwd_20d": 5.0, "median_fwd_20d": 4.0, "win_rate_20d": 60.0},
            "markup": {"mean_fwd_20d": 8.0, "median_fwd_20d": 7.0, "win_rate_20d": 70.0},
        },
    }
    result = evaluate_wyckoff_theory(period_stats)
    assert result["overall_score"] == 50.0
    assert result["overall_passed"] == 2
    assert result["overall_total"] == 4


def test_main_runs_with_mock(tmp_path) -> None:
    from scripts.wyckoff_multi_period_analysis import main
    import sys
    old_argv = sys.argv
    try:
        sys.argv = ["wyckoff_multi_period_analysis.py",
                    "--symbols", "golden_20",
                    "--output-dir", str(tmp_path)]
        main()
    finally:
        sys.argv = old_argv

    json_path = tmp_path / "wyckoff_multi_period_golden_20.json"
    assert json_path.exists()
    data = json.loads(json_path.read_text())
    assert "as_of_dates" in data
    assert len(data["as_of_dates"]) == 6
    assert "phase_transition_analysis" in data
    assert "wyckoff_theory_evaluation" in data

    csv_path = tmp_path / "wyckoff_multi_period_golden_20.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert len(df) >= 20 * 6


import json