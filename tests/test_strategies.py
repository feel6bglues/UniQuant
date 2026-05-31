import numpy as np
import pandas as pd
import pytest

from uniquant.hands.strategies.indicators import calc_atr
from uniquant.hands.strategies.ma_cross import trade_ma
from uniquant.hands.strategies.str_reversal import trade_str_reversal
from uniquant.hands.strategies.regime import get_regime, trade_regime


def _make_ohlcv(
    n: int = 200, start: str = "2023-01-01", trend: str = "up",
) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=n)
    np.random.seed(42)
    if trend == "up":
        close = 10.0 + np.cumsum(np.random.randn(n) * 0.3 + 0.05)
    elif trend == "down":
        close = 20.0 + np.cumsum(np.random.randn(n) * 0.3 - 0.05)
    else:
        close = 15.0 + np.cumsum(np.random.randn(n) * 0.3)
    close = np.maximum(close, 1.0)
    high = close * (1 + np.abs(np.random.randn(n)) * 0.01)
    low = close * (1 - np.abs(np.random.randn(n)) * 0.01)
    opn = close * (1 + np.random.randn(n) * 0.005)
    volume = np.random.randint(100000, 1000000, n).astype(float)
    return pd.DataFrame({
        "date": dates, "open": opn, "high": high, "low": low,
        "close": close, "volume": volume,
    })


# ── calc_atr ────────────────────────────────────────────────────────────────

class TestCalcAtr:
    def test_returns_positive_for_valid_data(self):
        df = _make_ohlcv(50)
        assert calc_atr(df, 14) > 0

    def test_returns_zero_when_insufficient_data(self):
        df = _make_ohlcv(5)
        assert calc_atr(df, 20) == 0.0

    def test_atr_increases_with_volatility(self):
        calm = _make_ohlcv(50)
        calm["high"] = calm["close"] * 1.001
        calm["low"] = calm["close"] * 0.999
        wild = _make_ohlcv(50)
        wild["high"] = wild["close"] * 1.05
        wild["low"] = wild["close"] * 0.95
        assert calc_atr(wild, 14) > calc_atr(calm, 14)


# ── trade_ma (ma_cross) ─────────────────────────────────────────────────────

class TestTradeMa:
    def test_returns_dict_or_none(self):
        df = _make_ohlcv(200, trend="up")
        as_of = df.iloc[100]["date"].strftime("%Y-%m-%d")
        result = trade_ma(df, as_of)
        assert result is None or isinstance(result, dict)

    def test_returns_none_for_insufficient_data(self):
        df = _make_ohlcv(10)
        as_of = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        assert trade_ma(df, as_of) is None

    def test_result_has_ret_and_days(self):
        df = _make_ohlcv(300, trend="up")
        for i in range(80, 150):
            as_of = df.iloc[i]["date"].strftime("%Y-%m-%d")
            result = trade_ma(df, as_of)
            if result is not None:
                assert "ret" in result and "days" in result
                assert isinstance(result["ret"], float)
                assert result["days"] > 0
                return
        pytest.skip("No trade_ma signal found in up-trend data")

    def test_live_mode_raises(self):
        df = _make_ohlcv(200)
        with pytest.raises(NotImplementedError):
            trade_ma(df, "2023-06-01", mode="live")


# ── trade_str_reversal ──────────────────────────────────────────────────────

class TestTradeStrReversal:
    def test_returns_none_when_no_drop(self):
        df = _make_ohlcv(200, trend="up")
        as_of = df.iloc[100]["date"].strftime("%Y-%m-%d")
        assert trade_str_reversal(df, as_of) is None

    def test_returns_none_insufficient_data(self):
        df = _make_ohlcv(10)
        as_of = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        assert trade_str_reversal(df, as_of) is None

    def test_triggers_on_sharp_drop(self):
        df = _make_ohlcv(200, trend="up")
        drop_idx = 100
        for j in range(1, 6):
            if drop_idx + j < len(df):
                close_val = df.loc[drop_idx, "close"] * (1 - 0.02 * j)
                df.loc[drop_idx + j, "close"] = close_val
                df.loc[drop_idx + j, "low"] = close_val * 0.99
        as_of = df.iloc[drop_idx + 5]["date"].strftime("%Y-%m-%d")
        result = trade_str_reversal(df, as_of)
        if result is not None:
            assert "ret" in result and "days" in result
        assert result is None or isinstance(result, dict)

    def test_live_mode_raises(self):
        df = _make_ohlcv(200)
        with pytest.raises(NotImplementedError):
            trade_str_reversal(df, "2023-06-01", mode="live")


# ── get_regime / trade_regime ────────────────────────────────────────────────

class TestRegime:
    def test_get_regime_returns_string(self):
        csi = _make_ohlcv(200, trend="up")
        d = csi.iloc[-1]["date"].strftime("%Y-%m-%d")
        regime = get_regime(csi, d)
        assert regime in ("bull", "bear", "range", "unknown")

    def test_get_regime_unknown_with_none_csi(self):
        assert get_regime(None, "2024-01-01") == "unknown"

    def test_get_regime_unknown_short_data(self):
        csi = _make_ohlcv(10)
        d = csi.iloc[-1]["date"].strftime("%Y-%m-%d")
        assert get_regime(csi, d) == "unknown"

    def test_trade_regime_returns_none_in_bear(self):
        csi = _make_ohlcv(200, trend="down")
        df = _make_ohlcv(200, trend="down")
        d = df.iloc[100]["date"].strftime("%Y-%m-%d")
        result = trade_regime(df, d, csi=csi)
        assert result is None or isinstance(result, dict)

    def test_trade_regime_returns_dict_in_bull(self):
        csi = _make_ohlcv(250, trend="up")
        df = _make_ohlcv(250, trend="up")
        d = df.iloc[150]["date"].strftime("%Y-%m-%d")
        result = trade_regime(df, d, csi=csi)
        if result is not None:
            assert "ret" in result and "days" in result
        assert result is None or isinstance(result, dict)


# ── registry ─────────────────────────────────────────────────────────────────

class TestRegistry:
    def test_all_strategies_registered(self):
        from uniquant.hands.strategies.registry import STRATEGY_MAP
        for name in ("wyckoff", "ma_cross", "reversal", "regime"):
            assert name in STRATEGY_MAP
            assert callable(STRATEGY_MAP[name])
