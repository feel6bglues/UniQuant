"""H-A 工程化测试 (2026-08-26):
1. daily_signal_ha.compute_state 与 canonical pit_vol_states 一致性
2. reconcile_ha 对账引擎: 漂移/缺失/多余/现金/状态转换
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.canslim.daily_signal_ha import compute_state  # noqa: E402
from scripts.factor_mining.conditional_stats import pit_vol_states  # noqa: E402


def _index_df(n: int = 900, seed: int = 11) -> pd.DataFrame:
    """合成指数: 平静段 + 高波段 + 趋势切换, 覆盖三档 vol_state。"""
    rng = np.random.RandomState(seed)
    rets = np.concatenate([
        rng.randn(min(300, n)) * 0.008,
        rng.randn(max(0, min(300, n - 300))) * 0.030,
        rng.randn(max(0, n - 600)) * 0.008 - 0.001,
    ])[:n]
    close = 4000 * np.exp(np.cumsum(rets))
    return pd.DataFrame({
        "date": pd.bdate_range("2020-01-02", periods=n),
        "close": close,
    })


class TestStateCanonicalConsistency:
    def test_matches_canonical_pit_states(self):
        idx = _index_df()
        state = compute_state(idx, None)
        states = pit_vol_states(idx)
        last_row = states[states["date"] == idx["date"].iloc[-1]]
        if len(last_row):
            assert state["vol_state"] == last_row.iloc[-1]["vol_state"]
            assert not state["vol_state"] == "insufficient_history"
        else:
            assert state["vol_state"] == "insufficient_history"

    def test_as_of_truncation_changes_nothing_upstream(self):
        idx = _index_df()
        cut = idx["date"].iloc[500]
        part = compute_state(idx, str(cut.date()))
        assert part["as_of"] == str(cut.date())
        # 截断日与全样本在截断日的判定一致
        states_full = pit_vol_states(idx)
        row = states_full[states_full["date"] == cut]
        if len(row):
            assert part["vol_state"] == row.iloc[-1]["vol_state"]

    def test_short_history_insufficient(self):
        idx = _index_df(120)
        assert compute_state(idx, None)["vol_state"] == "insufficient_history"

    def test_hot_bull_requires_both_conditions(self):
        idx = _index_df()
        s = compute_state(idx, None)
        assert s["hot_bull"] == bool(s["trend_on"] and s["vol_state"] == "vol_high")

    def test_trend_on_is_ma200_comparison(self):
        idx = _index_df()
        close = idx["close"]
        expect = bool(close.iloc[-1] > close.rolling(200).mean().iloc[-1])
        assert compute_state(idx, None)["trend_on"] == expect


# ─── reconcile_ha ─────────────────────────────────────────────────────────────

from scripts.canslim.reconcile_ha import (  # noqa: E402
    build_reconciliation,
    diff_signal_files,
)


def _signal_json(tmp_path: Path, target: list[dict], hot: bool = True,
                 date: str = "2026-07-23") -> Path:
    payload = {
        "generated_at": f"{date}T16:00:00",
        "strategy": "H-A conditional illiquidity (P7/P8/D+10)",
        "state": {"as_of": date, "hot_bull": hot},
        "action": "HOLD" if hot else "CASH (state off)",
        "target_portfolio": {"as_of": date, "n_eligible": 100, "target": target},
    }
    fp = tmp_path / f"{date}.json"
    fp.write_text(json.dumps(payload), encoding="utf-8")
    return fp


def _holdings_csv(tmp_path: Path, rows: list[tuple[str, int]],
                  cash: float = 0.0) -> Path:
    fp = tmp_path / "positions.csv"
    lines = ["code,shares,cash"] + [f"{c},{s},{cash if i == 0 else ''}"
                                    for i, (c, s) in enumerate(rows)]
    fp.write_text("\n".join(lines), encoding="utf-8")
    return fp


class TestDiffSignalFiles:
    def test_hot_to_cash_emits_liquidate(self, tmp_path):
        old = _signal_json(tmp_path, [{"code": "000001.SZ", "weight": 1.0}],
                           hot=True, date="2026-07-20")
        new = _signal_json(tmp_path, [], hot=False, date="2026-07-23")
        events = diff_signal_files(old, new)
        assert events[-1]["event"] == "ENTER_CASH"
        assert set(events[-1]["liquidate"]) == {"000001.SZ"}

    def test_cash_to_hot_emits_open(self, tmp_path):
        old = _signal_json(tmp_path, [], hot=False, date="2026-07-20")
        tgt = [{"code": "A", "weight": 0.5}, {"code": "B", "weight": 0.5}]
        new = _signal_json(tmp_path, tgt, hot=True, date="2026-07-23")
        events = diff_signal_files(old, new)
        assert events[-1]["event"] == "ENTER_HOT"
        assert set(events[-1]["open"]) == {"A", "B"}

    def test_in_market_rebalance_change(self, tmp_path):
        old = _signal_json(
            tmp_path, [{"code": "A", "weight": 0.5}, {"code": "B", "weight": 0.5}],
            True, "2026-07-18")
        new = _signal_json(
            tmp_path, [{"code": "B", "weight": 0.5}, {"code": "C", "weight": 0.5}],
            True, "2026-07-23")
        events = diff_signal_files(old, new)
        ev = events[-1]
        assert ev["event"] == "REBALANCE"
        assert ev["added"] == ["C"] and ev["removed"] == ["A"] and ev["kept"] == ["B"]


class TestBuildReconciliation:
    def _prices(self, tmp_path: Path, codes: dict[str, float]) -> dict[str, float]:
        # 简化: 价格直接给定 (reconcile 支持显式价格表输入)
        return codes

    def test_perfect_match_green(self, tmp_path):
        sig = _signal_json(tmp_path, [
            {"code": "A", "weight": 0.5}, {"code": "B", "weight": 0.5}])
        pos = _holdings_csv(tmp_path, [("A", 500), ("B", 250)])
        rep = build_reconciliation(sig, pos, prices={"A": 10.0, "B": 20.0})
        assert rep["summary"]["n_missing"] == 0
        assert rep["summary"]["n_extra"] == 0
        for row in rep["rows"]:
            assert abs(row["drift_pp"]) < 0.01

    def test_missing_and_extra_flagged(self, tmp_path):
        sig = _signal_json(tmp_path, [
            {"code": "A", "weight": 0.5}, {"code": "B", "weight": 0.5}])
        pos = _holdings_csv(tmp_path, [("A", 500), ("X", 100)])
        rep = build_reconciliation(sig, pos, prices={"A": 10.0, "X": 5.0})
        assert rep["summary"]["n_missing"] == 1
        missing_codes = {r["code"] for r in rep["rows"] if r["status"] == "MISSING"}
        assert missing_codes == {"B"}
        extra_codes = {r["code"] for r in rep["rows"] if r["status"] == "EXTRA"}
        assert extra_codes == {"X"}

    def test_drift_threshold_yellow(self, tmp_path):
        sig = _signal_json(tmp_path, [
            {"code": "A", "weight": 0.4}, {"code": "B", "weight": 0.6}])
        # A 市值 9000 / 总 21000 ≈ 42.9% → drift +2.9pp
        pos = _holdings_csv(tmp_path, [("A", 900), ("B", 60)])
        rep = build_reconciliation(sig, pos, prices={"A": 10.0, "B": 200.0},
                                   drift_tol_pp=2.0)
        row_a = next(r for r in rep["rows"] if r["code"] == "A")
        assert row_a["status"] == "DRIFT"
        assert row_a["drift_pp"] > 2.0

    def test_cash_mode_requires_empty_book(self, tmp_path):
        sig = _signal_json(tmp_path, [], hot=False)
        pos = _holdings_csv(tmp_path, [("A", 100)])
        rep = build_reconciliation(sig, pos, prices={"A": 10.0})
        assert rep["summary"]["mode"] == "CASH"
        assert rep["summary"]["n_extra"] == 1

    def test_total_value_consistency(self, tmp_path):
        sig = _signal_json(tmp_path, [{"code": "A", "weight": 1.0}])
        pos = _holdings_csv(tmp_path, [("A", 100)], cash=500.0)
        rep = build_reconciliation(sig, pos, prices={"A": 25.0})
        assert np.isclose(rep["summary"]["total_value"], 3000.0)
