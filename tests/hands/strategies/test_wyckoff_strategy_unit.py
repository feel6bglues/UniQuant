"""Behavioural unit tests for ``hands/strategies/wyckoff.trade_wyckoff``.

The strategy wraps :class:`WyckoffEngine`; these tests inject a deterministic
fake engine/report so every decision branch (threshold gate, spring freeze,
regime filter, exit simulation) is exercised with synthetic OHLCV only.

No data lake / network / TDX / czsc / backtrader dependencies.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import uniquant.hands.strategies.wyckoff as wyckoff
from uniquant.brain.wyckoff.models import (
    ConfidenceLevel,
    RiskRewardProjection,
    TradingPlan,
    WyckoffSignal,
)
from uniquant.hands.strategies.indicators import calc_atr
from uniquant.hands.strategies.wyckoff import load_wyckoff_params, trade_wyckoff
from uniquant.shared.cost_model import COST_BUY, COST_SELL

_AS_OF_IDX = 149  # 150 history bars (>= 100 required by the guard)


# ── synthetic data helpers ──────────────────────────────────────────────────


def _ohlcv(closes, start="2022-01-03", spread=0.001):
    c = np.asarray(closes, dtype=float)
    n = len(c)
    dates = pd.bdate_range(start, periods=n)
    o = np.concatenate([[c[0]], c[:-1]])
    hi = np.maximum(c, o) * (1.0 + spread)
    lo = np.minimum(c, o) * (1.0 - spread)
    return pd.DataFrame({
        "date": dates, "open": o, "high": hi, "low": lo,
        "close": c, "volume": np.full(n, 1_000_000.0),
    })


def _frame(future_rows, hist_close=100.0, hist_spread=0.001, n_hist=_AS_OF_IDX + 1):
    """History (flat) + an explicit list of future ``(open, high, low, close)``."""
    hist = _ohlcv([hist_close] * n_hist, spread=hist_spread)
    if not future_rows:
        return hist
    fut = pd.DataFrame(future_rows, columns=["open", "high", "low", "close"])
    fut["volume"] = 1_000_000.0
    fut["date"] = pd.bdate_range(hist["date"].iloc[-1], periods=len(fut) + 1)[1:]
    return pd.concat([hist, fut], ignore_index=True)


def _as_of(f):
    return f.iloc[_AS_OF_IDX]["date"].strftime("%Y-%m-%d")


def _dummy_csi():
    return _ohlcv([100.0 + i * 0.5 for i in range(200)], start="2020-01-02")


def _bear_csi():
    return _ohlcv([200.0 - i * 0.5 for i in range(200)], start="2020-01-02")


# ── fake engine plumbing ────────────────────────────────────────────────────


class _FakeReport:
    def __init__(self, signal_type="sos", direction="做多",
                 confidence=ConfidenceLevel.A, spring_date=None,
                 entry_price=None, stop_loss=None, first_target=None):
        self.signal = WyckoffSignal(
            signal_type=signal_type, confidence=confidence, spring_date=spring_date,
        )
        self.trading_plan = TradingPlan(direction=direction)
        self.risk_reward = RiskRewardProjection(
            entry_price=entry_price, stop_loss=stop_loss, first_target=first_target,
        )


class _FakeEngine:
    report = None
    raise_in_init = False

    def __init__(self, **_kwargs):
        if _FakeEngine.raise_in_init:
            raise RuntimeError("engine boom")

    def analyze(self, *_a, **_k):
        return _FakeEngine.report


@pytest.fixture(autouse=True)
def _clear_params_cache():
    load_wyckoff_params.cache_clear()
    yield
    load_wyckoff_params.cache_clear()


def _install_fake_engine(monkeypatch):
    monkeypatch.setattr(wyckoff, "WyckoffEngine", _FakeEngine)
    # Bypass the (broken) on-disk config lookup so the strategy body runs.
    monkeypatch.setattr(wyckoff, "load_wyckoff_params", lambda: (30, 10, 5, "B"))
    _FakeEngine.raise_in_init = False
    _FakeEngine.report = None
    return _FakeEngine


@pytest.fixture
def range_regime(monkeypatch):
    """Force the 'range' regime params (mh=90, ts=45, atr_mult=1.5)."""
    monkeypatch.setattr(wyckoff, "get_regime", lambda csi, d: "range")
    yield


@pytest.fixture
def fake_engine(monkeypatch, range_regime):
    yield _install_fake_engine(monkeypatch)


@pytest.fixture
def fake_engine_real_regime(monkeypatch):
    """Fake engine + real ``get_regime`` (for regime-filter tests)."""
    yield _install_fake_engine(monkeypatch)


# ── load_wyckoff_params (real config reader) ────────────────────────────────


_YAML = """\
strategies:
  wyckoff:
    lookback_days: 300
    weekly_lookback: 90
    monthly_lookback: 30
    min_confidence_level: "C"
"""


class TestLoadWyckoffParams:
    """第八轮更正：本类原先通过伪造 ``__file__`` 为 ``<tmp>/pkg/sub/mod.py``
    两级布局，使 ``parents[2]`` "恰好" 指向临时目录 —— 这等于把**生产 bug**
    固化为"正确行为"（真实文件位于 ``src/uniquant/hands/strategies/``，
    ``parents[2]`` 实为 ``src/uniquant/``，而真实配置在仓库根
    ``config/trading.yaml``）。修复后统一使用仓库根 SSOT ``PROJECT_ROOT``，
    测试同步改为断言真实解析路径与真实配置文件。"""

    def _point_at(self, tmp_path, monkeypatch, text):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir(exist_ok=True)
        (cfg_dir / "trading.yaml").write_text(text)
        monkeypatch.setattr(wyckoff, "PROJECT_ROOT", tmp_path)
        load_wyckoff_params.cache_clear()

    def test_resolves_via_project_root_ssot(self):
        from uniquant.shared.constants.path import PROJECT_ROOT

        assert wyckoff.PROJECT_ROOT == PROJECT_ROOT

    def test_reads_real_repo_config(self):
        """无 monkeypatch：真实 ``config/trading.yaml`` 必须可解析。

        修复前此处抛 ``FileNotFoundError``（被 ``trade_wyckoff`` 吞掉 →
        策略恒返回 None），故本用例即"策略不是死代码"的守卫之一。
        """
        import yaml

        from uniquant.shared.constants.path import PROJECT_ROOT

        cfg = yaml.safe_load((PROJECT_ROOT / "config" / "trading.yaml").read_text())
        w = cfg["strategies"]["wyckoff"]
        expected = (
            w["lookback_days"],
            w["weekly_lookback"],
            w["monthly_lookback"],
            w.get("min_confidence_level", "B"),
        )
        assert load_wyckoff_params() == expected

    def test_reads_values_and_min_confidence(self, tmp_path, monkeypatch):
        self._point_at(tmp_path, monkeypatch, _YAML)
        assert load_wyckoff_params() == (300, 90, 30, "C")

    def test_min_confidence_defaults_to_b(self, tmp_path, monkeypatch):
        self._point_at(tmp_path, monkeypatch, _YAML.replace('    min_confidence_level: "C"\n', ""))
        assert load_wyckoff_params() == (300, 90, 30, "B")


# ── trade_wyckoff: real-config wiring (round-8 regression guard) ─────────────


class TestTradeWyckoffRealConfigWiring:
    """第八轮回归守卫：``load_wyckoff_params`` **不得**被 mock。

    修复前该函数抛 ``FileNotFoundError`` → 被 ``trade_wyckoff`` 的
    ``except Exception`` 吞掉 → 引擎从未被调用、策略恒返回 ``None``。
    """

    def test_engine_is_invoked_with_real_config(self, monkeypatch):
        seen: dict = {}

        class _SpyEngine:
            def __init__(self, **kw):
                seen["kwargs"] = kw

            def analyze(self, *a, **k):
                seen["analyzed"] = True
                return _FakeReport(signal_type="no_signal", direction="空仓观望")

        monkeypatch.setattr(wyckoff, "WyckoffEngine", _SpyEngine)
        f = _frame([(100.0, 100.1, 99.9, 100.0)] * 5)
        out = trade_wyckoff(f, _as_of(f), symbol="000001.SZ")

        assert seen.get("analyzed") is True, "引擎未被调用 = 配置加载失败被静默吞掉"
        real = load_wyckoff_params()
        assert (
            seen["kwargs"]["lookback_days"],
            seen["kwargs"]["weekly_lookback"],
            seen["kwargs"]["monthly_lookback"],
        ) == real[:3]
        assert out is None  # no_signal


# ── trade_wyckoff guards ────────────────────────────────────────────────────


class TestTradeWyckoffGuards:
    def test_live_mode_rejected(self, fake_engine):
        with pytest.raises(NotImplementedError):
            trade_wyckoff(_frame([(100, 101, 99, 100)] * 60), _as_of(_frame([])), mode="live")

    def test_none_when_history_below_100(self, fake_engine):
        f = _frame([], n_hist=50)
        assert trade_wyckoff(f, f.iloc[-1]["date"].strftime("%Y-%m-%d")) is None

    def test_none_when_engine_construction_fails(self, fake_engine):
        fake_engine.raise_in_init = True
        fake_engine.report = _FakeReport()
        f = _frame([(100.0, 100.1, 99.9, 100.0)] * 100)
        assert trade_wyckoff(f, _as_of(f)) is None

    def test_none_for_no_signal(self, fake_engine):
        fake_engine.report = _FakeReport(signal_type="no_signal", direction="做多")
        f = _frame([(100.0, 100.1, 99.9, 100.0)] * 100)
        assert trade_wyckoff(f, _as_of(f)) is None

    def test_none_for_flat_direction(self, fake_engine):
        fake_engine.report = _FakeReport(signal_type="sos", direction="空仓观望")
        f = _frame([(100.0, 100.1, 99.9, 100.0)] * 100)
        assert trade_wyckoff(f, _as_of(f)) is None

    def test_none_when_confidence_below_threshold(self, fake_engine):
        fake_engine.report = _FakeReport(confidence=ConfidenceLevel.C)  # min is B
        f = _frame([(100.0, 100.1, 99.9, 100.0)] * 100)
        assert trade_wyckoff(f, _as_of(f)) is None

    def test_confidence_lookup_error_is_swallowed(self, monkeypatch, fake_engine):
        # Invalid min_confidence name -> KeyError inside ConfidenceLevel[...] -> pass.
        monkeypatch.setattr(wyckoff, "load_wyckoff_params", lambda: (30, 10, 5, "Z"))
        fake_engine.report = _FakeReport(confidence=ConfidenceLevel.B)
        f = _frame([(100.0, 100.0, 100.0, 100.0)] * 100, hist_spread=0.0)
        out = trade_wyckoff(f, _as_of(f), csi=_dummy_csi())
        assert out is not None

    def test_confidence_value_error_is_swallowed(self, fake_engine):
        # Non-enum confidence -> ValueError in list.index -> pass.
        fake_engine.report = _FakeReport(confidence="B")
        f = _frame([(100.0, 100.0, 100.0, 100.0)] * 100, hist_spread=0.0)
        out = trade_wyckoff(f, _as_of(f), csi=_dummy_csi())
        assert out is not None

    def test_none_when_regime_is_bear(self, fake_engine_real_regime):
        fake_engine_real_regime.report = _FakeReport()
        f = _frame([(100.0, 100.1, 99.9, 100.0)] * 100)
        assert trade_wyckoff(f, _as_of(f), csi=_bear_csi()) is None

    def test_none_when_forward_window_too_short(self, fake_engine):
        # regime "range" -> mh=90 -> requires >= 45 forward bars.
        fake_engine.report = _FakeReport()
        f = _frame([(100.0, 100.1, 99.9, 100.0)] * 20)
        assert trade_wyckoff(f, _as_of(f), csi=_dummy_csi()) is None


# ── spring freeze window ────────────────────────────────────────────────────


class _FakeCal:
    def __init__(self, size):
        self._size = size

    def sessions_in_range(self, _sd, _ad):
        return type("Sessions", (), {"size": self._size})()


class _FakeXcals:
    def __init__(self, size=None, raises=False):
        self._size = size
        self._raises = raises

    def get_calendar(self, _name):
        if self._raises:
            raise RuntimeError("calendar unavailable")
        return _FakeCal(self._size)


class TestSpringFreeze:
    def _spring_frame(self, days_before=0):
        f = _frame([(100.0, 100.0, 100.0, 100.0)] * 100, hist_spread=0.0)
        sd = f.iloc[_AS_OF_IDX - days_before]["date"].strftime("%Y-%m-%d")
        return f, sd

    def test_none_without_exchange_calendar_within_three_days(self, fake_engine, monkeypatch):
        monkeypatch.setattr(wyckoff, "xcals", None)
        f, sd = self._spring_frame(days_before=2)
        fake_engine.report = _FakeReport(signal_type="spring", spring_date=sd)
        assert trade_wyckoff(f, _as_of(f)) is None

    def test_uses_exchange_calendar_when_available(self, fake_engine, monkeypatch):
        monkeypatch.setattr(wyckoff, "xcals", _FakeXcals(size=10))
        f, sd = self._spring_frame(days_before=5)
        fake_engine.report = _FakeReport(signal_type="spring", spring_date=sd)
        out = trade_wyckoff(f, _as_of(f), csi=_dummy_csi())
        assert out is not None

    def test_calendar_error_falls_back_to_business_days(self, fake_engine, monkeypatch):
        monkeypatch.setattr(wyckoff, "xcals", _FakeXcals(raises=True))
        f, sd = self._spring_frame(days_before=10)
        fake_engine.report = _FakeReport(signal_type="spring", spring_date=sd)
        out = trade_wyckoff(f, _as_of(f), csi=_dummy_csi())
        assert out is not None

    def test_non_spring_signal_skips_freeze_block(self, fake_engine, monkeypatch):
        monkeypatch.setattr(wyckoff, "xcals", _FakeXcals(size=0))  # would freeze if used
        f = _frame([(100.0, 100.0, 100.0, 100.0)] * 100, hist_spread=0.0)
        fake_engine.report = _FakeReport(signal_type="sos", spring_date=None)
        out = trade_wyckoff(f, _as_of(f), csi=_dummy_csi())
        assert out is not None


# ── exit simulation ─────────────────────────────────────────────────────────


class TestExitSimulation:
    def _report(self, **kw):
        return _FakeReport(**kw)

    def _run(self, fake_engine, future, **report_kw):
        fake_engine.report = self._report(**report_kw)
        f = _frame(future)
        return trade_wyckoff(f, _as_of(f), csi=_dummy_csi())

    def test_gap_stop_loss(self, fake_engine):
        # stop_loss far above price -> first bar gaps below it.
        fut = [(90.0, 91.0, 89.0, 90.0)] + [(100.0, 100.5, 99.5, 100.0)] * 99
        out = self._run(fake_engine, fut, stop_loss=200.0)
        expected = (90.0 - 100.0) / 100.0 * 100 - (COST_BUY + COST_SELL) * 100
        assert out["days"] == 1
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_intrabar_stop_loss(self, fake_engine):
        fut = [(100.0, 100.0, 94.0, 99.0)] + [(100.0, 100.5, 99.5, 100.0)] * 99
        out = self._run(fake_engine, fut, stop_loss=95.0)
        expected = (95.0 - 100.0) / 100.0 * 100 - (COST_BUY + COST_SELL) * 100
        assert out["days"] == 1
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_uses_engine_entry_price_when_far_from_close(self, fake_engine):
        # entry_price well away from close -> use_we True -> entry = 50.
        fut = [(100.0, 100.0, 40.0, 45.0)] + [(100.0, 100.5, 99.5, 100.0)] * 99
        out = self._run(fake_engine, fut, entry_price=50.0, stop_loss=0.0)
        # ss = entry*0.93 = 46.5 (stop_loss<=0 -> fallback)
        expected = (46.5 - 50.0) / 50.0 * 100 - (COST_BUY + COST_SELL) * 100
        assert out["days"] == 1
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_target_half_then_trailing_stop(self, fake_engine):
        fut = [(100.0, 106.0, 100.0, 105.0), (101.0, 101.0, 95.0, 96.0)]
        fut += [(100.0, 100.0, 100.0, 100.0)] * 100
        out = self._run(fake_engine, fut, first_target=105.0)
        hist = _frame([]).tail(60)
        atr = calc_atr(hist, 20)
        ts_p = 106.0 - 1.5 * atr  # range regime atr_mult = 1.5
        r1 = (105.0 - 100.0) / 100.0 * 100
        r2 = (ts_p - 100.0) / 100.0 * 100
        expected = 0.5 * r1 + 0.5 * r2 - (COST_BUY + COST_SELL) * 100
        assert out["days"] == 2
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_time_stop_after_ts_days(self, fake_engine):
        # First target below entry -> eff_t falls back to atr target; flat prices
        # never reach it, so the trailing/time stop governs (ts=45).
        fut = [(100.02, 100.05, 100.02, 100.03)] * 120
        out = self._run(fake_engine, fut, first_target=90.0)
        assert out["days"] == 46
        assert isinstance(out["ret"], float)

    def test_max_hold_when_half_target_taken(self, fake_engine):
        # Monotonic rise: target half taken on day 1, tight bars avoid trailing
        # stop, loop runs to the full max-hold window (mh=90 for "range").
        closes = np.linspace(105.0, 120.0, 90)
        fut = [(c - 0.02, c + 0.01, c - 0.01, c) for c in closes]
        out = self._run(fake_engine, fut, first_target=105.0)
        expected = 0.5 * 5.0 + 0.5 * (120.0 - 100.0) / 100.0 * 100
        expected -= (COST_BUY + COST_SELL) * 100
        assert out["days"] == 90
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_zero_atr_history_falls_back_to_percent_atr(self, fake_engine):
        # Perfectly flat history => calc_atr == 0 => atr = entry*0.02 guard.
        fut = [(100.0, 100.0, 100.0, 100.0)] * 100
        fake_engine.report = self._report(first_target=90.0)
        f = _frame(fut, hist_spread=0.0)
        out = trade_wyckoff(f, _as_of(f), csi=_dummy_csi())
        assert out is not None
        assert isinstance(out["days"], int)

    def test_explicit_cost_override(self, fake_engine):
        fut = [(90.0, 91.0, 89.0, 90.0)] + [(100.0, 100.5, 99.5, 100.0)] * 99
        fake_engine.report = self._report(stop_loss=200.0)
        f = _frame(fut)
        out = trade_wyckoff(f, _as_of(f), csi=_dummy_csi(), cost_buy=0.01, cost_sell=0.02)
        expected = (90.0 - 100.0) / 100.0 * 100 - (0.01 + 0.02) * 100
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_unknown_regime_uses_default_params(self, fake_engine, monkeypatch):
        # csi is None -> regime "unknown" (mh=120); provide 130 forward bars.
        fut = [(90.0, 91.0, 89.0, 90.0)] + [(100.0, 100.5, 99.5, 100.0)] * 129
        fake_engine.report = self._report(stop_loss=200.0)
        f = _frame(fut)
        out = trade_wyckoff(f, _as_of(f))  # csi omitted
        assert out["days"] == 1
