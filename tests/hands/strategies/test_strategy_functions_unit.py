"""Behavioural unit tests for the small function-based strategies.

Targets (``src/uniquant/hands/strategies/``):
    * ``ma_cross.py``  -> ``trade_ma``
    * ``regime.py``    -> ``get_regime`` / ``trade_regime``
    * ``str_reversal.py`` -> ``trade_str_reversal``

These tests use synthetic OHLCV only (no data lake, no network, no TDX) and
assert real return shapes / numeric behaviour rather than merely hitting lines.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uniquant.hands.strategies.ma_cross import trade_ma
from uniquant.hands.strategies.regime import get_regime, trade_regime
from uniquant.hands.strategies.str_reversal import trade_str_reversal
from uniquant.shared.cost_model import COST_BUY, COST_SELL

_START = "2022-01-03"


def _frame(closes, start: str = _START, spread: float = 0.001,
           highs=None, lows=None, opens=None) -> pd.DataFrame:
    """Build a deterministic OHLCV frame from a close series.

    ``open`` defaults to the previous close (first open == first close), which
    keeps the synthetic series internally consistent without randomness.
    """
    c = np.asarray(closes, dtype=float)
    n = len(c)
    dates = pd.bdate_range(start, periods=n)
    o = np.concatenate([[c[0]], c[:-1]]) if opens is None else np.asarray(opens, float)
    hi = (np.maximum(c, o) * (1.0 + spread)) if highs is None else np.asarray(highs, float)
    lo = (np.minimum(c, o) * (1.0 - spread)) if lows is None else np.asarray(lows, float)
    return pd.DataFrame({
        "date": dates,
        "open": o,
        "high": hi,
        "low": lo,
        "close": c,
        "volume": np.full(n, 1_000_000.0),
    })


def _d(f: pd.DataFrame, i: int) -> str:
    return f.iloc[i]["date"].strftime("%Y-%m-%d")


# ── trade_ma (ma_cross) ─────────────────────────────────────────────────────


def _ma_cross_history() -> list:
    """30 closes whose last-30 window just produced a golden cross.

    First 25 fall 100 -> 76, last 5 jump to 110 (fast MA crosses above slow MA).
    """
    return [float(100 - i) for i in range(25)] + [90.0, 95.0, 100.0, 105.0, 110.0]


class TestTradeMa:
    def test_none_below_25_bars_of_history(self):
        f = _frame([100.0] * 20)
        assert trade_ma(f, _d(f, 19)) is None

    def test_none_when_no_golden_cross(self):
        f = _frame([100.0 - i * 0.5 for i in range(40)])  # steady decline: fast < slow
        assert trade_ma(f, _d(f, 30)) is None

    def test_none_when_no_future_bars(self):
        # Cross is present but as_of == last bar -> no forward data.
        f = _frame(_ma_cross_history())
        assert trade_ma(f, _d(f, 29)) is None

    def test_none_when_forward_window_shorter_than_five(self):
        # Cross present, only two future bars -> fx shorter than 5 -> None.
        closes = _ma_cross_history() + [109.0, 108.0]
        f = _frame(closes)
        assert trade_ma(f, _d(f, 29)) is None

    def test_death_cross_exit_uses_first_break_day(self):
        # Descending future -> fast MA drops below slow MA at day 6.
        closes = _ma_cross_history() + [float(109 - i) for i in range(30)]
        f = _frame(closes)
        out = trade_ma(f, _d(f, 29))
        assert out is not None
        # entry = open of first future bar (= close at as_of = 110)
        # exit  = close of the 6th future bar (104)
        expected = (104.0 - 110.0) / 110.0 * 100 - (COST_BUY + COST_SELL) * 100
        assert out["days"] == 6
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_executes_until_max_forward_window(self):
        # Flat future: loop finds no cross -> ed = min(120, len(fut)-1) = 9.
        closes = _ma_cross_history() + [120.0] * 10
        f = _frame(closes)
        out = trade_ma(f, _d(f, 29))
        expected = (120.0 - 110.0) / 110.0 * 100 - (COST_BUY + COST_SELL) * 100
        assert out["days"] == 10
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_explicit_cost_override_is_applied(self):
        closes = _ma_cross_history() + [float(109 - i) for i in range(30)]
        f = _frame(closes)
        out = trade_ma(f, _d(f, 29), cost_buy=0.01, cost_sell=0.02)
        expected = (104.0 - 110.0) / 110.0 * 100 - (0.01 + 0.02) * 100
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_live_mode_is_rejected(self):
        f = _frame(_ma_cross_history())
        with pytest.raises(NotImplementedError):
            trade_ma(f, _d(f, 29), mode="live")


# ── get_regime / trade_regime ───────────────────────────────────────────────


def _bull_csi() -> pd.DataFrame:
    # Starts well before the stock frames so it has 120+ bars at 2022 as_of dates.
    return _frame([100.0 + i for i in range(200)], start="2020-01-02")


def _bear_csi() -> pd.DataFrame:
    return _frame([200.0 - i * 0.5 for i in range(200)], start="2020-01-02")


def _range_csi() -> pd.DataFrame:
    return _frame([100.0 + 0.5 * np.sin(i / 3.0) for i in range(200)], start="2020-01-02")


class TestGetRegime:
    def test_bull_when_above_ma_and_ma_rising(self):
        csi = _bull_csi()
        assert get_regime(csi, _d(csi, 199)) == "bull"

    def test_bear_when_below_lower_band(self):
        csi = _bear_csi()
        assert get_regime(csi, _d(csi, 199)) == "bear"

    def test_range_when_within_band(self):
        csi = _range_csi()
        assert get_regime(csi, _d(csi, 199)) == "range"

    def test_unknown_without_index(self):
        assert get_regime(None, "2024-01-01") == "unknown"

    def test_unknown_when_history_shorter_than_120(self):
        csi = _frame([100.0] * 50)
        assert get_regime(csi, _d(csi, 49)) == "unknown"

    def test_as_of_truncation_uses_only_past_rows(self):
        csi = _bull_csi()
        # Querying an early date with <120 rows of history -> unknown.
        assert get_regime(csi, _d(csi, 50)) == "unknown"


class TestTradeRegime:
    def test_none_when_not_bull(self):
        csi = _bear_csi()
        f = _frame([100.0 - i for i in range(40)])
        assert trade_regime(f, _d(f, 30), csi=csi) is None

    def test_none_when_stock_history_below_five(self):
        csi = _bull_csi()
        f = _frame([100.0, 101.0, 102.0])  # only 3 rows <= as_of
        assert trade_regime(f, _d(f, 2), csi=csi) is None

    def test_none_when_forward_window_below_five(self):
        csi = _bull_csi()
        f = _frame([100.0 + i for i in range(10)])
        assert trade_regime(f, _d(f, 5), csi=csi) is None

    def test_returns_dict_with_default_costs(self):
        csi = _bull_csi()
        f = _frame([100.0 + i for i in range(40)])
        out = trade_regime(f, _d(f, 20), csi=csi)
        entry = 120.0
        exit_px = float(f.iloc[39]["close"])  # last of 19 forward bars
        expected = (exit_px - entry) / entry * 100 - (COST_BUY + COST_SELL) * 100
        assert out["days"] == 19
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_returns_dict_with_explicit_costs(self):
        csi = _bull_csi()
        f = _frame([100.0 + i for i in range(40)])
        out = trade_regime(f, _d(f, 20), cost_buy=0.001, cost_sell=0.002, csi=csi)
        entry = 120.0
        exit_px = float(f.iloc[39]["close"])
        expected = (exit_px - entry) / entry * 100 - (0.001 + 0.002) * 100
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_partial_cost_override_falls_back_to_default_for_other_side(self):
        csi = _bull_csi()
        f = _frame([100.0 + i for i in range(40)])
        out = trade_regime(f, _d(f, 20), cost_buy=0.0, csi=csi)
        entry = 120.0
        exit_px = float(f.iloc[39]["close"])
        expected = (exit_px - entry) / entry * 100 - (0.0 + COST_SELL) * 100
        assert out["ret"] == pytest.approx(round(expected, 2))


# ── trade_str_reversal ──────────────────────────────────────────────────────


def _reversal_history() -> list:
    """History that (a) has >=8 bars and (b) drops >5% over the last 5 bars."""
    return [100.0] * 20 + [112.0, 110.0, 108.0, 106.0, 104.0, 100.0]


class TestTradeStrReversal:
    def test_none_when_history_below_eight(self):
        f = _frame([100.0] * 5)
        assert trade_str_reversal(f, _d(f, 4)) is None

    def test_none_without_sharp_drop(self):
        f = _frame([100.0 + i for i in range(30)])
        assert trade_str_reversal(f, _d(f, 25)) is None

    def test_none_when_forward_window_below_three(self):
        # Sharp drop present but only two forward bars.
        f = _frame(_reversal_history())
        assert trade_str_reversal(f, _d(f, 25)) is None

    def test_take_profit_exit_on_first_bar(self):
        closes = _reversal_history() + [100.0, 101.0, 102.0]
        f = _frame(closes)
        # Force a wide first forward bar that reaches take profit.
        f.loc[26, "open"] = 100.0
        f.loc[26, "high"] = 130.0
        f.loc[26, "low"] = 99.9
        f.loc[26, "close"] = 105.0
        out = trade_str_reversal(f, _d(f, 25))
        assert out is not None
        atr = _atr_of_tail(f, 25, 14)
        tp = 100.0 + 2.0 * atr
        expected = (tp - 100.0) / 100.0 * 100 - (COST_BUY + COST_SELL) * 100
        assert out["days"] == 1
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_stop_loss_exit_on_first_bar(self):
        closes = _reversal_history() + [100.0, 100.0, 100.0]
        f = _frame(closes)
        f.loc[26, "open"] = 100.0
        f.loc[26, "high"] = 100.5
        f.loc[26, "low"] = 80.0
        f.loc[26, "close"] = 99.0
        out = trade_str_reversal(f, _d(f, 25))
        assert out is not None
        atr = _atr_of_tail(f, 25, 14)
        sl = 100.0 - 2.0 * atr
        expected = (sl - 100.0) / 100.0 * 100 - (COST_BUY + COST_SELL) * 100
        assert out["ret"] == pytest.approx(round(expected, 2))
        # 第八轮修复（回归守卫）: 止损分支原为 `ep, sl = sl, i + 1`（笔误，
        # 把退出天数写进了 sl，ed 保留初始 len(fut)）→ days 恒为可用前向
        # 天数。修复后与止盈分支对称，退出发生在第 1 根前向 K 线 → days == 1。
        assert out["days"] == 1

    def test_holds_to_end_when_neither_target_nor_stop_hit(self):
        closes = _reversal_history() + [100.0, 100.0, 100.0]
        f = _frame(closes)
        f.loc[26, ["open", "high", "low", "close"]] = [100.0, 100.0, 100.0, 100.0]
        f.loc[27, ["open", "high", "low", "close"]] = [100.0, 100.0, 100.0, 100.0]
        f.loc[28, ["open", "high", "low", "close"]] = [100.0, 100.0, 100.0, 100.0]
        out = trade_str_reversal(f, _d(f, 25))
        assert out is not None
        expected = 0.0 - (COST_BUY + COST_SELL) * 100
        assert out["days"] == 3
        assert out["ret"] == pytest.approx(round(expected, 2))

    def test_explicit_cost_override(self):
        closes = _reversal_history() + [100.0, 100.0, 100.0]
        f = _frame(closes)
        f.loc[26, ["open", "high", "low", "close"]] = [100.0, 100.0, 100.0, 100.0]
        f.loc[27, ["open", "high", "low", "close"]] = [100.0, 100.0, 100.0, 100.0]
        f.loc[28, ["open", "high", "low", "close"]] = [100.0, 100.0, 100.0, 100.0]
        out = trade_str_reversal(f, _d(f, 25), cost_buy=0.0, cost_sell=0.0)
        assert out["ret"] == pytest.approx(0.0)

    def test_live_mode_is_rejected(self):
        f = _frame(_reversal_history())
        with pytest.raises(NotImplementedError):
            trade_str_reversal(f, _d(f, 25), mode="live")


def _atr_of_tail(f: pd.DataFrame, as_of_idx: int, period: int) -> float:
    from uniquant.hands.strategies.indicators import calc_atr

    hist = f.iloc[: as_of_idx + 1].tail(25)
    return calc_atr(hist, period)
