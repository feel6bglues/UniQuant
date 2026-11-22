#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for run_n2n_verification.py."""

from pathlib import Path
import tempfile

from scripts.maintenance.run_n2n_verification import (
    N2NVerificationRunner,
    isolated_sandbox_context,
)


def test_isolated_sandbox_context() -> None:
    """Test that isolated_sandbox_context creates and cleans up the temp dir."""
    captured_dir: Path | None = None
    with isolated_sandbox_context() as sbox:
        captured_dir = sbox
        assert sbox.exists()
        (sbox / "temp.txt").write_text("hello", encoding="utf-8")
        assert (sbox / "temp.txt").exists()

    assert captured_dir is not None
    assert not captured_dir.exists()


def test_n2n_runner_track_2() -> None:
    """Test Track 2: Decision convergence and arbitrator sell-priority."""
    runner = N2NVerificationRunner(mode="sandbox")
    with tempfile.TemporaryDirectory() as td:
        res = runner._verify_track_2(Path(td))
        assert res["conflict_resolution"] == "SELL_WON"
        assert res["qar_adapter_mapping"] == "PASS"


def test_n2n_runner_track_3() -> None:
    """Test Track 3: Institutional execution and futures hedging limits."""
    runner = N2NVerificationRunner(mode="sandbox")
    with tempfile.TemporaryDirectory() as td:
        res = runner._verify_track_3(Path(td))
        assert res["regulatory_status"] == "SAFE"
        assert res["total_contracts"] > 0


def test_n2n_runner_track_5() -> None:
    """Test Track 5: KillSwitch persistence and restart fail-closed."""
    runner = N2NVerificationRunner(mode="sandbox")
    with tempfile.TemporaryDirectory() as td:
        res = runner._verify_track_5(Path(td))
        assert res["trip_intercept"] == "PASS"
        assert res["state_persistence"] == "PASS"
        assert res["restart_fail_closed"] == "PASS"
        assert res["reset"] == "PASS"


def test_n2n_runner_track_6() -> None:
    """Test Track 6: Bootstrap latency and Rule 4 false data defense."""
    runner = N2NVerificationRunner(mode="sandbox")
    with tempfile.TemporaryDirectory() as td:
        res = runner._verify_track_6(Path(td))
        assert res["bootstrap_latency_ms"] < 50.0
        assert res["rule4_fail_fast"] == "PASS"


def test_n2n_runner_run_all() -> None:
    """Test full N2N verification run in sandbox mode."""
    runner = N2NVerificationRunner(mode="sandbox")
    success = runner.run_all()
    assert success is True
    assert runner.report["overall_verdict"] == "PASS"
    assert runner.report["summary"]["passed"] == 6
    assert runner.report["summary"]["failed"] == 0
