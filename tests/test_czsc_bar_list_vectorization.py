"""
测试 CZSCEngine._prepare_bar_list 向量化优化

核心目标：
1. 向量化版本与原 for 循环版本逐行等价
2. 异常行被正确跳过（NaN、非正数、价格逻辑错误）
3. 有效行被正确转换为 RawBar
4. 性能基准：向量化版本应快于旧逐行过滤实现
"""

import time

import numpy as np
import pandas as pd
import pytest

czsc = pytest.importorskip("czsc")
from czsc import RawBar, Freq

from uniquant.brain.czsc.czsc_engine import CZSCEngine


def _make_valid_df(n: int, seed: int = 42) -> pd.DataFrame:
    """生成 n 行合法 OHLCV 数据（保证 low <= open/close <= high）"""
    np.random.seed(seed)
    close = 10 + np.cumsum(np.random.randn(n) * 0.3)
    close = np.maximum(close, 1.0)
    body = np.abs(np.random.randn(n) * 0.2)
    wick_up = np.abs(np.random.randn(n) * 0.3) + 0.01
    wick_down = np.abs(np.random.randn(n) * 0.3) + 0.01
    open_ = close + body * np.sign(np.random.randn(n))
    high = np.maximum(open_, close) + wick_up
    low = np.minimum(open_, close) - wick_down
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="B"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
    })


def _prepare_bar_list_legacy(df: pd.DataFrame) -> tuple[list[RawBar], int]:
    """旧版逐行过滤实现，用作性能和等价性基线。"""
    bars = []
    skipped_count = 0

    for i, row in df.iterrows():
        try:
            open_ = row["open"]
            close = row["close"]
            high = row["high"]
            low = row["low"]

            if pd.isna(open_) or pd.isna(close) or pd.isna(high) or pd.isna(low):
                skipped_count += 1
                continue

            if open_ <= 0 or close <= 0 or high <= 0 or low <= 0:
                skipped_count += 1
                continue

            if not (low <= close <= high and low <= open_ <= high):
                skipped_count += 1
                continue

            volume_col = "volume" if "volume" in df.columns else "vol"
            vol = float(row[volume_col]) if volume_col in df.columns else 0.0
            amount = float(row["amount"]) if "amount" in df.columns else float(close * vol)

            bars.append(
                RawBar(
                    symbol="STOCK",
                    dt=pd.to_datetime(row["date"]),
                    open=float(open_),
                    close=float(close),
                    high=float(high),
                    low=float(low),
                    vol=vol,
                    amount=amount,
                    freq=Freq.D,
                )
            )
        except (KeyError, TypeError, ValueError):
            skipped_count += 1

    return bars, skipped_count


class TestPrepareBarListVectorization:
    """_prepare_bar_list 向量化等价性测试"""

    @pytest.fixture
    def engine(self):
        return CZSCEngine()

    # ------------------------------------------------------------------ #
    #  测试 1：全有效数据 — 向量化与原版本结果一致
    # ------------------------------------------------------------------ #
    def test_valid_data_all_bars_created(self, engine):
        """全合法数据应全部转换为 RawBar。"""
        df = _make_valid_df(30)
        bars, skipped = engine._prepare_bar_list(df)

        assert len(bars) == 30
        assert skipped == 0
        assert all(isinstance(b, RawBar) for b in bars)

    # ------------------------------------------------------------------ #
    #  测试 2：含 NaN 行 — NaN 行被跳过
    # ------------------------------------------------------------------ #
    def test_nan_rows_are_skipped(self, engine):
        """含 NaN 的行应被跳过。"""
        df = _make_valid_df(30)
        # 注入 NaN
        df.loc[5, "open"] = np.nan
        df.loc[10, "close"] = np.nan
        df.loc[15, "high"] = np.nan

        bars, skipped = engine._prepare_bar_list(df)

        assert len(bars) == 27
        assert skipped == 3

    # ------------------------------------------------------------------ #
    #  测试 3：非正价格 — 零或负价格行被跳过
    # ------------------------------------------------------------------ #
    def test_non_positive_prices_are_skipped(self, engine):
        """价格 <= 0 的行应被跳过。"""
        df = _make_valid_df(30)
        df.loc[5, "open"] = 0
        df.loc[10, "close"] = -1
        df.loc[15, "high"] = 0

        bars, skipped = engine._prepare_bar_list(df)

        assert len(bars) == 27
        assert skipped == 3

    # ------------------------------------------------------------------ #
    #  测试 4：价格逻辑错误 — low > close 或 high < open 的行被跳过
    # ------------------------------------------------------------------ #
    def test_illogical_prices_are_skipped(self, engine):
        """违反 low <= close <= high 或 low <= open <= high 的行应被跳过。"""
        df = _make_valid_df(30)
        # close > high (不可能)
        df.loc[5, "close"] = df.loc[5, "high"] + 10
        # open < low (不可能)
        df.loc[10, "open"] = df.loc[10, "low"] - 10

        bars, skipped = engine._prepare_bar_list(df)

        assert len(bars) == 28
        assert skipped == 2

    # ------------------------------------------------------------------ #
    #  测试 5：混合异常 — 多种异常混合时结果正确
    # ------------------------------------------------------------------ #
    def test_mixed_anomalies(self, engine):
        """NaN、非正价格、逻辑错误混合时，结果应正确。"""
        df = _make_valid_df(50)
        df.loc[3, "open"] = np.nan          # NaN
        df.loc[7, "close"] = 0               # 零价格
        df.loc[12, "high"] = -1              # 负价格
        df.loc[20, "close"] = df.loc[20, "high"] + 5  # 逻辑错误
        df.loc[30, "open"] = df.loc[30, "low"] - 5    # 逻辑错误

        bars, skipped = engine._prepare_bar_list(df)

        assert len(bars) == 45
        assert skipped == 5

    # ------------------------------------------------------------------ #
    #  测试 6：全异常数据 — 全部被跳过
    # ------------------------------------------------------------------ #
    def test_all_anomalous_data(self, engine):
        """全部为 NaN 时应返回空列表。"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=20, freq="B"),
            "open": [np.nan] * 20,
            "high": [np.nan] * 20,
            "low": [np.nan] * 20,
            "close": [np.nan] * 20,
            "volume": [1000] * 20,
        })

        bars, skipped = engine._prepare_bar_list(df)

        assert len(bars) == 0
        assert skipped == 20

    # ------------------------------------------------------------------ #
    #  测试 7：无 volume 列 — 使用 vol 或默认 0
    # ------------------------------------------------------------------ #
    def test_no_volume_column(self, engine):
        """无 volume 列时应使用 vol 列或默认 0。"""
        df = _make_valid_df(20)
        df = df.rename(columns={"volume": "vol"})

        bars, skipped = engine._prepare_bar_list(df)

        assert len(bars) == 20
        assert skipped == 0
        # vol 列被引擎识别为成交量列，应使用其中的值
        assert all(b.vol > 0 for b in bars)

    # ------------------------------------------------------------------ #
    #  测试 8：有 amount 列 — 使用提供的 amount
    # ------------------------------------------------------------------ #
    def test_with_amount_column(self, engine):
        """有 amount 列时应使用提供的值。"""
        df = _make_valid_df(20)
        df["amount"] = df["close"] * df["volume"] * 1.5  # 自定义 amount

        bars, skipped = engine._prepare_bar_list(df)

        assert len(bars) == 20
        # 验证 amount 被正确使用
        assert np.isclose(bars[0].amount, df.loc[0, "amount"])

    # ------------------------------------------------------------------ #
    #  测试 9：大数据集性能 — 向量化版本应快于旧逐行过滤实现
    # ------------------------------------------------------------------ #
    def test_performance_large_dataset(self, engine):
        """大数据集下，向量化实现应快于旧逐行过滤实现。"""
        df = _make_valid_df(5000)

        optimized_start = time.perf_counter()
        bars, skipped = engine._prepare_bar_list(df)
        optimized_elapsed = time.perf_counter() - optimized_start

        legacy_start = time.perf_counter()
        legacy_bars, legacy_skipped = _prepare_bar_list_legacy(df)
        legacy_elapsed = time.perf_counter() - legacy_start

        assert len(bars) == 5000
        assert skipped == 0
        assert len(legacy_bars) == len(bars)
        assert legacy_skipped == skipped
        assert optimized_elapsed < legacy_elapsed, (
            f"Optimized path should be faster than legacy path: "
            f"{optimized_elapsed:.3f}s vs {legacy_elapsed:.3f}s"
        )

    # ------------------------------------------------------------------ #
    #  测试 10：RawBar 属性正确性
    # ------------------------------------------------------------------ #
    def test_rawbar_attributes(self, engine):
        """验证生成的 RawBar 属性与输入数据一致。"""
        df = _make_valid_df(5)
        bars, _ = engine._prepare_bar_list(df)

        for i, bar in enumerate(bars):
            assert bar.symbol == "STOCK"
            assert bar.open == pytest.approx(df.loc[i, "open"])
            assert bar.close == pytest.approx(df.loc[i, "close"])
            assert bar.high == pytest.approx(df.loc[i, "high"])
            assert bar.low == pytest.approx(df.loc[i, "low"])
            assert bar.vol == pytest.approx(df.loc[i, "volume"])
            assert bar.freq == Freq.D
