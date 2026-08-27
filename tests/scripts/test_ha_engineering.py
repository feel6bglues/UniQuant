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


# ─── build_holdings_map 5 日再平衡鞍律回归 (P13 修复) ────────────────────────


class TestHoldingsMapCadence:
    def test_five_day_cadence_not_daily_rebuild(self):
        """Top30 应只在再平衡日重建, 非再平衡热日沿用旧持仓 (修复每日重建 bug)。"""
        from scripts.canslim.ha_unified_adapter import (
            build_holdings_map, build_panel, load_hot_days,
        )

        panel = build_panel(200)
        hot = load_hot_days(pd.DatetimeIndex(sorted(panel["date"].unique())))
        hmap = build_holdings_map(panel, hot)

        # 统计连续热日内的持仓变更次数
        consec_changes = 0
        prev = None
        for d in sorted(hmap.keys()):
            s = hmap[d]
            if s and prev is not None:
                if s != prev:
                    consec_changes += 1
            prev = s
            if not s:
                prev = None
        total_hot_days = sum(1 for v in hmap.values() if v)

        # 修复前: 几乎每天都重建 (变更/天≈1.0); 修复后最大 ≈ REBALANCE_EVERY 天一次
        assert total_hot_days > 20
        assert consec_changes / total_hot_days < 0.6

    def test_holdings_persist_between_rebalances(self):
        from scripts.canslim.ha_unified_adapter import (
            build_holdings_map, build_panel, load_hot_days,
        )

        panel = build_panel(200)
        hot = load_hot_days(pd.DatetimeIndex(sorted(panel["date"].unique())))
        hmap = build_holdings_map(panel, hot)

        # 找一段连续 ≥5 个热日, 内部应无变更 (鞍律)
        dates = sorted(hmap.keys())
        for i in range(len(dates) - 4):
            if hmap[dates[i]] and all(hmap[dates[j]] for j in range(i, i + 5)):
                assert hmap[dates[i]] == hmap[dates[i + 1]] == hmap[dates[i + 4]]
                return
        assert False, "未找到连续5热日窗口"


# ─── SlotRotationSim 算术合成验证 ────────────────────────────────────────────


class TestRotationSimArithmetic:
    def test_two_slot_exact_nav_with_impact(self):
        """2 slot × 3 天 A/B: NAV 含市场冲击(0.1%)精确手算匹配。"""
        from scripts.canslim.ha_rotation_sim import SlotRotationSim

        A, B = "600001.SH", "000002.SZ"
        dates = pd.bdate_range("2024-01-02", periods=3)
        idx = pd.DatetimeIndex(dates)
        closes = pd.DataFrame({A: [10.0, 11.0, 10.5], B: [20.0, 21.0, 22.0]},
                              index=idx)
        pre = closes.shift(1)
        vol = pd.DataFrame({A: [1e6] * 3, B: [1e6] * 3}, index=idx)
        adv = vol.copy()
        hmap = {dates[0]: {A, B}, dates[1]: {A, B}, dates[2]: set()}
        z = {"commission_rate": 1e-9, "stamp_duty_rate": 1e-9,
             "slippage_rate": 1e-9, "min_commission": 0.0}
        res = SlotRotationSim(n_slots=2, initial_capital=200000.0,
                              engine_params=z).run(
            closes, pre, vol, adv, hmap, list(idx), nav_capture=True)
        got = [float(x) for x in res["_nav"].to_numpy()]
        # 手算 (冲击 impact=0.001, vol/adv=1):
        # slot0 budget=10万, 买价=10*1.001=10.01 → shares=int(10万/10.01/100)*100=9900,
        #   成本=9900*10.01=99099, 结余=901
        # slot1 budget=10万, 买价=20*1.001=20.02 → shares=int(10万/20.02/100)*100=4900,
        #   成本=4900*20.02=98098, 结余=1902
        day0 = 9900 * 10.0 + 901.0 + 4900 * 20.0 + 1902.0       # 199802
        day1 = 9900 * 11.0 + 901.0 + 4900 * 21.0 + 1902.0       # 214602
        # day2 全卖: 卖价 A=10.5*0.999=10.4895, B=22*0.999=21.978 → 各扣印花税(万5)
        sellA = 9900 * (10.5 * 0.999) - 9900 * (10.5 * 0.999) * 0.0005
        sellB = 4900 * (22.0 * 0.999) - 4900 * (22.0 * 0.999) * 0.0005
        day2 = sellA + sellB + 901.0 + 1902.0
        assert np.isclose(got[0], day0, atol=1.0), got
        assert np.isclose(got[1], day1, atol=1.0), got
        assert np.isclose(got[2], day2, atol=1.0), got
