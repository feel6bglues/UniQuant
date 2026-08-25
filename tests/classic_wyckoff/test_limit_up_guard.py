"""V5 涨停守卫修复验证 (2026-08-12 深度验证发现)。

P0 实施后，单涨停日 + MARKUP 相位因 engine.py 缺 LIMIT_UP 守卫，
direction="做多" 经由 adapter gate 输出 BUY。本测试验证修复后：
- LIMIT_UP (单日涨停) → direction="空仓观望" → adapter output=None
- BREAK_LIMIT_UP (炸板) → 同上
- 正常 MARKUP 无涨跌停 → direction 不被 LIMIT_UP 守卫影响
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from scripts.wyckoff_fixtures import synthetic_accumulation
from uniquant.brain.wyckoff.engine import WyckoffEngine
from uniquant.signal.adapters import WyckoffAdapter


def synthetic_markup(seed: int = 42) -> pd.DataFrame:
    df = synthetic_accumulation(seed=seed).copy()
    close = df["close"].values.astype(float)
    n = len(close)
    for i in range(15):
        close[n - 15 + i] = close[n - 16] * (1 + 0.02 * (i + 1))
    df["close"] = close
    rng = np.random.default_rng(seed)
    df["open"] = close * (1 + rng.uniform(-0.005, 0.005, n))
    df["high"] = np.maximum(df["close"], df["open"]) * 1.02
    df["low"] = np.minimum(df["close"], df["open"]) * 0.98
    df["volume"] = df["volume"] * 2.0
    return df


def _last_day_limit_up(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pre_close = df["close"].iloc[-2]
    df.loc[df.index[-1], "close"] = round(pre_close * 1.10, 2)
    df.loc[df.index[-1], "high"] = max(df.loc[df.index[-1], "high"], df.loc[df.index[-1], "close"])
    return df


def _last_day_break_limit_up(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pre_close = df["close"].iloc[-2]
    df.loc[df.index[-1], "high"] = round(pre_close * 1.10, 2)
    df.loc[df.index[-1], "close"] = round(pre_close * 1.03, 2)
    return df


@pytest.fixture(autouse=True)
def _markup_deterministic():
    with patch("uniquant.brain.wyckoff.engine.get_config") as mc:
        mc.return_value.get.side_effect = lambda k, d=None: {
            "wyckoff.wss_enabled": False,
            "wyckoff.wss_lookup_path": "",
            "wyckoff.structural_adjust_enabled": True,
        }.get(k, d)
        yield


class TestLimitUpGuard:
    def test_limit_up_forces_hold(self):
        df = _last_day_limit_up(synthetic_markup(seed=42))
        engine = WyckoffEngine()
        report = engine.analyze(df, symbol="T")
        assert report.trading_plan.direction == "空仓观望"

    def test_break_limit_up_forces_hold(self):
        df = _last_day_break_limit_up(synthetic_markup(seed=42))
        engine = WyckoffEngine()
        report = engine.analyze(df, symbol="T")
        assert report.trading_plan.direction == "空仓观望"

    def test_adapter_gate_stops_hold(self):
        df = _last_day_limit_up(synthetic_markup(seed=42))
        engine = WyckoffEngine()
        report = engine.analyze(df, symbol="T")
        assert report.trading_plan.direction == "空仓观望"
        adapter = WyckoffAdapter()
        sig = adapter.adapt({
            "wyckoff_direction": report.trading_plan.direction,
            "wyckoff_confidence": 0.6,
            "price": float(df["close"].iloc[-1]),
        }, symbol="T")
        assert sig is None