"""第九轮（2026-10-17）覆盖率补测：``brain/indicators/indicators.py``。

既有 ``tests/test_indicators.py`` 已覆盖各指标的**主干**路径；本文件只补其
**未覆盖分支**（不重复既有断言）：

* ``calc_turnover_z`` 的 ``turnover`` 列优先分支（199）；
* ``calc_vol_ratio`` 缺成交量列时的常量兜底（226）；
* ``calculate_all_indicators`` 的异常包装分支（285-287）；
* 弃用门面 ``calculate_indicator_from_data`` 的全部分发与异常分支（320-404）。

全部使用**合成数据**；不触网、不读数据湖、不依赖 czsc/backtrader。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uniquant.brain.indicators import IndicatorError, Indicators


def _ohlcv(n: int = 120, seed: int = 0, with_volume: bool = True) -> pd.DataFrame:
    """确定性合成 OHLC(V) 数据。"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100.0 + np.cumsum(rng.normal(0.0, 1.0, n))
    high = close + rng.uniform(0.1, 2.0, n)
    low = close - rng.uniform(0.1, 2.0, n)
    df = pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": high,
            "low": low,
            "close": close,
        }
    )
    if with_volume:
        df["volume"] = rng.integers(1_000_000, 2_000_000, n)
    return df


class _FakeFetcher:
    """最小 DataFetcherProtocol 替身，仅实现 ``fetch_history``。"""

    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = []

    def fetch_history(self, symbol, start_date, end_date):
        self.calls.append((symbol, start_date, end_date))
        return self._mapping.get(symbol)


class TestUncoveredBranches:
    def test_calc_turnover_z_prefers_turnover_column(self) -> None:
        """存在 turnover 列时优先使用它（覆盖 199）。"""
        df = _ohlcv(with_volume=False)
        df["turnover"] = np.linspace(0.01, 0.05, len(df))
        out = Indicators.calc_turnover_z(df, window=20)
        assert isinstance(out, pd.Series)
        assert len(out) == len(df)

    def test_calc_vol_ratio_missing_volume_returns_ones(self) -> None:
        """既无 volume 也无 vol 列 → 常量 1.0 兜底（覆盖 226）。"""
        df = _ohlcv(with_volume=False)
        out = Indicators.calc_vol_ratio(df, window=20)
        assert (out == 1.0).all()

    def test_calculate_all_indicators_wraps_unexpected_exception(self, monkeypatch) -> None:
        """内部指标抛异常 → 记录并包装为 IndicatorError（覆盖 285-287）。"""
        df = _ohlcv(n=60, seed=7)

        def _boom(*_args, **_kwargs):
            raise RuntimeError("合成故障")

        monkeypatch.setattr(Indicators, "calc_atr", staticmethod(_boom))
        with pytest.raises(IndicatorError):
            Indicators.calculate_all_indicators(df)


class TestCalculateIndicatorFromData:
    """弃用门面：从数据获取器取数并分发到具体指标方法。"""

    @pytest.mark.parametrize(
        "indicator_name",
        ["ma", "ema", "atr", "macd", "rsi", "market_entropy", "turnover_z", "vol_ratio", "bollinger"],
    )
    def test_dispatch_all_supported_indicators(self, indicator_name: str) -> None:
        df = _ohlcv(n=120, seed=1)
        fetcher = _FakeFetcher({"600000.SH": df})
        with pytest.warns(DeprecationWarning):
            out = Indicators.calculate_indicator_from_data(
                fetcher, "600000.SH", "2024-01-01", "2024-12-31", indicator_name
            )
        assert isinstance(out, (pd.Series, pd.DataFrame))

    def test_passes_extra_kwargs_to_indicator(self) -> None:
        """``**kwargs``（window）应透传到具体指标方法。"""
        df = _ohlcv(n=120, seed=11)
        fetcher = _FakeFetcher({"600000.SH": df})
        with pytest.warns(DeprecationWarning):
            out = Indicators.calculate_indicator_from_data(
                fetcher, "600000.SH", "2024-01-01", "2024-12-31", "ma", window=5
            )
        assert isinstance(out, pd.Series)

    def test_renames_capitalized_columns(self) -> None:
        """Date/Close/High/Low/Volume 大写列名应被标准化（覆盖 342-351）。"""
        df = _ohlcv(n=120, seed=2).rename(
            columns={
                "date": "Date",
                "close": "Close",
                "high": "High",
                "low": "Low",
                "volume": "Volume",
            }
        )
        fetcher = _FakeFetcher({"600000.SH": df})
        with pytest.warns(DeprecationWarning):
            out = Indicators.calculate_indicator_from_data(
                fetcher, "600000.SH", "2024-01-01", "2024-12-31", "ma"
            )
        assert isinstance(out, pd.Series)

    def test_returns_atr_and_macd_shapes(self) -> None:
        df = _ohlcv(n=120, seed=12)
        fetcher = _FakeFetcher({"600000.SH": df})
        with pytest.warns(DeprecationWarning):
            macd = Indicators.calculate_indicator_from_data(
                fetcher, "600000.SH", "2024-01-01", "2024-12-31", "MACD"
            )
        assert isinstance(macd, pd.DataFrame)
        assert set(macd.columns) == {"macd", "signal", "hist"}

    def test_empty_dataframe_raises_indicator_error(self) -> None:
        """取数返回空表 → IndicatorError（覆盖 338-339）。"""
        fetcher = _FakeFetcher({"600000.SH": pd.DataFrame()})
        with pytest.warns(DeprecationWarning), pytest.raises(IndicatorError):
            Indicators.calculate_indicator_from_data(
                fetcher, "600000.SH", "2024-01-01", "2024-12-31", "ma"
            )

    def test_none_dataframe_raises_indicator_error(self) -> None:
        fetcher = _FakeFetcher({})
        with pytest.warns(DeprecationWarning), pytest.raises(IndicatorError):
            Indicators.calculate_indicator_from_data(
                fetcher, "600000.SH", "2024-01-01", "2024-12-31", "ma"
            )

    @pytest.mark.parametrize(
        "symbol,indicator_name",
        [
            ("", "ma"),
            (None, "ma"),
            ("600000.SH", ""),
            ("600000.SH", None),
        ],
    )
    def test_invalid_parameters_wrapped_as_indicator_error(self, symbol, indicator_name) -> None:
        """非法 symbol/indicator_name → ValueError 被包装为 IndicatorError（覆盖 328-332,394-396）。"""
        fetcher = _FakeFetcher({"600000.SH": _ohlcv(n=60, seed=3)})
        with pytest.warns(DeprecationWarning), pytest.raises(IndicatorError):
            Indicators.calculate_indicator_from_data(
                fetcher, symbol, "2024-01-01", "2024-12-31", indicator_name
            )

    def test_unsupported_indicator_raises_indicator_error(self) -> None:
        """未知指标名 → IndicatorError 原样抛出（覆盖 388-389,391-393）。"""
        fetcher = _FakeFetcher({"600000.SH": _ohlcv(n=60, seed=4)})
        with pytest.warns(DeprecationWarning), pytest.raises(IndicatorError):
            Indicators.calculate_indicator_from_data(
                fetcher, "600000.SH", "2024-01-01", "2024-12-31", "totally-unknown"
            )

    def test_keyerror_wrapped_as_indicator_error(self, monkeypatch) -> None:
        """底层抛 KeyError → 包装为 IndicatorError（覆盖 397-399）。"""

        def _boom(*_args, **_kwargs):
            raise KeyError("close")

        monkeypatch.setattr(Indicators, "calc_rsi", staticmethod(_boom))
        fetcher = _FakeFetcher({"600000.SH": _ohlcv(n=60, seed=5)})
        with pytest.warns(DeprecationWarning), pytest.raises(IndicatorError):
            Indicators.calculate_indicator_from_data(
                fetcher, "600000.SH", "2024-01-01", "2024-12-31", "rsi"
            )

    def test_unexpected_exception_wrapped_as_indicator_error(self, monkeypatch) -> None:
        """底层抛非预期异常 → 包装为 IndicatorError（覆盖 400-404）。"""

        def _boom(*_args, **_kwargs):
            raise RuntimeError("合成故障")

        monkeypatch.setattr(Indicators, "calc_ma", staticmethod(_boom))
        fetcher = _FakeFetcher({"600000.SH": _ohlcv(n=60, seed=6)})
        with pytest.warns(DeprecationWarning), pytest.raises(IndicatorError):
            Indicators.calculate_indicator_from_data(
                fetcher, "600000.SH", "2024-01-01", "2024-12-31", "ma"
            )
