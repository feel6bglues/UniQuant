"""P1-1: 科研控制平面（自由度账本）接入生产因子链的回归测试。

覆盖：
- TrialRecord / DegreesOfFreedomLedger 序列化往返；
- LedgerStore 原子落盘 / 缺失 / 损坏降级；
- register_factor_trials 的诚实登记、FDR 校正、Alpha-Wealth 熔断；
- ScanPipeline.analyze_factors 的真实登记、幂等与跨运行累积。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from uniquant.research.ledger.bridge import (
    ic_t_stat_to_p_value,
    register_factor_trials,
)
from uniquant.research.ledger.degrees_of_freedom import (
    DegreesOfFreedomLedger,
    SearchSpaceSpec,
    StatisticType,
    TrialRecord,
)
from uniquant.research.ledger.ledger_store import LedgerStore
from uniquant.services.scan_service import ScanConfig, ScanPipeline

@dataclass
class _FakeIC:
    """Duck-typed stand-in for FactorICResult."""

    ic_mean: float = 0.0
    ic_std: float = 1.0
    icir: float = 0.0
    ic_positive_ratio: float = 0.5
    ic_t_stat: float = 0.0
    n_periods: int = 40


# --------------------------------------------------------------------------
# 1. p-value conversion
# --------------------------------------------------------------------------
class TestTStatToPValue:
    def test_zero_t_gives_p_one(self):
        assert ic_t_stat_to_p_value(0.0, 40) == pytest.approx(1.0)

    def test_large_t_gives_tiny_p(self):
        assert ic_t_stat_to_p_value(12.0, 40) < 1e-10

    def test_two_sided_symmetry(self):
        assert ic_t_stat_to_p_value(3.0, 30) == pytest.approx(
            ic_t_stat_to_p_value(-3.0, 30)
        )

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")])
    def test_non_finite_is_honest_p_one(self, bad):
        assert ic_t_stat_to_p_value(bad, 40) == 1.0

    def test_insufficient_periods_is_p_one(self):
        assert ic_t_stat_to_p_value(5.0, 1) == 1.0
        assert ic_t_stat_to_p_value(5.0, 0) == 1.0


# --------------------------------------------------------------------------
# 2. serialization round-trips
# --------------------------------------------------------------------------
def _make_trial(family="fam", p_raw=0.01) -> TrialRecord:
    return TrialRecord(
        experiment_id="exp1",
        hypothesis_id="h1",
        family_id=family,
        trial_index=1,
        search_space=SearchSpaceSpec(
            name="ss",
            dimension=2,
            parameter_grid={"factors": ["a", "b"], "holding_periods": [1, 5]},
        ),
        test_statistic_name=StatisticType.STUDENT_T,
        raw_statistic_value=3.5,
        sample_size_T=40,
        cross_section_N=500,
        p_raw=p_raw,
        metadata={"autocorr_adjusted": False},
    )


class TestSerialization:
    def test_search_space_round_trip(self):
        ss = SearchSpaceSpec(
            name="ss",
            dimension=2,
            parameter_grid={"f": ["a"]},
            continuous_bounds={"x": (0.0, 1.0)},
        )
        assert SearchSpaceSpec.from_dict(ss.to_dict()) == ss

    def test_trial_record_round_trip(self):
        rec = _make_trial()
        restored = TrialRecord.from_dict(rec.to_dict())
        assert restored == rec

    def test_ledger_state_round_trip(self):
        ledger = DegreesOfFreedomLedger()
        ledger.register_trial(
            experiment_id="e",
            hypothesis_id="h",
            family_id="fam",
            search_space=_make_trial().search_space,
            test_statistic_name=StatisticType.STUDENT_T,
            raw_statistic_value=4.0,
            sample_size_T=40,
            cross_section_N=500,
            p_raw=0.001,
        )
        state = ledger.to_state()
        restored = DegreesOfFreedomLedger.from_state(state)
        assert restored.total_trials == ledger.total_trials
        assert restored.current_alpha_wealth == pytest.approx(ledger.current_alpha_wealth)
        assert restored.get_hurdle_report("fam") == ledger.get_hurdle_report("fam")
        assert restored.trials[0] == ledger.trials[0]

    def test_from_state_recomputes_family_adjustments(self):
        """落盘后按 raw p 重推 FDR 校正 → 与内存账本一致（不二次计息）。"""
        ledger = DegreesOfFreedomLedger()
        for i, p in enumerate([1e-6, 0.02, 0.4]):
            ledger.register_trial(
                experiment_id="e",
                hypothesis_id=f"h{i}",
                family_id="fam",
                search_space=_make_trial().search_space,
                test_statistic_name=StatisticType.STUDENT_T,
                raw_statistic_value=2.0,
                sample_size_T=40,
                cross_section_N=500,
                p_raw=p,
            )
        restored = DegreesOfFreedomLedger.from_state(ledger.to_state())
        for a, b in zip(ledger.trials, restored.trials):
            assert a.p_adj_bh_fdr == pytest.approx(b.p_adj_bh_fdr)
            assert a.p_adj_bonferroni == pytest.approx(b.p_adj_bonferroni)
            assert a.passed_bh_fdr == b.passed_bh_fdr
        assert restored.current_alpha_wealth == pytest.approx(ledger.current_alpha_wealth)


# --------------------------------------------------------------------------
# 3. LedgerStore
# --------------------------------------------------------------------------
class TestLedgerStore:
    def test_missing_file_returns_empty_ledger(self, tmp_path):
        store = LedgerStore(tmp_path / "nope.json")
        assert store.load().total_trials == 0

    def test_save_then_load_accumulates(self, tmp_path):
        path = tmp_path / "ledger.json"
        store = LedgerStore(path)
        ledger = store.load()
        assert store.save(ledger) is True

        ledger2 = store.load()
        ledger2.register_trial(
            experiment_id="e",
            hypothesis_id="h",
            family_id="fam",
            search_space=_make_trial().search_space,
            test_statistic_name=StatisticType.STUDENT_T,
            raw_statistic_value=3.0,
            sample_size_T=40,
            cross_section_N=500,
            p_raw=0.01,
        )
        store.save(ledger2)

        ledger3 = store.load()
        assert ledger3.total_trials == 1
        assert path.exists()

    def test_corrupt_file_degrades_to_empty(self, tmp_path):
        path = tmp_path / "ledger.json"
        path.write_text("{not json", encoding="utf-8")
        assert LedgerStore(path).load().total_trials == 0

    def test_non_dict_state_degrades_to_empty(self, tmp_path):
        path = tmp_path / "ledger.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert LedgerStore(path).load().total_trials == 0


# --------------------------------------------------------------------------
# 4. register_factor_trials
# --------------------------------------------------------------------------
class TestRegisterFactorTrials:
    def test_registers_one_trial_per_factor_period(self):
        ledger = DegreesOfFreedomLedger()
        ic_results = {
            "f1": {1: _FakeIC(ic_t_stat=1.0), 5: _FakeIC(ic_t_stat=2.0)},
            "f2": {1: _FakeIC(ic_t_stat=0.5), 5: _FakeIC(ic_t_stat=0.3)},
        }
        audit = register_factor_trials(ledger, ic_results, family_id="fam")
        assert audit.registered == 4
        assert audit.total_platform_trials == 4
        assert set(audit.per_factor) == {"f1", "f2"}
        assert audit.per_factor["f1"]["best_period"] == 5

    def test_strong_factor_survives_bh_fdr_weak_does_not(self):
        ledger = DegreesOfFreedomLedger()
        ic_results = {
            "strong": {5: _FakeIC(ic_t_stat=12.0)},
            "weak": {5: _FakeIC(ic_t_stat=0.2)},
        }
        audit = register_factor_trials(ledger, ic_results, family_id="fam")
        assert audit.per_factor["strong"]["any_period_passed_bh_fdr"] is True
        assert audit.per_factor["weak"]["any_period_passed_bh_fdr"] is False
        assert audit.significant_factors == ["strong"]

    def test_alpha_wealth_exhaustion_is_graceful(self):
        ledger = DegreesOfFreedomLedger(initial_alpha_wealth=0.0015)
        ic_results = {
            f"f{i}": {5: _FakeIC(ic_t_stat=1.0)} for i in range(4)
        }
        audit = register_factor_trials(ledger, ic_results, family_id="fam")
        assert audit.alpha_wealth_exhausted is True
        assert audit.registered == 1
        assert audit.skipped >= 1
        assert audit.alpha_wealth_remaining < 0.001

    def test_skips_none_and_zero_period_results(self):
        ledger = DegreesOfFreedomLedger()
        ic_results = {
            "a": {5: _FakeIC(ic_t_stat=1.0)},
            "b": {5: None},
            "c": {5: _FakeIC(ic_t_stat=1.0, n_periods=0)},
            "d": {},
        }
        audit = register_factor_trials(ledger, ic_results, family_id="fam")
        assert audit.registered == 1

    def test_empty_results_is_noop(self):
        ledger = DegreesOfFreedomLedger()
        audit = register_factor_trials(ledger, {}, family_id="fam")
        assert audit.registered == 0
        assert audit.total_platform_trials == 0
        assert audit.to_dict()["significant_factors"] == []

    def test_trial_metadata_records_autocorr_limitation(self):
        ledger = DegreesOfFreedomLedger()
        register_factor_trials(
            ledger, {"a": {5: _FakeIC(ic_t_stat=1.0)}}, family_id="fam"
        )
        assert ledger.trials[0].metadata["autocorr_adjusted"] is False
        assert ledger.trials[0].test_statistic_name == StatisticType.STUDENT_T


# --------------------------------------------------------------------------
# 5. ScanPipeline wiring
# --------------------------------------------------------------------------
def _write_min_all_stock_codes(data_dir) -> None:
    path = Path(data_dir) / "all_stock_codes.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "code": ["sz.000001"],
            "name": ["平安银行"],
            "代码": ["000001"],
            "ipoDate": ["1991-04-03"],
            "outDate": [""],
            "type": ["1"],
            "status": ["1"],
        }
    ).to_csv(path, index=False, encoding="utf-8-sig")


def _synthetic_panel(n_codes: int = 20, n_dates: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(20261016)
    frames = []
    for i in range(n_codes):
        code = f"{i:06d}.SZ"
        close = 10.0 * np.cumprod(1.0 + rng.normal(0, 0.01, n_dates))
        df = pd.DataFrame(
            {
                "date": pd.bdate_range("2024-01-01", periods=n_dates),
                "code": code,
                "close": close,
            }
        )
        # 一眼可见的强信号：动量 = 未来 5 日收益（仅用于测试账本登记路径）
        df["momentum_20d"] = (
            df["close"].shift(-5) / df["close"] - 1.0
        ).fillna(0.0)
        df["volatility_20d"] = rng.normal(0, 1, n_dates).cumsum()
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _pipeline(tmp_path, **cfg) -> ScanPipeline:
    _write_min_all_stock_codes(tmp_path)
    return ScanPipeline(data_dir=str(tmp_path), config=ScanConfig(**cfg))


class TestScanPipelineLedgerWiring:
    def test_default_config_enables_ledger(self):
        config = ScanConfig()
        assert config.ledger_enabled is True
        assert config.ledger_path is None
        assert config.ledger_family_id == "factor_scan"

    def test_analyze_factors_registers_real_trials(self, tmp_path):
        pipeline = _pipeline(tmp_path)
        pipeline.combined_df = _synthetic_panel()

        report = pipeline.analyze_factors()
        ledger = report["research_ledger"]

        # 2 个因子列 × 3 个持有期 = 6 项试验
        assert ledger["registered"] == 6
        assert ledger["total_platform_trials"] == 6
        assert set(ledger["per_factor"]) == {"momentum_20d", "volatility_20d"}
        for trial in ledger["trials"]:
            assert 0.0 <= trial["p_adj_bh_fdr"] <= 1.0
            assert 0.0 <= trial["p_raw"] <= 1.0

    def test_registration_is_idempotent_within_instance(self, tmp_path):
        pipeline = _pipeline(tmp_path)
        pipeline.combined_df = _synthetic_panel()

        first = pipeline.analyze_factors()["research_ledger"]
        second = pipeline.analyze_factors()["research_ledger"]
        assert first == second
        assert pipeline._ledger.total_trials == 6

    def test_ledger_disabled_skips_registration(self, tmp_path):
        pipeline = _pipeline(tmp_path, ledger_enabled=False)
        pipeline.combined_df = _synthetic_panel()
        report = pipeline.analyze_factors()
        assert "research_ledger" not in report
        assert pipeline._ledger is None

    def test_lightweight_mode_skips_registration(self, tmp_path):
        pipeline = _pipeline(tmp_path, lightweight=True)
        pipeline.combined_df = _synthetic_panel()
        report = pipeline.analyze_factors()
        assert report.get("lightweight_mode") is True
        assert "research_ledger" not in report

    def test_persistent_ledger_accumulates_across_instances(self, tmp_path):
        ledger_path = str(tmp_path / "research" / "ledger.json")

        p1 = _pipeline(tmp_path, ledger_path=ledger_path)
        p1.combined_df = _synthetic_panel()
        a1 = p1.analyze_factors()["research_ledger"]
        assert a1["total_platform_trials"] == 6
        assert Path(ledger_path).exists()

        p2 = _pipeline(tmp_path, ledger_path=ledger_path)
        p2.combined_df = _synthetic_panel()
        a2 = p2.analyze_factors()["research_ledger"]
        # 同一族系跨运行累积 → 平台累计翻倍（这才是真实的科研自由度审计）
        assert a2["total_platform_trials"] == 12
        assert p2._ledger.trials[0].experiment_id != ""


# --------------------------------------------------------------------------
# 6. WalkForwardFactorPipeline wiring
# --------------------------------------------------------------------------
def _wf_panel(n_dates: int = 200, n_codes: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    frames = []
    for i in range(n_codes):
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "code": f"{i:06d}.SZ",
                    "close": 10.0 + np.cumsum(rng.normal(0, 0.05, n_dates)),
                    "factor_0": rng.normal(0, 1, n_dates),
                    "factor_1": rng.normal(0, 1, n_dates),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _wf_ic_results(window_index: int):
    from uniquant.brain.factors.analyzer import FactorICResult

    out = {}
    for factor in ("factor_0", "factor_1"):
        out[factor] = {
            period: FactorICResult(
                factor_name=factor,
                ic_mean=0.02,
                ic_std=0.1,
                icir=0.5,
                ic_positive_ratio=0.6,
                ic_t_stat=float(1 + window_index),
                n_periods=30,
            )
            for period in (1, 5, 20)
        }
    return out


def _make_ic_side_effect():
    """Per-window FakeIC results with an incrementing t-statistic.

    Mirrors the real pipeline call pattern: the per-window *train* IC call
    (factor_cols = the factor list) returns factor results; the OOS
    ``composite_score`` call returns no factor results.
    """
    state = {"i": 0}

    def side_effect(df, **kwargs):
        if kwargs.get("factor_cols") == ["composite_score"]:
            return {}
        idx = state["i"]
        state["i"] += 1
        return _wf_ic_results(idx)

    return side_effect


class TestWalkForwardLedgerWiring:
    def test_default_pipeline_has_no_ledger(self):
        from uniquant.brain.factors.walk_forward_pipeline import WalkForwardFactorPipeline

        pipeline = WalkForwardFactorPipeline(
            train_window=50, test_window=10, min_train_days=20
        )
        assert pipeline.ledger is None

    def test_run_without_ledger_leaves_audit_none(self):
        from unittest.mock import patch

        from uniquant.brain.factors.walk_forward_pipeline import WalkForwardFactorPipeline

        pipeline = WalkForwardFactorPipeline(
            train_window=50, test_window=10, min_train_days=20
        )
        data = _wf_panel()
        with patch.object(
            pipeline.analyzer, "compute_ic_ir", side_effect=_make_ic_side_effect()
        ):
            result = pipeline.run(data, factor_cols=["factor_0", "factor_1"])
        assert result.ledger_audit is None

    def test_run_registers_median_across_windows(self):
        from unittest.mock import patch

        from uniquant.brain.factors.walk_forward_pipeline import WalkForwardFactorPipeline

        ledger = DegreesOfFreedomLedger()
        pipeline = WalkForwardFactorPipeline(
            train_window=50,
            test_window=10,
            min_train_days=20,
            ledger=ledger,
            ledger_family_id="wf_test",
        )
        data = _wf_panel()
        with patch.object(
            pipeline.analyzer, "compute_ic_ir", side_effect=_make_ic_side_effect()
        ):
            result = pipeline.run(data, factor_cols=["factor_0", "factor_1"])

        audit = result.ledger_audit
        assert audit is not None
        assert audit["family_id"] == "wf_test"
        # 2 因子 × 3 持有期 = 6 项试验
        assert audit["registered"] == 6
        assert ledger.total_trials == 6

        # 跨窗取中位数，而非单一幸运窗口的 t 统计量
        payload = audit["trials"][0]
        assert payload["factor"] == "factor_0"
        assert payload["holding_period"] == 1
        # 每窗一个 train IC 调用（共 len(windows) 窗）→ median(t=1..N)
        n_windows = len(result.windows)
        expected_median = float(np.median(np.arange(1, n_windows + 1)))
        assert payload["statistic"] == pytest.approx(expected_median)
        assert ledger.trials[0].metadata["aggregation"] == "median_across_windows"

