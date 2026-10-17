"""第九轮（2026-10-17）覆盖率补测：``brain/alpha_decoupler/alpha_decoupler.py``。

既有 ``tests/test_alpha_decoupler.py`` 已覆盖 RS 斜率 / 基准相关性的**主干**路径；
本文件补其**未覆盖分支**（不重复既有断言）：

* 基准路由 ``get_benchmark`` / 名称查询 ``get_benchmark_name``（41-53, 68-70）；
* ``calc_rs_slope`` 的 bench 缺列、字符串日期转换、无重叠合并（93, 105-107, 120）；
* ``calc_benchmark_corr`` 的全部入参校验与早退（147-176）；
* ``get_alpha_score`` 的无重叠早退（231）；
* 弃用门面 ``get_alpha_score_from_data`` 的全部分支（299-349）。

全部使用**合成数据**；不触网、不读数据湖、不依赖 czsc/backtrader。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import uniquant.brain.alpha_decoupler.alpha_decoupler as ad_module
from uniquant.brain.alpha_decoupler import AlphaDecoupler
from uniquant.shared.exceptions import EngineError


def _price_df(
    start: str = "2024-01-01",
    n: int = 40,
    base: float = 10.0,
    seed: int = 0,
    as_str: bool = False,
) -> pd.DataFrame:
    """确定性合成价格序列（date + close）。"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=n, freq="D")
    close = base + np.cumsum(rng.normal(0.0, 0.1, n))
    date_col = dates.strftime("%Y-%m-%d") if as_str else dates
    return pd.DataFrame({"date": date_col, "close": close})


class _FakeConfig:
    """最小 config 替身，仅支持点号路径 ``get``。"""

    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        node = self._data
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node


class _FakeFetcher:
    """最小 DataFetcherProtocol 替身。"""

    def __init__(self, mapping=None, error=None):
        self._mapping = mapping or {}
        self._error = error

    def fetch_history(self, symbol, start_date, end_date):
        if self._error is not None:
            raise self._error
        return self._mapping.get(symbol)


class TestBenchmarkRouting:
    def test_get_benchmark_routes_by_market_cap(self, monkeypatch) -> None:
        """四个市值档位各返回对应基准（覆盖 41-53）。"""
        cfg = _FakeConfig(
            {
                "brain": {
                    "alpha_decoupler": {
                        "benchmark_thresholds": {
                            "large_cap": 500e8,
                            "mid_cap": 100e8,
                            "small_cap": 50e8,
                        }
                    }
                }
            }
        )
        monkeypatch.setattr(ad_module, "get_config", lambda: cfg)
        assert AlphaDecoupler.get_benchmark(600e8) == "000300.SH"
        assert AlphaDecoupler.get_benchmark(200e8) == "000905.SH"
        assert AlphaDecoupler.get_benchmark(80e8) == "000852.SH"
        assert AlphaDecoupler.get_benchmark(10e8) == "932000.CSI"

    def test_get_benchmark_uses_default_thresholds(self, monkeypatch) -> None:
        """配置缺失阈值时回落到内置默认值（覆盖 42-45 的默认分支）。"""
        monkeypatch.setattr(ad_module, "get_config", lambda: _FakeConfig({}))
        assert AlphaDecoupler.get_benchmark(60e8) == "000852.SH"  # > 默认 50e8
        assert AlphaDecoupler.get_benchmark(40e8) == "932000.CSI"

    def test_get_benchmark_name_maps_and_falls_back(self, monkeypatch) -> None:
        """已知符号映射为中文名，未知符号原样返回（覆盖 68-70）。"""
        cfg = _FakeConfig(
            {"markets": {"benchmarks": {"names": {"000300.SH": "沪深300"}}}}
        )
        monkeypatch.setattr(ad_module, "get_config", lambda: cfg)
        assert AlphaDecoupler.get_benchmark_name("000300.SH") == "沪深300"
        assert AlphaDecoupler.get_benchmark_name("ZZZ") == "ZZZ"


class TestCalcRsSlopeBranches:
    def test_bench_missing_columns_returns_default(self) -> None:
        """基准缺 close 列 → EngineError 被装饰器吞掉并回退 0.0（覆盖 92-93）。"""
        stock = _price_df(seed=1)
        bench = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=40, freq="D")})
        assert AlphaDecoupler.calc_rs_slope(stock, bench, window=10) == 0.0

    def test_string_dates_are_converted(self) -> None:
        """字符串日期列应被 ``pd.to_datetime`` 归一化（覆盖 104-107）。"""
        stock = _price_df(seed=2, as_str=True)
        bench = _price_df(base=3000.0, seed=3, as_str=True)
        out = AlphaDecoupler.calc_rs_slope(stock, bench, window=10)
        assert isinstance(out, float)
        assert not np.isnan(out)

    def test_no_overlapping_dates_returns_zero(self) -> None:
        """两序列日期完全不重叠 → merge 空 → 0.0（覆盖 119-120）。"""
        stock = _price_df(start="2024-01-01", seed=4)
        bench = _price_df(start="2025-01-01", base=3000.0, seed=5)
        assert AlphaDecoupler.calc_rs_slope(stock, bench, window=5) == 0.0


class TestCalcBenchmarkCorrBranches:
    def test_none_input_raises_engine_error(self) -> None:
        """None 输入 → EngineError（覆盖 146-147）。"""
        bench = _price_df(base=3000.0, seed=1)
        with pytest.raises(EngineError):
            AlphaDecoupler.calc_benchmark_corr(None, bench, window=5)

    def test_stock_missing_columns_raises_engine_error(self) -> None:
        """个股缺必要列 → EngineError（覆盖 148-149）。"""
        stock = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=20, freq="D")})
        bench = _price_df(base=3000.0, seed=2)
        with pytest.raises(EngineError):
            AlphaDecoupler.calc_benchmark_corr(stock, bench, window=5)

    def test_bench_missing_columns_raises_engine_error(self) -> None:
        """基准缺必要列 → EngineError（覆盖 150-151）。"""
        stock = _price_df(seed=3)
        bench = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=20, freq="D")})
        with pytest.raises(EngineError):
            AlphaDecoupler.calc_benchmark_corr(stock, bench, window=5)

    def test_non_positive_window_raises_engine_error(self) -> None:
        """非正 window → EngineError（覆盖 152-153）。"""
        stock = _price_df(seed=4)
        bench = _price_df(base=3000.0, seed=5)
        with pytest.raises(EngineError):
            AlphaDecoupler.calc_benchmark_corr(stock, bench, window=0)

    def test_string_dates_are_converted(self) -> None:
        """字符串日期列归一化后正常计算相关性（覆盖 160-163）。"""
        stock = _price_df(seed=6, as_str=True)
        bench = _price_df(base=3000.0, seed=7, as_str=True)
        out = AlphaDecoupler.calc_benchmark_corr(stock, bench, window=10)
        assert isinstance(out, float)
        assert -1.0 <= out <= 1.0

    def test_no_overlap_returns_zero(self) -> None:
        """无重叠日期 → 0.0（覆盖 175-176）。"""
        stock = _price_df(start="2024-01-01", seed=8)
        bench = _price_df(start="2025-01-01", base=3000.0, seed=9)
        assert AlphaDecoupler.calc_benchmark_corr(stock, bench, window=5) == 0.0

    def test_short_overlap_returns_zero(self) -> None:
        """重叠行数不足 window → 0.0（覆盖 175-176）。"""
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        stock = pd.DataFrame({"date": dates, "close": [10.0, 10.1, 10.2]})
        bench = pd.DataFrame({"date": dates, "close": [3000.0, 3001.0, 3002.0]})
        assert AlphaDecoupler.calc_benchmark_corr(stock, bench, window=10) == 0.0


class TestGetAlphaScoreBranches:
    def test_no_overlap_returns_zero(self) -> None:
        """个股与基准无重叠日期 → 内层对齐斜率为 0 → 总分 0.0（覆盖 230-231）。"""
        stock = _price_df(start="2024-01-01", seed=1)
        bench = _price_df(start="2025-01-01", base=3000.0, seed=2)
        assert AlphaDecoupler.get_alpha_score(stock, bench, None) == 0.0


class TestGetAlphaScoreFromData:
    def _mapping(self):
        return {
            "STOCK": _price_df(seed=1),
            "BENCH": _price_df(base=3000.0, seed=2),
            "SECTOR": _price_df(base=800.0, seed=3),
        }

    def test_success_returns_score_and_symbols(self) -> None:
        """三路取数齐全 → 返回 alpha_score 与符号（覆盖 306-346）。"""
        fetcher = _FakeFetcher(self._mapping())
        with pytest.warns(DeprecationWarning):
            out = AlphaDecoupler.get_alpha_score_from_data(
                fetcher, "STOCK", "BENCH", "SECTOR", "2024-01-01", "2024-06-30"
            )
        assert out["stock_symbol"] == "STOCK"
        assert out["bench_symbol"] == "BENCH"
        assert out["sector_symbol"] == "SECTOR"
        assert "alpha_score" in out
        assert "error" not in out

    def test_capitalized_columns_trigger_rename_then_error(self) -> None:
        """大写列名走重命名分支（332-336）；因重命名不回写 → 下游 KeyError 包装（347-349）。"""
        mapping = {
            "STOCK": _price_df(seed=4).rename(columns={"date": "Date", "close": "Close"}),
            "BENCH": _price_df(base=3000.0, seed=5).rename(
                columns={"date": "Date", "close": "Close"}
            ),
            "SECTOR": _price_df(base=800.0, seed=6).rename(
                columns={"date": "Date", "close": "Close"}
            ),
        }
        fetcher = _FakeFetcher(mapping)
        with pytest.warns(DeprecationWarning):
            out = AlphaDecoupler.get_alpha_score_from_data(
                fetcher, "STOCK", "BENCH", "SECTOR", "2024-01-01", "2024-06-30"
            )
        assert out["alpha_score"] == 0.0
        assert "error" in out

    def test_empty_stock_returns_error(self) -> None:
        """个股取数缺失 → 返回错误字典（覆盖 311-317）。"""
        mapping = self._mapping()
        mapping.pop("STOCK")
        fetcher = _FakeFetcher(mapping)
        with pytest.warns(DeprecationWarning):
            out = AlphaDecoupler.get_alpha_score_from_data(
                fetcher, "STOCK", "BENCH", "SECTOR", "2024-01-01", "2024-06-30"
            )
        assert out["alpha_score"] == 0.0
        assert "STOCK" in out["error"]

    def test_empty_bench_returns_error(self) -> None:
        """基准取数缺失 → 返回错误字典（覆盖 318-323）。"""
        mapping = self._mapping()
        mapping.pop("BENCH")
        fetcher = _FakeFetcher(mapping)
        with pytest.warns(DeprecationWarning):
            out = AlphaDecoupler.get_alpha_score_from_data(
                fetcher, "STOCK", "BENCH", "SECTOR", "2024-01-01", "2024-06-30"
            )
        assert out["alpha_score"] == 0.0
        assert "BENCH" in out["error"]

    def test_empty_sector_returns_error(self) -> None:
        """行业取数缺失 → 返回错误字典（覆盖 324-329）。"""
        mapping = self._mapping()
        mapping.pop("SECTOR")
        fetcher = _FakeFetcher(mapping)
        with pytest.warns(DeprecationWarning):
            out = AlphaDecoupler.get_alpha_score_from_data(
                fetcher, "STOCK", "BENCH", "SECTOR", "2024-01-01", "2024-06-30"
            )
        assert out["alpha_score"] == 0.0
        assert "SECTOR" in out["error"]

    def test_fetcher_exception_returns_error(self) -> None:
        """取数抛异常 → 返回错误字典（覆盖 347-349）。"""
        fetcher = _FakeFetcher(error=RuntimeError("合成取数故障"))
        with pytest.warns(DeprecationWarning):
            out = AlphaDecoupler.get_alpha_score_from_data(
                fetcher, "STOCK", "BENCH", "SECTOR", "2024-01-01", "2024-06-30"
            )
        assert out["alpha_score"] == 0.0
        assert "error" in out
