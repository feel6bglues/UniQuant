"""``data/data_fetcher.py`` — 湖优先单源读取契约与委托方法测试.

补充 ``tests/test_data_fetcher_init_fault_tolerance.py`` (构造容错) 与
``tests/test_get_price_contract.py`` (返回契约冻结), 本文件覆盖:

* 模块级辅助 ``lake_candidate_symbols`` / ``harmonize_local_volume_unit``
* 湖优先链路 ``_read_lake`` / ``_fetch_local_fallback`` / ``_normalize_price_frame``
  / ``_apply_adjustment`` / ``_empty_price_frame`` / ``_slice_by_date``
* LRU 价格缓存读写与淘汰
* 公开 API 的委托面 (market_coordinator / metadata_manager / calendar_manager)

纪律: 全部 I/O 走 ``tmp_path`` 或 mock, 绝不触碰真实 ``data/`` 数据湖。
"""

from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from uniquant.data.data_fetcher import (
    GET_PRICE_ADJUSTED_COLUMNS,
    GET_PRICE_LAKE_COLUMNS,
    DataFetcher,
    LegacyDataFetcher,
    create_fetcher,
    harmonize_local_volume_unit,
    lake_candidate_symbols,
)


def _make_fetcher(storage=None, local=None, cache_size: int = 5000) -> DataFetcher:
    """构造不经重型 ``__init__`` 的 DataFetcher 实例 (只装配被测方法所需属性)。"""
    f = DataFetcher.__new__(DataFetcher)
    f.storage_manager = storage if storage is not None else MagicMock()
    f.mootdx_local_source = local
    f.data_sources = []
    f._price_cache = OrderedDict()
    f._max_cache_size = cache_size
    return f


def _lake_frame(dates=("2024-01-02", "2024-01-03")) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(list(dates)),
            "open": [10.0, 11.0][: len(dates)],
            "high": [15.0, 16.0][: len(dates)],
            "low": [9.0, 10.0][: len(dates)],
            "close": [12.0, 13.0][: len(dates)],
            "amount": [1200.0, 1300.0][: len(dates)],
            "volume": [100.0, 100.0][: len(dates)],
            "reserved": [0, 0][: len(dates)],
            "code": ["600519.SH"] * len(dates),
        }
    )


# ── module helpers ────────────────────────────────────────────────────────


class TestLakeCandidateSymbols:
    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("600519.SH", ["600519.SH"]),          # 已带后缀 → 原样
            ("600519", ["600519", "600519.SH", "600519.SZ", "600519.BJ"]),
            ("900901", ["900901", "900901.SH", "900901.SZ", "900901.BJ"]),
            ("000001", ["000001", "000001.SZ", "000001.SH", "000001.BJ"]),
            ("300750", ["300750", "300750.SZ", "300750.SH", "300750.BJ"]),
            ("830799", ["830799", "830799.BJ", "830799.SH", "830799.SZ"]),
            ("430047", ["430047", "430047.BJ", "430047.SH", "430047.SZ"]),
            ("500001", ["500001", "500001.SH", "500001.SZ", "500001.BJ"]),  # 未知前缀兜底 SH
            ("ABC", ["ABC"]),                       # 非纯数字 → 原样
        ],
    )
    def test_candidate_expansion(self, symbol, expected):
        assert lake_candidate_symbols(symbol) == expected

    def test_first_candidate_is_always_input(self):
        for sym in ("600519", "000001", "600519.SH", "XYZ"):
            assert lake_candidate_symbols(sym)[0] == sym


class TestHarmonizeLocalVolumeUnit:
    def _frame(self, ratio: float, rows: int = 6) -> pd.DataFrame:
        close = [10.0] * rows
        volume = [1.0] * rows
        amount = [ratio * 10.0 * 1.0] * rows
        return pd.DataFrame({"close": close, "volume": volume, "amount": amount})

    def test_none_and_empty_passthrough(self):
        assert harmonize_local_volume_unit(None) is None
        empty = pd.DataFrame()
        assert harmonize_local_volume_unit(empty) is empty

    def test_missing_columns_passthrough(self):
        df = pd.DataFrame({"close": [10.0], "volume": [1.0]})
        assert harmonize_local_volume_unit(df) is df

    def test_too_few_valid_rows_passthrough(self):
        df = self._frame(100.0, rows=4)
        assert harmonize_local_volume_unit(df) is df

    def test_hand_ratio_scales_volume_by_100(self):
        out = harmonize_local_volume_unit(self._frame(100.0))
        assert out["volume"].iloc[0] == 100.0
        assert out["amount"].iloc[0] == 1000.0  # amount 不动

    def test_share_ratio_passthrough(self):
        df = self._frame(1.0)
        out = harmonize_local_volume_unit(df)
        assert out is df
        assert out["volume"].iloc[0] == 1.0

    def test_ratio_below_hand_range_passthrough(self):
        df = self._frame(30.0)
        assert harmonize_local_volume_unit(df) is df

    def test_ratio_above_hand_range_passthrough(self):
        df = self._frame(500.0)
        assert harmonize_local_volume_unit(df) is df

    def test_all_rows_filtered_by_non_positive_passthrough(self):
        df = self._frame(100.0)
        df.loc[:, "close"] = 0.0
        assert harmonize_local_volume_unit(df) is df


# ── LRU price cache ───────────────────────────────────────────────────────


class TestPriceCache:
    def test_miss_returns_none(self):
        f = _make_fetcher()
        assert f._get_price_cached("600519.SH", "") is None

    def test_set_then_get_returns_copy(self):
        f = _make_fetcher()
        df = pd.DataFrame({"close": [1.0]})
        f._set_price_cache("600519.SH", "", df)
        got = f._get_price_cached("600519.SH", "")
        assert got is not None
        got.loc[0, "close"] = 99.0
        assert f._get_price_cached("600519.SH", "")["close"].iloc[0] == 1.0  # 缓存未被外部污染

    def test_adjust_is_part_of_key(self):
        f = _make_fetcher()
        f._set_price_cache("600519.SH", "", pd.DataFrame({"close": [1.0]}))
        assert f._get_price_cached("600519.SH", "qfq") is None

    def test_eviction_respects_max_size(self):
        f = _make_fetcher(cache_size=2)
        for i in range(3):
            f._set_price_cache(f"60000{i}.SH", "", pd.DataFrame({"close": [float(i)]}))
        assert len(f._price_cache) == 2
        assert f._get_price_cached("600000.SH", "") is None      # 最旧被淘汰
        assert f._get_price_cached("600002.SH", "") is not None

    def test_clear_all(self):
        f = _make_fetcher()
        f._set_price_cache("600519.SH", "", pd.DataFrame({"close": [1.0]}))
        f._set_price_cache("000001.SZ", "qfq", pd.DataFrame({"close": [1.0]}))
        assert f.clear_price_cache() == 2
        assert len(f._price_cache) == 0

    def test_clear_by_symbol(self):
        f = _make_fetcher()
        f._set_price_cache("600519.SH", "", pd.DataFrame({"close": [1.0]}))
        f._set_price_cache("600519.SH", "qfq", pd.DataFrame({"close": [1.0]}))
        f._set_price_cache("000001.SZ", "", pd.DataFrame({"close": [1.0]}))
        assert f.clear_price_cache("600519.SH") == 2
        assert f._get_price_cached("000001.SZ", "") is not None

    def test_clear_by_symbol_and_adjust(self):
        f = _make_fetcher()
        f._set_price_cache("600519.SH", "", pd.DataFrame({"close": [1.0]}))
        f._set_price_cache("600519.SH", "qfq", pd.DataFrame({"close": [1.0]}))
        assert f.clear_price_cache("600519.SH", "qfq") == 1
        assert f._get_price_cached("600519.SH", "") is not None
        assert f._get_price_cached("600519.SH", "qfq") is None


# ── lake-first read chain ─────────────────────────────────────────────────


class TestReadLake:
    def test_returns_none_when_all_candidates_miss(self):
        storage = SimpleNamespace(has_data=lambda _c: False, read_data=MagicMock())
        f = _make_fetcher(storage=storage)
        assert f._read_lake("600519") is None
        storage.read_data.assert_not_called()

    def test_has_data_absent_is_tolerated(self):
        # 无 has_data 属性的 storage → 直接尝试 read_data
        storage = SimpleNamespace(read_data=MagicMock(return_value=_lake_frame()))
        f = _make_fetcher(storage=storage)
        out = f._read_lake("600519.SH")
        assert out is not None and len(out) == 2

    def test_has_data_exception_is_swallowed(self):
        storage = SimpleNamespace(
            has_data=MagicMock(side_effect=RuntimeError("io error")),
            read_data=MagicMock(return_value=_lake_frame()),
        )
        f = _make_fetcher(storage=storage)
        assert f._read_lake("600519.SH") is not None

    def test_read_data_exception_falls_through_to_next_candidate(self):
        calls = {"n": 0}

        def _read(candidate, data_type="daily"):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("boom")
            return _lake_frame()

        storage = SimpleNamespace(has_data=lambda _c: True, read_data=_read)
        f = _make_fetcher(storage=storage)
        out = f._read_lake("600519")
        assert out is not None
        assert calls["n"] == 2

    def test_bare_code_hits_suffixed_candidate(self):
        def _has(candidate):
            return candidate == "600519.SH"

        storage = SimpleNamespace(has_data=_has, read_data=MagicMock(return_value=_lake_frame()))
        f = _make_fetcher(storage=storage)
        assert f._read_lake("600519") is not None

    def test_empty_frame_keeps_searching(self):
        storage = SimpleNamespace(
            has_data=lambda _c: True, read_data=MagicMock(return_value=pd.DataFrame())
        )
        f = _make_fetcher(storage=storage)
        assert f._read_lake("600519") is None


class TestFetchLocalFallback:
    def test_no_source_returns_none(self):
        f = _make_fetcher(local=None)
        assert f._fetch_local_fallback("600519.SH", None, None) is None

    def test_source_exception_returns_none(self):
        local = MagicMock()
        local.fetch_daily.side_effect = RuntimeError("corrupt file")
        f = _make_fetcher(local=local)
        assert f._fetch_local_fallback("600519.SH", "2024-01-01", "2024-02-01") is None

    def test_default_dates_and_volume_harmonisation(self):
        raw = pd.DataFrame(
            {
                "date": pd.to_datetime([f"2024-01-{d:02d}" for d in range(1, 8)]),
                "close": [10.0] * 7,
                "volume": [1.0] * 7,
                "amount": [1000.0] * 7,   # ratio=100 → 手 → ×100
            }
        )
        local = MagicMock()
        local.fetch_daily.return_value = raw
        f = _make_fetcher(local=local)
        out = f._fetch_local_fallback("600519.SH", None, None)
        assert out is not None
        assert out["volume"].iloc[0] == 100.0
        start, end = local.fetch_daily.call_args[0][1], local.fetch_daily.call_args[0][2]
        assert start == "1990-01-01"
        assert end  # 默认取 time provider 当日


class TestNormalizePriceFrame:
    def test_missing_date_column_returns_empty(self):
        out = DataFetcher._normalize_price_frame(pd.DataFrame({"close": [1.0]}), "600519.SH")
        assert out.empty

    def test_coerces_dates_and_sorts_dedups(self):
        df = pd.DataFrame(
            {
                "date": ["2024-01-03", "2024-01-02", "2024-01-03", "bogus"],
                "close": [3.0, 2.0, 30.0, 9.0],
            }
        )
        out = DataFetcher._normalize_price_frame(df, "600519.SH")
        assert list(out["date"]) == list(pd.to_datetime(["2024-01-02", "2024-01-03"]))
        assert out["close"].tolist() == [2.0, 30.0]          # keep last
        assert list(out.columns) == GET_PRICE_LAKE_COLUMNS   # 合同列序冻结

    def test_fills_code_when_absent(self):
        df = pd.DataFrame({"date": ["2024-01-02"], "close": [1.0]})
        out = DataFetcher._normalize_price_frame(df, "600519.SH")
        assert out["code"].iloc[0] == "600519.SH"

    def test_fills_code_when_all_nan(self):
        df = pd.DataFrame({"date": ["2024-01-02"], "close": [1.0], "code": [None]})
        out = DataFetcher._normalize_price_frame(df, "600519.SH")
        assert out["code"].iloc[0] == "600519.SH"

    def test_preserves_existing_code(self):
        df = pd.DataFrame({"date": ["2024-01-02"], "close": [1.0], "code": ["000001.SZ"]})
        out = DataFetcher._normalize_price_frame(df, "600519.SH")
        assert out["code"].iloc[0] == "000001.SZ"

    def test_drops_extra_columns(self):
        df = pd.DataFrame({"date": ["2024-01-02"], "close": [1.0], "junk": [1]})
        out = DataFetcher._normalize_price_frame(df, "600519.SH")
        assert "junk" not in out.columns


class TestApplyAdjustment:
    @pytest.mark.parametrize("method", ["qfq", "hfq", "QFQ", " hfq "])
    def test_qfq_hfq_delegate_to_corporate_action(self, monkeypatch, method):
        adjuster = MagicMock()
        adjuster.adjust.return_value = pd.DataFrame({"adj_factor": [1.0]})
        monkeypatch.setattr(
            "uniquant.data.data_fetcher.get_corporate_action_adjuster", lambda: adjuster
        )
        out = DataFetcher._apply_adjustment(_lake_frame(), "600519.SH", method)
        assert "adj_factor" in out.columns
        assert adjuster.adjust.call_args[0][0].shape[0] == 2
        assert adjuster.adjust.call_args[1]["adjust_type"] == method.strip().lower()

    @pytest.mark.parametrize("method", ["", "none", "raw", "NONE"])
    def test_raw_passthrough(self, method):
        df = _lake_frame()
        assert DataFetcher._apply_adjustment(df, "600519.SH", method) is df

    def test_unknown_adjust_warns_and_passthrough(self):
        df = _lake_frame()
        assert DataFetcher._apply_adjustment(df, "600519.SH", "weird") is df


class TestEmptyPriceFrame:
    @pytest.mark.parametrize(
        "adjust,expected",
        [
            ("", GET_PRICE_LAKE_COLUMNS),
            ("none", GET_PRICE_LAKE_COLUMNS),
            ("qfq", GET_PRICE_ADJUSTED_COLUMNS),
            ("HFQ", GET_PRICE_ADJUSTED_COLUMNS),
        ],
    )
    def test_contract_columns(self, adjust, expected):
        out = DataFetcher._empty_price_frame(adjust)
        assert out.empty
        assert list(out.columns) == expected


class TestSliceByDate:
    def test_no_bounds_passthrough(self):
        df = _lake_frame()
        assert DataFetcher._slice_by_date(df, None, None) is df

    def test_empty_frame_passthrough(self):
        df = pd.DataFrame(columns=GET_PRICE_LAKE_COLUMNS)
        assert DataFetcher._slice_by_date(df, "2024-01-01", None) is df

    def test_missing_date_column_passthrough(self):
        df = pd.DataFrame({"close": [1.0]})
        assert DataFetcher._slice_by_date(df, "2024-01-01", None) is df

    def test_start_bound_inclusive(self):
        out = DataFetcher._slice_by_date(_lake_frame(), "2024-01-03", None)
        assert len(out) == 1
        assert out["date"].iloc[0] == pd.Timestamp("2024-01-03")

    def test_end_bound_inclusive(self):
        out = DataFetcher._slice_by_date(_lake_frame(), None, "2024-01-02")
        assert len(out) == 1
        assert out["date"].iloc[0] == pd.Timestamp("2024-01-02")

    def test_window(self):
        out = DataFetcher._slice_by_date(_lake_frame(), "2024-01-01", "2024-01-05")
        assert len(out) == 2


# ── get_price orchestration ───────────────────────────────────────────────


class TestGetPrice:
    def test_no_data_returns_contract_empty_frame(self):
        storage = SimpleNamespace(has_data=lambda _c: False, read_data=MagicMock())
        f = _make_fetcher(storage=storage, local=None)
        out = f.get_price("600519.SH")
        assert out.empty
        assert list(out.columns) == GET_PRICE_LAKE_COLUMNS

    def test_empty_after_normalization_returns_contract_frame(self):
        f = _make_fetcher()
        f._read_raw_price = MagicMock(return_value=pd.DataFrame({"close": [1.0]}))  # 无 date 列
        out = f.get_price("600519.SH")
        assert out.empty
        assert list(out.columns) == GET_PRICE_LAKE_COLUMNS

    def test_uses_cache_and_slices(self):
        f = _make_fetcher()
        f._set_price_cache("600519.SH", "", _lake_frame())
        f._read_raw_price = MagicMock(side_effect=AssertionError("不应触达湖"))
        out = f.get_price("600519.SH", start_date="2024-01-03")
        assert len(out) == 1
        f._read_raw_price.assert_not_called()

    def test_happy_path_caches_result(self):
        f = _make_fetcher()
        f._read_raw_price = MagicMock(return_value=_lake_frame())
        out = f.get_price("600519.SH", adjust="")
        assert len(out) == 2
        assert f._get_price_cached("600519.SH", "") is not None

    def test_qfq_applies_adjustment(self, monkeypatch):
        adjuster = MagicMock()
        adjusted = _lake_frame().assign(adj_factor=1.0)
        adjuster.adjust.return_value = adjusted
        monkeypatch.setattr(
            "uniquant.data.data_fetcher.get_corporate_action_adjuster", lambda: adjuster
        )
        f = _make_fetcher()
        f._read_raw_price = MagicMock(return_value=_lake_frame())
        out = f.get_price("600519.SH", adjust="qfq")
        assert "adj_factor" in out.columns
        adjuster.adjust.assert_called_once()

    def test_qfq_empty_returns_adjusted_contract_frame(self):
        f = _make_fetcher()
        f._read_raw_price = MagicMock(return_value=pd.DataFrame())
        out = f.get_price("600519.SH", adjust="qfq")
        assert out.empty
        assert list(out.columns) == GET_PRICE_ADJUSTED_COLUMNS


# ── public API delegation surface ─────────────────────────────────────────


class TestDelegationSurface:
    def test_fetch_stock_daily_delegates_to_get_price(self):
        f = _make_fetcher()
        f.get_price = MagicMock(return_value=pd.DataFrame({"close": [1.0]}))
        out = f.fetch_stock_daily("600519.SH", "2024-01-01", "2024-02-01", adjust="qfq")
        assert len(out) == 1
        assert f.get_price.call_args[0] == ("600519.SH", "qfq")
        assert f.get_price.call_args[1] == {"start_date": "2024-01-01", "end_date": "2024-02-01"}

    def test_fetch_stock_daily_default_qfq(self):
        f = _make_fetcher()
        f.get_price = MagicMock(return_value=pd.DataFrame())
        f.fetch_stock_daily("600519.SH", "2024-01-01", "2024-02-01")
        assert f.get_price.call_args[0][1] == "qfq"

    @pytest.mark.parametrize(
        "method,coordinator_method",
        [
            ("fetch_index_daily", "fetch_index_daily"),
            ("fetch_etf_daily_robust", "fetch_etf_daily_robust"),
            ("fetch_sector_daily", "fetch_sector_daily"),
        ],
    )
    def test_coordinator_delegation(self, method, coordinator_method):
        f = _make_fetcher()
        f.market_coordinator = MagicMock()
        getattr(f.market_coordinator, coordinator_method).return_value = pd.DataFrame({"x": [1]})
        out = getattr(f, method)("600519.SH", "2024-01-01", "2024-02-01")
        assert len(out) == 1
        getattr(f.market_coordinator, coordinator_method).assert_called_once()

    def test_fetch_industry_concept_data_delegates(self):
        f = _make_fetcher()
        f.market_coordinator = MagicMock()
        f.market_coordinator.fetch_industry_concept_data.return_value = (
            pd.DataFrame({"a": [1]}),
            pd.DataFrame({"b": [2]}),
        )
        a, b = f.fetch_industry_concept_data()
        assert "a" in a.columns and "b" in b.columns

    def test_fetch_stock_real_time_returns_empty(self):
        f = _make_fetcher()
        assert f.fetch_stock_real_time("600519.SH").empty

    def test_get_symbols_delegates_to_storage(self):
        storage = SimpleNamespace(get_symbols=MagicMock(return_value=["600519.SH"]))
        f = _make_fetcher(storage=storage)
        assert f.get_symbols() == ["600519.SH"]

    def test_calendar_delegations(self):
        f = _make_fetcher()
        f.calendar_manager = MagicMock()
        f.generate_trade_calendar(2024)
        f.calendar_manager.generate_trade_calendar.assert_called_once_with(2024, False)
        f.is_trading_day("2024-01-02")
        f.calendar_manager.is_trading_day.assert_called_once()
        f.get_trade_calendar("2024-01-01", "2024-12-31")
        f.calendar_manager.get_trade_calendar.assert_called_once_with("2024-01-01", "2024-12-31")

    def test_fetch_for_brain_payload_shape(self):
        f = _make_fetcher()
        f.get_price = MagicMock(return_value=_lake_frame())
        out = f.fetch_for_brain("600519.SH")
        assert set(out) == {"stock", "symbol", "timestamp"}
        assert out["symbol"] == "600519.SH"
        assert f.get_price.call_args[1]["adjust"] == ""


class TestFetchHistory:
    @pytest.mark.parametrize("symbol", ["sh000300", "sz399001", "000001.SH"])
    def test_index_symbols_route_to_index_path(self, symbol):
        f = _make_fetcher()
        f.fetch_index_daily = MagicMock(return_value=pd.DataFrame({"index": [1]}))
        f.fetch_stock_daily = MagicMock()
        out = f.fetch_history(symbol, "2024-01-01", "2024-02-01")
        assert "index" in out.columns
        f.fetch_stock_daily.assert_not_called()

    @pytest.mark.parametrize("symbol", ["600519.SH", "000001.SZ", "300750.SZ"])
    def test_stock_symbols_route_to_stock_path(self, symbol):
        f = _make_fetcher()
        f.fetch_index_daily = MagicMock()
        f.fetch_stock_daily = MagicMock(return_value=pd.DataFrame({"stock": [1]}))
        out = f.fetch_history(symbol, "2024-01-01", "2024-02-01")
        assert "stock" in out.columns
        f.fetch_index_daily.assert_not_called()


class TestMarketCap:
    def test_no_source_supports_market_cap_returns_zero(self):
        f = _make_fetcher()
        f.data_sources = [SimpleNamespace()]
        assert f.fetch_stock_market_cap("600519.SH") == 0.0

    def test_first_positive_wins(self):
        good = MagicMock()
        good.fetch_market_cap.return_value = 1.5e12
        f = _make_fetcher()
        f.data_sources = [good]
        assert f.fetch_stock_market_cap("600519.SH") == 1.5e12

    def test_zero_and_negative_are_skipped(self):
        zero = MagicMock()
        zero.fetch_market_cap.return_value = 0.0
        good = MagicMock()
        good.fetch_market_cap.return_value = 100.0
        f = _make_fetcher()
        f.data_sources = [zero, good]
        assert f.fetch_stock_market_cap("600519.SH") == 100.0

    def test_recoverable_error_is_swallowed(self):
        bad = MagicMock()
        bad.fetch_market_cap.side_effect = ValueError("bad symbol")
        f = _make_fetcher()
        f.data_sources = [bad]
        assert f.fetch_stock_market_cap("600519.SH") == 0.0


class TestFetchStocksDaily:
    def test_parallel_batch_with_one_failure(self):
        f = _make_fetcher()

        def _fetch(symbol, start, end, adjust="qfq"):
            if symbol == "BAD.SH":
                raise RuntimeError("boom")
            return pd.DataFrame({"symbol": [symbol]})

        f.fetch_stock_daily = _fetch
        out = f.fetch_stocks_daily(["600519.SH", "000001.SZ", "BAD.SH"], "2024-01-01", "2024-02-01")
        assert set(out) == {"600519.SH", "000001.SZ", "BAD.SH"}
        assert out["BAD.SH"].empty
        assert out["600519.SH"]["symbol"].iloc[0] == "600519.SH"


class TestMetadataDelegation:
    def _fetcher_with_metadata(self, cache):
        f = _make_fetcher()
        f.metadata_manager = MagicMock()
        f.metadata_manager._metadata_cache = cache
        return f

    def test_fetch_all_stock_codes_builds_chinese_columns(self):
        f = self._fetcher_with_metadata(
            {
                "600519.SH": SimpleNamespace(name="贵州茅台"),
                "000001.SZ": SimpleNamespace(name="平安银行"),
            }
        )
        out = f.fetch_all_stock_codes()
        assert list(out.columns) == ["代码", "名称"]
        assert set(out["代码"]) == {"600519.SH", "000001.SZ"}

    def test_fetch_all_stock_codes_empty_cache(self):
        f = self._fetcher_with_metadata({})
        assert f.fetch_all_stock_codes().empty

    def test_fetch_stock_info_returns_mapping(self):
        f = self._fetcher_with_metadata({"600519.SH": SimpleNamespace(name="贵州茅台")})
        assert f.fetch_stock_info() == {"600519.SH": "贵州茅台"}

    def test_fetch_stock_info_empty(self):
        assert self._fetcher_with_metadata({}).fetch_stock_info() == {}

    def test_is_valid_symbol_strips_decorations(self):
        f = _make_fetcher()
        f.fetch_all_stock_codes = MagicMock(
            return_value=pd.DataFrame({"代码": ["600519", "000001"], "名称": ["a", "b"]})
        )
        assert f.is_valid_symbol("600519.SH") is True
        assert f.is_valid_symbol("sh600519") is True
        assert f.is_valid_symbol("999999.SH") is False

    def test_is_valid_symbol_false_when_table_empty(self):
        f = _make_fetcher()
        f.fetch_all_stock_codes = MagicMock(return_value=pd.DataFrame())
        assert f.is_valid_symbol("600519.SH") is False

    def test_validate_symbols_filters(self):
        f = _make_fetcher()
        f.is_valid_symbol = lambda s: s == "600519.SH"
        assert f.validate_symbols(["600519.SH", "999999.SH"]) == ["600519.SH"]


class TestConstructors:
    def test_legacy_fetcher_subclasses_data_fetcher(self):
        assert issubclass(LegacyDataFetcher, DataFetcher)

    def test_create_fetcher_returns_data_fetcher(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "uniquant.data.data_fetcher.MootdxLocalSource",
            MagicMock(side_effect=ImportError("mootdx missing")),
        )
        pd.DataFrame(
            {"code": ["sh.600000"], "name": ["浦发银行"], "代码": ["600000"]}
        ).to_csv(tmp_path / "all_stock_codes.csv", index=False, encoding="utf-8-sig")
        fetcher = create_fetcher(data_dir=str(tmp_path))
        assert isinstance(fetcher, DataFetcher)
        assert fetcher.mootdx_local_source is None
